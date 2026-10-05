# Copyright (c) 2026, Thunder BluePhoenix and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


def fieldnames(text):
	"""The fieldnames listed one per line (blank lines and spaces ignored)."""
	return [f.strip() for f in (text or "").splitlines() if f.strip()]


def default_name():
	return frappe.db.get_value("WMS Settings", {"is_default": 1}) or frappe.db.get_value("WMS Settings", {})


def settings_names(warehouses):
	"""{warehouse: the WMS Settings it follows}: its own, else its nearest ancestor's, else the default one."""
	warehouses = list({w for w in warehouses or [] if w})
	if not warehouses:
		return {}
	# the warehouses asked about and every warehouse with settings, in one query; deepest first, so the first one
	# around a warehouse is its nearest
	# ponytail: every warehouse with settings is read on each call; cache them if there are thousands
	rows = frappe.db.sql(
		"""SELECT name, lft, rgt, custom_wms_settings FROM `tabWarehouse`
		WHERE name IN %(names)s OR IFNULL(custom_wms_settings, '') != '' ORDER BY lft DESC""",
		{"names": warehouses},
		as_dict=True,
	)
	carriers = [c for c in rows if c.custom_wms_settings]
	out = {
		w.name: next((c.custom_wms_settings for c in carriers if c.lft <= w.lft and c.rgt >= w.rgt), None)
		for w in rows
		if w.name in warehouses
	}
	if None in out.values():
		default = default_name()
		out = {w: ws or default for w, ws in out.items()}
	return out


def settings_for(warehouse=None):
	"""The WMS Settings that apply to a warehouse (the default one without a warehouse)."""
	name = settings_names([warehouse]).get(warehouse) if warehouse else None
	name = name or default_name()
	return frappe.get_cached_doc("WMS Settings", name) if name else frappe.new_doc("WMS Settings")


def ensure_default():
	"""A site always has one default WMS Settings (after install, and from the old single on migrate)."""
	if frappe.db.exists("WMS Settings", {"is_default": 1}):
		return
	name = frappe.db.get_value("WMS Settings", {})
	if name:
		frappe.db.set_value("WMS Settings", name, "is_default", 1)
		return
	doc = frappe.new_doc("WMS Settings")
	doc.settings_name = "Default"
	doc.is_default = 1
	doc.insert(ignore_permissions=True)


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
		if not self.is_default and not frappe.db.exists(
			"WMS Settings", {"is_default": 1, "name": ["!=", self.name]}
		):
			self.is_default = 1  # the first one, or the default being switched off with no other

	def on_update(self):
		if self.is_default:
			for other in frappe.get_all(
				"WMS Settings", {"is_default": 1, "name": ["!=", self.name]}, pluck="name"
			):
				frappe.db.set_value("WMS Settings", other, "is_default", 0)
				frappe.clear_document_cache("WMS Settings", other)

	def on_trash(self):
		if self.is_default:
			frappe.throw(_("Make another WMS Settings the default before deleting this one."))
		if used := frappe.get_all("Warehouse", {"custom_wms_settings": self.name}, pluck="name", limit=3):
			frappe.throw(_("Still used by {0}.").format(", ".join(used)), title=_("In use"))
