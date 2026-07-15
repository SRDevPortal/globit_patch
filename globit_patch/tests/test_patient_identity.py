from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from globit_patch.integrations.globifit.exceptions import PatientIdentityConflict
from globit_patch.integrations.globifit.patient_identity import normalize_mobile, resolve_patient


class TestPatientIdentity(unittest.TestCase):
	def test_mobile_is_normalized_to_last_ten_digits(self):
		self.assertEqual(normalize_mobile("+91 98765-43210"), "9876543210")

	@patch("globit_patch.integrations.globifit.patient_identity._linked_entities")
	@patch("globit_patch.integrations.globifit.patient_identity._contacts_by_mobile")
	@patch("globit_patch.integrations.globifit.patient_identity.get_external_mapping")
	@patch("globit_patch.integrations.globifit.patient_identity.frappe")
	def test_contact_linked_patient_is_reused(self, frappe, mapping, contacts, linked_entities):
		mapping.return_value = None
		contacts.return_value = [SimpleNamespace(name="CONTACT-1")]
		linked_entities.side_effect = lambda _contacts, doctype: ["PAT-1"] if doctype == "Patient" else []
		frappe.get_all.return_value = []
		frappe.get_doc.return_value = MagicMock(name="patient")
		frappe.get_doc.return_value.name = "PAT-1"
		frappe.get_all.side_effect = lambda doctype, **_kwargs: (
			[{"name": "PAT-1", "patient_name": "Test Patient", "sex": "Female"}]
			if doctype == "Patient"
			else []
		)

		result = resolve_patient(
			source_site="eternityerp.m.frappe.cloud",
			source_patient="SRC-PAT-1",
			patient_name="Test Patient",
			sex="Female",
			mobile="9876543210",
			allow_automatic_matching=True,
		)

		self.assertEqual(result.method, "Contact Link")
		self.assertEqual(result.matched_contact, "CONTACT-1")
		frappe.get_doc.assert_called_once_with("Patient", "PAT-1")

	@patch("globit_patch.integrations.globifit.patient_identity._linked_entities", return_value=[])
	@patch("globit_patch.integrations.globifit.patient_identity._contacts_by_mobile")
	@patch("globit_patch.integrations.globifit.patient_identity.get_external_mapping", return_value=None)
	@patch("globit_patch.integrations.globifit.patient_identity.frappe")
	def test_unlinked_contact_returns_structured_conflict(self, frappe, _mapping, contacts, _linked):
		contacts.return_value = [SimpleNamespace(name="CONTACT-1")]
		frappe.get_all.return_value = []

		with self.assertRaises(PatientIdentityConflict) as error:
			resolve_patient(
				source_site="eternityerp.m.frappe.cloud",
				source_patient="SRC-PAT-1",
				patient_name="Test Patient",
				sex="Female",
				mobile="9876543210",
				allow_automatic_matching=True,
			)

		self.assertEqual(error.exception.code, "PATIENT_IDENTITY_CONFLICT")
		self.assertEqual(error.exception.http_status, 409)
