from __future__ import annotations

import json
from typing import Any

import frappe

from globit_patch.integrations.globifit.child_tables import (
	ORDER_ITEM_FIELDS,
	PAYMENT_FIELDS,
	PRESCRIPTION_FIELDS,
	map_order_items,
	map_payments,
	map_prescriptions,
)
from globit_patch.integrations.globifit.contract import SyncPayload
from globit_patch.integrations.globifit.diffing import (
	audit_count,
	audit_paths,
	document_changes,
	field_changes,
	has_changes,
)
from globit_patch.integrations.globifit.exceptions import (
	PatientIdentityConflict,
	SyncConflict,
	SyncError,
)
from globit_patch.integrations.globifit.mappings import (
	get_external_mapping,
	resolve_link,
	save_external_mapping,
)
from globit_patch.integrations.globifit.patient_identity import PatientResolution, normalize_mobile, resolve_patient


CHILD_TABLE_SPECS = {
	"sr_pe_order_items": (ORDER_ITEM_FIELDS, ("sr_item_code",)),
	"enc_multi_payments": (
		PAYMENT_FIELDS,
		("mmp_mode_of_payment", "mmp_reference_no", "mmp_provider_payment_id"),
	),
	"sr_allopathy_drug_prescription": (PRESCRIPTION_FIELDS, ("medication", "drug_code")),
}


def synchronize(payload: SyncPayload, settings: Any) -> dict[str, Any]:
	existing = frappe.db.get_value(
		"Patient Encounter Sync Log",
		payload.event_id,
		[
			"status",
			"payload_hash",
			"action",
			"patient_resolution",
			"destination_patient",
			"destination_patient_encounter",
			"received_at",
		],
		as_dict=True,
	)
	if existing and existing.get("payload_hash") != payload.payload_hash:
		raise SyncConflict(
			"The event ID was already used for different content.",
			code="EVENT_HASH_CONFLICT",
		)
	if existing and existing.get("status") == "Succeeded":
		return _result(
			payload,
			action="unchanged",
			patient_action="unchanged",
			encounter_action="unchanged",
			patient=existing.get("destination_patient"),
			encounter=existing.get("destination_patient_encounter"),
		)
	if existing and existing.get("status") == "Processing" and existing.get("received_at"):
		processing_age = frappe.utils.time_diff_in_seconds(
			frappe.utils.now_datetime(),
			frappe.utils.get_datetime(existing.get("received_at")),
		)
		if processing_age < 600:
			raise SyncError(
				"This event is already being processed.",
				code="EVENT_IN_PROGRESS",
				http_status=409,
			)
	if settings.dry_run:
		return _dry_run(payload, settings)

	log = _start_log(payload, existing)
	replay = _mapped_replay(payload)
	if replay:
		patient, encounter = replay
		resolution = PatientResolution(patient, "External Mapping")
		_update_log_success(
			log.name,
			"unchanged",
			"unchanged",
			"unchanged",
			patient,
			encounter,
			resolution,
			{},
		)
		return _result(
			payload,
			action="unchanged",
			patient_action="unchanged",
			encounter_action="unchanged",
			patient=patient.name,
			encounter=encounter.name,
		)
	frappe.db.savepoint("globit_patient_encounter_sync")
	try:
		patient, patient_action, resolution, patient_changes = _sync_patient(payload, settings)
		encounter, encounter_action, encounter_changes = _sync_encounter(payload, settings, patient)
		overall_action = _overall_action(patient_action, encounter_action)
		audit = {}
		if has_changes(patient_changes):
			audit["patient"] = patient_changes
		if has_changes(encounter_changes):
			audit["encounter"] = encounter_changes
		_update_log_success(
			log.name,
			overall_action,
			patient_action,
			encounter_action,
			patient,
			encounter,
			resolution,
			audit,
		)
		return _result(
			payload,
			action=overall_action,
			patient_action=patient_action,
			encounter_action=encounter_action,
			patient=patient.name,
			encounter=encounter.name,
		)
	except SyncError as exc:
		frappe.db.rollback(save_point="globit_patient_encounter_sync")
		_update_log_error(log.name, exc)
		raise
	except Exception:
		frappe.db.rollback(save_point="globit_patient_encounter_sync")
		_update_log_error(log.name, SyncError("Unexpected destination processing error.", code="INTERNAL_ERROR"))
		raise


