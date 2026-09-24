"""Server-side rules for warehouses that the 3D app manages: area, bay type and weight limits on
incoming stock and on tote moves, and live-refresh events for the viewer. Wired in hooks.py (doc_events).

A tote (Storage Bin) keeps its contents in its own warehouse; for these rules that stock counts
at the level where the tote currently sits."""

import frappe
from frappe import _
from frappe.utils import flt

from warehouse_management.api.warehouse_3d import TOTE, kg_per_unit, totes_at

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
	if not rows:
		return
	level_of = {wh: location_of(wh) for wh in {r.get(wh_field) for r in rows}}
	rules = _level_rules(set(level_of.values()) - {None})
	if not rules:
		return

	incoming_kg = {}
	for row in rows:
		level = level_of[row.get(wh_field)]
		rule = rules.get(level)
		if not rule:
			continue
		item = _item(row.item_code)
		check_bay_type(item, row.item_code, rule, _("Row {0}").format(row.idx))
		if qty_field and flt(rule.wt_max_weight_kg):
			qty = flt(row.get(qty_field)) or flt(row.qty) * (flt(row.get("conversion_factor")) or 1)
			incoming_kg[level] = incoming_kg.get(level, 0) + qty * _kg(item)

	for level, adding in incoming_kg.items():
		check_weight(rules[level], current_kg(level) + adding)


def check_tote_move(tote_warehouse, level):
	"""Moving a tote puts its contents on `level`: the same bay-type and weight rules as a posting."""
	rule = _level_rules({level}).get(level)
	if not rule:
		return
	adding = 0.0
	for b in frappe.get_all(
		"Bin",
		filters={"warehouse": tote_warehouse, "actual_qty": [">", 0]},
		fields=["item_code", "actual_qty"],
	):
		item = _item(b.item_code)
		check_bay_type(item, b.item_code, rule, _("Tote"))
		adding += flt(b.actual_qty) * _kg(item)
	if flt(rule.wt_max_weight_kg) and adding:
		check_weight(rule, current_kg(level) + adding)


def _level_rules(levels):
	if not levels:
		return {}
	return {
		w.name: w
		for w in frappe.get_all(
			"Warehouse",
			filters={"name": ["in", list(levels)]},
			fields=["name", "wt_bay_type", "wt_max_weight_kg", "wt_weight_limit_action"],
		)
		if w.wt_bay_type or flt(w.wt_max_weight_kg)
	}


def _item(item_code):
	return frappe.get_cached_value(
		"Item", item_code, ["stock_uom", "weight_per_unit", "weight_uom", "wt_bay_type"], as_dict=True
	)


def _kg(item):
	return kg_per_unit(item.stock_uom, item.weight_per_unit, item.weight_uom) or 0


def check_bay_type(item, item_code, rule, where):
	if rule.wt_bay_type and item.wt_bay_type and item.wt_bay_type != rule.wt_bay_type:
		frappe.throw(
			_("{0}: {1} needs a {2} bay, but {3} is a {4} bay.").format(
				where, item_code, item.wt_bay_type, rule.name, rule.wt_bay_type
			),
			title=_("Wrong bay type"),
		)


def check_weight(rule, after):
	"""Above the limit: refuse (Block, while WMS Settings enforce it) or warn. Near it: warn at the alarm %."""
	limit = flt(rule.wt_max_weight_kg)
	settings = frappe.get_cached_doc("WMS Settings")
	if after > limit:
		message = _("{0} would hold {1} kg, above its limit of {2} kg.").format(
			frappe.bold(rule.name), frappe.bold(round(after, 1)), limit
		)
		if rule.wt_weight_limit_action == "Block" and settings.enforce_weight_block:
			frappe.throw(message, title=_("Weight limit exceeded"))
		frappe.msgprint(message, title=_("Weight limit exceeded"), indicator="orange")
	elif flt(settings.weight_alarm_percent) and after >= limit * flt(settings.weight_alarm_percent) / 100:
		frappe.msgprint(
			_("{0} would be at {1}% of its weight limit ({2} of {3} kg).").format(
				frappe.bold(rule.name), round(after * 100 / limit), round(after, 1), limit
			),
			title=_("Weight alarm"),
			indicator="orange",
		)


def location_of(warehouse):
	"""The level a warehouse's stock counts at: a tote's current location, otherwise the warehouse itself."""
	if frappe.get_cached_value("Warehouse", warehouse, "wt_warehouse_type") != TOTE:
		return warehouse
	return frappe.db.get_value("Storage Bin", {"warehouse": warehouse}, "location")


def current_kg(level):
	"""kg on a level, including the totes sitting on it."""
	total = 0.0
	for b in frappe.db.sql(
		"""
		SELECT i.stock_uom, i.weight_per_unit, i.weight_uom, SUM(b.actual_qty) AS qty
		FROM `tabBin` b INNER JOIN `tabItem` i ON i.name = b.item_code
		WHERE b.warehouse IN %(whs)s AND b.actual_qty != 0
		GROUP BY i.stock_uom, i.weight_per_unit, i.weight_uom
	""",
		{"whs": (level, *totes_at([level]))},
		as_dict=True,
	):
		total += flt(b.qty) * (kg_per_unit(b.stock_uom, b.weight_per_unit, b.weight_uom) or 0)
	return total


def validate_location(location, company):
	"""A tote or put-away target must be an enabled storage Level of the same company."""
	wh = frappe.db.get_value(
		"Warehouse", location, ["wt_warehouse_type", "is_group", "disabled", "company"], as_dict=True
	)
	if not wh or wh.wt_warehouse_type != "Level" or wh.is_group or wh.disabled:
		frappe.throw(_("{0} is not an enabled storage Level.").format(frappe.bold(location)))
	if company and wh.company != company:
		frappe.throw(_("{0} belongs to {1}, not {2}.").format(frappe.bold(location), wh.company, company))


def holds_stock(warehouse):
	return bool(frappe.db.exists("Bin", {"warehouse": warehouse, "actual_qty": ["!=", 0]}))


# ── live refresh ───────────────────────────────────────────


def queue_viewer_refresh(doc, method=None):
	"""Stock Ledger Entry.on_submit: after commit, tell open viewers which floors changed (one event per request)."""
	queue_floor_refresh(floor_of(doc.warehouse))


def queue_floor_refresh(floor):
	if not floor:
		return
	pending = frappe.flags.setdefault("wt3d_changed_floors", set())
	if not pending:
		frappe.db.after_commit.add(_publish_changed_floors)
	pending.add(floor)


def _publish_changed_floors():
	# Each floor's own document room: only viewers showing that floor subscribe to it, and Frappe
	# checks their read permission on the floor when they do.
	for floor in sorted(frappe.flags.pop("wt3d_changed_floors", None) or ()):
		frappe.publish_realtime("wt3d_stock_changed", {"floors": [floor]}, doctype="Warehouse", docname=floor)


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
