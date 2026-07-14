from vobiz_click_to_call.vobiz_click_to_call.doctype.vobiz_user_mapping.vobiz_user_mapping import (
	VobizUserMapping,
)


class GlobitVobizUserMapping(VobizUserMapping):
	"""Allow Globit Patch's Patient Encounter queue source."""

	def validate(self):
		queue_source = self.queue_source
		if queue_source != "Patient Encounter":
			return super().validate()

		# Run all upstream normalization and validation with a value accepted by
		# Vobiz, then restore the Globit-provided queue source for persistence.
		self.queue_source = "Patient"
		try:
			super().validate()
		finally:
			self.queue_source = queue_source
