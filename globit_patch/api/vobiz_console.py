from __future__ import annotations

from typing import Any

import frappe
from frappe import _


PATIENT_ENCOUNTER = "Patient Encounter"


@frappe.whitelist()
def get_agent_console_data(limit: int | str = 25, search: str | None = None) -> dict[str, Any]:
	"""Add the Patient Encounter queue to the standard Vobiz console response."""
	from vobiz_click_to_call.api.console import get_agent_console_data as get_vobiz_console_data

	data = get_vobiz_console_data(limit=limit, search=search)
	if _current_queue_source() != PATIENT_ENCOUNTER:
		return data

	limit = max(5, min(frappe.utils.cint(limit) or 25, 500))
	data["queue"] = _patient_encounter_queue(limit, search)
	data["queue_meta"] = {
		"source": PATIENT_ENCOUNTER,
		"doctype": PATIENT_ENCOUNTER,
		"title": _("Patient Encounter Queue"),
		"id_label": _("Encounter ID"),
		"selected_label": _("encounters"),
		"summary_tab_label": _("Patient Encounter"),
		"data_label": _("Encounter Data"),
		"empty_message": _("No callable patient encounters found"),
	}
	return data


def _current_queue_source() -> str:
	if not frappe.db.exists("DocType", "Vobiz User Mapping"):
		return ""
	return (
		frappe.db.get_value(
			"Vobiz User Mapping",
			{"user": frappe.session.user, "enabled": 1},
			"queue_source",
		)
		or ""
	).strip()


def _patient_encounter_queue(limit: int, search: str | None = None) -> list[dict[str, Any]]:
	if not frappe.db.exists("DocType", PATIENT_ENCOUNTER):
		return []

	meta = frappe.get_meta(PATIENT_ENCOUNTER)
	field_candidates = (
		"patient",
		"patient_name",
		"status",
		"sr_encounter_status",
		"encounter_date",
		"company",
		"channel_id",
		"doc_id",
		"created_by_agent",
		"owner",
	)
	fields = ["name", "modified", *[field for field in field_candidates if meta.has_field(field)]]
	filters: dict[str, Any] = {}
	if meta.has_field("created_by_agent") and not _can_view_all_encounters():
		filters["created_by_agent"] = frappe.session.user

	query = (search or "").strip()
	search_fields = [
		field
		for field in ("name", "patient", "patient_name", "status", "sr_encounter_status", "channel_id", "doc_id")
		if field == "name" or meta.has_field(field)
	]
	rows = frappe.get_list(
		PATIENT_ENCOUNTER,
		filters=filters,
		or_filters=[[field, "like", f"%{query}%"] for field in search_fields] if query else None,
		fields=fields,
		order_by="modified desc",
		limit_page_length=limit,
	)
	patient_phones = _patient_phone_map(rows)
	return [_encounter_queue_row(row, patient_phones.get(row.get("patient"))) for row in rows]


def _patient_phone_map(encounters: list[dict[str, Any]]) -> dict[str, str]:
	patient_names = {row.get("patient") for row in encounters if row.get("patient")}
	if not patient_names or not frappe.db.exists("DocType", "Patient"):
		return {}

	meta = frappe.get_meta("Patient")
	phone_fields = [field for field in ("mobile_no", "mobile", "phone", "phone_no") if meta.has_field(field)]
	if not phone_fields:
		return {}

	patients = frappe.get_all(
		"Patient",
		filters={"name": ["in", list(patient_names)]},
		fields=["name", *phone_fields],
	)
	return {
		patient.name: next((patient.get(field) for field in phone_fields if patient.get(field)), "")
		for patient in patients
	}


def _encounter_queue_row(encounter: dict[str, Any], phone: str | None) -> dict[str, Any]:
	return {
		"doctype": PATIENT_ENCOUNTER,
		"name": encounter.get("name"),
		"title": encounter.get("patient_name") or encounter.get("patient") or encounter.get("name"),
		"company": encounter.get("company") or PATIENT_ENCOUNTER,
		"phone": phone or "",
		"phone_field": "mobile_no" if phone else "",
		"status": encounter.get("sr_encounter_status") or encounter.get("status") or _("New"),
		"next_action": str(encounter.get("encounter_date") or _("Initial contact")),
		"owner": encounter.get("created_by_agent") or encounter.get("owner"),
	}


def _can_view_all_encounters() -> bool:
	return frappe.session.user == "Administrator" or "System Manager" in frappe.get_roles()
