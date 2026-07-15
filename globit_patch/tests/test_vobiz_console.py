from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from globit_patch.api import vobiz_console


class TestVobizConsole(unittest.TestCase):
	@patch("globit_patch.api.vobiz_console.get_vobiz_console_data")
	def test_wrapper_forwards_current_and_future_arguments(self, get_vobiz_console_data):
		data = {"queue_meta": {"doctype": "CRM Lead"}, "queue": []}
		get_vobiz_console_data.return_value = data

		result = vobiz_console.get_agent_console_data(
			limit=500,
			search="Ada",
			followup_day="Today",
			queue_source_filter="CRM Lead",
			sort_by="modified_desc",
			filters='[["CRM Lead", "status", "=", "Open"]]',
			future_option="compact",
		)

		self.assertIs(result, data)
		get_vobiz_console_data.assert_called_once_with(
			limit=500,
			search="Ada",
			followup_day="Today",
			queue_source_filter="CRM Lead",
			sort_by="modified_desc",
			filters='[["CRM Lead", "status", "=", "Open"]]',
			future_option="compact",
		)

	@patch("globit_patch.api.vobiz_console.get_vobiz_console_data")
	@patch("globit_patch.api.vobiz_console.frappe")
	def test_non_encounter_queue_is_unchanged(self, frappe, get_vobiz_console_data):
		data = {"queue_meta": {"doctype": "Patient"}, "queue": [{"name": "PAT-1"}]}
		get_vobiz_console_data.return_value = data

		result = vobiz_console.get_agent_console_data()

		self.assertIs(result, data)
		frappe.get_list.assert_not_called()

	@patch("globit_patch.api.vobiz_console.get_vobiz_console_data")
	@patch("globit_patch.api.vobiz_console.frappe")
	def test_encounter_queue_preserves_order_and_filters_access(self, frappe, get_vobiz_console_data):
		data = {
			"queue_meta": {"doctype": "Patient Encounter"},
			"queue": [{"name": "PE-1"}, {"name": "PE-2"}, {"name": "PE-3"}],
		}
		get_vobiz_console_data.return_value = data
		frappe.db.exists.return_value = True
		frappe.get_meta.return_value.has_field.return_value = True
		frappe.session.user = "agent@example.com"
		frappe.get_roles.return_value = ["Vobiz Agent"]
		frappe.get_list.return_value = ["PE-3", "PE-1"]

		result = vobiz_console.get_agent_console_data()

		self.assertEqual(result["queue"], [{"name": "PE-1"}, {"name": "PE-3"}])
		frappe.get_list.assert_called_once_with(
			"Patient Encounter",
			filters={
				"name": ["in", ["PE-1", "PE-2", "PE-3"]],
				"created_by_agent": "agent@example.com",
			},
			pluck="name",
			limit_page_length=3,
		)

	@patch("globit_patch.api.vobiz_console.frappe")
	def test_system_manager_is_not_restricted_by_agent_owner(self, frappe):
		frappe.db.exists.return_value = True
		frappe.get_meta.return_value.has_field.return_value = True
		frappe.session.user = "manager@example.com"
		frappe.get_roles.return_value = ["System Manager"]
		frappe.get_list.return_value = ["PE-1"]

		result = vobiz_console._permitted_patient_encounters([{"name": "PE-1"}])

		self.assertEqual(result, [{"name": "PE-1"}])
		filters = frappe.get_list.call_args.kwargs["filters"]
		self.assertNotIn("created_by_agent", filters)


if __name__ == "__main__":
	unittest.main()
