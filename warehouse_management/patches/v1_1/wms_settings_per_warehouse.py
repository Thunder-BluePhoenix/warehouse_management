import frappe

from warehouse_management.warehouse_management_system.doctype.wms_settings.wms_settings import ensure_default


def execute():
	"""WMS Settings was a single: its values become the "Default" record, which warehouses without their own follow."""
	values = dict(frappe.db.sql("SELECT field, value FROM `tabSingles` WHERE doctype = 'WMS Settings'"))
	if values and not frappe.db.exists("WMS Settings", {}):
		meta = frappe.get_meta("WMS Settings")
		doc = frappe.new_doc("WMS Settings")
		doc.update(
			{
				k: v
				for k, v in values.items()
				if meta.has_field(k) and k not in ("settings_name", "is_default")
			}
		)
		doc.settings_name = "Default"
		doc.is_default = 1
		doc.insert(ignore_permissions=True)
	frappe.db.delete("Singles", {"doctype": "WMS Settings"})
	ensure_default()
