"""Scan-first warehouse operations for the WMS Scan page: put-away, tote moves and picking.

Every write goes through ERPNext documents (Stock Entry, Storage Bin Movement, Pick List, Delivery Note)
with the user's own permissions, so the storage rules (bay type, weight) and ERPNext's validations apply."""

import json

import frappe
from frappe import _
from frappe.utils import flt

from warehouse_management.api.warehouse_3d import _locate, _require_view_permission
from warehouse_management.warehouse_rules import location_of, validate_location


def _item_info(item_code):
	frappe.has_permission("Item", "read", item_code, throw=True)
	item = frappe.get_cached_value(
		"Item", item_code, ["item_name", "stock_uom", "has_serial_no", "has_batch_no"], as_dict=True
	)
	return {
		"item_code": item_code,
		"item_name": item.item_name,
		"uom": item.stock_uom,
		"has_serial_no": item.has_serial_no,
		"has_batch_no": item.has_batch_no,
	}


@frappe.whitelist()
def resolve(code: str):
	"""What was scanned: a tote, a storage level, a serial no, a batch, or an item (code or barcode)."""
	_require_view_permission()
	code = (code or "").strip()
	if not code:
		frappe.throw(_("Nothing scanned."))

	if frappe.db.exists("Storage Bin", code):
		tote = frappe.get_doc("Storage Bin", code)
		tote.check_permission("read")
		return {
			"kind": "tote",
			"code": tote.name,
			"label": tote.name,
			"warehouse": tote.warehouse,
			"location": tote.location,
			"company": tote.company,
			"disabled": tote.disabled,
		}

	level = frappe.db.get_value(
		"Warehouse", code, ["name", "warehouse_name", "company", "wt_warehouse_type"], as_dict=True
	)
	if not level:  # a label usually carries the short name, without the " - ABBR" suffix
		same_name = frappe.get_all(
			"Warehouse",
			filters={"warehouse_name": code, "wt_warehouse_type": "Level", "disabled": 0},
			fields=["name", "warehouse_name", "company", "wt_warehouse_type"],
			limit=2,
		)
		level = same_name[0] if len(same_name) == 1 else None
	if level and level.wt_warehouse_type == "Level":
		frappe.has_permission("Warehouse", "read", level.name, throw=True)
		return {
			"kind": "location",
			"code": level.name,
			"label": level.warehouse_name,
			"warehouse": level.name,
			"location": level.name,
			"company": level.company,
		}

	serial = frappe.db.get_value("Serial No", code, ["name", "item_code", "warehouse"], as_dict=True)
	if serial:
		frappe.has_permission("Serial No", "read", serial.name, throw=True)
		return {
			"kind": "serial",
			"code": serial.name,
			"serial_no": serial.name,
			"warehouse": serial.warehouse,
			**_item_info(serial.item_code),
		}

	batch = frappe.db.get_value("Batch", code, ["name", "item"], as_dict=True)
	if batch:
		frappe.has_permission("Batch", "read", batch.name, throw=True)
		return {"kind": "batch", "code": batch.name, "batch_no": batch.name, **_item_info(batch.item)}

	item_code = frappe.db.get_value("Item Barcode", {"barcode": code}, "parent")
	if not item_code and frappe.db.exists("Item", code):
		item_code = code
	if item_code:
		return {"kind": "item", "code": item_code, **_item_info(item_code)}

	frappe.throw(_("Nothing found for {0}.").format(frappe.bold(code)), title=_("Unknown code"))


# ── tote moves ─────────────────────────────────────────────


@frappe.whitelist(methods=["POST"])
def move_tote(storage_bin: str, location: str):
	"""Scan the tote, then its new location."""
	movement = frappe.get_doc(
		{"doctype": "Storage Bin Movement", "storage_bin": storage_bin, "to_location": location}
	)
	movement.insert()  # needs create permission on Storage Bin Movement; the rules run in its validate
	return {"movement": movement.name, "from": movement.from_location, "to": movement.to_location}


# ── put-away ───────────────────────────────────────────────


