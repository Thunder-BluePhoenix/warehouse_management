"""The left-pane tree and the map: one level of the warehouse tree at a time, the path down to a warehouse, a whole
site in place with each warehouse's position and size, and the layout editor's save."""

import json
import unittest
import unittest.mock

import frappe
from frappe.tests import IntegrationTestCase

from warehouse_management.api import warehouse_3d as api


class TestWarehouseMap(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.company = frappe.db.get_value("Company", "_Test Company") or frappe.db.get_value(
			"Company", {}, "name"
		)
		if not cls.company:
			raise unittest.SkipTest("needs at least one Company on the test site")
		cls.root = frappe.db.get_value(
			"Warehouse", {"company": cls.company, "is_group": 1, "parent_warehouse": ["in", ["", None]]}
		)

	def make(self, name, wt_type=None, is_group=1, parent=None):
		return frappe.get_doc(
			doctype="Warehouse", warehouse_name=f"{name} {self.tag}", company=self.company,
			parent_warehouse=parent or self.root, is_group=is_group, wt_warehouse_type=wt_type,
		).insert().name  # fmt: skip

	def setUp(self):
		frappe.set_user("Administrator")
		self.tag = frappe.generate_hash(length=5).upper()
		# a site: a parking area (an untyped group) with a floor of two slots, each slot with a level; and a gate
		self.site = self.make("Site", "Building")
		self.gate = self.make("Gate", None, is_group=0, parent=self.site)
		self.area = self.make("Parking", None, parent=self.site)
		self.floor = self.make("Pillar A", "Floor", parent=self.area)
		self.slots = [self.make(f"Bay {i}", "Slot", parent=self.floor) for i in (1, 2)]
		self.levels = [self.make(f"L {i}", "Level", is_group=0, parent=s) for i, s in enumerate(self.slots)]

	def test_tree_one_level_at_a_time(self):
		top = api.get_tree()
		self.assertIn(self.root, [n["id"] for n in top])  # the top of the tree
		kids = {n["id"]: n for n in api.get_tree(parent=self.site)}
		self.assertEqual(set(kids), {self.gate, self.area})
		self.assertEqual((kids[self.area]["children"], kids[self.gate]["children"]), (1, 0))
		floor = api.get_tree(parent=self.area)[0]
		self.assertEqual((floor["id"], floor["type"], floor["slot_count"]), (self.floor, "Floor", 2))
		bays = api.get_tree(parent=self.slots[0])
		self.assertEqual(bays, [])  # levels are inside their slot in the 3D view, not in the tree
		self.assertEqual(api.get_path(self.levels[0])[-3:], [self.area, self.floor, self.slots[0]])

	def test_disabled_warehouses_are_left_out(self):
		frappe.db.set_value("Warehouse", self.gate, "disabled", 1)
		self.assertNotIn(self.gate, [n["id"] for n in api.get_tree(parent=self.site)])

	def test_map_draws_the_site_in_place(self):
		m = api.get_map(self.site)
		ids = {n["id"]: n for n in m["nodes"]}
		self.assertEqual(
			set(ids), {self.site, self.gate, self.area, self.floor}
		)  # slots and levels are the floor's
		self.assertIsNone(ids[self.area]["x"])  # not placed yet: the map arranges it
		self.assertEqual([s["wh"] for s in m["slots"][self.floor]], self.slots)
		self.assertEqual(len(m["slots"][self.floor][0]["levels"]), 1)

	def test_map_racks_come_in_pages(self):
		other = self.make("Pillar B", "Floor", parent=self.area)
		with unittest.mock.patch.object(api, "MAP_FLOORS", 1):
			first = api.get_map(self.site)
			self.assertEqual((list(first["slots"]), first["next"], first["floors"]), ([self.floor], 1, 2))
			rest = api.get_map(self.site, start=first["next"])
			self.assertEqual((list(rest["slots"]), rest["next"]), ([other], None))
			self.assertNotIn("nodes", rest)  # a later page is only the racks

	def test_save_positions(self):
		saved = api.save_positions(
			json.dumps(
				[
					{"warehouse": self.area, "x": 12.25, "y": 0, "length": 40, "breadth": 20, "rotation": 90},
					{"warehouse": self.slots[1], "x": 3, "y": 4.5},
				]
			)
		)
		self.assertEqual(set(saved["saved"]), {self.area, self.slots[1]})
		ids = {n["id"]: n for n in api.get_map(self.site)["nodes"]}
		a = ids[self.area]
		self.assertEqual((a["x"], a["y"], a["length"], a["breadth"], a["rotation"]), (12.25, 0, 40, 20, "90"))
		bay = next(s for s in api.get_map(self.site)["slots"][self.floor] if s["wh"] == self.slots[1])
		self.assertEqual(
			(bay["x"], bay["y"]), (3, 4.5)
		)  # a bay's place on its floor: the spaces between bays
		self.assertIsNone(ids[self.gate]["x"])  # untouched: still arranged by the map
		self.assertRaises(
			frappe.ValidationError,
			api.save_positions,
			json.dumps([{"warehouse": self.area, "length": -1}]),
		)

	def test_writes_are_post_only_and_need_edit_rights(self):
		self.assertEqual(frappe.allowed_http_methods_for_whitelisted_func[api.save_positions], ["POST"])
		email = f"wm-map-reader-{self.tag.lower()}@example.com"
		frappe.get_doc(doctype="User", email=email, first_name="Map", send_welcome_email=0,
			roles=[{"role": "Stock User"}]).insert(ignore_permissions=True)  # fmt: skip
		frappe.set_user(email)
		self.assertRaises(
			frappe.PermissionError, api.save_positions, json.dumps([{"warehouse": self.area, "x": 1}])
		)

	def test_position_from_the_warehouse_form(self):
		api.update_warehouse(self.gate, json.dumps({"wt_pos_x": 5, "wt_pos_y": 2.5, "wt_rotation": "90"}))
		g = next(n for n in api.get_map(self.site)["nodes"] if n["id"] == self.gate)
		self.assertEqual((g["x"], g["y"], g["rotation"]), (5, 2.5, "90"))
		api.update_warehouse(
			self.gate, json.dumps({"wt_pos_x": None, "wt_pos_y": None})
		)  # both blank: auto again
		g = next(n for n in api.get_map(self.site)["nodes"] if n["id"] == self.gate)
		self.assertIsNone(g["x"])
