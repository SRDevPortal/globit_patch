from __future__ import annotations

import hashlib
import hmac
import time
from typing import Any

import frappe

from globit_patch.integrations.globifit.exceptions import SecurityError


def verify_signed_request(
	*,
	raw_body: bytes,
	headers: Any,
	settings: Any,
	event_id: str,
) -> None:
	max_bytes = int(settings.maximum_payload_bytes or 1048576)
	if len(raw_body) > max_bytes:
		raise SecurityError("Request payload is too large.", code="PAYLOAD_TOO_LARGE", http_status=413)

	timestamp = str(headers.get("X-Globit-Timestamp") or "").strip()
	provided_signature = str(headers.get("X-Globit-Signature") or "").strip()
	if not timestamp or not provided_signature:
		raise SecurityError("Required signature headers are missing.")
	try:
		timestamp_value = int(timestamp)
	except ValueError as exc:
		raise SecurityError("Signature timestamp is invalid.") from exc
	tolerance = max(30, int(settings.signature_tolerance_seconds or 300))
	if abs(int(time.time()) - timestamp_value) > tolerance:
		raise SecurityError("Signature timestamp has expired.", code="SIGNATURE_EXPIRED")

	secret = frappe.conf.get("globit_sync_signing_secret") or _settings_secret(settings)
	if not secret:
		raise SecurityError("Destination signing secret is not configured.", code="SIGNING_SECRET_MISSING", http_status=503)
	message = timestamp.encode() + b"\n" + event_id.encode() + b"\n" + raw_body
	expected = hmac.new(str(secret).encode(), message, hashlib.sha256).hexdigest()
	provided = provided_signature.removeprefix("sha256=")
	if not hmac.compare_digest(expected, provided):
		raise SecurityError("Request signature is invalid.")


def _settings_secret(settings: Any) -> str:
	try:
		return settings.get_password("signing_secret") or ""
	except Exception:
		return ""
