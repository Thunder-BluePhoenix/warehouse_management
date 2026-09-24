import frappe


def execute():
	"""The storage-level role was called "Bin", which clashed with ERPNext's Bin (stock balance) DocType."""
	if frappe.db.has_column("Warehouse", "wt_warehouse_type"):
		frappe.db.sql("UPDATE `tabWarehouse` SET wt_warehouse_type = 'Level' WHERE wt_warehouse_type = 'Bin'")
