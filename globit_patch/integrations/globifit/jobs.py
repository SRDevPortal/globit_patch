from __future__ import annotations

import frappe


def cleanup_sync_logs() -> None:
	if not frappe.db.exists("DocType", "Globit Integration Settings"):
		return
	settings = frappe.get_single("Globit Integration Settings")
	retention_days = max(1, int(settings.log_retention_days or 30))
	cutoff = frappe.utils.add_days(frappe.utils.now_datetime(), -retention_days)
	frappe.db.delete(
		"Patient Encounter Sync Log",
		{
			"status": "Succeeded",
			"creation": ["<", cutoff],
		},
	)
