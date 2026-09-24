import json

import frappe
from frappe import _

# Roles allowed to VIEW the app (read-only access)
VIEW_ROLES = {"System Manager", "Stock Manager", "Stock User"}
# Roles allowed to EDIT (floor plan, configure slot, UOM capacity)
EDIT_ROLES = {"System Manager"}

# Security model (see docs/research/areas/11-codebase-platform.md §6.3):
# - every state-changing endpoint is POST-only, so Frappe enforces CSRF and commits the request itself;
# - writes go through Document.save()/insert()/delete_doc without ignore_permissions, so DocType
#   permissions, User Permissions (Company/Warehouse) and Version history (track_changes) all apply;
# - reads return only warehouses frappe.get_list lets the user see.


def _require_view_permission():
	"""Raise PermissionError unless the current user has a view role."""
	if not (set(frappe.get_roles()) & VIEW_ROLES):
		frappe.throw(_("You do not have permission to view Warehouse 3D."), frappe.PermissionError)


def _require_edit_permission():
	"""Raise PermissionError unless the current user has an edit role."""
	if not (set(frappe.get_roles()) & EDIT_ROLES):
		frappe.throw(
			_(
				"You do not have permission to edit Warehouse 3D. "
				"Only System Manager can edit floor plans, slot configuration, or UOM capacities."
			),
			frappe.PermissionError,
		)


def _permitted_warehouses():
	# ponytail: one list query per call; cache per request if warehouse counts reach the tens of thousands
	return set(frappe.get_list("Warehouse", pluck="name", limit_page_length=0))


def _get_doc_for_write(warehouse):
	_require_edit_permission()
	doc = frappe.get_doc("Warehouse", warehouse)
	doc.check_permission("write")
	return doc


def _flt(v):
	try:
		return float(v)
	except (TypeError, ValueError):
		return 0.0


def _int(v):
	try:
		return int(v)
	except (TypeError, ValueError):
		return 0


@frappe.whitelist()
def get_companies():
	_require_view_permission()
	return frappe.get_list("Company", fields=["name", "abbr"], order_by="name asc")


@frappe.whitelist()
def get_warehouse_groups(company=None):
	"""Return all Floor warehouses grouped under their Building."""
	_require_view_permission()
	params = []
	company_filter = ""
	if company:
		company_filter = "AND w.company = %s "
		params.append(company)

	query = (
		"SELECT "
		"w.name AS id, "
		"w.warehouse_name AS name, "
		"w.parent_warehouse AS parent_id, "
		"pw.warehouse_name AS parent_name, "
		"COUNT(slot.name) AS slot_count "
		"FROM `tabWarehouse` w "
		"LEFT JOIN `tabWarehouse` pw ON pw.name = w.parent_warehouse "
		"LEFT JOIN `tabWarehouse` slot "
		"ON slot.parent_warehouse = w.name "
		"AND slot.wt_warehouse_type = 'Slot' "
		"AND slot.disabled = 0 "
		"WHERE w.wt_warehouse_type = 'Floor' "
		"AND w.disabled = 0 " + company_filter + "GROUP BY w.name "
		"ORDER BY pw.warehouse_name, w.warehouse_name"
	)
	allowed = _permitted_warehouses()
	return [r for r in frappe.db.sql(query, params, as_dict=True) if r.id in allowed]


@frappe.whitelist()
def get_slots(group_warehouse):
	"""Return all Slot warehouses under a Floor, with their Bin levels."""
	_require_view_permission()
	frappe.has_permission("Warehouse", "read", group_warehouse, throw=True)
	allowed = _permitted_warehouses()
	slots = frappe.db.sql(
		"""
		SELECT
			w.name             AS wh,
			w.warehouse_name   AS label,
			COALESCE(w.wt_row, 0)     AS `row`,
			COALESCE(w.wt_col, 0)     AS col,
			COALESCE(w.wt_row_gap, 0) AS row_gap
		FROM `tabWarehouse` w
		WHERE w.parent_warehouse = %s
		  AND w.wt_warehouse_type = 'Slot'
		  AND w.disabled = 0
		ORDER BY w.wt_row, w.wt_col, w.warehouse_name
	""",
		(group_warehouse,),
		as_dict=True,
	)
	slots = [sl for sl in slots if sl["wh"] in allowed]

	for sl in slots:
		sl["levels"] = _get_levels(sl["wh"], allowed)

	return slots


