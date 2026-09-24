# Copyright (c) 2026, Thunder BluePhoenix and contributors
# For license information, please see license.txt

"""Stock per item across facilities (Building-role warehouses), with what is promised and what is left.

In stock is counted where it sits (a tote counts under the facility of its warehouse). Available =
in stock - reserved for open sales orders - active Stock Holds. Moving stock between facilities is a
standard Material Transfer (same company) or an inter-company Delivery Note -> Purchase Receipt."""

import frappe
from frappe import _
from frappe.utils import flt, now_datetime


def execute(filters=None):
	filters = frappe._dict(filters or {})
	permitted = set(frappe.get_list("Warehouse", pluck="name", limit_page_length=0))
	facility_filters = {"wt_warehouse_type": "Building", "disabled": 0}
	if filters.company:
		facility_filters["company"] = filters.company
	facilities = [
		f
		for f in frappe.get_all(
			"Warehouse",
			filters=facility_filters,
			fields=["name", "warehouse_name", "lft", "rgt"],
			order_by="warehouse_name",
		)
		if f.name in permitted
	]

	group = frappe.db.get_value("Item Group", filters.item_group, ["lft", "rgt"], as_dict=True) or {}
	bins = frappe.db.sql(
		"""
		SELECT b.item_code, i.item_name, i.stock_uom, b.warehouse, w.lft, b.actual_qty, b.reserved_qty
		FROM `tabBin` b
		JOIN `tabWarehouse` w ON w.name = b.warehouse
		JOIN `tabItem` i ON i.name = b.item_code
		WHERE (b.actual_qty != 0 OR b.reserved_qty != 0)
		  AND (%(company)s IS NULL OR w.company = %(company)s)
		  AND (%(item_code)s IS NULL OR b.item_code = %(item_code)s)
		  AND (%(ig_lft)s IS NULL OR i.item_group IN
		       (SELECT name FROM `tabItem Group` WHERE lft >= %(ig_lft)s AND rgt <= %(ig_rgt)s))
	""",
		{
			"company": filters.company or None,
			"item_code": filters.item_code or None,
			"ig_lft": group.get("lft"),
			"ig_rgt": group.get("rgt"),
		},
		as_dict=True,
	)
	bins = [b for b in bins if b.warehouse in permitted]

	held = {}
	for h in frappe.get_all(
		"Stock Hold",
		filters={"status": "Active", "expires_at": [">", now_datetime()]},
		fields=["item_code", "warehouse", "qty"],
	):
		held[(h.item_code, h.warehouse)] = held.get((h.item_code, h.warehouse), 0) + flt(h.qty)

	def facility_of(lft):
		return next((f"f{i}" for i, f in enumerate(facilities) if f.lft <= lft <= f.rgt), "other")

	rows = {}
	for b in bins:
		row = rows.setdefault(
			b.item_code,
			frappe._dict(
				item_code=b.item_code,
				item_name=b.item_name,
				stock_uom=b.stock_uom,
				in_stock=0.0,
				reserved=0.0,
				on_hold=0.0,
			),
		)
		key = facility_of(b.lft)
		row[key] = flt(row.get(key)) + flt(b.actual_qty)
		row.in_stock += flt(b.actual_qty)
		row.reserved += flt(b.reserved_qty)
		row.on_hold += held.get((b.item_code, b.warehouse), 0)
	for row in rows.values():
		row.available = row.in_stock - row.reserved - row.on_hold

	columns = [
		{"fieldname": "item_code", "label": _("Item"), "fieldtype": "Link", "options": "Item", "width": 160},
		{"fieldname": "item_name", "label": _("Item Name"), "fieldtype": "Data", "width": 180},
		{"fieldname": "stock_uom", "label": _("UOM"), "fieldtype": "Link", "options": "UOM", "width": 70},
	]
	columns += [
		{"fieldname": f"f{i}", "label": f.warehouse_name, "fieldtype": "Float", "width": 110}
		for i, f in enumerate(facilities)
	]
	if any("other" in r for r in rows.values()):
		columns.append(
			{"fieldname": "other", "label": _("Not in a facility"), "fieldtype": "Float", "width": 110}
		)
	columns += [
		{"fieldname": "in_stock", "label": _("In Stock"), "fieldtype": "Float", "width": 100},
		{"fieldname": "reserved", "label": _("Reserved"), "fieldtype": "Float", "width": 100},
		{"fieldname": "on_hold", "label": _("On Hold"), "fieldtype": "Float", "width": 100},
		{"fieldname": "available", "label": _("Available"), "fieldtype": "Float", "width": 100},
	]
	return columns, sorted(rows.values(), key=lambda r: r.item_code)
