// Desk dialogs shared by the Warehouse form and the 3D viewer. Loaded on demand with frappe.require.
(function () {
	const wm = frappe.provide("wm");
	const API = "warehouse_management.api.warehouse_3d.";

	// Split a storage Level: a new area beside it, what remains of the original, and stock to carry over.
	wm.split_area = async function (warehouse, after) {
		const [detail, items] = await Promise.all([
			frappe.call(API + "get_warehouse_detail", { warehouse }).then((r) => r.message),
			frappe.call(API + "get_level_items", { warehouse }).then((r) => r.message || []),
		]);
		const own = items.filter((it) => !it.t); // tote contents move with the tote, not here
		const area = (detail.wt_length || 0) * (detail.wt_breadth || 0);
		// suggest the new area's weight limit from its share of the original's area
		const suggest = () => {
			const part = (dialog.get_value("length") || 0) * (dialog.get_value("breadth") || 0);
			if (area && part && detail.wt_max_weight_kg) {
				dialog.set_value(
					"max_weight_kg",
					Math.round((detail.wt_max_weight_kg * part) / area)
				);
			}
		};
		const dialog = new frappe.ui.Dialog({
			title: __("Split {0}", [detail.warehouse_name]),
			fields: [
				{
					fieldname: "new_name",
					fieldtype: "Data",
					label: __("New Area Name"),
					reqd: 1,
					default: detail.warehouse_name + " B",
				},
				{ fieldtype: "Section Break", label: __("New Area") },
				{
					fieldname: "length",
					fieldtype: "Float",
					label: __("Length"),
					onchange: suggest,
				},
				{
					fieldname: "breadth",
					fieldtype: "Float",
					label: __("Breadth"),
					onchange: suggest,
				},
				{ fieldtype: "Column Break" },
				{
					fieldname: "max_weight_kg",
					fieldtype: "Float",
					label: __("Max Weight (kg)"),
					description:
						area && detail.wt_max_weight_kg
							? __("Suggested from its share of the area")
							: "",
				},
				{
					fieldtype: "Section Break",
					label: __("What Remains of {0}", [detail.warehouse_name]),
				},
				{
					fieldname: "keep_length",
					fieldtype: "Float",
					label: __("Length"),
					default: detail.wt_length,
				},
				{
					fieldname: "keep_breadth",
					fieldtype: "Float",
					label: __("Breadth"),
					default: detail.wt_breadth,
				},
				{ fieldtype: "Column Break" },
				{
					fieldname: "keep_max_weight_kg",
					fieldtype: "Float",
					label: __("Max Weight (kg)"),
					default: detail.wt_max_weight_kg,
				},
				{
					fieldtype: "Section Break",
					label: __("Move Stock to the New Area"),
					hidden: !own.length,
				},
				{
					fieldname: "moves",
					fieldtype: "Table",
					cannot_add_rows: true,
					in_place_edit: true,
					hidden: !own.length,
					data: own.map((it) => ({
						item_code: it.c,
						available: it.a,
						uom: it.u,
						qty: 0,
					})),
					fields: [
						{
							fieldname: "item_code",
							fieldtype: "Link",
							options: "Item",
							label: __("Item"),
							in_list_view: 1,
							read_only: 1,
						},
						{
							fieldname: "available",
							fieldtype: "Float",
							label: __("Here Now"),
							in_list_view: 1,
							read_only: 1,
						},
						{ fieldname: "uom", fieldtype: "Data", label: __("UOM"), read_only: 1 },
						{
							fieldname: "qty",
							fieldtype: "Float",
							label: __("Move"),
							in_list_view: 1,
						},
					],
				},
			],
			primary_action_label: __("Split"),
			primary_action(values) {
				frappe
					.call({
						method: API + "split_area",
						args: {
							warehouse,
							new_name: values.new_name,
							length: values.length || 0,
							breadth: values.breadth || 0,
							max_weight_kg: values.max_weight_kg || 0,
							keep: {
								length: values.keep_length || 0,
								breadth: values.keep_breadth || 0,
								max_weight_kg: values.keep_max_weight_kg || 0,
							},
							moves: (values.moves || []).filter((m) => m.qty > 0),
						},
						freeze: true,
					})
					.then((r) => {
						dialog.hide();
						frappe.show_alert({
							message: __("Created {0}", [r.message.name]),
							indicator: "green",
						});
						if (after) after(r.message);
					});
			},
		});
		dialog.show();
	};
})();