def _get_levels(slot_wh, allowed):
	"""Bin warehouses under a Slot."""
	levels = frappe.db.sql(
		"""
		SELECT w.name AS wh, w.warehouse_name AS label
		FROM `tabWarehouse` w
		WHERE w.parent_warehouse = %s
		  AND w.wt_warehouse_type = 'Bin'
		  AND w.disabled = 0
		ORDER BY w.warehouse_name ASC
	""",
		(slot_wh,),
		as_dict=True,
	)
	levels = [lv for lv in levels if lv["wh"] in allowed]

	for lv in levels:
		lv["uoms"] = _get_uom_data(lv["wh"])
		lv["items"] = _get_items(lv["wh"])

	return levels


def _get_uom_data(level_wh):
	bins = frappe.db.sql(
		"""
		SELECT i.stock_uom AS uom,
		       SUM(b.actual_qty)   AS qty,
		       SUM(b.reserved_qty) AS reserved
		FROM `tabBin` b
		INNER JOIN `tabItem` i ON i.name = b.item_code
		WHERE b.warehouse = %s AND b.actual_qty != 0
		GROUP BY i.stock_uom
	""",
		(level_wh,),
		as_dict=True,
	)

	try:
		caps = {
			r.uom: _flt(r.capacity)
			for r in frappe.db.sql(
				"""
			SELECT uom, capacity FROM `tabWarehouse UOM Capacity`
			WHERE parent = %s
		""",
				(level_wh,),
				as_dict=True,
			)
		}
	except Exception:
		caps = {}

	result = []
	for b in bins:
		result.append(
			{"u": b.uom, "qty": _flt(b.qty), "reserved": _flt(b.reserved), "cap": caps.get(b.uom, 0)}
		)
	for uom, cap in caps.items():
		if not any(r["u"] == uom for r in result):
			result.append({"u": uom, "qty": 0, "reserved": 0, "cap": cap})
	return result


def _get_items(level_wh):
	return frappe.db.sql(
		"""
		SELECT b.item_code AS c, i.item_name AS n,
		       i.stock_uom AS u, i.item_group AS g,
		       b.actual_qty AS a, b.reserved_qty AS r,
		       b.valuation_rate AS rate, b.stock_value
		FROM `tabBin` b
		INNER JOIN `tabItem` i ON i.name = b.item_code
		WHERE b.warehouse = %s AND b.actual_qty != 0
		ORDER BY b.actual_qty DESC LIMIT 20
	""",
		(level_wh,),
		as_dict=True,
	)


@frappe.whitelist(methods=["POST"])
def save_slot_position(warehouse, row, col, row_gap=0):
	doc = _get_doc_for_write(warehouse)
	doc.update({"wt_row": _int(row), "wt_col": _int(col), "wt_row_gap": _flt(row_gap)})
	doc.save()
	return {"ok": True}


@frappe.whitelist()
def get_floor_layout(group_warehouse):
	"""Return the saved Floor Plan editor grid (rows/cells incl. span & aisle flags) for a Floor.

	This is purely editor metadata - it does not drive the 3D scene (which reads
	wt_row/wt_col/wt_row_gap off each Slot warehouse). It exists so aisle markers,
	column spans, and custom row labels survive closing and reopening the editor,
	since aisle cells have no underlying Slot warehouse to store that state on.
	"""
	_require_view_permission()
	frappe.has_permission("Warehouse", "read", group_warehouse, throw=True)
	raw = frappe.db.get_value("Warehouse", group_warehouse, "wt_floor_layout")
	if not raw:
		return {}
	try:
		return json.loads(raw)
	except Exception:
		return {}


@frappe.whitelist(methods=["POST"])
def save_floor_layout(group_warehouse, layout):
	"""Persist the Floor Plan editor grid as JSON on the Floor warehouse."""
	doc = _get_doc_for_write(group_warehouse)
	doc.wt_floor_layout = layout if isinstance(layout, str) else json.dumps(layout)
	doc.save()
	return {"ok": True}


