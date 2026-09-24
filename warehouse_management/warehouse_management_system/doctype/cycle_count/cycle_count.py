# Copyright (c) 2026, Thunder BluePhoenix and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, get_datetime, now_datetime

from warehouse_management.api.warehouse_3d import totes_at


def _serials(text):
	return [s.strip() for s in (text or "").splitlines() if s.strip()]


class CycleCount(Document):
	"""Count the stock at a location and post the differences only after someone else approves.

	Counters fill Counted Qty (or scan in WMS Scan); expected quantities are permlevel 1, which counters
	cannot read, so the count is blind unless Role Permission Manager says otherwise. Send for Approval
	re-reads the expected stock at that moment; submitting (approval) posts one Stock Reconciliation,
	dated at the count, for the rows that differ. The approver must not be the counter."""

	def before_insert(self):
		if not self.items:
			self.set("items", self.expected_rows())

	def validate(self):
		for row in self.items:
			if row.counted_serials:
				row.counted_qty = len(_serials(row.counted_serials))
		if self.status == "Pending Approval" and not self.flags.status_change:
			before = self.get_doc_before_save()
			old = {
				r.name: (flt(r.counted_qty), r.counted_serials or "")
				for r in (before.items if before else [])
			}
			if any(old.get(r.name) != (flt(r.counted_qty), r.counted_serials or "") for r in self.items):
				frappe.throw(_("This count is waiting for approval. Reject it to recount."))

	# ── expected stock ─────────────────────────────────────

	def _warehouses(self):
		bounds = frappe.db.get_value("Warehouse", self.location, ["lft", "rgt"], as_dict=True)
		leaves = frappe.get_all(
			"Warehouse",
			filters={
				"lft": [">=", bounds.lft],
				"rgt": ["<=", bounds.rgt],
				"is_group": 0,
				"company": self.company,
			},
			pluck="name",
		)
		return sorted(set(leaves) | set(totes_at(leaves)))

	def expected_rows(self):
		"""One row per warehouse and item (per batch for batch items), with what the system holds now."""
		from erpnext.stock.doctype.batch.batch import get_batch_qty

		rows = []
		warehouses = self._warehouses()
		for b in frappe.get_all(
			"Bin",
			filters={"warehouse": ["in", warehouses or [""]], "actual_qty": ["!=", 0]},
			fields=["warehouse", "item_code", "actual_qty"],
			order_by="warehouse, item_code",
		):
			item = frappe.get_cached_value(
				"Item", b.item_code, ["has_serial_no", "has_batch_no"], as_dict=True
			)
			if item.has_serial_no:
				# ponytail: serial+batch items are counted by serial only; their batch is not re-assigned
				serials = frappe.get_all(
					"Serial No", filters={"item_code": b.item_code, "warehouse": b.warehouse}, pluck="name"
				)
				rows.append(
					dict(
						warehouse=b.warehouse,
						item_code=b.item_code,
						expected_qty=len(serials),
						expected_serials="\n".join(sorted(serials)),
					)
				)
			elif item.has_batch_no:
				for batch in get_batch_qty(item_code=b.item_code, warehouse=b.warehouse) or []:
					if flt(batch.get("qty")):
						rows.append(
							dict(
								warehouse=b.warehouse,
								item_code=b.item_code,
								batch_no=batch.get("batch_no"),
								expected_qty=flt(batch.get("qty")),
							)
						)
			else:
				rows.append(
					dict(warehouse=b.warehouse, item_code=b.item_code, expected_qty=flt(b.actual_qty))
				)
		return rows

	# ── workflow ───────────────────────────────────────────

	@frappe.whitelist()
	def mark_uncounted_as_zero(self):
		self.check_permission("write")
		for row in self.items:
			if not row.counted:
				row.counted, row.counted_qty = 1, 0
		self.save()

	@frappe.whitelist()
	def send_for_approval(self):
		self.check_permission("write")
		if self.status != "Counting":
			frappe.throw(_("Only a count in progress can be sent for approval."))
		missing = [str(r.idx) for r in self.items if not r.counted]
		if missing:
			frappe.throw(
				_("Rows not counted yet: {0}. Count them, or mark them as zero.").format(", ".join(missing))
			)
		now = {(r["warehouse"], r["item_code"], r.get("batch_no")): r for r in self.expected_rows()}
		for row in self.items:
			fresh = now.get((row.warehouse, row.item_code, row.batch_no), {})
			row.expected_qty = flt(fresh.get("expected_qty"))
			row.expected_serials = fresh.get("expected_serials")
			row.variance = flt(row.counted_qty) - row.expected_qty
		self.update(
			{"status": "Pending Approval", "counted_by": frappe.session.user, "counted_at": now_datetime()}
		)
		self.flags.status_change = True
		self.save(ignore_permissions=True)  # the counter cannot write the permlevel-1 expected columns

	@frappe.whitelist()
	def reject(self, reason: str | None = None):
		if self.status != "Pending Approval":
			frappe.throw(_("Only a count waiting for approval can be rejected."))
		frappe.has_permission(self.doctype, "submit", self, throw=True)
		self.status = "Counting"
		self.flags.status_change = True
		self.save()
		self.add_comment("Comment", _("Rejected for recount: {0}").format(reason or "-"))

	def before_submit(self):
		if self.status != "Pending Approval":
			frappe.throw(_("Send the count for approval first."))
		if frappe.session.user == self.counted_by:
			frappe.throw(
				_("The count must be approved by someone other than the counter."), title=_("Approval")
			)

	def on_submit(self):
		self.db_set({"status": "Approved", "approved_by": frappe.session.user})
		changed = [
			r
			for r in self.items
			if flt(r.variance) or sorted(_serials(r.counted_serials)) != sorted(_serials(r.expected_serials))
		]
		if changed:
			self.db_set("stock_reconciliation", self._post_reconciliation(changed))

	def on_cancel(self):
		if (
			self.stock_reconciliation
			and frappe.db.get_value("Stock Reconciliation", self.stock_reconciliation, "docstatus") == 1
		):
			frappe.get_doc("Stock Reconciliation", self.stock_reconciliation).cancel()
		self.db_set("status", "Cancelled")

	def _post_reconciliation(self, rows):
		counted_at = get_datetime(self.counted_at)
		company = frappe.get_cached_value(
			"Company", self.company, ["stock_adjustment_account", "cost_center"], as_dict=True
		)
		recon = frappe.new_doc("Stock Reconciliation")
		recon.update(
			{
				"company": self.company,
				"purpose": "Stock Reconciliation",
				"set_posting_time": 1,
				"posting_date": counted_at.date(),
				"posting_time": counted_at.time(),
				"expense_account": company.stock_adjustment_account,
				"cost_center": company.cost_center,
			}
		)
		for r in rows:
			rate = flt(
				frappe.db.get_value(
					"Bin", {"item_code": r.item_code, "warehouse": r.warehouse}, "valuation_rate"
				)
			)
			rate = rate or flt(frappe.get_cached_value("Item", r.item_code, "valuation_rate"))
			line = {"item_code": r.item_code, "warehouse": r.warehouse, "qty": flt(r.counted_qty)}
			if r.batch_no or r.counted_serials or r.expected_serials:
				line.update(
					use_serial_batch_fields=1,
					batch_no=r.batch_no,
					serial_no="\n".join(_serials(r.counted_serials)),
				)
			if rate:
				line["valuation_rate"] = rate
			else:
				line["allow_zero_valuation_rate"] = 1  # found stock of an item that has never been valued
			recon.append("items", line)
		recon.remarks = _("Cycle Count {0}").format(self.name)
		recon.insert()
		recon.submit()
		return recon.name
