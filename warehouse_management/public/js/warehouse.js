// Warehouse form: storage actions for 3D-managed warehouses (doctype_js in hooks.py)
frappe.ui.form.on("Warehouse", {
	refresh(frm) {
		if (frm.is_new()) return;
		if (frm.doc.is_group && ["Floor", "Zone"].includes(frm.doc.wt_warehouse_type)) {
			frm.add_custom_button(
				__("Generate Locations"),
				() =>
					frappe.require("/assets/warehouse_management/js/wm_desk.js", () =>
						window.wm.generate_locations(frm.doc.name, () => frm.reload_doc())
					),
				__("Storage")
			);
		}
		if (frm.doc.is_group || frm.doc.wt_warehouse_type !== "Level") return;
		frm.add_custom_button(
			__("Split Area"),
			() =>
				frappe.require("/assets/warehouse_management/js/wm_desk.js", () =>
					window.wm.split_area(frm.doc.name, () => frm.reload_doc())
				),
			__("Storage")
		);
	},
});