@frappe.whitelist(methods=["POST"])
def save_uom_capacity(warehouse, uom, capacity):
	doc = _get_doc_for_write(warehouse)
	row = next((r for r in doc.get("wt_uom_capacities") or [] if r.uom == uom), None)
	if row:
		row.capacity = _flt(capacity)
	else:
		doc.append("wt_uom_capacities", {"uom": uom, "capacity": _flt(capacity)})
	doc.save()
	return {"ok": True}


@frappe.whitelist()
def check_app_permission():
	"""Used by Frappe to decide whether to show the app icon on /apps screen."""
	return bool(set(frappe.get_roles()) & VIEW_ROLES)


@frappe.whitelist()
def get_user_access():
	"""Returns the current user's access level for the frontend to adapt UI."""
	user_roles = set(frappe.get_roles())
	return {
		"can_view": bool(user_roles & VIEW_ROLES),
		"can_edit": bool(user_roles & EDIT_ROLES),
		"setup_complete": bool(frappe.db.exists("Warehouse", {"wt_warehouse_type": ["is", "set"]})),
	}


# ─────────────────────────────────────────────────────────────
# WAREHOUSE CRUD  (Manage Warehouses panel)
# ─────────────────────────────────────────────────────────────


def _default_is_group(wt_warehouse_type):
	"""Building/Floor/Slot are containers by convention; Bin is the leaf stock warehouse."""
	return 0 if wt_warehouse_type == "Bin" else 1


def _set_uom_capacities(doc, rows):
	doc.set("wt_uom_capacities", [])
	for row in rows or []:
		if row.get("uom"):
			doc.append("wt_uom_capacities", {"uom": row.get("uom"), "capacity": _flt(row.get("capacity"))})


@frappe.whitelist()
def get_uom_list():
	"""UOM options for the WT UOM Capacities table in the warehouse form."""
	_require_view_permission()
	return frappe.get_all("UOM", fields=["name"], order_by="name asc", pluck="name")


@frappe.whitelist()
def get_parent_warehouse_options(wt_warehouse_type, company=None):
	"""Valid parents for a given Warehouse Type (3D): one theatre level up.
	Building's valid parent is the company's root warehouse (e.g. 'All Warehouses - ABBR')."""
	_require_view_permission()

	parent_role = {"Floor": "Building", "Slot": "Floor", "Bin": "Slot"}.get(wt_warehouse_type)
	if parent_role:
		filters = {"wt_warehouse_type": parent_role, "disabled": 0}
	elif wt_warehouse_type == "Building":
		filters = {"is_group": 1, "parent_warehouse": ["in", ["", None]]}
	else:
		return []

	if company:
		filters["company"] = company
	return frappe.get_list(
		"Warehouse", filters=filters, fields=["name", "warehouse_name"], order_by="warehouse_name asc"
	)


@frappe.whitelist()
def get_warehouse_manage_list(company=None):
	"""Full warehouse list (all theatre roles, incl. disabled) for the Manage Warehouses panel."""
	_require_edit_permission()
	filters = {"company": company} if company else {}
	return frappe.get_list(
		"Warehouse",
		filters=filters,
		fields=[
			"name",
			"warehouse_name",
			"wt_warehouse_type",
			"parent_warehouse",
			"is_group",
			"disabled",
			"company",
		],
		order_by="disabled asc, wt_warehouse_type asc, warehouse_name asc",
		limit_page_length=0,
	)


@frappe.whitelist()
def get_warehouse_detail(warehouse):
	"""Full field set for the edit form, incl. the WT UOM Capacities child table."""
	_require_edit_permission()
	doc = frappe.get_doc("Warehouse", warehouse)
	doc.check_permission("read")
	return {
		"name": doc.name,
		"warehouse_name": doc.warehouse_name,
		"company": doc.company,
		"wt_warehouse_type": doc.get("wt_warehouse_type"),
		"parent_warehouse": doc.parent_warehouse,
		"is_group": doc.is_group,
		"disabled": doc.disabled,
		"wt_row": doc.get("wt_row") or 0,
		"wt_col": doc.get("wt_col") or 0,
		"wt_row_gap": doc.get("wt_row_gap") or 0,
		"uom_capacities": [
			{"uom": r.uom, "capacity": r.capacity} for r in (doc.get("wt_uom_capacities") or [])
		],
	}


