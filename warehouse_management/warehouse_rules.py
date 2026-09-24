"""Server-side rules for warehouses that the 3D app manages: area, bay type and weight limits on
incoming stock, and live-refresh events for the viewer. Wired in hooks.py (doc_events)."""

import frappe
from frappe import _
from frappe.utils import flt

from warehouse_management.api.warehouse_3d import kg_per_unit

# Incoming stock rows per voucher: (child table, target warehouse field, stock-qty field)
INCOMING = {
	"Stock Entry": ("items", "t_warehouse", "transfer_qty"),
	"Purchase Receipt": ("items", "warehouse", "stock_qty"),
	"Purchase Invoice": ("items", "warehouse", "stock_qty"),
	"Stock Reconciliation": ("items", "warehouse", None),  # bay type only: it sets balances, not receipts
}


def set_area(doc, method=None):
	"""Warehouse.validate: area of a floor area (e.g. a scrap pile) from its length and breadth."""
	doc.wt_area = flt(doc.get("wt_length")) * flt(doc.get("wt_breadth")) or None


def validate_storage_rules(doc, method=None):
	"""before_submit on stock vouchers: a target level's bay type must match the item's, and its weight
	limit is enforced as configured on the warehouse (Warn = message, Block = refuse)."""
	table, wh_field, qty_field = INCOMING[doc.doctype]
	if doc.doctype == "Purchase Invoice" and not doc.get("update_stock"):
		return
	rows = [r for r in doc.get(table) or [] if r.get(wh_field)]
	targets = {r.get(wh_field) for r in rows}
	if not targets:
		return
	rules = {
		w.name: w
		for w in frappe.get_all(
			"Warehouse",
			filters={"name": ["in", list(targets)]},
			fields=["name", "wt_bay_type", "wt_max_weight_kg", "wt_weight_limit_action"],
		)
		if w.wt_bay_type or flt(w.wt_max_weight_kg)
	}
	if not rules:
		return

	incoming_kg = {}
	for row in rows:
		wh = row.get(wh_field)
		rule = rules.get(wh)
		if not rule:
			continue
		item = frappe.get_cached_value(
			"Item", row.item_code, ["stock_uom", "weight_per_unit", "weight_uom", "wt_bay_type"], as_dict=True
		)
		if rule.wt_bay_type and item.wt_bay_type and item.wt_bay_type != rule.wt_bay_type:
			frappe.throw(
				_("Row {0}: {1} needs a {2} bay, but {3} is a {4} bay.").format(
					row.idx, row.item_code, item.wt_bay_type, wh, rule.wt_bay_type
				),
				title=_("Wrong bay type"),
			)
		if qty_field and flt(rule.wt_max_weight_kg):
			factor = kg_per_unit(item.stock_uom, item.weight_per_unit, item.weight_uom) or 0
			qty = flt(row.get(qty_field)) or flt(row.qty) * (flt(row.get("conversion_factor")) or 1)
			incoming_kg[wh] = incoming_kg.get(wh, 0) + qty * factor

	for wh, adding in incoming_kg.items():
		rule = rules[wh]
		after = current_kg(wh) + adding
		if after <= flt(rule.wt_max_weight_kg):
			continue
		message = _("{0} would hold {1} kg, above its limit of {2} kg.").format(
			frappe.bold(wh), frappe.bold(round(after, 1)), flt(rule.wt_max_weight_kg)
		)
		if rule.wt_weight_limit_action == "Block":
			frappe.throw(message, title=_("Weight limit exceeded"))
		frappe.msgprint(message, title=_("Weight limit exceeded"), indicator="orange")


def current_kg(warehouse):
	total = 0.0
	for b in frappe.db.sql(
		"""
		SELECT i.stock_uom, i.weight_per_unit, i.weight_uom, SUM(b.actual_qty) AS qty
		FROM `tabBin` b INNER JOIN `tabItem` i ON i.name = b.item_code
		WHERE b.warehouse = %s AND b.actual_qty != 0
		GROUP BY i.stock_uom, i.weight_per_unit, i.weight_uom
	""",
		(warehouse,),
		as_dict=True,
	):
		total += flt(b.qty) * (kg_per_unit(b.stock_uom, b.weight_per_unit, b.weight_uom) or 0)
	return total


# ── live refresh ───────────────────────────────────────────


def queue_viewer_refresh(doc, method=None):
	"""Stock Ledger Entry.on_submit: after commit, tell open viewers which floors changed (one event per request)."""
	floor = floor_of(doc.warehouse)
	if not floor:
		return
	pending = frappe.flags.setdefault("wt3d_changed_floors", set())
	if not pending:
		frappe.db.after_commit.add(_publish_changed_floors)
	pending.add(floor)


def _publish_changed_floors():
	floors = frappe.flags.pop("wt3d_changed_floors", None) or set()
	if floors:
		frappe.publish_realtime("wt3d_stock_changed", {"floors": sorted(floors)})


def floor_of(warehouse):
	"""The Floor-role ancestor of a warehouse the 3D app manages, else None (cheap for untagged warehouses)."""
	if not warehouse or not frappe.get_cached_value("Warehouse", warehouse, "wt_warehouse_type"):
		return None
	cache = frappe.flags.setdefault("wt3d_floor_of", {})
	if warehouse not in cache:
		row = frappe.db.sql(
			"""
			SELECT a.name FROM `tabWarehouse` h
			JOIN `tabWarehouse` a ON a.lft <= h.lft AND a.rgt >= h.rgt AND a.wt_warehouse_type = 'Floor'
			WHERE h.name = %s LIMIT 1
		""",
			(warehouse,),
		)
		cache[warehouse] = row[0][0] if row else None
	return cache[warehouse]
