import frappe
from frappe.model.document import Document

from globit_patch.integrations.globifit.contract import parse_allowed_source_sites
from globit_patch.integrations.globifit.exceptions import ContractError


class GlobitIntegrationSettings(Document):
	def validate(self):
		try:
			sites = parse_allowed_source_sites(self.allowed_source_site)
		except ContractError as exc:
			frappe.throw(exc.message, title="Invalid Allowed Source Site")
		if not sites:
			frappe.throw("At least one allowed source site is required.")
		self.allowed_source_site = "\n".join(sorted(sites))
