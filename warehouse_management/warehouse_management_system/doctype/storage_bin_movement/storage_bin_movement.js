// Copyright (c) 2026, Thunder BluePhoenix and contributors
// For license information, please see license.txt

frappe.ui.form.on("Storage Bin Movement", {
	setup(frm) {
		frm.set_query("storage_bin", () => ({ filters: { disabled: 0 } }));
		frm.set_query("to_location", () => ({
			filters: { wt_warehouse_type: "Level", is_group: 0, disabled: 0 },
		}));
	},
});
