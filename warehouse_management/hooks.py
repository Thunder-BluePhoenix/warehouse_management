app_name = "warehouse_management"
app_title = "Warehouse Management System"
app_publisher = "Thunder BluePhoenix"
app_description = "3D/2D warehouse visualisation and yard/warehouse operations on top of ERPNext stock: layouts, capacities, bay types, gate entries and live stock views."
app_email = "bluephoenix00995@gmail.com"
app_license = "gpl-3.0"

# Apps
# ------------------

# Warehouse, Bin, Item and UOM doctypes come from ERPNext
required_apps = ["erpnext"]

# Each item in the list will be shown as an app in the apps page
add_to_apps_screen = [
	{
		"name": "warehouse_management",
		"logo": "/assets/warehouse_management/images/warehouse_3d_logo.svg",
		"title": "Warehouse Management System",
		"route": "/warehouse-3d",
		"has_permission": "warehouse_management.api.warehouse_3d.check_app_permission",
	}
]

website_route_rules = [
	{"from_route": "/warehouse-3d/<path:app_path>", "to_route": "warehouse-3d"},
]

# Custom Fields on Warehouse used by the 3D view (wt_* fields)
fixtures = [
	{"dt": "Custom Field", "filters": [["module", "=", "Warehouse Management System"]]},
]

# Includes in <head>
# ------------------

# include js, css files in header of desk.html
# app_include_css = "/assets/warehouse_management/css/warehouse_management.css"
# app_include_js = "/assets/warehouse_management/js/warehouse_management.js"

# include js, css files in header of web template
# web_include_css = "/assets/warehouse_management/css/warehouse_management.css"
# web_include_js = "/assets/warehouse_management/js/warehouse_management.js"

# include custom scss in every website theme (without file extension ".scss")
# website_theme_scss = "warehouse_management/public/scss/website"

# include js, css files in header of web form
# webform_include_js = {"doctype": "public/js/doctype.js"}
# webform_include_css = {"doctype": "public/css/doctype.css"}

# include js in page
# page_js = {"page" : "public/js/file.js"}

# include js in doctype views
# doctype_js = {"doctype" : "public/js/doctype.js"}
# doctype_list_js = {"doctype" : "public/js/doctype_list.js"}
# doctype_tree_js = {"doctype" : "public/js/doctype_tree.js"}
# doctype_calendar_js = {"doctype" : "public/js/doctype_calendar.js"}

# Svg Icons
# ------------------
# include app icons in desk
# app_include_icons = "warehouse_management/public/icons.svg"

# Home Pages
# ----------

# application home page (will override Website Settings)
# home_page = "login"

# website user home page (by Role)
# role_home_page = {
# 	"Role": "home_page"
# }

# Generators
# ----------

# automatically create page for each record of this doctype
# website_generators = ["Web Page"]

# automatically load and sync documents of this doctype from downstream apps
# importable_doctypes = [doctype_1]

# Jinja
# ----------

# add methods and filters to jinja environment
# jinja = {
# 	"methods": "warehouse_management.utils.jinja_methods",
# 	"filters": "warehouse_management.utils.jinja_filters"
# }

# Installation
# ------------

# before_install = "warehouse_management.install.before_install"
# after_install = "warehouse_management.install.after_install"

# Uninstallation
# ------------

# before_uninstall = "warehouse_management.uninstall.before_uninstall"
# after_uninstall = "warehouse_management.uninstall.after_uninstall"

# Integration Setup
# ------------------
# To set up dependencies/integrations with other apps
# Name of the app being installed is passed as an argument

# before_app_install = "warehouse_management.utils.before_app_install"
# after_app_install = "warehouse_management.utils.after_app_install"

# Integration Cleanup
# -------------------
# To clean up dependencies/integrations with other apps
# Name of the app being uninstalled is passed as an argument

# before_app_uninstall = "warehouse_management.utils.before_app_uninstall"
# after_app_uninstall = "warehouse_management.utils.after_app_uninstall"

# Build
# ------------------
# To hook into the build process

# after_build = "warehouse_management.build.after_build"

# Desk Notifications
# ------------------
# See frappe.core.notifications.get_notification_config

