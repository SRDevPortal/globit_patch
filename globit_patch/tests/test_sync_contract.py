from __future__ import annotations

import unittest

from globit_patch.integrations.globifit.contract import (
	entity_key,
	parse_allowed_source_sites,
	parse_payload,
	payload_hash,
)
from globit_patch.integrations.globifit.exceptions import ContractError


def valid_payload() -> dict:
	encounter = {
		"name": "ENC-0001",
		"modified": "2026-07-15 12:30:00",
		"patient": "SRC-PAT-1",
		"patient_name": "Test Patient",
		"patient_sex": "Female",
		"sr_pe_mobile": "+91 99999 99999",
		"sr_pe_deptt": "General",
		"company": "Globifit",
		"encounter_date": "2026-07-15",
		"encounter_time": "12:30:00",
		"sr_encounter_type": "Order",
		"sr_pe_order_items": [],
		"enc_multi_payments": [],
		"sr_allopathy_drug_prescription": [],
	}
	source = {
		"site": "eternityerp.m.frappe.cloud",
		"doctype": "Patient Encounter",
		"name": encounter["name"],
		"modified": encounter["modified"],
	}
	return {
		"schema_version": 1,
		"event_id": "event-1",
		"trace_id": "trace-1",
		"idempotency_key": entity_key(source["site"], source["doctype"], source["name"]),
		"payload_hash": payload_hash(1, source, encounter),
		"source": source,
		"encounter": encounter,
	}


class TestSyncContract(unittest.TestCase):
	def test_multiple_allowed_source_sites_are_supported(self):
		payload = valid_payload()
		payload["source"]["site"] = "clinic-two.example.com"
		payload.pop("idempotency_key")
		payload["payload_hash"] = payload_hash(1, payload["source"], payload["encounter"])

		result = parse_payload(
			payload,
			allowed_source_sites={"eternityerp.m.frappe.cloud", "clinic-two.example.com"},
			allowed_versions={1},
		)

		self.assertEqual(result.source_site, "clinic-two.example.com")

	def test_source_site_settings_accept_newlines_commas_and_urls(self):
		sites = parse_allowed_source_sites(
			"eternityerp.m.frappe.cloud, https://clinic-two.example.com/\nETERNITYERP.M.FRAPPE.CLOUD"
		)

		self.assertEqual(
			sites,
			{"eternityerp.m.frappe.cloud", "clinic-two.example.com"},
		)

	def test_unlisted_source_site_is_rejected(self):
		payload = valid_payload()
		payload["source"]["site"] = "forged.example.com"
		payload.pop("idempotency_key")
		payload["payload_hash"] = payload_hash(1, payload["source"], payload["encounter"])

		with self.assertRaises(ContractError) as error:
			parse_payload(
				payload,
				allowed_source_sites={"eternityerp.m.frappe.cloud"},
				allowed_versions={1},
			)

		self.assertEqual(error.exception.code, "SOURCE_NOT_ALLOWED")

	def test_invalid_mobile_is_rejected(self):
		value = valid_payload()
		value["encounter"]["sr_pe_mobile"] = "12345"

		with self.assertRaises(ContractError) as error:
			parse_payload(
				value,
				allowed_source_site="eternityerp.m.frappe.cloud",
				allowed_versions={1},
			)

		self.assertEqual(error.exception.code, "INVALID_MOBILE")

	def test_valid_contract_is_normalized(self):
		result = parse_payload(
			valid_payload(),
			allowed_source_site="eternityerp.m.frappe.cloud",
			allowed_versions={1},
		)

		self.assertEqual(result.source_name, "ENC-0001")
		self.assertEqual(result.source_patient, "SRC-PAT-1")

	def test_source_name_must_match_encounter(self):
		payload = valid_payload()
		payload["source"]["name"] = "ENC-OTHER"

		with self.assertRaisesRegex(ContractError, "does not match"):
			parse_payload(
				payload,
				allowed_source_site="eternityerp.m.frappe.cloud",
				allowed_versions={1},
			)

	def test_payload_hash_is_verified(self):
		payload = valid_payload()
		payload["encounter"]["patient_name"] = "Changed"

		with self.assertRaisesRegex(ContractError, "payload_hash"):
			parse_payload(
				payload,
				allowed_source_site="eternityerp.m.frappe.cloud",
				allowed_versions={1},
			)

	def test_child_tables_must_be_arrays(self):
		payload = valid_payload()
		payload["encounter"]["sr_pe_order_items"] = {}
		payload["payload_hash"] = payload_hash(1, payload["source"], payload["encounter"])

		with self.assertRaisesRegex(ContractError, "must be an array"):
			parse_payload(
				payload,
				allowed_source_site="eternityerp.m.frappe.cloud",
				allowed_versions={1},
			)
