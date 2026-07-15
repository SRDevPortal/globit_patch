from __future__ import annotations

from typing import Any

from globit_patch.integrations.globifit.exceptions import ContractError
from globit_patch.integrations.globifit.mappings import resolve_link


ORDER_ITEM_FIELDS = {
	"sr_item_code",
	"sr_item_name",
	"sr_item_uom",
	"sr_item_qty",
	"sr_item_rate",
	"sr_item_amount",
	"sr_item_description",
}
PAYMENT_FIELDS = {
	"mmp_paid_amount",
	"mmp_mode_of_payment",
	"mmp_reference_no",
	"mmp_reference_date",
	"mmp_payment_intent",
	"mmp_provider_payment_id",
	"mmp_gateway",
	"mmp_payment_mode",
	"mmp_orchestrator_status",
}
PRESCRIPTION_FIELDS = {
	"medication",
	"sr_medication_name_print",
	"drug_code",
	"drug_name",
	"strength",
	"strength_uom",
	"dosage_form",
	"dosage_by_interval",
	"dosage",
	"interval",
	"interval_uom",
	"period",
	"sr_drug_instruction",
	"number_of_repeats_allowed",
	"intent",
	"priority",
	"medication_request",
	"comment",
	"update_schedule",
}


def map_order_items(rows: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
	result = []
	for row in _rows(rows, "sr_pe_order_items"):
		mapped = _allow(row, ORDER_ITEM_FIELDS)
		mapped["sr_item_code"] = resolve_link("Item", row.get("sr_item_code"), "Item", required=True)
		if row.get("sr_item_uom"):
			mapped["sr_item_uom"] = resolve_link("UOM", row.get("sr_item_uom"), "UOM")
		if not row.get("sr_item_qty") or row.get("sr_item_rate") in (None, ""):
			raise ContractError("Every order item requires quantity and rate.", code="INVALID_ORDER_ITEM")
		result.append(mapped)
	return result


def map_payments(rows: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
	result = []
	for row in _rows(rows, "enc_multi_payments"):
		mapped = _allow(row, PAYMENT_FIELDS)
		if row.get("mmp_mode_of_payment"):
			mapped["mmp_mode_of_payment"] = resolve_link(
				"Mode of Payment",
				row.get("mmp_mode_of_payment"),
				"Mode of Payment",
			)
		result.append(mapped)
	return result


def map_prescriptions(rows: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
	link_fields = {
		"medication": "Medication",
		"drug_code": "Item",
		"strength_uom": "UOM",
		"dosage_form": "Dosage Form",
		"dosage": "Prescription Dosage",
		"period": "Prescription Duration",
		"sr_drug_instruction": "SR Instruction",
		"intent": "Code Value",
		"priority": "Code Value",
	}
	result = []
	for row in _rows(rows, "sr_allopathy_drug_prescription"):
		mapped = _allow(row, PRESCRIPTION_FIELDS)
		for fieldname, doctype in link_fields.items():
			if row.get(fieldname):
				mapped[fieldname] = resolve_link(doctype, row.get(fieldname), doctype)
		result.append(mapped)
	return result


def _rows(value: Any, fieldname: str) -> list[dict[str, Any]]:
	if value is None:
		return []
	if not isinstance(value, list) or any(not isinstance(row, dict) for row in value):
		raise ContractError(f"{fieldname} must contain JSON objects.", code="INVALID_CHILD_TABLE")
	return value


def _allow(row: dict[str, Any], allowed: set[str]) -> dict[str, Any]:
	return {fieldname: row.get(fieldname) for fieldname in allowed if row.get(fieldname) not in (None, "")}
