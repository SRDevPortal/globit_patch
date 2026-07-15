from __future__ import annotations

import json
from typing import Any

import frappe

from globit_patch.integrations.globifit.contract import parse_allowed_source_sites, parse_payload
from globit_patch.integrations.globifit.exceptions import SecurityError, SyncError
from globit_patch.integrations.globifit.security import verify_signed_request
from globit_patch.integrations.globifit.sync_service import synchronize


@frappe.whitelist(methods=["POST"])
def sync_patient_encounter(payload: dict[str, Any] | str | None = None, **kwargs: Any) -> dict[str, Any]:
	"""Synchronize one trusted source Patient Encounter into this destination site."""
	frappe.only_for("Globit Integration User")
	settings = frappe.get_single("Globit Integration Settings")
	if not settings.enabled:
		return _error_response(
			SyncError("Patient Encounter synchronization is disabled.", code="INTEGRATION_DISABLED", http_status=503)
		)

	raw_body = frappe.request.get_data(cache=True) if getattr(frappe.local, "request", None) else b""
	request_value: dict[str, Any] = {}
	event_id = str(frappe.request.headers.get("X-Globit-Event-ID") or "").strip()
	try:
		if not event_id:
			raise SecurityError("X-Globit-Event-ID is required.", code="MISSING_EVENT_ID_HEADER")
		verify_signed_request(
			raw_body=raw_body,
			headers=frappe.request.headers,
			settings=settings,
			event_id=event_id,
		)
		request_value = _request_value(payload, kwargs, raw_body)
		payload_event_id = str(request_value.get("event_id") or "").strip()
		if not payload_event_id:
			raise SyncError("event_id is required.", code="MISSING_EVENT_ID", http_status=422)
		if payload_event_id != event_id:
			raise SecurityError("Event ID header does not match the payload.", code="EVENT_ID_MISMATCH")
		parsed = parse_payload(
			request_value,
			allowed_source_sites=parse_allowed_source_sites(settings.allowed_source_site),
			allowed_versions=_allowed_versions(settings.allowed_schema_versions),
		)
		return synchronize(parsed, settings)
	except SyncError as exc:
		return _error_response(exc, event_id=event_id, trace_id=request_value.get("trace_id"))
	except Exception:
		frappe.log_error(title="Globit Patient Encounter synchronization failed")
		return _error_response(
			SyncError("Unexpected destination processing error.", code="INTERNAL_ERROR", http_status=500),
			event_id=event_id,
			trace_id=request_value.get("trace_id"),
		)


def _request_value(payload: Any, kwargs: dict[str, Any], raw_body: bytes) -> dict[str, Any]:
	if payload is not None:
		if isinstance(payload, str):
			try:
				payload = json.loads(payload)
			except (TypeError, ValueError):
				return {}
		return payload if isinstance(payload, dict) else {}
	if kwargs:
		return dict(kwargs)
	try:
		value = json.loads(raw_body.decode())
	except (UnicodeDecodeError, ValueError):
		return {}
	if isinstance(value, dict) and isinstance(value.get("payload"), dict):
		return value["payload"]
	return value if isinstance(value, dict) else {}


def _allowed_versions(value: str | None) -> set[int]:
	versions = set()
	for row in str(value or "1").replace(",", "\n").splitlines():
		try:
			versions.add(int(row.strip()))
		except (TypeError, ValueError):
			continue
	return versions or {1}


def _error_response(error: SyncError, *, event_id: str = "", trace_id: Any = "") -> dict[str, Any]:
	frappe.local.response.http_status_code = error.http_status
	return {
		"ok": False,
		"error_code": error.code,
		"message": error.message,
		"requires_manual_review": error.requires_manual_review,
		"event_id": event_id,
		"trace_id": str(trace_id or ""),
	}
