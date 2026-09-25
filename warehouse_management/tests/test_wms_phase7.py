import frappe
from frappe.utils import add_to_date, now_datetime

from warehouse_management import holds
from warehouse_management.api import scan
from warehouse_management.tests.test_wm_features import WMTestCase
from warehouse_management.warehouse_management_system.report.stock_by_facility import stock_by_facility


class TestWmsPhase7(WMTestCase):
	"""Labels, stock holds, cycle counts with approval, and the facility stock view."""

	def user(self, email, *roles):
		if not frappe.db.exists("User", email):
			frappe.get_doc(
				doctype="User",
				email=email,
				first_name=email.split("@")[0],
				send_welcome_email=0,
				roles=[{"role": r} for r in roles],
			).insert(ignore_permissions=True)
		return email

	def as_user(self, email):
		frappe.set_user(email)
		self.addCleanup(frappe.set_user, "Administrator")

	# ── labels ──────────────────────────────────────────────

	def test_labels_carry_the_scannable_code_as_qr_and_set_the_label_page_size(self):
		from frappe.utils.pdf import read_options_from_html

		_floor, _slot, (level, _other) = self.floor_with_levels("_W7 Label")
		tote = frappe.get_doc(doctype="Storage Bin", bin_id="_W7-T1", company=self.company).insert()

		html = frappe.get_print("Warehouse", level.name, print_format="WMS Location Label")
		self.assertIn("<svg", html)
		self.assertIn("_W7 Label L0", html)
		self.assertIn("_W7 Label F", html)  # the location path
		_html, options = read_options_from_html(html)
		self.assertEqual((options.get("page-width"), options.get("page-height")), ("100mm", "50mm"))
		self.assertIn("<svg", frappe.get_print("Storage Bin", tote.name, print_format="WMS Tote Label"))

	# ── stock holds (cart hold) ─────────────────────────────

	def test_holds_lower_availability_expire_and_release(self):
		_floor, _slot, (level, _other) = self.floor_with_levels("_W7 Hold")
		part = self.item("_W7 Hold Part")
		self.receive(part, level.name, qty=5)

		first = holds.create_hold(part, level.name, 3, hold_key="cart-A")
		self.assertEqual(holds.available_qty(part, level.name), 2)
		with self.assertRaises(frappe.ValidationError):
			holds.create_hold(part, level.name, 3, hold_key="cart-B")  # only 2 left

		frappe.db.set_value(
			"Stock Hold", first["name"], "expires_at", add_to_date(now_datetime(), minutes=-1)
		)
		self.assertEqual(holds.available_qty(part, level.name), 5)  # a lapsed hold no longer counts
		holds.expire_holds()
		self.assertEqual(frappe.db.get_value("Stock Hold", first["name"], "status"), "Expired")

		holds.create_hold(part, level.name, 2, hold_key="cart-B")
		holds.create_hold(part, level.name, 1, hold_key="cart-B")
		self.assertEqual(holds.get_available_qty(part, level.name)["total"], 2)
		self.assertEqual(holds.release_hold(hold_key="cart-B")["released"], 2)
		self.assertEqual(holds.available_qty(part, level.name), 5)

		kept = holds.create_hold(part, level.name, 1)
		holds.convert_hold(kept["name"], "Item", part)  # any document the hold turned into
		self.assertEqual(frappe.db.get_value("Stock Hold", kept["name"], "status"), "Converted")

	# ── cycle count ─────────────────────────────────────────

	def test_blind_count_is_approved_by_someone_else_and_posts_the_difference(self):
		_floor, _slot, (level, other) = self.floor_with_levels("_W7 Count")
		part = self.item("_W7 Count Part")
		serial_item = self.item("_W7 Count Serial", has_serial_no=1)
		found = self.item("_W7 Count Found")
		self.receive(part, level.name, qty=10)
		for serial in ("_W7-SN-1", "_W7-SN-2"):
			self.receive(serial_item, level.name, use_serial_batch_fields=1, serial_no=serial)
		counter = self.user("_w7.counter@example.com", "Stock User")
		approver = self.user("_w7.approver@example.com", "Stock Manager")

		self.as_user(counter)
		count = frappe.get_doc(doctype="Cycle Count", company=self.company, location=level.name).insert()
		self.assertEqual({r.item_code for r in count.items}, {part, serial_item})
		seen = frappe.get_doc("Cycle Count", count.name)
		seen.apply_fieldlevel_read_permissions()
		self.assertTrue(all(r.get("expected_qty") is None for r in seen.items))  # blind for the counter
		self.assertNotIn("expected_qty", scan.get_count(count.name)["rows"][0])

		scan.record_count(count.name, part, level.name, qty=7)
		scan.record_count(count.name, found, other.name, qty=2)  # not expected there
		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc("Cycle Count", count.name).send_for_approval()  # the serial row is not counted yet
		scan.record_count(count.name, "_W7-SN-1", level.name)
		frappe.get_doc("Cycle Count", count.name).send_for_approval()
		with self.assertRaises(frappe.PermissionError):
			frappe.get_doc("Cycle Count", count.name).submit()  # a counter has no right to approve

		frappe.set_user(approver)
		doc = frappe.get_doc("Cycle Count", count.name)
		self.assertEqual(
			{(r.item_code, r.expected_qty, r.counted_qty, r.variance) for r in doc.items},
			{(part, 10, 7, -3), (serial_item, 2, 1, -1), (found, 0, 2, 2)},
		)
		doc.submit()
		frappe.set_user("Administrator")

		from erpnext.stock.utils import get_stock_balance

		self.assertEqual(frappe.db.get_value("Cycle Count", count.name, "status"), "Approved")
		self.assertTrue(frappe.db.get_value("Cycle Count", count.name, "stock_reconciliation"))
		self.assertEqual(
			[get_stock_balance(i, w) for i, w in ((part, level.name), (found, other.name))], [7, 2]
		)
		self.assertFalse(frappe.db.get_value("Serial No", "_W7-SN-2", "warehouse"))  # not found: out of stock

	def test_the_counter_cannot_approve_their_own_count(self):
		_floor, _slot, (level, _other) = self.floor_with_levels("_W7 Self")
		self.receive(self.item("_W7 Self Part"), level.name, qty=1)
		manager = self.user("_w7.manager@example.com", "Stock Manager", "Stock User")
		self.as_user(manager)
		count = frappe.get_doc(doctype="Cycle Count", company=self.company, location=level.name).insert()
		count.mark_uncounted_as_zero()
		count = frappe.get_doc("Cycle Count", count.name)
		count.send_for_approval()
		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc("Cycle Count", count.name).submit()

	# ── multi-facility view ─────────────────────────────────

	def test_facility_report_splits_stock_by_building_and_subtracts_holds(self):
		_floor_a, _slot, (level_a, _o) = self.floor_with_levels("_W7 FacA")
		_floor_b, _slot, (level_b, _o) = self.floor_with_levels("_W7 FacB")
		part = self.item("_W7 Fac Part")
		self.receive(part, level_a.name, qty=4)
		self.receive(part, level_b.name, qty=6)
		holds.create_hold(part, level_b.name, 1)

		columns, rows = stock_by_facility.execute({"company": self.company, "item_code": part})
		labels = {c["fieldname"]: c["label"] for c in columns}
		row = rows[0]
		by_facility = {labels[k]: v for k, v in row.items() if k.startswith("f")}
		self.assertEqual((by_facility["_W7 FacA B"], by_facility["_W7 FacB B"]), (4, 6))
		self.assertEqual((row.in_stock, row.on_hold, row.available), (10, 1, 9))

	# ── location generator (rack naming) ────────────────────

	def test_generate_locations_builds_a_named_rack_layout_and_can_be_rerun(self):
		from warehouse_management.api import warehouse_3d as api

		building = self.wh("_W7 Gen B", "Building")
		floor = self.wh("_W7 Gen F", "Floor", building.name)
		args = dict(
			bays="A-B",
			tiers=2,
			rows=3,
			level_pattern="_G{bay}{tier}{row:02d}",
			slot_pattern="_G{bay}-{row:02d}",
		)

		preview = api.generate_locations(floor.name, preview=1, **args)
		self.assertEqual((preview["slots"], preview["levels"], preview["new_levels"]), (6, 12, 12))
		self.assertEqual(preview["sample"][0], "_GA101")
		made = api.generate_locations(floor.name, uom="Nos", capacity=4, **args)
		self.assertEqual((made["slots"], made["levels"], made["skipped"]), (6, 12, 0))

		slots = {s["label"]: s for s in api.get_slots(floor.name)}
		self.assertEqual(
			[lv["label"] for lv in slots["_GA-03"]["levels"]], ["_GA103", "_GA203"]
		)  # tier 1 at the bottom
		self.assertEqual((slots["_GB-02"]["row"], slots["_GB-02"]["col"]), (1, 1))
		self.assertEqual(slots["_GA-01"]["levels"][0]["uoms"][0]["cap"], 4)
		self.assertEqual(api.generate_locations(floor.name, **args)["skipped"], 12)  # rerun: nothing new
		with self.assertRaises(frappe.ValidationError):
			api.generate_locations(floor.name, bays="A", tiers=1, rows=1, level_pattern="{bay.__class__}")

	# ── packing ─────────────────────────────────────────────

	def test_pack_scans_fill_packages_that_become_packing_slips(self):
		_floor, _slot, (level, _other) = self.floor_with_levels("_W7 Pack")
		part = self.item("_W7 Pack Part")
		self.receive(part, level.name, qty=5)
		customer = frappe.db.exists("Customer", "_W7 Customer") or (
			frappe.get_doc(
				doctype="Customer",
				customer_name="_W7 Customer",
				customer_group=frappe.db.get_value("Customer Group", {"is_group": 0}),
				territory=frappe.db.get_value("Territory", {"is_group": 0}),
			)
			.insert()
			.name
		)
		note = frappe.get_doc(
			doctype="Delivery Note",
			customer=customer,
			company=self.company,
			items=[{"item_code": part, "qty": 3, "rate": 50, "warehouse": level.name}],
		).insert()

		scan.pack_scan(note.name, part)
		scan.pack_scan(note.name, part)
		self.assertEqual(scan.get_pack(note.name)["rows"][0]["in_package"], 2)
		first = scan.close_package(note.name)
		self.assertEqual(
			(first["package"], frappe.db.get_value("Packing Slip", first["packing_slip"], "docstatus")),
			(1, 1),
		)
		self.assertEqual(frappe.db.get_value("Delivery Note Item", note.items[0].name, "packed_qty"), 2)

		with self.assertRaises(frappe.ValidationError):
			scan.pack_scan(note.name, part, qty=2)  # only 1 left to pack
		scan.pack_scan(note.name, part)
		self.assertEqual(scan.close_package(note.name)["package"], 2)
		with self.assertRaises(frappe.ValidationError):
			scan.close_package(note.name)  # nothing open

	# ── cross-entity visibility ─────────────────────────────

	def test_availability_shows_only_warehouses_the_user_may_see(self):
		_floor, _slot, (mine, theirs) = self.floor_with_levels("_W7 Vis")
		part = self.item("_W7 Vis Part")
		self.receive(part, mine.name, qty=2)
		self.receive(part, theirs.name, qty=7)
		user = self.user("_w7.channel@example.com", "Stock User")
		frappe.get_doc(doctype="User Permission", user=user, allow="Warehouse", for_value=mine.name).insert()

		self.as_user(user)
		self.assertEqual(holds.get_available_qty(part)["warehouses"], {mine.name: 2})
