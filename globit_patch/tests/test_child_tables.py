from __future__ import annotations

import unittest
from unittest.mock import patch

from globit_patch.integrations.globifit.child_tables import map_order_items, map_payments


class TestChildTables(unittest.TestCase):
	@patch("globit_patch.integrations.globifit.child_tables.resolve_link", side_effect=lambda _s, value, _d, **_k: value)
	def test_order_item_strips_frappe_metadata(self, _resolve):
		rows = map_order_items(
			[
				{
					"name": "ROW-1",
					"parent": "ENC-1",
					"sr_item_code": "ITEM-1",
					"sr_item_qty": 1,
					"sr_item_rate": 100,
				}
			]
		)

		self.assertEqual(rows, [{"sr_item_code": "ITEM-1", "sr_item_qty": 1, "sr_item_rate": 100}])

	@patch("globit_patch.integrations.globifit.child_tables.resolve_link", side_effect=lambda _s, value, _d, **_k: value)
	def test_payment_does_not_copy_generated_payment_entry_or_source_file(self, _resolve):
		rows = map_payments(
			[
				{
					"mmp_paid_amount": 100,
					"mmp_mode_of_payment": "Cash",
					"mmp_payment_entry": "ACC-PAY-1",
					"mmp_payment_proof": "/private/files/source.jpg",
				}
			]
		)

		self.assertEqual(rows, [{"mmp_paid_amount": 100, "mmp_mode_of_payment": "Cash"}])
