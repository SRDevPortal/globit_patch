from __future__ import annotations

from collections import defaultdict

import frappe


def execute():
	"""Backfill blank Patient company IDs from trusted synchronization history."""
	if not frappe.db.has_column("Patient", "company_id"):
		return

	candidates = _company_id_candidates()
	logger = frappe.logger("globit_patch")
	for patient, company_ids in candidates.items():
		if not frappe.db.exists("Patient", patient):
			continue
		if len(company_ids) != 1:
			logger.warning(
				"Patient %s company_id backfill skipped; conflicting values: %s",
				patient,
				sorted(company_ids),
			)
			continue
		if not frappe.db.get_value("Patient", patient, "company_id"):
			frappe.db.set_value(
				"Patient",
				patient,
				"company_id",
				next(iter(company_ids)),
				update_modified=False,
			)


def _company_id_candidates() -> dict[str, set[str]]:
	candidates: dict[str, set[str]] = defaultdict(set)
	for row in frappe.get_all(
		"External Record Mapping",
		filters={"source_doctype": "Patient", "destination_doctype": "Patient"},
		fields=["source_site", "destination_name"],
	):
		_add_candidate(candidates, row.destination_name, row.source_site)

	encounter_fieldname = (
		"company_id" if frappe.db.has_column("Patient Encounter", "company_id") else "channel_id"
	)
	for row in frappe.get_all(
		"Patient Encounter",
		filters={"patient": ["is", "set"], encounter_fieldname: ["is", "set"]},
		fields=["patient", encounter_fieldname],
	):
		_add_candidate(candidates, row.patient, row.get(encounter_fieldname))
	return candidates


def _add_candidate(candidates: dict[str, set[str]], patient: str, company_id: str) -> None:
	patient = str(patient or "").strip()
	company_id = (
		str(company_id or "")
		.strip()
		.lower()
		.removeprefix("https://")
		.removeprefix("http://")
		.rstrip("/")
	)
	if patient and company_id:
		candidates[patient].add(company_id)