def _sync_patient(payload: SyncPayload, settings: Any) -> tuple[Any, str, PatientResolution, dict[str, Any]]:
	encounter = payload.encounter
	sex = resolve_link("Gender", encounter.get("patient_sex"), "Gender", required=True)
	department = resolve_link(
		"Medical Department",
		encounter.get("sr_pe_deptt"),
		"Medical Department",
		required=True,
	)
	resolution = resolve_patient(
		source_site=payload.source_site,
		source_patient=payload.source_patient,
		patient_name=str(encounter.get("patient_name") or "").strip(),
		sex=sex,
		mobile=str(encounter.get("sr_pe_mobile") or ""),
		allow_automatic_matching=bool(settings.allow_automatic_patient_matching),
	)
	patient = resolution.patient
	changes: dict[str, Any] = {"fields": {}, "child_tables": {}}
	if patient:
		patient_action = "matched_existing" if resolution.method != "External Mapping" else "unchanged"
		if resolution.method == "External Mapping":
			desired = {
				"first_name": str(encounter.get("patient_name") or "").strip(),
				"sex": sex,
				"mobile": normalize_mobile(encounter.get("sr_pe_mobile")),
				"sr_medical_department": department,
			}
			changes["fields"] = field_changes(patient, desired)
			if changes["fields"]:
				for fieldname in changes["fields"]:
					patient.set(fieldname, desired[fieldname])
				_save_patient(patient)
				patient_action = "updated"
	else:
		patient = frappe.get_doc(
			{
				"doctype": "Patient",
				"first_name": str(encounter.get("patient_name") or "").strip(),
				"sex": sex,
				"mobile": normalize_mobile(encounter.get("sr_pe_mobile")),
				"sr_medical_department": department,
			}
		)
		_save_patient(patient, insert=True)
		patient_action = "created"

	save_external_mapping(
		source_site=payload.source_site,
		source_doctype="Patient",
		source_name=payload.source_patient,
		destination_doctype="Patient",
		destination_name=patient.name,
		source_modified=payload.source_modified,
		payload_hash=payload.payload_hash,
	)
	return patient, patient_action, resolution, changes


def _save_patient(patient: Any, *, insert: bool = False) -> None:
	try:
		if insert:
			patient.insert(ignore_permissions=True)
		else:
			patient.save(ignore_permissions=True)
	except frappe.ValidationError as exc:
		message = str(exc).lower()
		if "already linked" in message or ("mobile" in message and "contact" in message):
			raise PatientIdentityConflict(
				"The mobile number is already linked to a different destination identity."
			) from exc
		raise SyncError(
			"The destination rejected the Patient data.",
			code="DESTINATION_PATIENT_VALIDATION_FAILED",
			http_status=422,
		) from exc


def _dry_run(payload: SyncPayload, settings: Any) -> dict[str, Any]:
	"""Execute normal validation and hooks, then roll back every database change."""
	frappe.db.savepoint("globit_patient_encounter_dry_run")
	try:
		patient, patient_action, _resolution, _patient_changes = _sync_patient(payload, settings)
		encounter, encounter_action, _encounter_changes = _sync_encounter(payload, settings, patient)
		return _result(
			payload,
			action="dry_run",
			patient_action=patient_action,
			encounter_action=encounter_action,
			patient=patient.name,
			encounter=encounter.name,
		)
	finally:
		frappe.db.rollback(save_point="globit_patient_encounter_dry_run")


