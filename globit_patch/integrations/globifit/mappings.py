from __future__ import annotations

from typing import Any

import frappe

from globit_patch.integrations.globifit.contract import entity_key
from globit_patch.integrations.globifit.exceptions import ContractError


def get_external_mapping(source_site: str, source_doctype: str, source_name: str) -> dict[str, Any] | None:
	key = entity_key(source_site, source_doctype, source_name)
	return frappe.db.get_value(
		"External Record Mapping",
		key,
		[
			"name",
			"destination_doctype",
			"destination_name",
			"last_source_modified",
			"last_payload_hash",
		],
		as_dict=True,
	)


def save_external_mapping(
	*,
	source_site: str,
	source_doctype: str,
	source_name: str,
	destination_doctype: str,
	destination_name: str,
	source_modified: str,
	payload_hash: str,
) -> None:
	key = entity_key(source_site, source_doctype, source_name)
	values = {
		"source_site": source_site,
		"source_doctype": source_doctype,
		"source_name": source_name,
		"destination_doctype": destination_doctype,
		"destination_name": destination_name,
		"last_source_modified": source_modified,
		"last_payload_hash": payload_hash,
	}
	if frappe.db.exists("External Record Mapping", key):
		frappe.db.set_value("External Record Mapping", key, values, update_modified=True)
	else:
		frappe.get_doc(
			{
				"doctype": "External Record Mapping",
				"external_key": key,
				**values,
			}
		).insert(ignore_permissions=True)


def resolve_link(source_doctype: str, source_value: Any, destination_doctype: str, *, required: bool = False) -> str:
	value = str(source_value or "").strip()
	if not value:
		if required:
			raise ContractError(
				f"A value is required for {destination_doctype}.",
				code="MISSING_MASTER_VALUE",
			)
		return ""

	mapped = frappe.db.get_value(
		"Integration Value Mapping",
		{
			"enabled": 1,
			"source_doctype": source_doctype,
			"source_value": value,
			"destination_doctype": destination_doctype,
		},
		"destination_value",
	)
	if mapped and frappe.db.exists(destination_doctype, mapped):
		return mapped
	if frappe.db.exists(destination_doctype, value):
		return value
	if required or value:
		raise ContractError(
			f"No destination {destination_doctype} mapping exists for the supplied value.",
			code="MISSING_MASTER_MAPPING",
		)
	return ""
