from __future__ import annotations

import json
import unittest
from pathlib import Path


SYNC_LOG_JSON = (
	Path(__file__).parents[1]
	/ "globit_patch"
	/ "doctype"
	/ "patient_encounter_sync_log"
	/ "patient_encounter_sync_log.json"
)


class TestSyncLogMetadata(unittest.TestCase):
	def test_operational_fields_are_visible_and_filterable(self):
		metadata = json.loads(SYNC_LOG_JSON.read_text())
		fields = {field["fieldname"]: field for field in metadata["fields"]}

		visible = {
			"status",
			"action",
			"source_name",
			"change_count",
			"changed_fields",
			"destination_patient_encounter",
			"completed_at",
		}
		for fieldname in visible:
			self.assertEqual(fields[fieldname].get("in_list_view"), 1, fieldname)

		filterable = visible - {"changed_fields"}
		for fieldname in filterable:
			self.assertEqual(fields[fieldname].get("in_standard_filter"), 1, fieldname)
