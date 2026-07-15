frappe.listview_settings["Patient Encounter Sync Log"] = {
	add_fields: ["status", "requires_manual_review"],

	get_indicator(doc) {
		if (doc.requires_manual_review) {
			return [__("Manual Review"), "orange", "requires_manual_review,=,1"];
		}

		const indicators = {
			Processing: [__("Processing"), "blue", "status,=,Processing"],
			Succeeded: [__("Succeeded"), "green", "status,=,Succeeded"],
			Failed: [__("Failed"), "red", "status,=,Failed"],
			Conflict: [__("Conflict"), "orange", "status,=,Conflict"],
		};

		return indicators[doc.status];
	},
};
