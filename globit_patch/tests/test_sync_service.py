from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

import frappe

from globit_patch.integrations.globifit.contract import parse_payload
from globit_patch.integrations.globifit.exceptions import PatientIdentityConflict, SyncError
from globit_patch.integrations.globifit.patient_identity import PatientResolution
from globit_patch.integrations.globifit.sync_service import (
	_dry_run,
	_encounter_values,
	_mapped_replay,
	_save_patient,
	_sync_encounter,
)
from globit_patch.tests.test_sync_contract import valid_payload


class TestSyncService(unittest.TestCase):
	@patch("globit_patch.integrations.globifit.sync_service.save_external_mapping")
	@patch("globit_patch.integrations.globifit.sync_service._encounter_values")
	@patch("globit_patch.integrations.globifit.sync_service.get_external_mapping")
	@patch("globit_patch.integrations.globifit.sync_service.frappe")
	def test_semantically_identical_encounter_is_not_saved(
		self, frappe, get_mapping, encounter_values, save_mapping
	):
		class Encounter(dict):
			name = "ENC-TARGET-1"
			docstatus = 0
			saved = False

			def set(self, fieldname, value):
				self[fieldname] = value

			def save(self, **_kwargs):
				self.saved = True

		payload = parse_payload(
			valid_payload(),
			allowed_source_site="eternityerp.m.frappe.cloud",
			allowed_versions={1},
		)
		desired = {
			"patient": "PAT-TARGET-1",
			"patient_name": "Test Patient",
			"sr_pe_order_items": [{"sr_item_code": "ITEM-1", "sr_item_qty": 1}],
			"enc_multi_payments": [],
			"sr_allopathy_drug_prescription": [],
		}
		doc = Encounter(desired)
		get_mapping.return_value = SimpleNamespace(
			destination_doctype="Patient Encounter",
			destination_name=doc.name,
			last_source_modified=None,
			get=lambda key, default=None: getattr(get_mapping.return_value, key, default),
		)
		frappe.db.exists.return_value = True
		frappe.get_doc.return_value = doc
		encounter_values.return_value = desired

		result, action, changes = _sync_encounter(
			payload, SimpleNamespace(), SimpleNamespace(name="PAT-TARGET-1")
		)

		self.assertIs(result, doc)
		self.assertEqual(action, "unchanged")
		self.assertEqual(changes, {"fields": {}, "child_tables": {}})
		self.assertFalse(doc.saved)
		save_mapping.assert_called_once()

	@patch("globit_patch.integrations.globifit.sync_service.map_prescriptions", return_value=[])
	@patch("globit_patch.integrations.globifit.sync_service.map_payments", return_value=[])
	@patch("globit_patch.integrations.globifit.sync_service.map_order_items", return_value=[])
	@patch("globit_patch.integrations.globifit.sync_service.resolve_link")
	def test_online_encounter_requires_and_maps_encounter_source(
		self, resolve_link, _order_items, _payments, _prescriptions
	):
		value = valid_payload()
		value["encounter"]["sr_encounter_place"] = "Online"
		value["encounter"]["sr_encounter_source"] = "SRC-00069"
		value.pop("payload_hash")
		payload = parse_payload(
			value,
			allowed_source_site="eternityerp.m.frappe.cloud",
			allowed_versions={1},
		)

		def map_value(_source_doctype, source_value, destination_doctype, *, required=False):
			if destination_doctype == "SR Encounter Place":
				return "Online"
			if destination_doctype == "SR Lead Source":
				self.assertTrue(required)
				return "SRC-DESTINATION"
			return str(source_value or "")

		resolve_link.side_effect = map_value
		values = _encounter_values(
			payload,
			SimpleNamespace(default_encounter_place="OPD"),
			SimpleNamespace(name="PAT-1", patient_name="Test Patient", first_name="Test"),
		)

		self.assertEqual(values["sr_encounter_source"], "SRC-DESTINATION")
		self.assertEqual(values["patient_name"], "Test Patient")

	def test_linked_mobile_validation_is_a_patient_identity_conflict(self):
		patient = SimpleNamespace(
			save=lambda **_kwargs: (_ for _ in ()).throw(
				frappe.ValidationError("Mobile already linked with Contact CONTACT-1")
			)
		)

		with self.assertRaises(PatientIdentityConflict):
			_save_patient(patient)

	def test_other_patient_validation_is_structured(self):
		patient = SimpleNamespace(
			save=lambda **_kwargs: (_ for _ in ()).throw(frappe.ValidationError("Invalid Patient"))
		)

		with self.assertRaises(SyncError) as error:
			_save_patient(patient)

		self.assertEqual(error.exception.code, "DESTINATION_PATIENT_VALIDATION_FAILED")

	@patch("globit_patch.integrations.globifit.sync_service._sync_encounter")
	@patch("globit_patch.integrations.globifit.sync_service._sync_patient")
	@patch("globit_patch.integrations.globifit.sync_service.frappe")
	def test_dry_run_executes_validation_and_rolls_back(self, frappe, sync_patient, sync_encounter):
		payload = parse_payload(
			valid_payload(),
			allowed_source_site="eternityerp.m.frappe.cloud",
			allowed_versions={1},
		)
		patient = SimpleNamespace(name="PAT-TARGET-1")
		encounter = SimpleNamespace(name="ENC-TARGET-1")
		empty_changes = {"fields": {}, "child_tables": {}}
		sync_patient.return_value = (patient, "created", PatientResolution(patient, "Created"), empty_changes)
		sync_encounter.return_value = (encounter, "created", empty_changes)

		result = _dry_run(payload, SimpleNamespace())

		self.assertEqual(result["action"], "dry_run")
		self.assertEqual(result["patient"], "PAT-TARGET-1")
		frappe.db.savepoint.assert_called_once_with("globit_patient_encounter_dry_run")
		frappe.db.rollback.assert_called_once_with(save_point="globit_patient_encounter_dry_run")

	@patch("globit_patch.integrations.globifit.sync_service.get_external_mapping")
	@patch("globit_patch.integrations.globifit.sync_service.frappe")
	def test_same_entity_payload_is_replayed_without_writes(self, frappe, get_mapping):
		payload = parse_payload(
			valid_payload(),
			allowed_source_site="eternityerp.m.frappe.cloud",
			allowed_versions={1},
		)
		get_mapping.side_effect = [
			{
				"destination_name": "ENC-TARGET-1",
				"last_payload_hash": payload.payload_hash,
			},
			{"destination_name": "PAT-TARGET-1"},
		]
		frappe.db.exists.return_value = True
		frappe.get_doc.side_effect = lambda doctype, name: SimpleNamespace(doctype=doctype, name=name)

		patient, encounter = _mapped_replay(payload)

		self.assertEqual(patient.name, "PAT-TARGET-1")
		self.assertEqual(encounter.name, "ENC-TARGET-1")

	@patch("globit_patch.integrations.globifit.sync_service.get_external_mapping")
	@patch("globit_patch.integrations.globifit.sync_service.frappe")
	def test_changed_payload_is_not_treated_as_replay(self, frappe, get_mapping):
		payload = parse_payload(
			valid_payload(),
			allowed_source_site="eternityerp.m.frappe.cloud",
			allowed_versions={1},
		)
		get_mapping.return_value = {
			"destination_name": "ENC-TARGET-1",
			"last_payload_hash": "different",
		}

		self.assertIsNone(_mapped_replay(payload))
		frappe.get_doc.assert_not_called()
