from unittest.mock import patch

import erpnext
import frappe
from frappe.utils import add_days, nowdate

from warehouse_management.api import scan
from warehouse_management.api import warehouse_3d as api
from warehouse_management.tests.test_wm_features import WMTestCase


class TestWmsOperations(WMTestCase):
	"""Totes, WMS Settings, splitting an area, and the scan screen's put-away and picking."""

	def settings(self, **values):
		doc = frappe.get_doc("WMS Settings")
		before = {k: doc.get(k) for k in values}
		doc.update(values)
		doc.save()
		# restore by saving again, which also refreshes the cached settings
		self.addCleanup(lambda: frappe.get_doc("WMS Settings").update(before).save())

	def two_slots(self, prefix, **level_extra):
		floor, slot, (level, _other) = self.floor_with_levels(prefix, **level_extra)
		slot2 = self.wh(f"{prefix} S2", "Slot", floor.name)
		level2 = self.wh(f"{prefix} S2 L0", "Level", slot2.name, is_group=0, **level_extra)
		return floor, (slot, level), (slot2, level2)

	def tote(self, bin_id, location=None):
		return frappe.get_doc(
			doctype="Storage Bin", bin_id=bin_id, company=self.company, location=location
		).insert()

	def payload(self, floor, level):
		return next(lv for sl in api.get_slots(floor.name) for lv in sl["levels"] if lv["wh"] == level)

	def sales_order(self, item_code, qty, warehouse):
		customer = frappe.db.exists("Customer", "_WO Customer") or (
			frappe.get_doc(
				doctype="Customer",
				customer_name="_WO Customer",
				customer_group=frappe.db.get_value("Customer Group", {"is_group": 0}),
				territory=frappe.db.get_value("Territory", {"is_group": 0}),
			)
			.insert()
			.name
		)
		order = frappe.get_doc(
			doctype="Sales Order",
			customer=customer,
			company=self.company,
			transaction_date=nowdate(),
			delivery_date=add_days(nowdate(), 7),
			set_warehouse=warehouse,
			items=[{"item_code": item_code, "qty": qty, "rate": 100, "warehouse": warehouse}],
		).insert()
		order.submit()
		return order

	# ── settings ────────────────────────────────────────────

	def test_settings_turn_block_into_a_warning_and_raise_an_early_alarm(self):
		_floor, _slot, (level, other) = self.floor_with_levels(
			"_WO Set", wt_max_weight_kg=100, wt_weight_limit_action="Block"
		)
		scrap = self.item("_WO Scrap", stock_uom="Kg")

		self.settings(enforce_weight_block=0)
		frappe.message_log.clear()
		self.receive(scrap, level.name, qty=150)  # Block is not enforced: posts with a warning
		self.assertTrue(any("above its limit" in str(m) for m in frappe.message_log))

		self.settings(enforce_weight_block=1, weight_alarm_percent=80)
		frappe.message_log.clear()
		self.receive(scrap, other.name, qty=85)
		self.assertTrue(any("of its weight limit" in str(m) for m in frappe.message_log))

	# ── totes ───────────────────────────────────────────────

	def test_tote_holds_stock_in_its_own_warehouse_and_moves_with_its_history(self):
		floor, (slot, level), (slot2, level2) = self.two_slots("_WO Tote")
		tote = self.tote("_WO-T1", location=level.name)
		self.assertEqual(
			frappe.db.get_value("Warehouse", tote.warehouse, ["wt_warehouse_type", "parent_warehouse"]),
			("Tote", slot.name),
		)
		if erpnext.is_perpetual_inventory_enabled(self.company):  # pinned, so moves never change it
			self.assertTrue(frappe.db.get_value("Warehouse", tote.warehouse, "account"))
		part = self.item("_WO Tote Part")
		loose = self.item("_WO Tote Loose")
		self.receive(part, tote.warehouse, qty=3)
		self.receive(loose, level.name, qty=1)  # stock on the level itself, beside the tote

		at_level = self.payload(floor, level.name)
		self.assertEqual(at_level["totes"], ["_WO-T1"])
		self.assertEqual([(i["c"], i["t"]) for i in at_level["items"]], [(part, "_WO-T1"), (loose, None)])
		self.assertEqual((at_level["item_count"], at_level["uoms"][0]["qty"]), (2, 4))
		self.assertEqual([i["t"] for i in api.get_level_items(level.name)], ["_WO-T1", None])
		hit = next(h for h in api.find_locations("_WO Tote Part") if h["kind"] == "Item")
		self.assertEqual((hit["warehouse"], hit["tote"], hit["slot"]), (level.name, "_WO-T1", slot.name))

		scan.move_tote("_WO-T1", level2.name)
		self.assertEqual(frappe.db.get_value("Storage Bin", "_WO-T1", "location"), level2.name)
		self.assertEqual(frappe.db.get_value("Warehouse", tote.warehouse, "parent_warehouse"), slot2.name)
		self.assertEqual(self.payload(floor, level.name)["totes"], [])
		self.assertEqual(self.payload(floor, level2.name)["totes"], ["_WO-T1"])
		history = frappe.get_all(
			"Storage Bin Movement",
			filters={"storage_bin": "_WO-T1"},
			fields=["from_location", "to_location"],
			order_by="creation asc",
		)
		self.assertEqual(
			[(m.from_location, m.to_location) for m in history],
			[(None, level.name), (level.name, level2.name)],
		)
		with self.assertRaises(frappe.ValidationError):
			scan.move_tote("_WO-T1", level2.name)  # already there

	def test_tote_contents_count_against_the_level_weight_and_bay_rules(self):
		frappe.get_doc(doctype="Bay Type", bay_type_name="_WO Heavy").insert()
		frappe.get_doc(doctype="Bay Type", bay_type_name="_WO Small").insert()
		_floor, (_slot, level), (_slot2, small) = self.two_slots(
			"_WO Rule", wt_max_weight_kg=50, wt_weight_limit_action="Block"
		)
		frappe.db.set_value("Warehouse", level.name, "wt_bay_type", "_WO Heavy")
		frappe.db.set_value("Warehouse", small.name, "wt_bay_type", "_WO Small")
		scrap = self.item("_WO Rule Scrap", stock_uom="Kg", wt_bay_type="_WO Heavy")
		tote = self.tote("_WO-T2", location=level.name)

		self.receive(scrap, tote.warehouse, qty=40)  # into the tote: checked against its level
		with self.assertRaises(frappe.ValidationError):
			self.receive(scrap, level.name, qty=20)  # 40 in the tote + 20 > 50 kg
		with self.assertRaises(frappe.ValidationError):
			scan.move_tote("_WO-T2", small.name)  # heavy-bay item into a small bay

	# ── split an area ───────────────────────────────────────

	def test_split_area_creates_a_sibling_and_moves_stock(self):
		_floor, slot, (level, _other) = self.floor_with_levels(
			"_WO Split", wt_length=10, wt_breadth=4, wt_max_weight_kg=1000
		)
		scrap = self.item("_WO Split Iron", stock_uom="Kg")
		self.receive(scrap, level.name, qty=300)

		result = api.split_area(
			level.name,
			"_WO Split A3",
			length=5,
			breadth=4,
			max_weight_kg=500,
			keep={"length": 5, "breadth": 4, "max_weight_kg": 500},
			moves=[{"item_code": scrap, "qty": 100}],
		)
		new = frappe.get_doc("Warehouse", result["name"])
		self.assertEqual(
			(new.parent_warehouse, new.wt_split_from, new.wt_area, new.wt_max_weight_kg),
			(slot.name, level.name, 20, 500),
		)
		self.assertEqual(frappe.db.get_value("Warehouse", level.name, "wt_area"), 20)
		from erpnext.stock.utils import get_stock_balance

		self.assertEqual(
			(get_stock_balance(scrap, level.name), get_stock_balance(scrap, new.name)), (200, 100)
		)

	# ── scan: put-away ──────────────────────────────────────

	def test_scan_resolves_codes_and_puts_away_to_levels_and_totes(self):
		_floor, _slot, (level, other) = self.floor_with_levels("_WO Put")
		stage = self.wh("_WO Stage", None, is_group=0)
		tote = self.tote("_WO-T3", location=other.name)
		part = self.item("_WO Put Part")
		self.receive(part, stage.name, qty=5)
		self.receive(part, level.name, qty=1)

		self.assertEqual(scan.resolve(part)["kind"], "item")
		self.assertEqual(scan.resolve("_WO-T3")["kind"], "tote")
		self.assertEqual(scan.resolve("_WO Put L0")["warehouse"], level.name)  # label without " - ABBR"
		self.assertEqual(scan.suggest_putaway(part)["code"], level.name)  # where it already is

		scan.putaway(
			stage.name,
			[
				{"item_code": part, "qty": 2, "target": level.name},
				{"item_code": part, "qty": 3, "target": "_WO-T3"},
			],
		)
		from erpnext.stock.utils import get_stock_balance

		self.assertEqual(
			[get_stock_balance(part, w) for w in (stage.name, level.name, tote.warehouse)], [0, 3, 3]
		)

	# ── scan: picking ───────────────────────────────────────

	def test_short_pick_ships_what_was_picked_and_tells_the_customer(self):
		from erpnext.selling.doctype.sales_order.sales_order import create_pick_list

		_floor, _slot, (level, _other) = self.floor_with_levels("_WO Pick")
		part = self.item("_WO Pick Part")
		self.receive(part, level.name, qty=3)
		order = self.sales_order(part, 5, level.name)
		order.db_set("contact_email", "buyer@example.com")
		pick = create_pick_list(order.name)
		pick.insert()

		with self.assertRaises(frappe.ValidationError):
			scan.record_pick(pick.name, self.item("_WO Pick Other"))  # not on this pick
		scan.record_pick(pick.name, part, qty=3, warehouse=level.name)
		self.assertEqual(sum(r["picked"] for r in scan.get_pick(pick.name)["rows"]), 3)

		with patch("frappe.sendmail") as sendmail:
			result = scan.finish_pick(pick.name)
		self.assertEqual(frappe.db.get_value("Pick List", pick.name, "docstatus"), 1)
		self.assertEqual([(s["ordered"], s["picked"], s["missing"]) for s in result["short"]], [(5, 3, 2)])
		self.assertEqual(result["notified"], [{"sales_order": order.name, "email": "buyer@example.com"}])
		sendmail.assert_called_once()
		self.assertTrue(
			frappe.db.exists("Comment", {"reference_name": order.name, "content": ["like", "%Short pick%"]})
		)
		self.assertEqual(len(result["delivery_notes"]), 1)
		self.assertEqual(
			frappe.db.get_value("Delivery Note Item", {"parent": result["delivery_notes"][0]}, "qty"), 3
		)

	def test_serial_pick_ships_exactly_the_scanned_serials(self):
		from erpnext.selling.doctype.sales_order.sales_order import create_pick_list
		from erpnext.stock.serial_batch_bundle import get_serial_nos_from_bundle

		_floor, _slot, (level, _other) = self.floor_with_levels("_WO SPick")
		part = self.item("_WO SPick Part", has_serial_no=1)
		for serial in ("_WO-SN-1", "_WO-SN-2"):
			self.receive(part, level.name, use_serial_batch_fields=1, serial_no=serial)
		pick = create_pick_list(self.sales_order(part, 2, level.name).name)
		pick.insert()

		scan.record_pick(pick.name, "_WO-SN-2")
		with self.assertRaises(frappe.ValidationError):
			scan.record_pick(pick.name, "_WO-SN-2")  # already picked
		result = scan.finish_pick(pick.name)

		row = frappe.get_doc("Pick List", pick.name).locations[0]
		self.assertEqual((row.stock_qty, row.serial_no), (1, "_WO-SN-2"))
		self.assertEqual(get_serial_nos_from_bundle(row.serial_and_batch_bundle), ["_WO-SN-2"])
		self.assertEqual([s["missing"] for s in result["short"]], [1])
