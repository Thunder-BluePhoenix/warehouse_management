import unittest
from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from warehouse_management import warehouse_rules
from warehouse_management.api import warehouse_3d as api

HSN = "870310"  # india_compliance requires an HSN code on items


class TestWarehouseFeatures(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.company = frappe.db.get_value("Company", {}, "name")
		if not cls.company:
			raise unittest.SkipTest("needs at least one Company on the test site")
		cls.root = frappe.db.get_value(
			"Warehouse", {"company": cls.company, "is_group": 1, "parent_warehouse": ["in", ["", None]]}
		)

	# ── fixtures ─────────────────────────────────────────────

	def wh(self, name, role, parent=None, is_group=1, **extra):
		return frappe.get_doc(
			doctype="Warehouse",
			warehouse_name=name,
			company=self.company,
			parent_warehouse=parent or self.root,
			is_group=is_group,
			wt_warehouse_type=role,
			**extra,
		).insert()

	def floor_with_levels(self, prefix, levels=2, **level_extra):
		building = self.wh(f"{prefix} B", "Building")
		floor = self.wh(f"{prefix} F", "Floor", building.name)
		slot = self.wh(f"{prefix} S", "Slot", floor.name)
		lvls = [self.wh(f"{prefix} L{i}", "Bin", slot.name, is_group=0, **level_extra) for i in range(levels)]
		return floor, slot, lvls

	def item(self, code, **kw):
		if not frappe.db.exists("Item", code):
			frappe.get_doc(
				doctype="Item",
				item_code=code,
				item_group="All Item Groups",
				stock_uom=kw.pop("stock_uom", "Nos"),
				is_stock_item=1,
				gst_hsn_code=HSN,
				**kw,
			).insert()
		return code

	def receive(self, item_code, warehouse, qty=1, submit=True, **row):
		entry = frappe.get_doc(
			doctype="Stock Entry",
			stock_entry_type="Material Receipt",
			company=self.company,
			items=[{"item_code": item_code, "qty": qty, "t_warehouse": warehouse, "basic_rate": 10, **row}],
		).insert()
		if submit:
			entry.submit()
		return entry

	# ── zones (dynamic depth) ───────────────────────────────

	def test_zones_nest_to_any_depth_and_slots_report_their_path(self):
		building = self.wh("_WF Z B", "Building")
		floor = self.wh("_WF Z F", "Floor", building.name)
		zone = self.wh("_WF Zone A", "Zone", floor.name)
		rack = self.wh("_WF Rack 01", "Zone", zone.name)
		deep = self.wh("_WF Z Deep", "Slot", rack.name)
		self.wh("_WF Z Direct", "Slot", floor.name)
		self.wh("_WF Z L", "Bin", deep.name, is_group=0)

		slots = {s["label"]: s for s in api.get_slots(floor.name)}
		self.assertEqual(slots["_WF Z Deep"]["zone_path"], ["_WF Zone A", "_WF Rack 01"])
		self.assertEqual(slots["_WF Z Direct"]["zone_path"], [])
		self.assertEqual(len(slots["_WF Z Deep"]["levels"]), 1)
		group = next(g for g in api.get_warehouse_groups(self.company) if g.id == floor.name)
		self.assertEqual(group.slot_count, 2)
		parents = {p.name for p in api.get_parent_warehouse_options("Slot", self.company)}
		self.assertTrue({floor.name, zone.name, rack.name} <= parents)

	# ── search ──────────────────────────────────────────────

	def test_find_locations_by_serial_batch_and_item(self):
		floor, slot, (level, _other) = self.floor_with_levels("_WF Srch")
		serial_item = self.item("_WF Serial Item", has_serial_no=1)
		self.receive(serial_item, level.name, use_serial_batch_fields=1, serial_no="_WF-SN-0001")
		batch_item = self.item("_WF Batch Item", has_batch_no=1)
		frappe.get_doc(doctype="Batch", batch_id="_WF-BATCH-01", item=batch_item).insert()
		self.receive(batch_item, level.name, qty=5, use_serial_batch_fields=1, batch_no="_WF-BATCH-01")

		serial_hit = api.find_locations("_WF-SN-0001")
		self.assertEqual(
			[(h["kind"], h["warehouse"], h["floor"], h["slot"]) for h in serial_hit],
			[("Serial No", level.name, floor.name, slot.name)],
		)
		batch_hits = [h for h in api.find_locations("_WF-BATCH-01") if h["kind"] == "Batch"]
		self.assertEqual([(h["warehouse"], h["qty"]) for h in batch_hits], [(level.name, 5)])
		item_hits = [h for h in api.find_locations("_WF Batch") if h["kind"] == "Item"]
		self.assertEqual({h["warehouse"] for h in item_hits}, {level.name})

	# ── weight, bay type, level payload ─────────────────────

	def test_weight_limit_blocks_or_warns_and_bay_type_is_enforced(self):
		frappe.get_doc(doctype="Bay Type", bay_type_name="_WF Heavy").insert()
		frappe.get_doc(doctype="Bay Type", bay_type_name="_WF Light").insert()
		_floor, _slot, (level, _other) = self.floor_with_levels(
			"_WF Wt", wt_max_weight_kg=100, wt_weight_limit_action="Block", wt_bay_type="_WF Heavy"
		)
		scrap = self.item("_WF Scrap Iron", stock_uom="Kg")
		self.receive(scrap, level.name, qty=60)
		with self.assertRaises(frappe.ValidationError):
			self.receive(scrap, level.name, qty=50)  # 110 kg > 100 kg, Block

		frappe.db.set_value("Warehouse", level.name, "wt_weight_limit_action", "Warn")
		frappe.message_log.clear()
		self.receive(scrap, level.name, qty=50)  # Warn: posts, with a message
		self.assertTrue(any("above its limit" in str(m) for m in frappe.message_log))

		light = self.item("_WF Light Part", wt_bay_type="_WF Light")
		with self.assertRaises(frappe.ValidationError):
			self.receive(light, level.name)

	def test_level_payload_has_weight_bay_type_area_and_item_count(self):
		floor, _slot, (level, _other) = self.floor_with_levels(
			"_WF Pay", wt_max_weight_kg=500, wt_length=4, wt_breadth=2.5
		)
		self.assertEqual(frappe.db.get_value("Warehouse", level.name, "wt_area"), 10)
		self.receive(self.item("_WF Pay Kg", stock_uom="Kg"), level.name, qty=40)
		self.receive(self.item("_WF Pay Nos"), level.name, qty=3)  # no known weight

		payload = api.get_slots(floor.name)[0]["levels"][0]
		self.assertEqual((payload["kg"], payload["max_kg"], payload["kg_partial"]), (40, 500, True))
		self.assertEqual((payload["item_count"], payload["area"]), (2, 10))

	def test_full_item_list_beyond_top_twenty(self):
		floor, _slot, (level, _other) = self.floor_with_levels("_WF Many")
		for i in range(22):
			frappe.get_doc(
				doctype="Bin",
				item_code=self.item(f"_WF Many {i:02d}"),
				warehouse=level.name,
				actual_qty=i + 1,
			).insert()
		payload = api.get_slots(floor.name)[0]["levels"][0]
		self.assertEqual((len(payload["items"]), payload["item_count"]), (20, 22))
		self.assertEqual(len(api.get_level_items(level.name)), 22)

	# ── putaway rules, bay suggestion ───────────────────────

	def test_sync_putaway_rules_from_capacities(self):
		_floor, slot, (level, other) = self.floor_with_levels("_WF Put")
		part = self.item("_WF Put Part")
		api.save_uom_capacity(level.name, "Nos", 10)
		self.receive(part, level.name, qty=3)

		first = api.sync_putaway_rules(slot.name)
		self.assertEqual((first["created"], first["updated"]), (1, 0))
		self.assertEqual(
			frappe.db.get_value("Putaway Rule", {"item_code": part, "warehouse": level.name}, "capacity"), 10
		)
		api.save_uom_capacity(other.name, "Nos", 5)
		second = api.sync_putaway_rules(slot.name)
		self.assertEqual((second["created"], second["updated"]), (1, 1))

	def test_suggest_free_bay_skips_full_and_wrong_type_levels(self):
		frappe.get_doc(doctype="Bay Type", bay_type_name="_WF Car").insert()
		frappe.get_doc(doctype="Bay Type", bay_type_name="_WF Truck").insert()
		floor, slot, (full, free) = self.floor_with_levels("_WF Bay", wt_bay_type="_WF Car")
		truck_bay = self.wh("_WF Bay L9", "Bin", slot.name, is_group=0, wt_bay_type="_WF Truck")
		for lv in (full, free, truck_bay):
			api.save_uom_capacity(lv.name, "Nos", 1)
		car = self.item("_WF Car Unit", wt_bay_type="_WF Car")
		self.receive(car, full.name)

		self.assertEqual(api.suggest_free_bay(floor.name, car)["warehouse"], free.name)
		self.receive(car, free.name)
		self.assertIsNone(api.suggest_free_bay(floor.name, car))  # only the truck bay is left

	# ── gate entry ──────────────────────────────────────────

	def test_gate_entry_in_and_out_post_and_cancel_stock(self):
		_floor, _slot, (level, _other) = self.floor_with_levels("_WF Gate")
		vehicle = self.item("_WF Gate Vehicle", has_serial_no=1)

		gate_in = frappe.get_doc(
			doctype="Gate Entry",
			entry_type="In",
			company=self.company,
			item_code=vehicle,
			serial_no="_WF-GATE-01",
			warehouse=level.name,
			allow_zero_valuation_rate=1,
			reference_no="DL1AB1234",
		).insert()
		gate_in.submit()
		self.assertEqual(frappe.db.get_value("Stock Entry", gate_in.stock_entry, "docstatus"), 1)
		self.assertEqual(frappe.db.get_value("Serial No", "_WF-GATE-01", "warehouse"), level.name)

		gate_out = frappe.get_doc(
			doctype="Gate Entry",
			entry_type="Out",
			company=self.company,
			item_code=vehicle,
			serial_no="_WF-GATE-01",
		).insert()
		self.assertEqual(gate_out.warehouse, level.name)  # taken from the serial
		gate_out.submit()
		self.assertFalse(frappe.db.get_value("Serial No", "_WF-GATE-01", "warehouse"))

		gate_out.cancel()
		self.assertEqual(frappe.db.get_value("Stock Entry", gate_out.stock_entry, "docstatus"), 2)
		self.assertEqual(frappe.db.get_value("Serial No", "_WF-GATE-01", "warehouse"), level.name)

	# ── live refresh ────────────────────────────────────────

	def test_stock_posting_notifies_viewers_of_the_changed_floor(self):
		floor, _slot, (level, _other) = self.floor_with_levels("_WF Live")
		frappe.flags.pop("wt3d_changed_floors", None)
		self.receive(self.item("_WF Live Part"), level.name)
		with patch("frappe.publish_realtime") as publish:
			warehouse_rules._publish_changed_floors()  # what the after-commit callback runs
		publish.assert_called_once_with("wt3d_stock_changed", {"floors": [floor.name]})
