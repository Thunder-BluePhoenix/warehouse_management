# Copyright (c) 2026, Thunder BluePhoenix and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt


class GateEntry(Document):
	"""Goods or vehicles entering or leaving through the gate. Submitting posts the matching Stock Entry
	(Material Receipt for In, Material Issue for Out); cancelling cancels it."""

	def validate(self):
		has_serial = frappe.get_cached_value("Item", self.item_code, "has_serial_no")
		if has_serial and not self.serial_no:
			frappe.throw(_("Serial No is required for {0}").format(self.item_code))
		if self.serial_no:
			self.qty = 1
		if self.entry_type == "Out" and self.serial_no and not self.warehouse:
			self.warehouse = frappe.db.get_value("Serial No", self.serial_no, "warehouse")
		if not self.warehouse:
			frappe.throw(_("Warehouse is required"))
		if frappe.db.get_value("Warehouse", self.warehouse, "is_group"):
			frappe.throw(_("{0} is a group warehouse; pick a storage level").format(self.warehouse))
		if self.entry_type == "Out" and self.serial_no:
			current = frappe.db.get_value("Serial No", self.serial_no, "warehouse")
			if current != self.warehouse:
				frappe.throw(_("Serial No {0} is in {1}, not {2}").format(self.serial_no, current or _("no warehouse"), self.warehouse))

	def on_submit(self):
		row = {
			"item_code": self.item_code,
			"qty": flt(self.qty),
			"use_serial_batch_fields": 1,
			"serial_no": self.serial_no,
		}
		if self.entry_type == "In":
			row.update(t_warehouse=self.warehouse, basic_rate=flt(self.basic_rate), allow_zero_valuation_rate=self.allow_zero_valuation_rate)
		else:
			row.update(s_warehouse=self.warehouse)
		entry = frappe.get_doc(
			{
				"doctype": "Stock Entry",
				"stock_entry_type": "Material Receipt" if self.entry_type == "In" else "Material Issue",
				"company": self.company,
				"posting_date": self.posting_date,
				"posting_time": self.posting_time,
				"set_posting_time": 1,
				"remarks": _("Gate Entry {0}").format(self.name),
				"items": [row],
			}
		)
		entry.insert()
		entry.submit()
		self.db_set("stock_entry", entry.name)

	def on_cancel(self):
		if self.stock_entry and frappe.db.get_value("Stock Entry", self.stock_entry, "docstatus") == 1:
			frappe.get_doc("Stock Entry", self.stock_entry).cancel()
