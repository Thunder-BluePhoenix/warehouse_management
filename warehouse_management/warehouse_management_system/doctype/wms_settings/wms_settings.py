# Copyright (c) 2026, Thunder BluePhoenix and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


def fieldnames(text):
	"""The fieldnames listed one per line (blank lines and spaces ignored)."""
	return [f.strip() for f in (text or "").splitlines() if f.strip()]


class WMSSettings(Document):
	def validate(self):
		for doctype, field in (("Warehouse", "warehouse_fields"), ("Serial No", "serial_no_fields")):
			meta = frappe.get_meta(doctype)
			unknown = [f for f in fieldnames(self.get(field)) if not meta.has_field(f)]
			if unknown:
				frappe.throw(
					_("{0} has no field {1}.").format(_(doctype), ", ".join(unknown)),
					title=_("Unknown field"),
				)
