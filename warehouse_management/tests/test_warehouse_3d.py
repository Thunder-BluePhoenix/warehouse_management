import unittest
from unittest.mock import patch

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
		# ERPNext's test company on CI (bootstrap_test_data), else whatever the dev site has
		cls.company = frappe.db.get_value("Company", "_Test Company") or frappe.db.get_value(
			"Company", {}, "name"
		)
		if not cls.company:
			raise unittest.SkipTest("needs at least one Company on the test site")
		cls.root = frappe.db.get_value(
			"Warehouse", {"company": cls.company, "is_group": 1, "parent_warehouse": ["in", ["", None]]}
		)

	def _make(self, name, wt_type, is_group=1, parent=None):
		return frappe.get_doc(
			doctype="Warehouse",
			warehouse_name=name,
			company=self.company,
			parent_warehouse=parent or self.root,
			is_group=is_group,
			wt_warehouse_type=wt_type,
		).insert()

	def _stock_item(self):
		item = frappe.db.get_value("Item", {"is_stock_item": 1, "has_serial_no": 0, "has_batch_no": 0})
		if not item:
			self.skipTest("needs a stock Item on the test site")
		return item

	def _user(self, email, roles):
		if not frappe.db.exists("User", email):
			frappe.get_doc(
				doctype="User",
				email=email,
				first_name="WM Test",
				send_welcome_email=0,
				roles=[{"role": r} for r in roles],
			).insert(ignore_permissions=True)
		return email

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
		wh = self._make("_WT Test Level", "Level", is_group=0)
		frappe.get_doc(doctype="Bin", item_code=item, warehouse=wh.name, actual_qty=5).insert()

		with self.assertRaises(frappe.ValidationError):
			api.delete_warehouse(wh.name)
		self.assertEqual(frappe.db.get_value("Warehouse", wh.name, "disabled"), 0)

	def test_get_slots_returns_levels_fill_and_items_in_constant_queries(self):
		item = self._stock_item()
		building = self._make("_WT Q Building", "Building")
		floor = self._make("_WT Q Floor", "Floor", parent=building.name)
		slots = [self._make(f"_WT Q S{i}", "Slot", parent=floor.name) for i in range(5)]
		levels = [
			[self._make(f"_WT Q S{i}-L{j}", "Level", is_group=0, parent=slot.name) for j in range(4)]
			for i, slot in enumerate(slots)
		]
		stocked, cap_only = levels[0][0], levels[0][1]
		frappe.get_doc(doctype="Bin", item_code=item, warehouse=stocked.name, actual_qty=5).insert()
		api.save_uom_capacity(stocked.name, frappe.db.get_value("Item", item, "stock_uom"), 10)
		api.save_uom_capacity(cap_only.name, "Kg", 500)

		# 20 levels: the old per-level code ran ~66 queries here. The first call also loads metadata and UOM
		# conversions (once per process/request); a warm call must run only the fixed floor queries.
		api.get_slots(floor.name)
		with self.assertQueryCount(12):
			result = api.get_slots(floor.name)

		self.assertEqual([len(sl["levels"]) for sl in result], [4] * 5)
		first = result[0]["levels"]
		self.assertEqual([lv["label"] for lv in first], [f"_WT Q S0-L{j}" for j in range(4)])
		uom = frappe.db.get_value("Item", item, "stock_uom")
		self.assertEqual(first[0]["uoms"], [{"u": uom, "qty": 5.0, "reserved": 0.0, "cap": 10.0}])
		self.assertEqual((first[0]["items"][0]["c"], first[0]["items"][0]["a"]), (item, 5))
		self.assertEqual(first[1]["uoms"], [{"u": "Kg", "qty": 0, "reserved": 0, "cap": 500.0}])
		self.assertEqual((first[2]["uoms"], first[2]["items"]), ([], []))

	def test_access_follows_erpnext_warehouse_and_bin_permissions(self):
		stock_user = self._user("wm-test-stock-user@example.com", ["Stock User"])
		item_manager = self._user("wm-test-item-manager@example.com", ["Stock User", "Item Manager"])
		accounts_user = self._user("wm-test-accounts-user@example.com", ["Accounts User"])
		slot = self._make("_WT Perm Slot", "Slot")
		try:
			frappe.set_user(stock_user)
			self.assertEqual((api.can_view(), api.can_edit()), (True, False))
			with self.assertRaises(frappe.PermissionError):
				api.save_slot_position(slot.name, 1, 1)

			frappe.set_user(item_manager)  # Item Manager holds Warehouse write in ERPNext
			self.assertEqual((api.can_view(), api.can_edit()), (True, True))
			api.save_slot_position(slot.name, 1, 1)

			frappe.set_user(accounts_user)  # reads Warehouse but not Bin (stock)
			self.assertFalse(api.can_view())
			with self.assertRaises(frappe.PermissionError):
				api.get_warehouse_groups()
		finally:
			frappe.set_user("Administrator")

	def test_setup_wizard_maps_tree_depths_to_roles(self):
		building = self._make("_WT M Building", None)
		floor = self._make("_WT M Floor", None, parent=building.name)
		slot = self._make("_WT M Slot", None, parent=floor.name)
		level = self._make("_WT M Level", None, is_group=0, parent=slot.name)

		scan = setup_api.scan_warehouse_tree(self.company)
		self.assertTrue({2, 3, 4, 5} <= {d["depth"] for d in scan["depths"]})

		roles = {2: "Building", 3: "Floor", 4: "Slot", 5: "Level"}
		setup_api.apply_depth_mapping([{"depth": d, "role": r} for d, r in roles.items()], self.company)
		self.assertEqual(
			[
				frappe.db.get_value("Warehouse", w.name, "wt_warehouse_type")
				for w in (building, floor, slot, level)
			],
			["Building", "Floor", "Slot", "Level"],
		)
		self.assertGreaterEqual(setup_api.get_setup_summary().get("Level", 0), 1)

	def test_role_labels_are_configurable(self):
		"""WMS Settings > Location Labels renames what Warehouse 3D shows; a blank label keeps the role name."""
		settings = frappe.get_single("WMS Settings")
		settings.update({"label_floor": "Pillar", "label_slot": " Bay ", "label_building": ""})
		settings.save()
		labels = api.get_user_access()["labels"]
		self.assertEqual(
			(labels["Floor"], labels["Slot"], labels["Building"], labels["Level"]),
			("Pillar", "Bay", "Building", "Level"),
		)
		self.assertEqual(set(labels), set(api.ROLES))

	def test_level_extras_from_settings_and_hooks(self):
		"""Serial numbers with the configured fields, Warehouse fields to show, and what other apps add through the
		wm_location_badges and wm_location_search hooks (faked here, so the test needs no other app)."""
		floor = self._make("_WT X Floor", "Floor", parent=self._make("_WT X Building", "Building").name)
		slot = self._make("_WT X Slot", "Slot", parent=floor.name)
		level = self._make("_WT X Slot-L0", "Level", is_group=0, parent=slot.name)
		item = frappe.db.get_value("Item", {"has_serial_no": 1, "is_stock_item": 1}) or frappe.get_doc(
			doctype="Item", item_code="_WT Serial Item", item_group="All Item Groups", stock_uom="Nos",
			is_stock_item=1, has_serial_no=1,
		).insert().name  # fmt: skip
		sn = frappe.get_doc(
			doctype="Serial No", serial_no=f"_WT-SN-{frappe.generate_hash(length=6)}", item_code=item
		).insert()
		sn.db_set("warehouse", level.name)
		settings = frappe.get_single("WMS Settings")
		settings.update(
			{
				"serial_no_fields": "item_name",
				"warehouse_fields": "warehouse_name",
				"bay_fill": "Share of Levels Used",
			}
		)
		settings.save()
		FAKE_HITS[:] = [{"kind": "Fake", "ref": "X-1", "item": None, "warehouse": level.name, "qty": 1}]

		hooks = {
			"wm_location_badges": [f"{__name__}.fake_badges"],
			"wm_location_search": [f"{__name__}.fake_search"],
		}
		real = frappe.get_hooks
		with patch(
			"frappe.get_hooks",
			side_effect=lambda hook=None, *a, **kw: hooks.get(hook) or real(hook, *a, **kw),
		):
			(found,) = api.get_slots(floor.name)
			hits = api.find_locations("_WT X Slot")
		lv = found["levels"][0]
		self.assertEqual([x["sn"] for x in lv["serials"]], [sn.name])
		self.assertEqual(lv["serials"][0]["fields"][0]["label"], "Item Name")
		self.assertEqual(lv["badges"], [{"label": "Held", "color": "orange"}])
		self.assertEqual(lv["details"], [{"label": "Warehouse Name", "value": "_WT X Slot-L0"}])
		self.assertEqual(found["details"], [{"label": "Warehouse Name", "value": "_WT X Slot"}])
		self.assertEqual(hits[0]["ref"], slot.name)  # the closest location first
		self.assertIn(("Fake", "X-1"), [(h["kind"], h["ref"]) for h in hits])
		self.assertEqual(api.get_user_access()["bay_fill"], "Share of Levels Used")

		settings.serial_no_fields = "no_such_field"
		self.assertRaises(frappe.ValidationError, settings.save)


FAKE_HITS = []


def fake_badges(levels, serials):
	return {lv: [{"label": "Held", "color": "orange"}] for lv, names in serials.items() if names}


def fake_search(query):
	return FAKE_HITS
