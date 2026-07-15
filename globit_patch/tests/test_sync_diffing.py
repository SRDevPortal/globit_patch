from __future__ import annotations

import unittest

from globit_patch.integrations.globifit.diffing import (
	audit_count,
	audit_paths,
	document_changes,
	field_changes,
	has_changes,
)


class TestSyncDiffing(unittest.TestCase):
	def test_identical_child_business_values_ignore_frappe_metadata(self):
		document = {
			"status": "Draft",
			"items": [{"name": "ROW-OLD", "modified": "yesterday", "item_code": "TDF", "qty": 1}],
		}
		desired = {
			"status": "Draft",
			"items": [{"name": "ROW-NEW", "modified": "today", "item_code": "TDF", "qty": 1}],
		}

		changes = document_changes(
			document,
			desired,
			{"items": ({"item_code", "qty"}, ("item_code",))},
		)

		self.assertFalse(has_changes(changes))

	def test_scalar_and_child_changes_are_audited(self):
		document = {"status": "Draft", "items": [{"item_code": "TDF", "qty": 1}]}
		desired = {"status": "Open", "items": [{"item_code": "TDF", "qty": 2}]}

		changes = document_changes(
			document,
			desired,
			{"items": ({"item_code", "qty"}, ("item_code",))},
		)
		audit = {"encounter": changes}

		self.assertEqual(changes["fields"]["status"], {"from": "Draft", "to": "Open"})
		self.assertEqual(changes["child_tables"]["items"]["changed"][0]["fields"]["qty"]["to"], 2)
		self.assertEqual(audit_count(audit), 2)
		self.assertEqual(audit_paths(audit), ["encounter.status", "encounter.items.qty"])

	def test_sensitive_values_are_redacted(self):
		changes = field_changes({"mobile": "9999999999"}, {"mobile": "8888888888"})

		self.assertEqual(changes["mobile"], {"from": "[REDACTED]", "to": "[REDACTED]"})
