from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from globit_patch.patches import backfill_patient_company_id


class TestPatientCompanyIdPatch(unittest.TestCase):
	@patch("globit_patch.patches.backfill_patient_company_id.frappe")
	def test_blank_patient_is_backfilled_from_consistent_history(self, frappe):
		frappe.db.has_column.return_value = True
		frappe.db.exists.return_value = True
		frappe.db.get_value.return_value = ""
		frappe.get_all.side_effect = [
			[
				SimpleNamespace(
					source_site="https://SOURCE.EXAMPLE.COM/",
					destination_name="PAT-1",
				)
			],
			[
				SimpleNamespace(
					patient="PAT-1",
					company_id="source.example.com",
					get=lambda fieldname: "source.example.com" if fieldname == "company_id" else None,
				)
			],
		]

		backfill_patient_company_id.execute()

		frappe.db.set_value.assert_called_once_with(
			"Patient",
			"PAT-1",
			"company_id",
			"source.example.com",
			update_modified=False,
		)

	@patch("globit_patch.patches.backfill_patient_company_id.frappe")
	def test_conflicting_history_is_not_guessed(self, frappe):
		frappe.db.has_column.return_value = True
		frappe.db.exists.return_value = True
		frappe.get_all.side_effect = [
			[SimpleNamespace(source_site="one.example.com", destination_name="PAT-1")],
			[
				SimpleNamespace(
					patient="PAT-1",
					company_id="two.example.com",
					get=lambda fieldname: "two.example.com" if fieldname == "company_id" else None,
				)
			],
		]

		backfill_patient_company_id.execute()

		frappe.db.set_value.assert_not_called()
		frappe.logger.return_value.warning.assert_called_once()

	@patch("globit_patch.patches.backfill_patient_company_id.frappe")
	def test_existing_company_id_is_preserved(self, frappe):
		frappe.db.has_column.return_value = True
		frappe.db.exists.return_value = True
		frappe.db.get_value.return_value = "existing.example.com"
		frappe.get_all.side_effect = [
			[SimpleNamespace(source_site="source.example.com", destination_name="PAT-1")],
			[],
		]

		backfill_patient_company_id.execute()

		frappe.db.set_value.assert_not_called()
