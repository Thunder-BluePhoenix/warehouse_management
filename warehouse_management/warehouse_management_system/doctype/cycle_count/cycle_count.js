// Copyright (c) 2026, Thunder BluePhoenix and contributors
// For license information, please see license.txt

frappe.ui.form.on("Cycle Count", {
	setup(frm) {
		frm.set_query("location", () => ({ filters: { company: frm.doc.company } }));
	},
	refresh(frm) {
		const call = (method, args) =>
			frm.call({ doc: frm.doc, method, args, freeze: true }).then(() => frm.reload_doc());
		if (frm.doc.docstatus === 0 && !frm.is_new() && frm.doc.status === "Counting") {
			frm.add_custom_button(__("Mark Uncounted as Zero"), () =>
				call("mark_uncounted_as_zero")
			);
			frm.add_custom_button(__("Send for Approval"), () =>
				call("send_for_approval")
			).addClass("btn-primary");
		}
		if (
			frm.doc.docstatus === 0 &&
			frm.doc.status === "Pending Approval" &&
			frm.perm[0].submit
		) {
			frm.add_custom_button(__("Reject for Recount"), () =>
				frappe.prompt(
					{ fieldname: "reason", fieldtype: "Small Text", label: __("Reason") },
					({ reason }) => call("reject", { reason }),
					__("Reject for Recount")
				)
			);
		}
	},
});

frappe.ui.form.on("Cycle Count Item", {
	counted_qty(frm, cdt, cdn) {
		frappe.model.set_value(cdt, cdn, "counted", 1);
	},
	counted_serials(frm, cdt, cdn) {
		frappe.model.set_value(cdt, cdn, "counted", 1);
	},
});
