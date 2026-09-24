/* Warehouse 3D — Frappe Page */
frappe.pages["warehouse-3d"].on_page_load = function (wrapper) {
	frappe.ui.make_app_page({
		parent: wrapper,
		title: "Warehouse 3D",
		single_column: true,
	});

	// Full-bleed layout for this page only: Frappe sets body[data-route] on every route change,
	// so these rules stop applying (and desk sidebars come back) as soon as the user leaves.
	if (!document.getElementById("wt3d-layout")) {
		const scope = 'body[data-route="warehouse-3d"]';
		$('<style id="wt3d-layout">')
			.text(
				`
			${scope} .layout-main-section-wrapper,${scope} .layout-main-section,${scope} .page-content {
				padding:0!important;margin:0!important;max-width:none!important;
			}
			${scope} .layout-side-section{display:none!important;}
			${scope} .layout-main-section{padding:0!important;box-shadow:none!important;}
			${scope} .page-body .container{max-width:none!important;padding:0!important;}
		`
			)
			.appendTo("head");
	}

	const mount = document.createElement("div");
	mount.id = "wt3d-root";
	mount.style.cssText = "width:100%;height:calc(100vh - 57px);";
	$(wrapper).find(".layout-main-section")[0].appendChild(mount);

	function loadScript(src, cb) {
		const s = document.createElement("script");
		s.src = src;
		s.onload = cb;
		document.head.appendChild(s);
	}

	// Libraries ship with the app (no CDN), so the page works on restricted networks.
	const assets = "/assets/warehouse_management/js/";
	loadScript(assets + "lib/three.r128.min.js", function () {
		loadScript(assets + "lib/vue.3.5.13.global.prod.js", function () {
			loadScript(assets + "warehouse_3d.js?v=" + Date.now(), function () {
				if (window.WarehouseTheatre3D) window.WarehouseTheatre3D.init("wt3d-root");
			});
		});
	});
};
