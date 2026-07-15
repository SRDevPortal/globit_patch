from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any

import frappe

from globit_patch.integrations.globifit.exceptions import ContractError


SUPPORTED_SOURCE_DOCTYPE = "Patient Encounter"
REQUIRED_ENCOUNTER_FIELDS = (
	"name",
	"modified",
	"patient",
	"patient_name",
	"patient_sex",
	"sr_pe_mobile",
	"sr_pe_deptt",
	"company",
	"encounter_date",
	"encounter_time",
	"sr_encounter_type",
)
CHILD_TABLE_FIELDS = (
	"sr_pe_order_items",
	"enc_multi_payments",
	"sr_allopathy_drug_prescription",
)


@dataclass(frozen=True)
class SyncPayload:
	schema_version: int
	event_id: str
	trace_id: str
	idempotency_key: str
	payload_hash: str
	source_site: str
	source_doctype: str
	source_name: str
	source_modified: str
	encounter: dict[str, Any]

	@property
	def source_patient(self) -> str:
		return str(self.encounter["patient"])


def parse_payload(
	value: Any,
	*,
	allowed_versions: set[int],
	allowed_source_sites: set[str] | None = None,
	allowed_source_site: str | None = None,
) -> SyncPayload:
	"""Validate a sync payload against the configured source allowlist.

	``allowed_source_site`` remains accepted for callers upgrading from the
	single-site contract.
	"""
	configured_sites = allowed_source_sites or parse_allowed_source_sites(allowed_source_site)
	if isinstance(value, str):
		try:
			value = json.loads(value)
		except (TypeError, ValueError) as exc:
			raise ContractError("Payload must contain valid JSON.") from exc
	if not isinstance(value, dict):
		raise ContractError("Payload must be a JSON object.")

	try:
		schema_version = int(value.get("schema_version"))
	except (TypeError, ValueError) as exc:
		raise ContractError("schema_version must be an integer.") from exc
	if schema_version not in allowed_versions:
		raise ContractError("Unsupported schema_version.", code="UNSUPPORTED_SCHEMA_VERSION")

	source = value.get("source")
	encounter = value.get("encounter")
	if not isinstance(source, dict) or not isinstance(encounter, dict):
		raise ContractError("source and encounter must be JSON objects.")

	source_site = normalize_source_site(_required_text(source, "site"))
	source_doctype = _required_text(source, "doctype")
	source_name = _required_text(source, "name")
	source_modified = _required_text(source, "modified")
	if source_site not in {normalize_source_site(site) for site in configured_sites}:
		raise ContractError("Source site is not allowed.", code="SOURCE_NOT_ALLOWED")
	if source_doctype != SUPPORTED_SOURCE_DOCTYPE:
		raise ContractError("Source DocType must be Patient Encounter.", code="INVALID_SOURCE_DOCTYPE")
	if source_name != str(encounter.get("name") or "").strip():
		raise ContractError("Source name does not match encounter.name.", code="SOURCE_NAME_MISMATCH")
	if source_modified != str(encounter.get("modified") or "").strip():
		raise ContractError("Source modified does not match encounter.modified.", code="SOURCE_VERSION_MISMATCH")

	for fieldname in REQUIRED_ENCOUNTER_FIELDS:
		if encounter.get(fieldname) in (None, ""):
			raise ContractError(f"encounter.{fieldname} is required.", code="MISSING_REQUIRED_FIELD")
	if len(re.sub(r"\D", "", str(encounter.get("sr_pe_mobile")))) < 10:
		raise ContractError(
			"encounter.sr_pe_mobile must contain at least 10 digits.",
			code="INVALID_MOBILE",
		)
	for fieldname in CHILD_TABLE_FIELDS:
		if encounter.get(fieldname) is not None and not isinstance(encounter.get(fieldname), list):
			raise ContractError(f"encounter.{fieldname} must be an array.", code="INVALID_CHILD_TABLE")

	try:
		frappe.utils.get_datetime(source_modified)
	except Exception as exc:
		raise ContractError("source.modified must be a valid datetime.") from exc

	computed_idempotency_key = entity_key(source_site, source_doctype, source_name)
	provided_idempotency_key = str(value.get("idempotency_key") or computed_idempotency_key).strip()
	if provided_idempotency_key != computed_idempotency_key:
		raise ContractError("idempotency_key does not match the source identity.", code="INVALID_IDEMPOTENCY_KEY")

	computed_payload_hash = payload_hash(schema_version, source, encounter)
	provided_payload_hash = str(value.get("payload_hash") or computed_payload_hash).strip()
	if provided_payload_hash != computed_payload_hash:
		raise ContractError("payload_hash does not match the request content.", code="INVALID_PAYLOAD_HASH")

	return SyncPayload(
		schema_version=schema_version,
		event_id=_required_text(value, "event_id"),
		trace_id=str(value.get("trace_id") or value.get("event_id") or "").strip(),
		idempotency_key=computed_idempotency_key,
		payload_hash=computed_payload_hash,
		source_site=source_site,
		source_doctype=source_doctype,
		source_name=source_name,
		source_modified=source_modified,
		encounter=encounter,
	)


def entity_key(source_site: str, source_doctype: str, source_name: str) -> str:
	identity = "|".join((source_site.lower().rstrip("/"), source_doctype, source_name))
	return hashlib.sha256(identity.encode()).hexdigest()


def payload_hash(schema_version: int, source: dict[str, Any], encounter: dict[str, Any]) -> str:
	canonical = json.dumps(
		{"schema_version": schema_version, "source": source, "encounter": encounter},
		sort_keys=True,
		separators=(",", ":"),
		default=str,
	)
	return hashlib.sha256(canonical.encode()).hexdigest()


def parse_allowed_source_sites(value: str | None) -> set[str]:
	"""Return normalized source hostnames from newline- or comma-separated settings."""
	sites = set()
	for row in str(value or "").replace(",", "\n").splitlines():
		if row.strip():
			sites.add(normalize_source_site(row))
	return sites


def normalize_source_site(value: str) -> str:
	site = str(value or "").strip().lower()
	site = re.sub(r"^https?://", "", site).rstrip("/")
	if not site or not re.fullmatch(r"[a-z0-9.-]+(?::\d{1,5})?", site):
		raise ContractError("source.site must be a valid hostname.", code="INVALID_SOURCE_SITE")
	return site


def _required_text(values: dict[str, Any], key: str) -> str:
	value = str(values.get(key) or "").strip()
	if not value:
		raise ContractError(f"{key} is required.", code="MISSING_REQUIRED_FIELD")
	return value