@frappe.whitelist()
def suggest_putaway(item_code: str, qty: float = 1):
	"""Where should this go? A Putaway Rule with room, else where the item already is (level or tote)."""
	_require_view_permission()
	from erpnext.stock.utils import get_stock_balance

	qty = flt(qty) or 1
	for rule in frappe.get_list(
		"Putaway Rule",
		filters={"item_code": item_code, "disable": 0},
		fields=["warehouse", "stock_capacity"],
		order_by="priority asc",
	):
		if flt(rule.stock_capacity) - flt(get_stock_balance(item_code, rule.warehouse)) >= qty:
			return {"code": rule.warehouse, "label": rule.warehouse, "reason": _("Putaway Rule")}

	for b in frappe.get_list(
		"Bin",
		filters={"item_code": item_code, "actual_qty": [">", 0]},
		fields=["warehouse"],
		order_by="actual_qty desc",
		limit_page_length=10,
	):
		level = location_of(b.warehouse)
		if level and frappe.get_cached_value("Warehouse", level, "wt_warehouse_type") == "Level":
			tote = frappe.db.get_value("Storage Bin", {"warehouse": b.warehouse}, "name")
			return {"code": tote or level, "label": tote or level, "reason": _("Already stored here")}
	return None


def _target_warehouse(target, company):
	"""A put-away target is a storage level or a tote (its own warehouse)."""
	tote = frappe.db.get_value(
		"Storage Bin", target, ["warehouse", "location", "company", "disabled"], as_dict=True
	)
	if tote:
		if tote.disabled or not tote.location:
			frappe.throw(_("Tote {0} is disabled or not placed on a level yet.").format(target))
		if tote.company != company:
			frappe.throw(_("Tote {0} belongs to {1}, not {2}.").format(target, tote.company, company))
		return tote.warehouse
	validate_location(target, company)
	return target


@frappe.whitelist(methods=["POST"])
def putaway(source_warehouse: str, lines: str | list):
	"""Post one Material Transfer from the staging warehouse to each scanned level or tote.
	lines: [{item_code, qty, target, serial_no?, batch_no?}]"""
	if isinstance(lines, str):
		lines = json.loads(lines)
	if not lines:
		frappe.throw(_("Nothing to put away."))
	company = frappe.db.get_value("Warehouse", source_warehouse, "company")
	if not company:
		frappe.throw(_("Pick the warehouse the stock comes from."))

	rows = []
	for line in lines:
		row = {
			"item_code": line["item_code"],
			"qty": flt(line.get("qty")) or 1,
			"s_warehouse": source_warehouse,
			"t_warehouse": _target_warehouse(line["target"], company),
		}
		if line.get("serial_no") or line.get("batch_no"):
			row.update(
				use_serial_batch_fields=1, serial_no=line.get("serial_no"), batch_no=line.get("batch_no")
			)
		rows.append(row)

	entry = frappe.get_doc(
		{
			"doctype": "Stock Entry",
			"stock_entry_type": "Material Transfer",
			"company": company,
			"remarks": _("Put-away (WMS Scan)"),
			"items": rows,
		}
	)
	entry.insert()
	entry.submit()
	return {"stock_entry": entry.name}


# ── picking ────────────────────────────────────────────────


def _draft_pick_list(pick_list, ptype="write"):
	doc = frappe.get_doc("Pick List", pick_list)
	doc.check_permission(ptype)
	if doc.docstatus != 0:
		frappe.throw(_("Pick List {0} is already submitted.").format(pick_list))
	return doc


@frappe.whitelist()
def get_pick(pick_list: str):
	"""The pick list's rows in walking order (floor, slot row/column, level), each with where to go."""
	_require_view_permission()
	doc = _draft_pick_list(pick_list, "read")
	whs = list({r.warehouse for r in doc.locations if r.warehouse})
	tote_of = {
		t.warehouse: t
		for t in frappe.get_all(
			"Storage Bin",
			filters={"warehouse": ["in", whs or [""]]},
			fields=["name", "warehouse", "location"],
		)
	}
	level_of = {wh: (tote_of[wh].location if wh in tote_of else wh) for wh in whs}
	where = _locate([lv for lv in set(level_of.values()) if lv])
	slot_pos = {
		s.name: (s.wt_row or 0, s.wt_col or 0)
		for s in frappe.get_all(
			"Warehouse",
			filters={"name": ["in", [w["slot"] for w in where.values() if w["slot"]] or [""]]},
			fields=["name", "wt_row", "wt_col"],
		)
	}
	rows = []
	for r in doc.locations:
		level = level_of.get(r.warehouse)
		loc = where.get(level, {})
		rows.append(
			{
				"row": r.name,
				"idx": r.idx,
				"item_code": r.item_code,
				"item_name": r.item_name,
				"qty": flt(r.stock_qty),
				"picked": flt(r.picked_qty),
				"uom": r.stock_uom,
				"warehouse": r.warehouse,
				"tote": tote_of[r.warehouse].name if r.warehouse in tote_of else None,
				"level": level,
				"floor_name": loc.get("floor_name"),
				"zone_path": loc.get("zone_path") or [],
				"slot_label": loc.get("slot_label"),
				"serial_no": r.serial_no,
				"batch_no": r.batch_no,
				"_order": (
					loc.get("floor_name") or "",
					slot_pos.get(loc.get("slot"), (0, 0)),
					level or "",
					r.idx,
				),
			}
		)
	rows.sort(key=lambda x: x.pop("_order"))
	return {"name": doc.name, "customer": doc.customer, "purpose": doc.purpose, "rows": rows}