@frappe.whitelist(methods=["POST"])
def create_warehouse(data):
	_require_edit_permission()
	if isinstance(data, str):
		data = json.loads(data)

	warehouse_name = (data.get("warehouse_name") or "").strip()
	if not warehouse_name:
		frappe.throw(_("Warehouse Name is required."))

	wt_type = data.get("wt_warehouse_type")
	if wt_type not in ("Building", "Floor", "Slot", "Bin"):
		frappe.throw(_("A valid Warehouse Type (3D) is required."))

	is_group = data.get("is_group")
	is_group = _int(is_group) if is_group is not None else _default_is_group(wt_type)

	doc = frappe.new_doc("Warehouse")
	doc.warehouse_name = warehouse_name
	doc.company = data.get("company")
	doc.wt_warehouse_type = wt_type
	doc.parent_warehouse = data.get("parent_warehouse") or None
	doc.is_group = is_group
	doc.wt_row = _int(data.get("wt_row"))
	doc.wt_col = _int(data.get("wt_col"))
	doc.wt_row_gap = _flt(data.get("wt_row_gap"))
	_set_uom_capacities(doc, data.get("uom_capacities"))

	doc.insert()  # enforces Warehouse "create" permission
	return {"ok": True, "name": doc.name}


@frappe.whitelist(methods=["POST"])
def update_warehouse(warehouse, data):
	if isinstance(data, str):
		data = json.loads(data)

	doc = _get_doc_for_write(warehouse)

	if (data.get("warehouse_name") or "").strip():
		doc.warehouse_name = data["warehouse_name"].strip()
	if data.get("wt_warehouse_type") in ("Building", "Floor", "Slot", "Bin"):
		doc.wt_warehouse_type = data["wt_warehouse_type"]
	if "parent_warehouse" in data:
		doc.parent_warehouse = data.get("parent_warehouse") or None
	if "is_group" in data and data.get("is_group") is not None:
		doc.is_group = _int(data.get("is_group"))
	if "company" in data and data.get("company"):
		doc.company = data.get("company")

	# Only touch layout/capacity fields the caller actually sent: a rename-only payload
	# (Config modal) must not reset the slot to row 0/col 0 or wipe its capacities.
	if "wt_row" in data:
		doc.wt_row = _int(data.get("wt_row"))
	if "wt_col" in data:
		doc.wt_col = _int(data.get("wt_col"))
	if "wt_row_gap" in data:
		doc.wt_row_gap = _flt(data.get("wt_row_gap"))
	if "uom_capacities" in data:
		_set_uom_capacities(doc, data.get("uom_capacities"))

	doc.save()
	return {"ok": True, "name": doc.name}


def _has_open_quantities(warehouse):
	return bool(
		frappe.get_all(
			"Bin",
			filters={"warehouse": warehouse},
			or_filters=[
				["actual_qty", "!=", 0],
				["reserved_qty", "!=", 0],
				["ordered_qty", "!=", 0],
				["indented_qty", "!=", 0],
				["planned_qty", "!=", 0],
			],
			limit=1,
		)
	)


@frappe.whitelist(methods=["POST"])
def delete_warehouse(warehouse):
	"""Hard-delete when the warehouse has no stock history; disable it when it has history but no
	open quantities. Never disables a warehouse that still holds or expects stock, because ERPNext
	rejects every posting to a disabled warehouse and that stock would be stranded."""
	doc = _get_doc_for_write(warehouse)

	if frappe.db.exists("Warehouse", {"parent_warehouse": warehouse}):
		frappe.throw(_("This warehouse has child warehouses. Delete or reassign them first."))

	if _has_open_quantities(warehouse):
		frappe.throw(
			_(
				"Warehouse {0} still holds or expects stock (actual, reserved, ordered, requested or planned quantity). "
				"Move the stock and close open orders before removing it."
			).format(warehouse)
		)

	if not doc.check_if_sle_exists():
		frappe.delete_doc("Warehouse", warehouse)  # enforces Warehouse "delete" permission
		return {"ok": True, "disabled": False, "message": _("Warehouse deleted.")}

	doc.disabled = 1
	doc.save()
	return {
		"ok": True,
		"disabled": True,
		"message": _(
			"This warehouse has transaction history, so it was disabled instead of permanently deleted."
		),
	}
