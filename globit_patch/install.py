import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
from frappe.custom.doctype.property_setter.property_setter import make_property_setter


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


def setup_integrations():
	setup_patient_encounter_fields()
	setup_vobiz_patient_encounter_queue()


def setup_patient_encounter_fields():
	"""Create or update the webhook identifiers on Patient Encounter."""
	create_custom_fields(PATIENT_ENCOUNTER_FIELDS, update=True)


def setup_vobiz_patient_encounter_queue():
	"""Expose Patient Encounter as a Vobiz queue without editing the Vobiz app."""
	if not frappe.db.exists("DocType", "Vobiz User Mapping"):
		return

	make_property_setter(
		"Vobiz User Mapping",
		"queue_source",
		"options",
		"CRM Lead\nPatient\nPatient Encounter",
		"Text",
		validate_fields_for_doctype=False,
	)
	frappe.clear_cache(doctype="Vobiz User Mapping")

	if frappe.db.exists("DocType", "Vobiz Settings"):
		settings = frappe.get_single("Vobiz Settings")
		allowed = [row.strip() for row in (settings.allowed_doctypes or "").splitlines() if row.strip()]
		if "Patient Encounter" not in allowed:
			allowed.append("Patient Encounter")
			settings.allowed_doctypes = "\n".join(allowed)
			settings.save(ignore_permissions=True)