@frappe.whitelist(methods=["POST"])
def record_pick(pick_list: str, code: str, qty: float = 1, warehouse: str | None = None):
	"""One scan while picking: an item, serial or batch, optionally at a scanned level/tote (`warehouse`).
	Adds to the first matching row that still needs it."""
	doc = _draft_pick_list(pick_list)
	scanned = resolve(code)
	if scanned["kind"] not in ("item", "serial", "batch"):
		frappe.throw(_("Scan the item, serial no or batch you are picking."))

	qty = 1 if scanned["kind"] == "serial" else (flt(qty) or 1)
	rows = [
		r
		for r in doc.locations
		if r.item_code == scanned["item_code"] and flt(r.picked_qty) < flt(r.stock_qty)
	]
	if warehouse:
		rows = [r for r in rows if r.warehouse == warehouse]
	if scanned["kind"] == "serial":
		picked_serials = {
			s for r in doc.locations if flt(r.picked_qty) for s in (r.serial_no or "").split("\n")
		}
		if scanned["serial_no"] in picked_serials:
			frappe.throw(_("Serial No {0} is already picked.").format(scanned["serial_no"]))
		rows = [r for r in rows if r.warehouse == scanned["warehouse"]]
	if scanned["kind"] == "batch":
		rows = sorted(
			(r for r in rows if r.batch_no in (None, "", scanned["batch_no"])),
			key=lambda r: r.batch_no != scanned["batch_no"],
		)
	if not rows:
		frappe.throw(
			_("{0} is not needed here, or is already fully picked.").format(frappe.bold(scanned["code"])),
			title=_("Not on this pick"),
		)

	row = rows[0]
	take = min(qty, flt(row.stock_qty) - flt(row.picked_qty))
	if scanned["kind"] == "serial":
		# the row's serial list becomes the serials actually picked (ERPNext bundles exactly these on submit)
		already = [s for s in (row.serial_no or "").split("\n") if s] if flt(row.picked_qty) else []
		row.serial_no = "\n".join([*already, scanned["serial_no"]])
		row.use_serial_batch_fields = 1
	if scanned["kind"] == "batch" and not row.batch_no:
		row.batch_no = scanned["batch_no"]
		row.use_serial_batch_fields = 1
	row.picked_qty = flt(row.picked_qty) + take
	doc.pick_manually = 1  # keep the rows as picked; don't let ERPNext re-plan locations on save
	doc.save()
	return {"row": row.name, "picked": row.picked_qty, "qty": row.stock_qty}


@frappe.whitelist(methods=["POST"])
def finish_pick(pick_list: str):
	"""Ship what was picked: trim short rows to the picked quantity, submit the Pick List, tell the
	customer about anything short (WMS Settings), and draft the Delivery Note for the picked goods.

	Short is measured against the order, not the pick plan: ERPNext only plans what is in stock, so
	"100 ordered, 90 available" is a fully picked list of 90 and still a short shipment of 10."""
	doc = _draft_pick_list(pick_list)
	short = []
	for row in list(doc.locations):
		picked, needed = flt(row.picked_qty), flt(row.stock_qty)
		if picked >= needed:
			continue
		if not row.sales_order:  # order lines are measured after submit, below
			short.append(
				{
					"item_code": row.item_code,
					"item_name": row.item_name,
					"ordered": needed,
					"picked": picked,
					"missing": needed - picked,
					"uom": row.stock_uom,
					"sales_order": None,
				}
			)
		if not picked:
			doc.remove(row)
			continue
		row.stock_qty = picked
		row.qty = picked / (flt(row.conversion_factor) or 1)
	if not doc.locations:
		frappe.throw(_("Nothing was picked."))
	for idx, row in enumerate(doc.locations, start=1):
		row.idx = idx

	doc.pick_manually = 1
	doc.save()
	doc.submit()

	short += _short_against_orders(doc)
	notified = _tell_customers(doc, short) if short else []
	delivery_notes = []
	if doc.purpose == "Delivery":
		from erpnext.stock.doctype.pick_list.pick_list import create_delivery_note

		note = create_delivery_note(doc.name)
		if note and note.is_new():
			note.insert()
		delivery_notes = frappe.get_all(
			"Delivery Note Item",
			filters={"against_pick_list": doc.name, "docstatus": 0},
			pluck="parent",
			distinct=True,
		)
	return {"pick_list": doc.name, "short": short, "notified": notified, "delivery_notes": delivery_notes}


