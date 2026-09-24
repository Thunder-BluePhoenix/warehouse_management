import json
from collections import Counter

import frappe
from frappe import _

from warehouse_management.api.warehouse_3d import (
	ROLES,
	TOTE,
	_get_doc_for_write,
	_require_edit_permission,
	_require_view_permission,
)


@frappe.whitelist()
def is_setup_complete():
	"""True if at least one warehouse already has wt_warehouse_type assigned."""
	_require_view_permission()
	return bool(frappe.db.exists("Warehouse", {"wt_warehouse_type": ["is", "set"]}))


def _list_warehouses(company, fields):
	filters = {"company": company} if company else {}
	return frappe.get_list("Warehouse", filters=filters, fields=fields, limit_page_length=0)


def _depth_fn(by_name):
	def _depth(wh_name, _seen=None):
		_seen = _seen or set()
		if wh_name in _seen:
			return 0  # cycle guard
		_seen.add(wh_name)
		w = by_name.get(wh_name)
		if not w or not w.parent_warehouse or w.parent_warehouse not in by_name:
			return 1
		return 1 + _depth(w.parent_warehouse, _seen)

	return _depth


@frappe.whitelist()
def scan_warehouse_tree(company=None):
	"""
	Walk the existing Warehouse parent_warehouse tree (no relabeling) and
	return a summary grouped by depth, so the setup wizard can ask the
	admin to assign a role (Building/Floor/Zone/Slot/Level/Skip) per depth.
	"""
	_require_edit_permission()

	warehouses = _list_warehouses(
		company, ["name", "warehouse_name", "parent_warehouse", "is_group", "disabled"]
	)
	if not warehouses:
		return {"depths": [], "total_warehouses": 0, "uniform": True}

	_depth = _depth_fn({w.name: w for w in warehouses})
	parents = {w.parent_warehouse for w in warehouses}

	depth_map = {}
	for w in warehouses:
		if w.disabled:
			continue
		depth_map.setdefault(_depth(w.name), []).append(w)

	depths = []
	for d in sorted(depth_map.keys()):
		items = depth_map[d]
		sample = sorted(items, key=lambda x: x.warehouse_name)[:5]
		depths.append(
			{
				"depth": d,
				"count": len(items),
				"sample_names": [i.warehouse_name for i in sample],
				"is_leaf": all(i.name not in parents for i in items),
				"all_group": all(i.is_group for i in items),
				"all_leaf_wh": all(not i.is_group for i in items),
			}
		)

	return {
		"depths": depths,
		"total_warehouses": len(warehouses),
		"max_depth": max(depth_map.keys()) if depth_map else 0,
		"min_depth": min(depth_map.keys()) if depth_map else 0,
	}


@frappe.whitelist(methods=["POST"])
def apply_depth_mapping(mapping, company=None):
	"""
	mapping: JSON list like [{"depth": 1, "role": "Building"}, {"depth": 2, "role": "Floor"}, ...]
	role is one of: Building, Floor, Zone (may repeat at several depths), Slot, Level, Skip.
	Tote warehouses (owned by Storage Bins) are never relabelled
	Writes wt_warehouse_type to every warehouse at each mapped depth (via Document.save, so
	permissions and Version history apply). Does not rename, move, or otherwise alter the tree.
	"""
	_require_edit_permission()

	if isinstance(mapping, str):
		mapping = json.loads(mapping)

	valid_roles = set(ROLES)
	depth_to_role = {int(m["depth"]): m["role"] for m in mapping if m.get("role") in valid_roles}
	if not depth_to_role:
		frappe.throw(_("No valid role mapping provided."))

	warehouses = _list_warehouses(company, ["name", "parent_warehouse", "disabled", "wt_warehouse_type"])
	_depth = _depth_fn({w.name: w for w in warehouses})

	updated = 0
	for w in warehouses:
		if w.disabled or w.wt_warehouse_type == TOTE:
			continue
		role = depth_to_role.get(_depth(w.name))
		if role:
			doc = _get_doc_for_write(w.name)
			if doc.get("wt_warehouse_type") != role:
				doc.wt_warehouse_type = role
				doc.save()
			updated += 1

	return {"ok": True, "updated": updated}


@frappe.whitelist()
def get_setup_summary():
	"""Returns counts per wt_warehouse_type, for the wizard's review/preview step."""
	_require_edit_permission()
	rows = frappe.get_list(
		"Warehouse",
		filters={"wt_warehouse_type": ["is", "set"], "disabled": 0},
		pluck="wt_warehouse_type",
		limit_page_length=0,
	)
	return dict(Counter(rows))
