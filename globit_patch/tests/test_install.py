from __future__ import annotations

import json
import unittest
from unittest.mock import MagicMock, patch

from globit_patch import hooks, install


class TestHooks(unittest.TestCase):
	def test_only_permission_safe_console_override_is_registered(self):
		self.assertFalse(hasattr(hooks, "override_doctype_class"))
		self.assertEqual(
			hooks.override_whitelisted_methods,
			{
				"vobiz_click_to_call.api.console.get_agent_console_data": (
					"globit_patch.api.vobiz_console.get_agent_console_data"
				)
			},
		)

	def test_setup_runs_after_install_and_migrate(self):
		setup = "globit_patch.install.setup_integrations"
		self.assertEqual(hooks.after_install, setup)
		self.assertEqual(hooks.after_migrate, setup)


class TestInstall(unittest.TestCase):
	@patch("globit_patch.install.setup_vobiz_patient_encounter_queue")
	@patch("globit_patch.install.position_patient_company_id")
	@patch("globit_patch.install.migrate_patient_encounter_identifiers")
	@patch("globit_patch.install.setup_patient_encounter_fields")
	@patch("globit_patch.install.setup_integration_settings")
	@patch("globit_patch.install.setup_integration_role")
	def test_setup_integrations_runs_all_steps(
		self, setup_role, setup_settings, setup_fields, migrate_fields, position_field, setup_queue
	):
		install.setup_integrations()

		setup_role.assert_called_once_with()
		setup_settings.assert_called_once_with()
		setup_fields.assert_called_once_with()
		migrate_fields.assert_called_once_with()
		position_field.assert_called_once_with()
		setup_queue.assert_called_once_with()

	@patch("globit_patch.install.frappe")
	def test_setup_integration_role_creates_missing_role(self, frappe):
		frappe.db.exists.return_value = False
		doc = frappe.get_doc.return_value

		install.setup_integration_role()

		frappe.get_doc.assert_called_once_with(
			{
				"doctype": "Role",
				"role_name": "Globit Integration User",
				"desk_access": 0,
				"is_custom": 0,
			}
		)
		doc.insert.assert_called_once_with(ignore_permissions=True)

	@patch("globit_patch.install.frappe")
	def test_setup_integration_settings_seeds_fail_closed_defaults(self, frappe):
		frappe.db.exists.return_value = True
		settings = MagicMock(configuration_initialized=0)
		frappe.get_single.return_value = settings

		install.setup_integration_settings()

		self.assertEqual(settings.enabled, 0)
		self.assertEqual(settings.dry_run, 1)
		self.assertEqual(settings.allowed_source_site, "eternityerp.m.frappe.cloud")
		self.assertEqual(settings.configuration_initialized, 1)
		settings.save.assert_called_once_with(ignore_permissions=True)

	@patch("globit_patch.install.create_custom_fields")
	def test_patient_encounter_fields_are_updated(self, create_custom_fields):
		install.setup_patient_encounter_fields()

		create_custom_fields.assert_called_once_with(install.PATIENT_ENCOUNTER_FIELDS, update=True)

	def test_patient_and_encounter_integration_field_labels(self):
		patient_fields = {
			field["fieldname"]: field for field in install.PATIENT_ENCOUNTER_FIELDS["Patient"]
		}
		encounter_fields = {
			field["fieldname"]: field
			for field in install.PATIENT_ENCOUNTER_FIELDS["Patient Encounter"]
		}

		self.assertEqual(patient_fields["company_id"]["label"], "Company ID")
		self.assertEqual(patient_fields["company_id"]["insert_after"], "created_by_agent")
		self.assertEqual(encounter_fields["company_id"]["label"], "Company ID")
		self.assertEqual(encounter_fields["reference_id"]["label"], "Reference ID")
		self.assertNotIn("channel_id", encounter_fields)
		self.assertNotIn("doc_id", encounter_fields)

	@patch("globit_patch.install.frappe")
	def test_legacy_encounter_identifiers_are_copied_and_removed(self, frappe):
		frappe.db.has_column.return_value = True
		frappe.db.exists.return_value = True

		install.migrate_patient_encounter_identifiers()

		self.assertEqual(frappe.db.sql.call_count, 2)
		self.assertEqual(frappe.delete_doc.call_count, 2)
		frappe.delete_doc.assert_any_call(
			"Custom Field",
			"Patient Encounter-channel_id",
			force=True,
			ignore_permissions=True,
			ignore_missing=True,
		)
		frappe.delete_doc.assert_any_call(
			"Custom Field",
			"Patient Encounter-doc_id",
			force=True,
			ignore_permissions=True,
			ignore_missing=True,
		)
		frappe.clear_cache.assert_called_once_with(doctype="Patient Encounter")

	@patch("globit_patch.install.frappe")
	def test_patient_company_id_is_positioned_after_created_by(self, frappe):
		frappe.get_meta.return_value.fields = [
			MagicMock(fieldname="first_name"),
			MagicMock(fieldname="created_by_agent"),
			MagicMock(fieldname="customer"),
			MagicMock(fieldname="company_id"),
		]
		frappe.db.get_value.return_value = "Patient-main-field_order"

		install.position_patient_company_id()

		value = frappe.db.set_value.call_args.args[3]
		self.assertEqual(
			json.loads(value),
			["first_name", "created_by_agent", "company_id", "customer"],
		)
		frappe.clear_cache.assert_called_once_with(doctype="Patient")

	@patch("globit_patch.install.remove_legacy_queue_source_property_setter")
	@patch("globit_patch.install.validate_vobiz_capabilities")
	@patch("globit_patch.install.frappe")
	def test_queue_setup_removes_legacy_setter_and_merges_allowed_doctypes(
		self,
		frappe,
		validate_capabilities,
		remove_legacy_setter,
	):
		frappe.db.exists.side_effect = lambda doctype, name: name in {
			"Vobiz User Mapping",
			"Vobiz Settings",
		}
		settings = MagicMock(allowed_doctypes="CRM Lead\nPatient")
		frappe.get_single.return_value = settings

		install.setup_vobiz_patient_encounter_queue()

		remove_legacy_setter.assert_called_once_with()
		frappe.clear_cache.assert_called_once_with(doctype="Vobiz User Mapping")
		validate_capabilities.assert_called_once_with()
		self.assertEqual(settings.allowed_doctypes, "CRM Lead\nPatient\nPatient Encounter")
		settings.save.assert_called_once_with(ignore_permissions=True)

	@patch("globit_patch.install.remove_legacy_queue_source_property_setter")
	@patch("globit_patch.install.validate_vobiz_capabilities")
	@patch("globit_patch.install.frappe")
	def test_queue_setup_does_not_duplicate_allowed_doctype(
		self,
		frappe,
		_validate_capabilities,
		_remove_legacy_setter,
	):
		frappe.db.exists.return_value = True
		settings = MagicMock(allowed_doctypes="Patient Encounter\nPatient")
		frappe.get_single.return_value = settings

		install.setup_vobiz_patient_encounter_queue()

		settings.save.assert_not_called()

	@patch("globit_patch.install.frappe")
	def test_legacy_property_setter_is_removed(self, frappe):
		frappe.db.get_value.return_value = "Vobiz User Mapping-queue_source-options"

		install.remove_legacy_queue_source_property_setter()

		frappe.db.get_value.assert_called_once_with(
			"Property Setter",
			{
				"doc_type": "Vobiz User Mapping",
				"field_name": "queue_source",
				"property": "options",
				"value": install.LEGACY_QUEUE_SOURCE_OPTIONS,
			},
			"name",
		)
		frappe.delete_doc.assert_called_once_with(
			"Property Setter",
			"Vobiz User Mapping-queue_source-options",
			force=True,
			ignore_permissions=True,
			ignore_missing=True,
		)

	@patch("globit_patch.install.frappe")
	def test_custom_property_setter_is_preserved(self, frappe):
		frappe.db.get_value.return_value = None

		install.remove_legacy_queue_source_property_setter()

		frappe.delete_doc.assert_not_called()

	@patch("globit_patch.install.frappe")
	def test_vobiz_capability_validation_accepts_native_contract(self, frappe):
		queue_source = MagicMock(options="CRM Lead\nPatient Encounter")
		frappe.get_meta.return_value.get_field.return_value = queue_source

		install.validate_vobiz_capabilities()

		frappe.throw.assert_not_called()

	@patch("globit_patch.install.frappe")
	def test_vobiz_capability_validation_rejects_missing_queue_source(self, frappe):
		queue_source = MagicMock(options="CRM Lead\nPatient")
		frappe.get_meta.return_value.get_field.return_value = queue_source
		frappe.throw.side_effect = RuntimeError("incompatible")

		with self.assertRaisesRegex(RuntimeError, "incompatible"):
			install.validate_vobiz_capabilities()

		message = frappe.throw.call_args.args[0]
		self.assertIn("Patient Encounter is not a native Queue Source", message)

	@patch(
		"vobiz_click_to_call.api.console.get_agent_console_data",
		new=lambda limit=25: {},
	)
	@patch("globit_patch.install.frappe")
	def test_vobiz_capability_validation_rejects_incomplete_console_api(self, frappe):
		queue_source = MagicMock(options="CRM Lead\nPatient Encounter")
		frappe.get_meta.return_value.get_field.return_value = queue_source
		frappe.throw.side_effect = RuntimeError("incompatible")

		with self.assertRaisesRegex(RuntimeError, "incompatible"):
			install.validate_vobiz_capabilities()

		message = frappe.throw.call_args.args[0]
		self.assertIn("console API is missing parameters", message)
		self.assertIn("queue_source_filter", message)


if __name__ == "__main__":
	unittest.main()
