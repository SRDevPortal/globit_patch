frappe.ui.form.on("Patient Encounter Sync Log", {
	refresh(frm) {
		const wrapper = frm.fields_dict.change_summary_html?.$wrapper;
		if (!wrapper) return;

		let audit = {};
		try {
			audit = JSON.parse(frm.doc.change_details || "{}");
		} catch (_error) {
			wrapper.html(`<div class="text-muted">${__("Change details are not valid JSON.")}</div>`);
			return;
		}

		const rows = [];
		for (const [entity, details] of Object.entries(audit)) {
			for (const [fieldname, values] of Object.entries(details.fields || {})) {
				rows.push([entity, fieldname, values.from, values.to]);
			}
			for (const [table, changes] of Object.entries(details.child_tables || {})) {
				for (const row of changes.added || []) rows.push([entity, `${table} (${__("Added")})`, "", row]);
				for (const row of changes.removed || []) rows.push([entity, `${table} (${__("Removed")})`, row, ""]);
				for (const row of changes.changed || []) {
					const key = Object.entries(row.key || {})
						.map(([fieldname, value]) => `${fieldname}=${value}`)
						.join(", ");
					const rowLabel = key ? `${table} [${key}]` : table;
					for (const [fieldname, values] of Object.entries(row.fields || {})) {
						rows.push([entity, `${rowLabel}.${fieldname}`, values.from, values.to]);
					}
				}
			}
		}

		if (!rows.length) {
			wrapper.html(`<div class="text-muted">${__("No material field changes recorded.")}</div>`);
			return;
		}

		const escape = (value) => frappe.utils.escape_html(
			typeof value === "object" ? JSON.stringify(value) : String(value ?? "")
		);
		const body = rows
			.map(
				([entity, fieldname, before, after]) => `<tr>
					<td>${escape(entity)}</td><td>${escape(fieldname)}</td>
					<td>${escape(before)}</td><td>${escape(after)}</td>
				</tr>`
			)
			.join("");
		wrapper.html(`<div class="table-responsive"><table class="table table-bordered table-sm">
			<thead><tr><th>${__("Entity")}</th><th>${__("Field")}</th><th>${__("Before")}</th><th>${__("After")}</th></tr></thead>
			<tbody>${body}</tbody>
		</table></div>`);
	},
});
