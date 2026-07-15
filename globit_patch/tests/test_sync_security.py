from __future__ import annotations

import hashlib
import hmac
import unittest
from unittest.mock import MagicMock, patch

from globit_patch.integrations.globifit.exceptions import SecurityError
from globit_patch.integrations.globifit.security import verify_signed_request


class TestSyncSecurity(unittest.TestCase):
	@patch("globit_patch.integrations.globifit.security.time.time", return_value=1_700_000_000)
	@patch("globit_patch.integrations.globifit.security.frappe")
	def test_valid_signature_is_accepted(self, frappe, _time):
		raw = b'{"event_id":"event-1"}'
		timestamp = "1700000000"
		secret = "test-secret"
		signature = hmac.new(
			secret.encode(),
			timestamp.encode() + b"\nevent-1\n" + raw,
			hashlib.sha256,
		).hexdigest()
		settings = MagicMock(maximum_payload_bytes=1024, signature_tolerance_seconds=300)
		settings.get_password.return_value = secret
		frappe.conf.get.return_value = None

		verify_signed_request(
			raw_body=raw,
			headers={"X-Globit-Timestamp": timestamp, "X-Globit-Signature": f"sha256={signature}"},
			settings=settings,
			event_id="event-1",
		)

	@patch("globit_patch.integrations.globifit.security.time.time", return_value=1_700_000_000)
	@patch("globit_patch.integrations.globifit.security.frappe")
	def test_expired_signature_is_rejected(self, frappe, _time):
		settings = MagicMock(maximum_payload_bytes=1024, signature_tolerance_seconds=300)

		with self.assertRaisesRegex(SecurityError, "expired"):
			verify_signed_request(
				raw_body=b"{}",
				headers={"X-Globit-Timestamp": "1600000000", "X-Globit-Signature": "invalid"},
				settings=settings,
				event_id="event-1",
			)

		frappe.conf.get.assert_not_called()

	@patch("globit_patch.integrations.globifit.security.frappe")
	def test_oversized_payload_is_rejected_before_signature_work(self, frappe):
		settings = MagicMock(maximum_payload_bytes=3)

		with self.assertRaisesRegex(SecurityError, "too large"):
			verify_signed_request(raw_body=b"1234", headers={}, settings=settings, event_id="event-1")

		frappe.conf.get.assert_not_called()