# notification_config = "warehouse_management.notifications.get_notification_config"

# Awesome Bar
# -----------
# Extra search results: list of dicts with label, description, route, index.
# route: ["List", "ToDo"], "/desk/docs/some/page", or "https://example.com"
# awesomebar_search = ["warehouse_management.search.awesomebar_results"]

# Permissions
# -----------
# Permissions evaluated in scripted ways

# permission_query_conditions = {
# 	"Event": "frappe.desk.doctype.event.event.get_permission_query_conditions",
# }
#
# has_permission = {
# 	"Event": "frappe.desk.doctype.event.event.has_permission",
# }

# Document Events
# ---------------
# Hook on document methods and events

# doc_events = {
# 	"*": {
# 		"on_update": "method",
# 		"on_cancel": "method",
# 		"on_trash": "method"
# 	}
# }

# Scheduled Tasks
# ---------------

# scheduler_events = {
# 	"all": [
# 		"warehouse_management.tasks.all"
# 	],
# 	"daily": [
# 		"warehouse_management.tasks.daily"
# 	],
# 	"hourly": [
# 		"warehouse_management.tasks.hourly"
# 	],
# 	"weekly": [
# 		"warehouse_management.tasks.weekly"
# 	],
# 	"monthly": [
# 		"warehouse_management.tasks.monthly"
# 	],
# }

# Testing
# -------

# before_tests = "warehouse_management.install.before_tests"

# Extend DocType Class
# ------------------------------
#
# Specify custom mixins to extend the standard doctype controller.
# extend_doctype_class = {
# 	"Task": "warehouse_management.custom.task.CustomTaskMixin"
# }

# Overriding Methods
# ------------------------------
#
# override_whitelisted_methods = {
# 	"frappe.desk.doctype.event.event.get_events": "warehouse_management.event.get_events"
# }
#
# each overriding function accepts a `data` argument;
# generated from the base implementation of the doctype dashboard,
# along with any modifications made in other Frappe apps
# override_doctype_dashboards = {
# 	"Task": "warehouse_management.task.get_dashboard_data"
# }

# exempt linked doctypes from being automatically cancelled
#
# auto_cancel_exempted_doctypes = ["Auto Repeat"]

# Ignore links to specified DocTypes when deleting documents
# -----------------------------------------------------------

# ignore_links_on_delete = ["Communication", "ToDo"]

# Request Events
# ----------------
# before_request = ["warehouse_management.utils.before_request"]
# after_request = ["warehouse_management.utils.after_request"]

# Job Events
# ----------
# before_job = ["warehouse_management.utils.before_job"]
# after_job = ["warehouse_management.utils.after_job"]

# User Data Protection
# --------------------

# user_data_fields = [
# 	{
# 		"doctype": "{doctype_1}",
# 		"filter_by": "{filter_by}",
# 		"redact_fields": ["{field_1}", "{field_2}"],
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_2}",
# 		"filter_by": "{filter_by}",
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_3}",
# 		"strict": False,
# 	},
# 	{
# 		"doctype": "{doctype_4}"
# 	}
# ]

# Authentication and authorization
# --------------------------------

# auth_hooks = [
# 	"warehouse_management.auth.validate"
# ]

# Automatically update python controller files with type annotations for this app.
# export_python_type_annotations = True

# default_log_clearing_doctypes = {
# 	"Logging DocType Name": 30  # days to retain logs
# }

# Translation
# ------------
# List of apps whose translatable strings should be excluded from this app's translations.
# ignore_translatable_strings_from = []

# ─────────────────────────────────────────────────────────────
# Storage rules and live refresh (warehouse_management/warehouse_rules.py)
# ─────────────────────────────────────────────────────────────

doc_events = {
	"Warehouse": {"validate": "warehouse_management.warehouse_rules.set_area"},
	**{
		dt: {"before_submit": "warehouse_management.warehouse_rules.validate_storage_rules"}
		for dt in ("Stock Entry", "Purchase Receipt", "Purchase Invoice", "Stock Reconciliation")
	},
	"Stock Ledger Entry": {"on_submit": "warehouse_management.warehouse_rules.queue_viewer_refresh"},
}
