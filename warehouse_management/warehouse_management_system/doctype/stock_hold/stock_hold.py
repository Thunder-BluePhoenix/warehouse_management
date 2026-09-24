# Copyright (c) 2026, Thunder BluePhoenix and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import add_to_date, flt, now_datetime

from warehouse_management.holds import available_qty


class StockHold(Document):
	"""A short promise of stock to a sales channel (e.g. a web cart held for 5 minutes). It lowers the
	quantity `available_qty` reports, so no other channel customer can hold the same units; it expires on
	its own. When the order is placed the hold is converted (the order then reserves the stock)."""

	def validate(self):
		if flt(self.qty) <= 0:
			frappe.throw(_("Qty must be greater than 0."))
		if not self.is_new():
			return
		self.status = "Active"
		if not self.expires_at:
			minutes = frappe.get_cached_doc("WMS Settings").hold_minutes or 5
			self.expires_at = add_to_date(now_datetime(), minutes=minutes)
		# locks the item's Bin row until commit, so two carts cannot both take the last units
		available = available_qty(self.item_code, self.warehouse, lock=True)
		if flt(self.qty) > available:
			frappe.throw(
				_("Only {0} of {1} can be held in {2}.").format(
					max(available, 0), self.item_code, self.warehouse
				),
				title=_("Not enough stock"),
			)
