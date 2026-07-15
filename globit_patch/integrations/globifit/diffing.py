from __future__ import annotations

import json
from collections import defaultdict
from typing import Any


SENSITIVE_FIELDS = {
	"mobile",
	"sr_pe_mobile",
	"mmp_reference_no",
	"mmp_payment_intent",
	"mmp_provider_payment_id",
}


def field_changes(document: Any, desired: dict[str, Any]) -> dict[str, dict[str, Any]]:
	changes = {}
	for fieldname, new_value in desired.items():
		old_value = document.get(fieldname)
		if _normalized_value(old_value) != _normalized_value(new_value):
			changes[fieldname] = {
				"from": _audit_value(fieldname, old_value),
				"to": _audit_value(fieldname, new_value),
			}
	return changes


def document_changes(
	document: Any,
	desired: dict[str, Any],
	child_specs: dict[str, tuple[set[str], tuple[str, ...]]],
) -> dict[str, Any]:
	scalar_values = {key: value for key, value in desired.items() if key not in child_specs}
	result: dict[str, Any] = {"fields": field_changes(document, scalar_values), "child_tables": {}}
	for fieldname, (allowed_fields, key_fields) in child_specs.items():
		changes = child_table_changes(
			document.get(fieldname) or [],
			desired.get(fieldname) or [],
			allowed_fields=allowed_fields,
			key_fields=key_fields,
		)
		if changes:
			result["child_tables"][fieldname] = changes
	return result


def child_table_changes(
	old_rows: list[Any],
	new_rows: list[Any],
	*,
	allowed_fields: set[str],
	key_fields: tuple[str, ...],
) -> dict[str, Any]:
	old = [_normalized_row(row, allowed_fields) for row in old_rows]
	new = [_normalized_row(row, allowed_fields) for row in new_rows]
	old_groups = _group_rows(old, key_fields)
	new_groups = _group_rows(new, key_fields)
	added = []
	removed = []
	changed = []

	for key in sorted(set(old_groups) | set(new_groups), key=lambda value: json.dumps(value, default=str)):
		old_group = sorted(old_groups.get(key, []), key=_canonical)
		new_group = sorted(new_groups.get(key, []), key=_canonical)
		paired = min(len(old_group), len(new_group))
		for index in range(paired):
			row_changes = _row_changes(old_group[index], new_group[index], allowed_fields)
			if row_changes:
				changed.append(
					{
						"key": _masked_row(dict(zip(key_fields, key, strict=False))),
						"fields": row_changes,
					}
				)
		removed.extend(_masked_row(row) for row in old_group[paired:])
		added.extend(_masked_row(row) for row in new_group[paired:])

	result = {}
	if added:
		result["added"] = added
	if removed:
		result["removed"] = removed
	if changed:
		result["changed"] = changed
	return result


def audit_count(audit: dict[str, Any]) -> int:
	count = 0
	for entity in audit.values():
		count += len(entity.get("fields") or {})
		for changes in (entity.get("child_tables") or {}).values():
			count += len(changes.get("added") or [])
			count += len(changes.get("removed") or [])
			count += sum(len(row.get("fields") or {}) for row in changes.get("changed") or [])
	return count


def audit_paths(audit: dict[str, Any]) -> list[str]:
	paths = []
	for entity_name, entity in audit.items():
		paths.extend(f"{entity_name}.{fieldname}" for fieldname in (entity.get("fields") or {}))
		for table_name, changes in (entity.get("child_tables") or {}).items():
			if changes.get("added"):
				paths.append(f"{entity_name}.{table_name}.added")
			if changes.get("removed"):
				paths.append(f"{entity_name}.{table_name}.removed")
			for row in changes.get("changed") or []:
				paths.extend(
					f"{entity_name}.{table_name}.{fieldname}"
					for fieldname in (row.get("fields") or {})
				)
	return list(dict.fromkeys(paths))


def has_changes(changes: dict[str, Any]) -> bool:
	return bool(changes.get("fields") or changes.get("child_tables"))


def _group_rows(rows: list[dict[str, Any]], key_fields: tuple[str, ...]) -> dict[tuple[Any, ...], list[dict]]:
	groups: dict[tuple[Any, ...], list[dict]] = defaultdict(list)
	for index, row in enumerate(rows):
		key = tuple(row.get(fieldname) for fieldname in key_fields)
		if not any(value not in (None, "") for value in key):
			key = ("__row__", index)
		groups[key].append(row)
	return groups


def _normalized_row(row: Any, allowed_fields: set[str]) -> dict[str, Any]:
	values = {}
	for fieldname in sorted(allowed_fields):
		value = row.get(fieldname) if hasattr(row, "get") else None
		value = _normalized_value(value)
		if value not in (None, ""):
			values[fieldname] = value
	return values


def _row_changes(
	old: dict[str, Any], new: dict[str, Any], allowed_fields: set[str]
) -> dict[str, dict[str, Any]]:
	changes = {}
	for fieldname in sorted(allowed_fields):
		old_value = old.get(fieldname)
		new_value = new.get(fieldname)
		if old_value != new_value:
			changes[fieldname] = {
				"from": _audit_value(fieldname, old_value),
				"to": _audit_value(fieldname, new_value),
			}
	return changes


def _normalized_value(value: Any) -> Any:
	if value is None:
		return None
	if isinstance(value, (str, int, float, bool)):
		return value
	if hasattr(value, "isoformat"):
		return str(value)
	return str(value)


def _audit_value(fieldname: str, value: Any) -> Any:
	if fieldname in SENSITIVE_FIELDS and value not in (None, ""):
		return "[REDACTED]"
	return _normalized_value(value)


def _masked_row(row: dict[str, Any]) -> dict[str, Any]:
	return {fieldname: _audit_value(fieldname, value) for fieldname, value in row.items()}


def _canonical(row: dict[str, Any]) -> str:
	return json.dumps(row, sort_keys=True, separators=(",", ":"), default=str)
