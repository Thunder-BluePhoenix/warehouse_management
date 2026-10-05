"""Printable labels: QR codes for storage locations and totes, used by the WMS print formats (Jinja methods
in hooks.py). A label's QR holds exactly what WMS Scan resolves: the warehouse name, or the tote's Bin ID."""

import io

import frappe
import pyqrcode
from markupsafe import Markup

from warehouse_management.api.warehouse_3d import _locate
from warehouse_management.warehouse_management_system.doctype.wms_settings.wms_settings import settings_for


def wm_qr_svg(value: str, size_mm: float = 30) -> Markup:
	buf = io.BytesIO()
	pyqrcode.create(str(value), error="M").svg(buf, scale=4, xmldecl=False, omithw=True, quiet_zone=2)
	svg = buf.getvalue().decode()
	return Markup(
		svg.replace("<svg ", f'<svg style="width:{float(size_mm)}mm;height:{float(size_mm)}mm" ', 1)
	)


def wm_location_path(warehouse: str) -> str:
	"""Floor > zones > slot of a level, for the label's small print."""
	if not warehouse:
		return ""
	loc = _locate([warehouse]).get(warehouse, {})
	return " > ".join(
		filter(None, [loc.get("floor_name"), *(loc.get("zone_path") or []), loc.get("slot_label")])
	)


def wm_label_size(warehouse: str | None = None) -> frappe._dict:
	settings = settings_for(warehouse)
	return frappe._dict(width=settings.label_width_mm or 100, height=settings.label_height_mm or 50)
