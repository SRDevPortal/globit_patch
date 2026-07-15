from __future__ import annotations

import hashlib

import frappe
from frappe.model.document import Document


class IntegrationValueMapping(Document):
	def autoname(self):
		self.mapping_key = self._mapping_key()
		self.name = self.mapping_key

	def validate(self):
		mapping_key = self._mapping_key()
		if not self.is_new() and self.name != mapping_key:
			frappe.throw("Create a new mapping instead of changing an existing mapping identity.")
		self.mapping_key = mapping_key

	def _mapping_key(self):
		parts = (
			self.source_doctype,
			self.source_value,
			self.destination_doctype,
			self.destination_value,
		)
		return hashlib.sha256("|".join(parts).encode()).hexdigest()
