# Copyright (c) 2026, Thunder BluePhoenix and contributors
# For license information, please see license.txt

import erpnext
import frappe
from frappe import _
from frappe.model.document import Document

from warehouse_management.api.warehouse_3d import TOTE
from warehouse_management.warehouse_rules import holds_stock, validate_location


class StorageBin(Document):
	"""A movable, barcoded tote. It owns a leaf Warehouse (role Tote) that holds its contents, so stock in a
	tote is ordinary ERPNext stock: put-away and picking post to that warehouse. Moving the tote
	(Storage Bin Movement) re-parents the warehouse next to its new level; no stock entry is needed."""

	def validate(self):
		if self.is_new() and self.location:
			validate_location(self.location, self.company)
		if self.disabled and self.warehouse and holds_stock(self.warehouse):
			frappe.throw(_("Empty tote {0} before disabling it.").format(self.name))

	def after_insert(self):
		root = frappe.db.get_value(
			"Warehouse", {"company": self.company, "is_group": 1, "parent_warehouse": ["in", ["", None]]}
		)
		warehouse = frappe.get_doc(
			{
				"doctype": "Warehouse",
				"warehouse_name": self.bin_id,
				"company": self.company,
				"parent_warehouse": root,
				"is_group": 0,
				"wt_warehouse_type": TOTE,
				# Pin the stock account. Without one a warehouse inherits it from its ancestors, so moving
				# the tote between branches with different accounts would silently move its value too.
				"account": self._stock_account(root),
			}
		)
		# the tote's warehouse is system-managed: creating the tote is the permitted act, and
		# a Stock User (who may create totes) usually has no create right on Warehouse
		warehouse.insert(ignore_permissions=True)
		self.db_set("warehouse", warehouse.name)
		if self.location:
			# the first placement is a movement too, so the history starts at the first location
			first = self.location
			self.db_set("location", None)
			frappe.get_doc(
				{"doctype": "Storage Bin Movement", "storage_bin": self.name, "to_location": first}
			).insert()
			self.reload()

	def _stock_account(self, root):
		if not erpnext.is_perpetual_inventory_enabled(self.company):
			return None
		from erpnext.stock import get_warehouse_account

		return get_warehouse_account(frappe.get_doc("Warehouse", self.location or root), raise_error=False)

	def on_trash(self):
		if not self.warehouse:
			return
		if holds_stock(self.warehouse):
			frappe.throw(_("Tote {0} still holds stock.").format(self.name))
		warehouse = frappe.get_doc("Warehouse", self.warehouse)
		if warehouse.check_if_sle_exists():
			warehouse.disabled = 1
			warehouse.save(ignore_permissions=True)
		else:
			frappe.delete_doc("Warehouse", warehouse.name, ignore_permissions=True, force=True)