def _sync_encounter(payload: SyncPayload, settings: Any, patient: Any) -> tuple[Any, str, dict[str, Any]]:
	mapping = get_external_mapping(payload.source_site, "Patient Encounter", payload.source_name)
	if mapping:
		if mapping.get("destination_doctype") != "Patient Encounter" or not frappe.db.exists(
			"Patient Encounter", mapping.get("destination_name")
		):
			raise SyncConflict(
				"The source Encounter mapping points to a missing destination record.",
				code="BROKEN_ENCOUNTER_MAPPING",
			)
		if mapping.get("last_source_modified") and frappe.utils.get_datetime(
			payload.source_modified
		) < frappe.utils.get_datetime(mapping.get("last_source_modified")):
			raise SyncConflict("The source update is older than the imported version.", code="STALE_SOURCE_UPDATE")
		doc = frappe.get_doc("Patient Encounter", mapping.destination_name)
		if doc.docstatus != 0:
			raise SyncConflict(
				"Submitted or cancelled destination Encounters cannot be synchronized.",
				code="DESTINATION_ENCOUNTER_LOCKED",
			)
		action = "unchanged"
	else:
		existing_name = frappe.db.get_value(
			"Patient Encounter",
			{"channel_id": payload.source_site, "doc_id": payload.source_name},
			"name",
		)
		doc = frappe.get_doc("Patient Encounter", existing_name) if existing_name else frappe.new_doc("Patient Encounter")
		if existing_name and doc.docstatus != 0:
			raise SyncConflict(
				"Submitted or cancelled destination Encounters cannot be synchronized.",
				code="DESTINATION_ENCOUNTER_LOCKED",
			)
		action = "unchanged" if existing_name else "created"

	values = _encounter_values(payload, settings, patient)
	changes: dict[str, Any] = {"fields": {}, "child_tables": {}}
	if action == "created":
		for fieldname, value in values.items():
			doc.set(fieldname, value)
		try:
			doc.insert(ignore_permissions=True)
		except frappe.ValidationError as exc:
			raise SyncError(
				"The destination rejected the Patient Encounter data.",
				code="DESTINATION_ENCOUNTER_VALIDATION_FAILED",
				http_status=422,
			) from exc
	else:
		changes = document_changes(doc, values, CHILD_TABLE_SPECS)
		if has_changes(changes):
			for fieldname in changes["fields"]:
				doc.set(fieldname, values[fieldname])
			for fieldname in changes["child_tables"]:
				doc.set(fieldname, values[fieldname])
			try:
				doc.save(ignore_permissions=True)
			except frappe.ValidationError as exc:
				raise SyncError(
					"The destination rejected the Patient Encounter data.",
					code="DESTINATION_ENCOUNTER_VALIDATION_FAILED",
					http_status=422,
				) from exc
			action = "updated"

	save_external_mapping(
		source_site=payload.source_site,
		source_doctype="Patient Encounter",
		source_name=payload.source_name,
		destination_doctype="Patient Encounter",
		destination_name=doc.name,
		source_modified=payload.source_modified,
		payload_hash=payload.payload_hash,
	)
	return doc, action, changes


def _encounter_values(payload: SyncPayload, settings: Any, patient: Any) -> dict[str, Any]:
	source = payload.encounter
	encounter_place = resolve_link(
		"SR Encounter Place",
		source.get("sr_encounter_place") or settings.default_encounter_place,
		"SR Encounter Place",
		required=True,
	)
	return {
		"channel_id": payload.source_site,
		"doc_id": payload.source_name,
		"patient": patient.name,
		"patient_name": patient.patient_name or patient.first_name,
		"company": resolve_link("Company", source.get("company"), "Company", required=True),
		"encounter_date": source.get("encounter_date"),
		"encounter_time": source.get("encounter_time"),
		"sr_encounter_type": resolve_link(
			"SR Encounter Type", source.get("sr_encounter_type"), "SR Encounter Type", required=True
		),
		"sr_encounter_place": encounter_place,
		"sr_encounter_source": resolve_link(
			"SR Lead Source",
			source.get("sr_encounter_source"),
			"SR Lead Source",
			required=encounter_place == "Online",
		),
		"sr_encounter_status": resolve_link(
			"SR Encounter Status", source.get("sr_encounter_status") or "Draft", "SR Encounter Status", required=True
		),
		"sr_sales_type": resolve_link("SR Sales Type", source.get("sr_sales_type"), "SR Sales Type")
		if source.get("sr_sales_type")
		else "",
		"sr_delivery_type": resolve_link("SR Delivery Type", source.get("sr_delivery_type"), "SR Delivery Type")
		if source.get("sr_delivery_type")
		else "",
		"sr_pe_order_items": map_order_items(source.get("sr_pe_order_items")),
		"enc_multi_payments": map_payments(source.get("enc_multi_payments")),
		"sr_allopathy_drug_prescription": map_prescriptions(source.get("sr_allopathy_drug_prescription")),
	}


