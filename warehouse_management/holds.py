"""Short stock holds for sales channels (Stock Hold): availability, the channel API, and expiry.

Available = actual - reserved for open sales orders - active holds. Holds are a promise among channel
customers; ERPNext postings (a counter sale, a transfer) do not check them.
# ponytail: holds are not enforced on outgoing stock documents; add a before_submit check on
# Delivery Note / Stock Entry if counter sales must respect web-cart holds too.
"""

import frappe
from frappe import _
from frappe.utils import add_to_date, flt, now_datetime

from warehouse_management.warehouse_management_system.doctype.wms_settings.wms_settings import settings_for


def _active_holds(item_code, warehouses, exclude=None):
	filters = {
		"item_code": item_code,
		"warehouse": ["in", list(warehouses)],
		"status": "Active",
		"expires_at": [">", now_datetime()],
	}
	if exclude:
		filters["name"] = ["!=", exclude]
	held = {}
	for h in frappe.get_all("Stock Hold", filters=filters, fields=["warehouse", "qty"]):
		held[h.warehouse] = held.get(h.warehouse, 0) + flt(h.qty)
	return held


def available_qty(item_code, warehouse, lock=False, exclude=None):
	"""Units of an item in one warehouse that a channel may still promise."""
	stock = frappe.db.get_value(
		"Bin",
		{"item_code": item_code, "warehouse": warehouse},
		["actual_qty", "reserved_qty"],
		as_dict=True,
		for_update=lock,
	)
	if not stock:
		return 0.0
	held = _active_holds(item_code, [warehouse], exclude).get(warehouse, 0)
	return flt(stock.actual_qty) - flt(stock.reserved_qty) - held


@frappe.whitelist()
def get_available_qty(item_code: str, warehouse: str | None = None, company: str | None = None):
	"""What a sales channel may still sell: per warehouse, and in total."""
	frappe.has_permission("Stock Hold", "read", throw=True)
	filters = {"item_code": item_code}
	if warehouse:
		filters["warehouse"] = warehouse
	# only warehouses the user may see: one entity's channel must not learn another entity's stock
	visible = set(
		frappe.get_list(
			"Warehouse", filters={"company": company} if company else {}, pluck="name", limit_page_length=0
		)
	)
	bins = [
		b
		for b in frappe.get_all("Bin", filters=filters, fields=["warehouse", "actual_qty", "reserved_qty"])
		if b.warehouse in visible
	]
	held = _active_holds(item_code, [b.warehouse for b in bins] or [""])
	per_warehouse = {
		b.warehouse: flt(b.actual_qty) - flt(b.reserved_qty) - held.get(b.warehouse, 0) for b in bins
	}
	return {"item_code": item_code, "warehouses": per_warehouse, "total": sum(per_warehouse.values())}


@frappe.whitelist(methods=["POST"])
def create_hold(
	item_code: str,
	warehouse: str,
	qty: float,
	hold_key: str | None = None,
	minutes: float | None = None,
):
	"""Hold stock for a cart. Fails if the units are not available (someone else holds or ordered them)."""
	hold = frappe.new_doc("Stock Hold")
	hold.update({"item_code": item_code, "warehouse": warehouse, "qty": qty, "hold_key": hold_key})
	if minutes:
		hold.expires_at = add_to_date(now_datetime(), minutes=flt(minutes))
	hold.insert()
	return {"name": hold.name, "expires_at": hold.expires_at}


def _active(name):
	hold = frappe.get_doc("Stock Hold", name)
	hold.check_permission("write")
	if hold.status != "Active" or hold.expires_at < now_datetime():
		frappe.throw(_("Stock Hold {0} is no longer active.").format(name), title=_("Hold expired"))
	return hold


@frappe.whitelist(methods=["POST"])
def extend_hold(name: str | int, minutes: float | None = None):
	hold = _active(name)
	minutes = flt(minutes) or settings_for(hold.warehouse).hold_minutes or 5
	hold.db_set("expires_at", add_to_date(now_datetime(), minutes=minutes))
	return {"name": hold.name, "expires_at": hold.expires_at}


@frappe.whitelist(methods=["POST"])
def release_hold(name: str | int | None = None, hold_key: str | None = None):
	"""Release one hold, or every active hold of a cart (hold_key)."""
	if name:
		names = [name]
	elif hold_key:
		names = frappe.get_all("Stock Hold", filters={"hold_key": hold_key, "status": "Active"}, pluck="name")
	else:
		frappe.throw(_("Give the hold, or the cart (hold_key) to release."))
	for n in names:
		hold = frappe.get_doc("Stock Hold", n)
		hold.check_permission("write")
		if hold.status == "Active":
			hold.db_set("status", "Released")
	return {"released": len(names)}


@frappe.whitelist(methods=["POST"])
def convert_hold(name: str | int, reference_doctype: str, reference_name: str):
	"""The order is placed: the hold ends and the order (e.g. a Sales Order) now carries the promise."""
	hold = _active(name)
	frappe.get_doc(reference_doctype, reference_name).check_permission("read")
	hold.db_set(
		{"status": "Converted", "reference_doctype": reference_doctype, "reference_name": reference_name}
	)
	return {"name": hold.name, "status": hold.status}


def expire_holds():
	"""Scheduler (every minute): mark lapsed holds Expired. Availability already ignores them."""
	hold = frappe.qb.DocType("Stock Hold")
	(
		frappe.qb.update(hold)
		.set(hold.status, "Expired")
		.where((hold.status == "Active") & (hold.expires_at <= now_datetime()))
	).run()