def _short_against_orders(pick):
	"""Order lines still not picked once this pick is submitted (ERPNext has updated their picked_qty)."""
	orders = list({r.sales_order for r in pick.locations if r.sales_order})
	if not orders:
		return []
	this_pick = {}
	for r in pick.locations:
		this_pick[r.sales_order_item] = this_pick.get(r.sales_order_item, 0) + flt(r.picked_qty)
	short = []
	for line in frappe.get_all(
		"Sales Order Item",
		filters={"parent": ["in", orders]},
		fields=["name", "parent", "item_code", "item_name", "stock_qty", "picked_qty", "stock_uom"],
		order_by="parent, idx",
	):
		missing = flt(line.stock_qty) - flt(line.picked_qty)
		if missing > 0:
			short.append(
				{
					"item_code": line.item_code,
					"item_name": line.item_name,
					"ordered": flt(line.stock_qty),
					"picked": this_pick.get(line.name, 0),
					"missing": missing,
					"uom": line.stock_uom,
					"sales_order": line.parent,
				}
			)
	return short


def _tell_customers(pick, short):
	"""A comment on each Sales Order with a short pick, and (if enabled) an email to its contact."""
	send = frappe.get_cached_doc("WMS Settings").notify_customer_on_short_pick
	by_order = {}
	for line in short:
		if line["sales_order"]:
			by_order.setdefault(line["sales_order"], []).append(line)

	notified = []
	for sales_order, lines in by_order.items():
		order = frappe.get_doc("Sales Order", sales_order)
		rows = []
		for line in lines:
			name = frappe.utils.escape_html(line["item_name"] or line["item_code"])
			rows.append(
				f"<tr><td>{name}</td><td>{line['ordered']:g} {line['uom']}</td>"
				+ f"<td>{line['picked']:g}</td><td>{line['missing']:g}</td></tr>"
			)
		table = "".join(rows)
		detail = (
			"<table border='1' cellpadding='4' style='border-collapse:collapse'>"
			f"<tr><th>{_('Item')}</th><th>{_('Ordered')}</th><th>{_('Shipping now')}</th>"
			f"<th>{_('Not in this shipment')}</th></tr>{table}</table>"
		)
		order.add_comment("Comment", _("Short pick on {0}:").format(pick.name) + detail)
		if send and order.contact_email:
			frappe.sendmail(
				recipients=[order.contact_email],
				subject=_("Your order {0}: partial shipment").format(sales_order),
				message=_(
					"We are shipping part of your order {0} now. These items are not in this shipment:"
				).format(sales_order)
				+ detail,
				reference_doctype="Sales Order",
				reference_name=sales_order,
			)
			notified.append({"sales_order": sales_order, "email": order.contact_email})
	return notified


# ── cycle count ────────────────────────────────────────────


@frappe.whitelist(methods=["POST"])
def record_count(cycle_count: str, code: str, warehouse: str, qty: float = 1):
	"""One scan while counting, at the scanned level or tote (`warehouse`). Unexpected items get a new row.
	Returns only what was counted: expected quantities stay hidden from counters."""
	doc = frappe.get_doc("Cycle Count", cycle_count)
	doc.check_permission("write")
	if doc.docstatus != 0 or doc.status != "Counting":
		frappe.throw(_("Cycle Count {0} is not being counted.").format(cycle_count))
	if not warehouse:
		frappe.throw(_("Scan the location or tote first."))
	scanned = resolve(code)
	if scanned["kind"] not in ("item", "serial", "batch"):
		frappe.throw(_("Scan an item, serial no or batch."))

	batch = scanned.get("batch_no")
	row = next(
		(
			r
			for r in doc.items
			if r.warehouse == warehouse
			and r.item_code == scanned["item_code"]
			and (r.batch_no or None) == batch
		),
		None,
	)
	if not row:
		row = doc.append(
			"items", {"warehouse": warehouse, "item_code": scanned["item_code"], "batch_no": batch}
		)
	if scanned["kind"] == "serial":
		serials = [s for s in (row.counted_serials or "").splitlines() if s.strip()]
		if scanned["serial_no"] in serials:
			frappe.throw(_("Serial No {0} is already counted here.").format(scanned["serial_no"]))
		row.counted_serials = "\n".join([*serials, scanned["serial_no"]])
	else:
		row.counted_qty = flt(row.counted_qty) + (flt(qty) or 1)
	row.counted = 1
	doc.save()
	return {"item_code": row.item_code, "warehouse": row.warehouse, "counted": row.counted_qty}


