# Copyright (c) 2026, Thunder BluePhoenix and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now_datetime

from warehouse_management.warehouse_rules import (
	check_tote_move,
	floor_of,
	queue_floor_refresh,
	validate_location,
)


class StorageBinMovement(Document):
	"""One tote move: scan the tote, then its new location. Insert-only, so the list is the tote's history."""

	def validate(self):
		if not self.is_new():
			frappe.throw(_("A Storage Bin Movement cannot be changed; record a new move instead."))
		tote = frappe.get_doc("Storage Bin", self.storage_bin)
		if tote.disabled:
			frappe.throw(_("Tote {0} is disabled.").format(tote.name))
		validate_location(self.to_location, tote.company)
		self.from_location = tote.location
		if self.from_location == self.to_location:
			frappe.throw(_("Tote {0} is already at {1}.").format(tote.name, self.to_location))
		check_tote_move(tote.warehouse, self.to_location)

	def after_insert(self):
		tote = frappe.get_doc("Storage Bin", self.storage_bin)
		parent = frappe.db.get_value("Warehouse", self.to_location, "parent_warehouse")
		warehouse = frappe.get_doc("Warehouse", tote.warehouse)
		if warehouse.parent_warehouse != parent:
			# keep ERPNext's warehouse-tree reports right: the tote's stock sits under its slot.
			# System-managed warehouse; the permitted act is this movement (see Storage Bin)
			warehouse.parent_warehouse = parent
			warehouse.save(ignore_permissions=True)
		tote.db_set({"location": self.to_location, "last_moved_on": now_datetime()})
		for location in (self.from_location, self.to_location):
			queue_floor_refresh(floor_of(location))
