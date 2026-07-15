from __future__ import annotations

from typing import Any

import frappe
from vobiz_click_to_call.api.console import get_agent_console_data as get_vobiz_console_data


PATIENT_ENCOUNTER = "Patient Encounter"


@frappe.whitelist()
def get_agent_console_data(
	limit: int | str = 25,
	search: str | None = None,
	followup_day: str | None = None,
	queue_source_filter: str | None = None,
	sort_by: str | None = None,
	filters: str | list | None = None,
	**kwargs: Any,
) -> dict[str, Any]:
	"""Return native Vobiz console data with Patient Encounter access enforced.

	All console behavior and response fields remain owned by Vobiz. Globit Patch
	only removes encounter rows the current user cannot read or does not own.
	Unknown keyword arguments are forwarded to keep the wrapper compatible with
	future additive changes to the upstream endpoint.
	"""
	data = get_vobiz_console_data(
		limit=limit,
		search=search,
		followup_day=followup_day,
		queue_source_filter=queue_source_filter,
		sort_by=sort_by,
		filters=filters,
		**kwargs,
	)
	if (data.get("queue_meta") or {}).get("doctype") != PATIENT_ENCOUNTER:
		return data

	data["queue"] = _permitted_patient_encounters(data.get("queue") or [])
	return data


def _permitted_patient_encounters(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
	"""Keep native queue ordering while applying permissions in one query."""
	names = [row.get("name") for row in rows if row.get("name")]
	if not names or not frappe.db.exists("DocType", PATIENT_ENCOUNTER):
		return []

	filters: dict[str, Any] = {"name": ["in", names]}
	meta = frappe.get_meta(PATIENT_ENCOUNTER)
	if meta.has_field("created_by_agent") and not _can_view_all_encounters():
		filters["created_by_agent"] = frappe.session.user

	permitted_names = set(
		frappe.get_list(
			PATIENT_ENCOUNTER,
			filters=filters,
			pluck="name",
			limit_page_length=len(names),
		)
	)
	return [row for row in rows if row.get("name") in permitted_names]


def _can_view_all_encounters() -> bool:
	return frappe.session.user == "Administrator" or "System Manager" in frappe.get_roles()
