import unittest

import frappe
from frappe.tests import IntegrationTestCase

from warehouse_management.api import warehouse_3d as api
from warehouse_management.api import warehouse_3d_setup as setup_api

WRITE_ENDPOINTS = [
	api.save_slot_position,
	api.save_floor_layout,
	api.save_uom_capacity,
	api.create_warehouse,
	api.update_warehouse,
	api.delete_warehouse,
	setup_api.apply_depth_mapping,
]


class TestWarehouse3DSecurity(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.company = frappe.db.get_value("Company", {}, "name")
		if not cls.company:
			raise unittest.SkipTest("needs at least one Company on the test site")
		cls.root = frappe.db.get_value(
			"Warehouse", {"company": cls.company, "is_group": 1, "parent_warehouse": ["in", ["", None]]}
		)

	def _make(self, name, wt_type, is_group=1):
		return frappe.get_doc(
			doctype="Warehouse",
			warehouse_name=name,
			company=self.company,
			parent_warehouse=self.root,
			is_group=is_group,
			wt_warehouse_type=wt_type,
		).insert()

	def test_write_endpoints_are_post_only(self):
		# GET skips CSRF validation in Frappe, so state-changing endpoints must refuse it.
		for fn in WRITE_ENDPOINTS:
			self.assertEqual(frappe.allowed_http_methods_for_whitelisted_func[fn], ["POST"], fn.__name__)

	def test_rename_only_update_keeps_layout_and_capacity(self):
		slot = self._make("_WT Test Slot", "Slot")
		api.save_slot_position(slot.name, 3, 4, 1.5)
		api.save_uom_capacity(slot.name, "Nos", 10)
		api.update_warehouse(slot.name, {"warehouse_name": "_WT Test Slot Renamed"})

		slot.reload()
		self.assertEqual((slot.wt_row, slot.wt_col, slot.wt_row_gap), (3, 4, 1.5))
		self.assertEqual([(r.uom, r.capacity) for r in slot.wt_uom_capacities], [("Nos", 10)])
		# Version rows (audit) are not asserted: Frappe skips them under the test runner (document.py _save,
		# ignore_version = frappe.in_test). Verified manually via bench console on 2026-09-24.

	def test_delete_refuses_warehouse_that_holds_stock(self):
		item = frappe.db.get_value("Item", {"is_stock_item": 1, "has_serial_no": 0, "has_batch_no": 0})
		if not item:
			self.skipTest("needs a stock Item on the test site")
		wh = self._make("_WT Test Level", "Bin", is_group=0)
		frappe.get_doc(doctype="Bin", item_code=item, warehouse=wh.name, actual_qty=5).insert()

		with self.assertRaises(frappe.ValidationError):
			api.delete_warehouse(wh.name)
		self.assertEqual(frappe.db.get_value("Warehouse", wh.name, "disabled"), 0)
