// Copyright (c) 2026, Thunder BluePhoenix and contributors
// For license information, please see license.txt

frappe.query_reports["Stock by Facility"] = {
	filters: [
		{ fieldname: "company", label: __("Company"), fieldtype: "Link", options: "Company" },
		{ fieldname: "item_code", label: __("Item"), fieldtype: "Link", options: "Item" },
		{
			fieldname: "item_group",
			label: __("Item Group"),
			fieldtype: "Link",
			options: "Item Group",
		},
	],
};
