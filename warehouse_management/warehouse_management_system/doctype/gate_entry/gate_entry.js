// Copyright (c) 2026, Thunder BluePhoenix and contributors
// For license information, please see license.txt

frappe.ui.form.on("Gate Entry", {
	setup(frm) {
		frm.set_query("floor", () => ({
			filters: { wt_warehouse_type: "Floor", company: frm.doc.company },
		}));
		frm.set_query("warehouse", () => ({ filters: { is_group: 0, company: frm.doc.company } }));
	},
	refresh(frm) {
		if (frm.doc.docstatus === 0 && frm.doc.entry_type === "In") {
			frm.add_custom_button(__("Suggest Free Bay"), () => {
				if (!frm.doc.floor) {
					frappe.msgprint(__("Pick a Floor first."));
					return;
				}
				frappe
					.call("warehouse_management.api.warehouse_3d.suggest_free_bay", {
						floor: frm.doc.floor,
						item_code: frm.doc.item_code,
						qty: frm.doc.qty || 1,
					})
					.then((r) => {
						if (r.message) {
							frm.set_value("warehouse", r.message.warehouse);
							frappe.show_alert({
								message: __("Suggested {0}", [r.message.label]),
								indicator: "green",
							});
						} else {
							frappe.msgprint(__("No free bay on this floor for this item."));
						}
					});
			});
		}
	},
	serial_no(frm) {
		if (frm.doc.entry_type === "Out" && frm.doc.serial_no) {
			frappe.db
				.get_value("Serial No", frm.doc.serial_no, ["warehouse", "item_code"])
				.then(({ message }) => {
					if (message && message.warehouse)
						frm.set_value("warehouse", message.warehouse);
					if (message && message.item_code && !frm.doc.item_code)
						frm.set_value("item_code", message.item_code);
				});
		}
	},
});