@frappe.whitelist()
def get_count(cycle_count: str):
	"""Rows as a counter sees them (no expected quantities)."""
	doc = frappe.get_doc("Cycle Count", cycle_count)
	doc.check_permission("read")
	return {
		"name": doc.name,
		"status": doc.status,
		"rows": [
			{
				"warehouse": r.warehouse,
				"item_code": r.item_code,
				"batch_no": r.batch_no,
				"counted": r.counted,
				"counted_qty": r.counted_qty,
			}
			for r in doc.items
		],
	}


# ── packing ────────────────────────────────────────────────


def _draft_delivery_note(delivery_note, ptype="read"):
	note = frappe.get_doc("Delivery Note", delivery_note)
	note.check_permission(ptype)
	if note.docstatus != 0:
		frappe.throw(
			_("Delivery Note {0} is already submitted; packing is done before it ships.").format(
				delivery_note
			)
		)
	return note


def _open_package(delivery_note):
	"""The package being filled: a draft Packing Slip for this Delivery Note."""
	name = frappe.db.get_value(
		"Packing Slip", {"delivery_note": delivery_note, "docstatus": 0}, "name", order_by="creation desc"
	)
	return frappe.get_doc("Packing Slip", name) if name else None


@frappe.whitelist()
def get_pack(delivery_note: str):
	"""Lines still to pack (ordered, packed in closed packages, in the open package) and the open package."""
	note = _draft_delivery_note(delivery_note)
	package = _open_package(delivery_note)
	in_package = {}
	for row in package.items if package else []:
		in_package[row.dn_detail] = in_package.get(row.dn_detail, 0) + flt(row.qty)
	return {
		"name": note.name,
		"customer": note.customer,
		"package": package.from_case_no if package else None,
		"rows": [
			{
				"item_code": r.item_code,
				"item_name": r.item_name,
				"batch_no": r.batch_no,
				"qty": flt(r.qty),
				"packed": flt(r.packed_qty),
				"in_package": in_package.get(r.name, 0),
				"uom": r.uom,
			}
			for r in note.items
		],
	}


@frappe.whitelist(methods=["POST"])
def pack_scan(delivery_note: str, code: str, qty: float = 1):
	"""Put one scanned item (or batch/serial) into the open package, starting a new package if none is open."""
	note = _draft_delivery_note(delivery_note)
	scanned = resolve(code)
	if scanned["kind"] not in ("item", "serial", "batch"):
		frappe.throw(_("Scan the item, serial no or batch you are packing."))
	qty = 1 if scanned["kind"] == "serial" else (flt(qty) or 1)

	package = _open_package(delivery_note)
	if not package:
		package = frappe.new_doc("Packing Slip")
		package.delivery_note = delivery_note
		package.from_case_no = package.get_recommended_case_no()
	in_package = {}
	for row in package.items:
		in_package[row.dn_detail] = in_package.get(row.dn_detail, 0) + flt(row.qty)

	line = next(
		(
			r
			for r in note.items
			if r.item_code == scanned["item_code"]
			and (not scanned.get("batch_no") or r.batch_no == scanned["batch_no"])
			and flt(r.qty) - flt(r.packed_qty) - in_package.get(r.name, 0) >= qty
		),
		None,
	)
	if not line:
		frappe.throw(
			_("{0} is not on this delivery, or is already packed.").format(frappe.bold(scanned["code"])),
			title=_("Not to pack"),
		)
	row = next((r for r in package.items if r.dn_detail == line.name), None)
	if row:
		row.qty = flt(row.qty) + qty
	else:
		package.append(
			"items",
			{
				"item_code": line.item_code,
				"item_name": line.item_name,
				"batch_no": line.batch_no,
				"qty": qty,
				"stock_uom": line.stock_uom,
				"dn_detail": line.name,
			},
		)
	package.save()  # Packing Slip permissions; ERPNext checks the quantities against the Delivery Note
	return {"package": package.from_case_no, "packing_slip": package.name}


@frappe.whitelist(methods=["POST"])
def close_package(delivery_note: str, gross_weight: float = 0):
	"""Seal the open package (submit its Packing Slip); the next scan starts the next package."""
	_draft_delivery_note(delivery_note)
	package = _open_package(delivery_note)
	if not package or not package.items:
		frappe.throw(_("There is no open package with items in it."))
	if flt(gross_weight):
		package.gross_weight_pkg = flt(gross_weight)
	package.submit()
	return {"package": package.from_case_no, "packing_slip": package.name}
