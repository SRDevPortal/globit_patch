import inspect
import json

import frappe
from frappe import _
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
from frappe.custom.doctype.property_setter.property_setter import make_property_setter


PATIENT_ENCOUNTER_FIELDS = {
	"Patient": [
		{
			"fieldname": "company_id",
			"label": "Company ID",
			"fieldtype": "Data",
			"insert_after": "created_by_agent",
			"module": "Globit Patch",
			"description": "Source site identifier for synchronized patients.",
			"in_standard_filter": 1,
			"no_copy": 1,
			"read_only": 1,
		},
	],
	"Patient Encounter": [
		{
			"fieldname": "company_id",
			"label": "Company ID",
			"fieldtype": "Data",
			"insert_after": "company",
			"module": "Globit Patch",
			"description": "Source site identifier for synchronized encounters.",
			"in_standard_filter": 1,
			"no_copy": 1,
			"read_only": 1,
		},
		{
			"fieldname": "reference_id",
			"label": "Reference ID",
			"fieldtype": "Data",
			"insert_after": "company_id",
			"module": "Globit Patch",
			"description": "Patient Encounter name on the source site.",
			"in_standard_filter": 1,
			"no_copy": 1,
			"read_only": 1,
		},
	]
}

LEGACY_QUEUE_SOURCE_OPTIONS = "CRM Lead\nPatient\nPatient Encounter"
REQUIRED_CONSOLE_PARAMETERS = {
	"limit",
	"search",
	"followup_day",
	"queue_source_filter",
	"sort_by",
	"filters",
}


def setup_integrations():
	setup_integration_role()
	setup_integration_settings()
	setup_patient_encounter_fields()
	migrate_patient_encounter_identifiers()
	position_patient_company_id()
	setup_vobiz_patient_encounter_queue()


def setup_integration_role():
	"""Create the least-privilege role required by the destination sync API."""
	if not frappe.db.exists("Role", "Globit Integration User"):
		frappe.get_doc(
			{
				"doctype": "Role",
				"role_name": "Globit Integration User",
				"desk_access": 0,
				"is_custom": 0,
			}
		).insert(ignore_permissions=True)


def setup_integration_settings():
	"""Seed fail-closed integration defaults exactly once after model sync."""
	if not frappe.db.exists("DocType", "Globit Integration Settings"):
		return
	settings = frappe.get_single("Globit Integration Settings")
	if settings.configuration_initialized:
		return
	settings.enabled = 0
	settings.dry_run = 1
	settings.allowed_source_site = "eternityerp.m.frappe.cloud"
	settings.allowed_schema_versions = "1"
	settings.default_encounter_place = "OPD"
	settings.signature_tolerance_seconds = 300
	settings.maximum_payload_bytes = 1048576
	settings.allow_automatic_patient_matching = 1
	settings.log_retention_days = 30
	settings.configuration_initialized = 1
	settings.save(ignore_permissions=True)


def setup_patient_encounter_fields():
	"""Create or update the Patient synchronization identifiers."""
	create_custom_fields(PATIENT_ENCOUNTER_FIELDS, update=True)


def migrate_patient_encounter_identifiers():
	"""Copy legacy identifiers and retire their old Custom Field definitions."""
	for old_fieldname, new_fieldname in (
		("channel_id", "company_id"),
		("doc_id", "reference_id"),
	):
		if frappe.db.has_column("Patient Encounter", old_fieldname) and frappe.db.has_column(
			"Patient Encounter", new_fieldname
		):
			frappe.db.sql(
				f"""UPDATE `tabPatient Encounter`
				SET `{new_fieldname}` = `{old_fieldname}`
				WHERE IFNULL(`{new_fieldname}`, '') = ''
				AND IFNULL(`{old_fieldname}`, '') != ''"""
			)
		legacy_field = f"Patient Encounter-{old_fieldname}"
		if frappe.db.exists("Custom Field", legacy_field):
			frappe.delete_doc(
				"Custom Field",
				legacy_field,
				force=True,
				ignore_permissions=True,
				ignore_missing=True,
			)
	frappe.clear_cache(doctype="Patient Encounter")


def position_patient_company_id():
	"""Place Company ID directly after Created By in the customized Patient layout."""
	field_order = [field.fieldname for field in frappe.get_meta("Patient", cached=False).fields]
	if "company_id" not in field_order or "created_by_agent" not in field_order:
		return
	field_order.remove("company_id")
	field_order.insert(field_order.index("created_by_agent") + 1, "company_id")
	value = json.dumps(field_order)
	setter = frappe.db.get_value(
		"Property Setter",
		{"doc_type": "Patient", "property": "field_order", "doctype_or_field": "DocType"},
		"name",
	)
	if setter:
		frappe.db.set_value("Property Setter", setter, "value", value, update_modified=False)
	else:
		make_property_setter(
			"Patient",
			"Patient",
			"field_order",
			value,
			"Text",
			for_doctype=True,
		)
	frappe.clear_cache(doctype="Patient")


def setup_vobiz_patient_encounter_queue():
	"""Keep Patient Encounter callable without overriding Vobiz's native queue support."""
	if not frappe.db.exists("DocType", "Vobiz User Mapping"):
		return

	remove_legacy_queue_source_property_setter()
	frappe.clear_cache(doctype="Vobiz User Mapping")
	validate_vobiz_capabilities()

	if frappe.db.exists("DocType", "Vobiz Settings"):
		settings = frappe.get_single("Vobiz Settings")
		allowed = [row.strip() for row in (settings.allowed_doctypes or "").splitlines() if row.strip()]
		if "Patient Encounter" not in allowed:
			allowed.append("Patient Encounter")
			settings.allowed_doctypes = "\n".join(allowed)
			settings.save(ignore_permissions=True)


def remove_legacy_queue_source_property_setter():
	"""Remove only the obsolete property setter created by older app versions.

	A site administrator may intentionally maintain a different queue-source
	property setter, so cleanup is deliberately limited to the exact legacy
	value previously installed by this app.
	"""
	setter_name = frappe.db.get_value(
		"Property Setter",
		{
			"doc_type": "Vobiz User Mapping",
			"field_name": "queue_source",
			"property": "options",
			"value": LEGACY_QUEUE_SOURCE_OPTIONS,
		},
		"name",
	)
	if setter_name:
		frappe.delete_doc(
			"Property Setter",
			setter_name,
			force=True,
			ignore_permissions=True,
			ignore_missing=True,
		)


def validate_vobiz_capabilities():
	"""Fail setup with an actionable error when the Vobiz contract is incompatible."""
	from vobiz_click_to_call.api.console import get_agent_console_data

	parameters = set(inspect.signature(get_agent_console_data).parameters)
	missing_parameters = sorted(REQUIRED_CONSOLE_PARAMETERS - parameters)
	queue_source = frappe.get_meta("Vobiz User Mapping").get_field("queue_source")
	queue_sources = set()
	if queue_source:
		queue_sources = {
			row.strip()
			for row in (queue_source.options or "").splitlines()
			if row.strip()
		}

	problems = []
	if missing_parameters:
		problems.append(
			_("console API is missing parameters: {0}").format(", ".join(missing_parameters))
		)
	if "Patient Encounter" not in queue_sources:
		problems.append(_("Patient Encounter is not a native Queue Source"))

	if problems:
		frappe.throw(
			_("Upgrade Vobiz Click To Call before installing or migrating Globit Patch: {0}.").format(
				"; ".join(problems)
			),
			title=_("Incompatible Vobiz Click To Call"),
		)