def _start_log(payload: SyncPayload, existing: Any) -> Any:
	previous = frappe.get_all(
		"Patient Encounter Sync Log",
		filters={
			"source_site": payload.source_site,
			"source_doctype": payload.source_doctype,
			"source_name": payload.source_name,
			"event_id": ["!=", payload.event_id],
		},
		pluck="event_id",
		order_by="source_modified desc",
		limit=1,
	)
	values = {
		"trace_id": payload.trace_id,
		"status": "Processing",
		"action": "",
		"idempotency_key": payload.idempotency_key,
		"source_site": payload.source_site,
		"source_doctype": payload.source_doctype,
		"source_name": payload.source_name,
		"source_modified": payload.source_modified,
		"payload_hash": payload.payload_hash,
		"previous_event_id": previous[0] if previous else "",
		"patient_action": "",
		"encounter_action": "",
		"change_count": 0,
		"changed_fields": "",
		"change_details": "",
		"requires_manual_review": 0,
		"error_code": "",
		"error_summary": "",
		"received_at": frappe.utils.now(),
	}
	if existing:
		frappe.db.set_value("Patient Encounter Sync Log", payload.event_id, values, update_modified=True)
		return frappe.get_doc("Patient Encounter Sync Log", payload.event_id)
	try:
		return frappe.get_doc(
			{
				"doctype": "Patient Encounter Sync Log",
				"event_id": payload.event_id,
				**values,
			}
		).insert(ignore_permissions=True)
	except frappe.DuplicateEntryError as exc:
		raise SyncError(
			"This event is already being processed.",
			code="EVENT_IN_PROGRESS",
			http_status=409,
		) from exc


def _mapped_replay(payload: SyncPayload) -> tuple[Any, Any] | None:
	encounter_mapping = get_external_mapping(payload.source_site, "Patient Encounter", payload.source_name)
	if not encounter_mapping or encounter_mapping.get("last_payload_hash") != payload.payload_hash:
		return None
	patient_mapping = get_external_mapping(payload.source_site, "Patient", payload.source_patient)
	if not patient_mapping:
		return None
	patient_name = patient_mapping.get("destination_name")
	encounter_name = encounter_mapping.get("destination_name")
	if not frappe.db.exists("Patient", patient_name) or not frappe.db.exists("Patient Encounter", encounter_name):
		return None
	return frappe.get_doc("Patient", patient_name), frappe.get_doc("Patient Encounter", encounter_name)


def _update_log_success(
	log_name: str,
	action: str,
	patient_action: str,
	encounter_action: str,
	patient: Any,
	encounter: Any,
	resolution: PatientResolution,
	audit: dict[str, Any],
) -> None:
	paths = audit_paths(audit)
	frappe.db.set_value(
		"Patient Encounter Sync Log",
		log_name,
		{
			"status": "Succeeded",
			"action": _action_label(action),
			"patient_action": _action_label(patient_action),
			"encounter_action": _action_label(encounter_action),
			"change_count": audit_count(audit),
			"changed_fields": ", ".join(paths),
			"change_details": json.dumps(audit, sort_keys=True, default=str) if audit else "",
			"patient_resolution": resolution.method,
			"destination_patient": patient.name,
			"destination_patient_encounter": encounter.name,
			"matched_contact": resolution.matched_contact,
			"matched_customer": resolution.matched_customer,
			"completed_at": frappe.utils.now(),
		},
		update_modified=True,
	)


def _overall_action(patient_action: str, encounter_action: str) -> str:
	if encounter_action == "created":
		return "created"
	if patient_action == "created" and encounter_action == "unchanged":
		return "created"
	if "updated" in (patient_action, encounter_action):
		return "updated"
	return "unchanged"


def _action_label(value: str) -> str:
	return value.replace("_", " ").title() if value else ""


def _update_log_error(log_name: str, error: SyncError) -> None:
	frappe.db.set_value(
		"Patient Encounter Sync Log",
		log_name,
		{
			"status": "Conflict" if error.http_status == 409 else "Failed",
			"patient_resolution": "Conflict" if isinstance(error, PatientIdentityConflict) else "",
			"requires_manual_review": int(error.requires_manual_review),
			"error_code": error.code,
			"error_summary": error.message[:500],
			"completed_at": frappe.utils.now(),
		},
		update_modified=True,
	)


def _result(
	payload: SyncPayload,
	*,
	action: str,
	patient_action: str = "",
	encounter_action: str = "",
	patient: str | None = None,
	encounter: str | None = None,
) -> dict[str, Any]:
	return {
		"ok": True,
		"action": action,
		"patient_action": patient_action,
		"encounter_action": encounter_action,
		"patient": patient,
		"patient_encounter": encounter,
		"event_id": payload.event_id,
		"trace_id": payload.trace_id,
	}
