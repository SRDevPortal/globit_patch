from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

import frappe

from globit_patch.integrations.globifit.exceptions import PatientIdentityConflict, SyncConflict
from globit_patch.integrations.globifit.mappings import get_external_mapping


@dataclass
class PatientResolution:
	patient: Any | None
	method: str
	matched_contact: str = ""
	matched_customer: str = ""


def normalize_mobile(value: Any) -> str:
	digits = re.sub(r"\D", "", str(value or ""))
	return digits[-10:] if len(digits) >= 10 else ""


def resolve_patient(
	*,
	source_site: str,
	source_patient: str,
	patient_name: str,
	sex: str,
	mobile: str,
	allow_automatic_matching: bool,
) -> PatientResolution:
	mapping = get_external_mapping(source_site, "Patient", source_patient)
	if mapping:
		if mapping.get("destination_doctype") != "Patient" or not frappe.db.exists(
			"Patient", mapping.get("destination_name")
		):
			raise SyncConflict(
				"The source Patient mapping points to a missing destination Patient.",
				code="BROKEN_PATIENT_MAPPING",
			)
		return PatientResolution(frappe.get_doc("Patient", mapping.destination_name), "External Mapping")

	if not allow_automatic_matching:
		return PatientResolution(None, "Created")

	normalized_mobile = normalize_mobile(mobile)
	if not normalized_mobile:
		return PatientResolution(None, "Created")

	contacts = _contacts_by_mobile(normalized_mobile)
	linked_patients = _linked_entities([row.name for row in contacts], "Patient")
	if linked_patients:
		patient_rows = frappe.get_all(
			"Patient",
			filters={"name": ["in", linked_patients]},
			fields=["name", "patient_name", "first_name", "sex", "customer"],
		)
		patient = _one_compatible_patient(patient_rows, patient_name, sex)
		return PatientResolution(
			patient,
			"Contact Link",
			matched_contact=contacts[0].name if len(contacts) == 1 else "",
		)

	linked_customers = _linked_entities([row.name for row in contacts], "Customer")
	if linked_customers:
		customer_patients = frappe.get_all(
			"Patient",
			filters={"customer": ["in", linked_customers]},
			fields=["name", "patient_name", "first_name", "sex", "customer"],
		)
		if customer_patients:
			patient = _one_compatible_patient(customer_patients, patient_name, sex)
			return PatientResolution(
				patient,
				"Customer Link",
				matched_contact=contacts[0].name if len(contacts) == 1 else "",
				matched_customer=patient.get("customer") or "",
			)

	patient_candidates = frappe.get_all(
		"Patient",
		filters={"mobile": normalized_mobile},
		fields=["name", "patient_name", "first_name", "sex", "customer"],
	)
	if patient_candidates:
		return PatientResolution(
			_one_compatible_patient(patient_candidates, patient_name, sex),
			"Verified Patient Match",
		)

	if contacts:
		raise PatientIdentityConflict(
			"The mobile number belongs to a destination Contact that cannot be mapped unambiguously to a Patient."
		)

	customers = frappe.get_all(
		"Customer",
		filters={"mobile_no": normalized_mobile},
		pluck="name",
	)
	if customers:
		customer_patients = frappe.get_all(
			"Patient",
			filters={"customer": ["in", customers]},
			fields=["name", "patient_name", "first_name", "sex", "customer"],
		)
		if customer_patients:
			patient = _one_compatible_patient(customer_patients, patient_name, sex)
			return PatientResolution(
				patient,
				"Customer Link",
				matched_customer=patient.get("customer") or "",
			)
		raise PatientIdentityConflict(
			"The mobile number belongs to a destination Customer without one verified Patient."
		)

	return PatientResolution(None, "Created")


def _contacts_by_mobile(mobile: str) -> list[Any]:
	return frappe.db.sql(
		"""
		SELECT name
		FROM `tabContact`
		WHERE RIGHT(REPLACE(REPLACE(mobile_no, ' ', ''), '+91', ''), 10) = %s
		   OR RIGHT(REPLACE(REPLACE(phone, ' ', ''), '+91', ''), 10) = %s
		ORDER BY modified DESC
		LIMIT 20
		""",
		(mobile, mobile),
		as_dict=True,
	)


def _linked_entities(contacts: list[str], doctype: str) -> list[str]:
	if not contacts:
		return []
	return list(
		dict.fromkeys(
			frappe.get_all(
				"Dynamic Link",
				filters={
					"parenttype": "Contact",
					"parent": ["in", contacts],
					"link_doctype": doctype,
				},
				pluck="link_name",
			)
		)
	)


def _one_compatible_patient(candidates: list[Any], patient_name: str, sex: str) -> Any:
	compatible = [row for row in candidates if _identity_matches(row, patient_name, sex)]
	if len(compatible) != 1:
		raise PatientIdentityConflict()
	return frappe.get_doc("Patient", compatible[0].get("name"))


def _identity_matches(candidate: Any, patient_name: str, sex: str) -> bool:
	name = candidate.get("patient_name") or candidate.get("first_name") or ""
	return _normalize_name(name) == _normalize_name(patient_name) and not (
		candidate.get("sex") and sex and candidate.get("sex") != sex
	)


def _normalize_name(value: Any) -> str:
	return " ".join(re.sub(r"[^a-z0-9 ]", " ", str(value or "").lower()).split())
