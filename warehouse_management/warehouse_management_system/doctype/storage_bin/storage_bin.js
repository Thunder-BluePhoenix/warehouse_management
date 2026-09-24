// Copyright (c) 2026, Thunder BluePhoenix and contributors
// For license information, please see license.txt

frappe.ui.form.on("Storage Bin", {
	setup(frm) {
		frm.set_query("location", () => ({
			filters: {
				wt_warehouse_type: "Level",
				is_group: 0,
				disabled: 0,
				company: frm.doc.company,
			},
		}));
	},
	refresh(frm) {
		if (frm.is_new() || frm.doc.disabled) return;
		frm.add_custom_button(__("Move"), () => {
			frappe.prompt(
				{
					fieldname: "to_location",
					fieldtype: "Link",
					options: "Warehouse",
					label: __("New Location"),
					reqd: 1,
					get_query: () => ({
						filters: {
							wt_warehouse_type: "Level",
							is_group: 0,
							disabled: 0,
							company: frm.doc.company,
						},
					}),
				},
				({ to_location }) =>
					frappe
						.call("warehouse_management.api.scan.move_tote", {
							storage_bin: frm.doc.name,
							location: to_location,
						})
						.then(() => frm.reload_doc()),
				__("Move {0}", [frm.doc.name]),
				__("Move")
			);
		});
	},
});
