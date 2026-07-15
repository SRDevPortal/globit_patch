import inspect

import frappe
from frappe import _
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


PATIENT_ENCOUNTER_FIELDS = {
	"Patient Encounter": [
		{
			"fieldname": "channel_id",
			"label": "Channel ID",
			"fieldtype": "Data",
			"insert_after": "company",
			"module": "Globit Patch",
		},
		{
			"fieldname": "doc_id",
			"label": "Doc ID",
			"fieldtype": "Data",
			"insert_after": "channel_id",
			"module": "Globit Patch",
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
	setup_patient_encounter_fields()
	setup_vobiz_patient_encounter_queue()


def setup_patient_encounter_fields():
	"""Create or update the webhook identifiers on Patient Encounter."""
	create_custom_fields(PATIENT_ENCOUNTER_FIELDS, update=True)


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
