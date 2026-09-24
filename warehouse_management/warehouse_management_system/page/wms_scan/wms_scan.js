/* WMS Scan: put away, move totes and pick by scanning. Works with a hardware scanner (types the code and
   presses Enter) or the phone camera (the scan icon in the input). All the rules run on the server. */
frappe.pages["wms-scan"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("WMS Scan"),
		single_column: true,
	});
	wrapper.wms_scan = new WmsScan(page);
};

const WMS_API = "warehouse_management.api.scan.";

class WmsScan {
	constructor(page) {
		this.page = page;
		this.reset();
		this.$body = $(`
			<div class="wms-scan">
				<div class="wms-input"></div>
				<div class="wms-qty"></div>
				<div class="wms-prompt"></div>
				<div class="wms-list"></div>
			</div>
		`).appendTo(page.body);
		this.add_style();

		this.mode_field = page.add_field({
			fieldname: "mode",
			fieldtype: "Select",
			label: __("Task"),
			options: [
				{ value: "putaway", label: __("Put away") },
				{ value: "move", label: __("Move tote") },
				{ value: "pick", label: __("Pick") },
			],
			default: "putaway",
			change: () => this.set_mode(this.mode_field.get_value()),
		});
		this.source_field = page.add_field({
			fieldname: "source",
			fieldtype: "Link",
			options: "Warehouse",
			label: __("From Warehouse"),
			get_query: () => ({ filters: { is_group: 0, disabled: 0 } }),
		});
		this.pick_field = page.add_field({
			fieldname: "pick_list",
			fieldtype: "Link",
			options: "Pick List",
			label: __("Pick List"),
			get_query: () => ({ filters: { docstatus: 0 } }),
			change: () => this.load_pick(),
		});

		this.code = frappe.ui.form.make_control({
			parent: this.$body.find(".wms-input"),
			df: {
				fieldname: "code",
				fieldtype: "Data",
				options: "Barcode",
				placeholder: __("Scan or type a code, then Enter"),
				// the camera scanner sets the value: treat it like a scan
				change: () => {
					const v = this.code.get_value();
					if (v && !this.typing) this.scan(v);
				},
			},
			render_input: true,
		});
		this.code.$input.on("keydown", (e) => {
			this.typing = e.key !== "Enter";
			if (e.key === "Enter") {
				e.preventDefault();
				this.scan(this.code.$input.val());
			}
		});
		this.qty = frappe.ui.form.make_control({
			parent: this.$body.find(".wms-qty"),
			df: { fieldname: "qty", fieldtype: "Float", label: __("Qty"), default: 1 },
			render_input: true,
		});
		this.qty.set_value(1);

		frappe.db.get_single_value("WMS Settings", "default_putaway_source").then((wh) => {
			if (wh && !this.source_field.get_value()) this.source_field.set_value(wh);
		});
		this.set_mode("putaway");
	}

	reset() {
		this.item = null; // put-away: the scanned item waiting for its location
		this.lines = []; // put-away: lines ready to post
		this.tote = null; // move: the scanned tote
		this.at = null; // pick: the level or tote the picker is standing at
		this.pick = null; // pick: rows from the server
	}

	set_mode(mode) {
		this.mode = mode;
		this.reset();
		this.source_field.$wrapper.toggle(mode === "putaway");
		this.pick_field.$wrapper.toggle(mode === "pick");
		this.page.clear_primary_action();
		if (mode === "putaway") {
			this.page.set_primary_action(__("Post"), () => this.post_putaway());
		} else if (mode === "pick") {
			this.page.set_primary_action(__("Finish Pick"), () => this.finish_pick());
			this.load_pick();
		}
		this.render();
	}

	focus() {
		this.typing = false;
		this.code.set_value("");
		setTimeout(() => this.code.$input.trigger("focus"), 50);
	}

	fail(message) {
		frappe.utils.play_sound("error");
		frappe.show_alert({ message, indicator: "red" }, 5);
		this.focus();
	}

	async scan(raw) {
		const code = (raw || "").trim();
		if (!code || this.busy) return;
		this.busy = true;
		try {
			const r = await frappe.call({ method: WMS_API + "resolve", args: { code } });
			await this["on_" + this.mode](r.message);
		} finally {
			this.busy = false;
			this.focus();
			this.render();
		}
	}

	// ── put away ───────────────────────────────────────
	async on_putaway(s) {
		if (["item", "serial", "batch"].includes(s.kind)) {
			this.item = s;
			if (s.kind === "serial") this.qty.set_value(1);
			const r = await frappe.call({
				method: WMS_API + "suggest_putaway",
				args: { item_code: s.item_code, qty: this.qty.get_value() || 1 },
			});
			this.item.suggestion = r.message;
			return;
		}
		if (!this.item) return this.fail(__("Scan the item first, then where it goes."));
		if (s.kind === "tote" && !s.location) return this.fail(__("This tote is not placed yet."));
		this.lines.push({
			item_code: this.item.item_code,
			item_name: this.item.item_name,
			uom: this.item.uom,
			qty: this.item.kind === "serial" ? 1 : this.qty.get_value() || 1,
			serial_no: this.item.serial_no,
			batch_no: this.item.batch_no,
			target: s.code,
			target_label: s.kind === "tote" ? "🧺 " + s.label : s.label,
		});
		this.item = null;
		frappe.utils.play_sound("click");
	}

	async post_putaway() {
		if (!this.lines.length) return this.fail(__("Nothing scanned yet."));
		if (!this.source_field.get_value()) return this.fail(__("Pick the From Warehouse."));
		const r = await frappe.call({
			method: WMS_API + "putaway",
			args: { source_warehouse: this.source_field.get_value(), lines: this.lines },
			freeze: true,
		});
		frappe.show_alert({
			message: __("Put away: {0}", [r.message.stock_entry]),
			indicator: "green",
		});
		frappe.utils.play_sound("submit");
		this.lines = [];
		this.render();
		this.focus();
	}

	// ── move tote ──────────────────────────────────────
	async on_move(s) {
		if (s.kind === "tote") {
			this.tote = s;
			return;
		}
		if (s.kind !== "location") return this.fail(__("Scan a tote, then its new location."));
		if (!this.tote) return this.fail(__("Scan the tote first."));
		const r = await frappe.call({
			method: WMS_API + "move_tote",
			args: { storage_bin: this.tote.code, location: s.code },
		});
		frappe.show_alert({
			message: __("{0} moved to {1}", [this.tote.code, r.message.to]),
			indicator: "green",
		});
		frappe.utils.play_sound("submit");
		this.tote = null;
	}

	// ── pick ───────────────────────────────────────────
	async load_pick() {
		const name = this.pick_field.get_value();
		this.pick = null;
		if (name) {
			const r = await frappe.call({
				method: WMS_API + "get_pick",
				args: { pick_list: name },
			});
			this.pick = r.message;
		}
		this.render();
		this.focus();
	}

	async on_pick(s) {
		if (!this.pick) return this.fail(__("Choose the Pick List first."));
		if (s.kind === "location" || s.kind === "tote") {
			this.at = s;
			return;
		}
		await frappe.call({
			method: WMS_API + "record_pick",
			args: {
				pick_list: this.pick.name,
				code: s.code,
				qty: this.qty.get_value() || 1,
				warehouse: this.at ? this.at.warehouse : null,
			},
		});
		frappe.utils.play_sound("click");
		this.qty.set_value(1);
		const r = await frappe.call({
			method: WMS_API + "get_pick",
			args: { pick_list: this.pick.name },
		});
		this.pick = r.message;
	}

	finish_pick() {
		if (!this.pick) return this.fail(__("Choose the Pick List first."));
		const short = this.pick.rows.filter((r) => r.picked < r.qty);
		const msg = short.length
			? __("{0} line(s) are short. Ship what was picked and tell the customer?", [
					short.length,
			  ])
			: __("Everything is picked. Submit the pick?");
		frappe.confirm(msg, async () => {
			const r = await frappe.call({
				method: WMS_API + "finish_pick",
				args: { pick_list: this.pick.name },
				freeze: true,
			});
			const res = r.message;
			const notes = (res.delivery_notes || [])
				.map((dn) => `<a href="/app/delivery-note/${encodeURIComponent(dn)}">${dn}</a>`)
				.join(", ");
			frappe.msgprint({
				title: __("Pick submitted"),
				indicator: "green",
				message: [
					__("Pick List {0} is submitted.", [res.pick_list]),
					res.short.length
						? __("{0} line(s) were short.", [res.short.length])
						: __("Nothing was short."),
					res.notified.length
						? __("Emailed: {0}", [res.notified.map((n) => n.email).join(", ")])
						: "",
					notes ? __("Delivery Note to pack and submit: {0}", [notes]) : "",
				]
					.filter(Boolean)
					.join("<br>"),
			});
			this.pick_field.set_value("");
		});
	}

	// ── view ───────────────────────────────────────────
	render() {
		const esc = frappe.utils.escape_html;
		let prompt = "";
		let list = "";
		if (this.mode === "putaway") {
			prompt = this.item
				? __("{0}: scan where it goes", [`<b>${esc(this.item.item_code)}</b>`]) +
				  (this.item.suggestion
						? ` — ${__("suggested")} <b>${esc(this.item.suggestion.label)}</b> (${esc(
								this.item.suggestion.reason
						  )})`
						: "")
				: __("Scan an item, serial no or batch");
			list = this.lines
				.map(
					(l, i) => `<div class="wms-row">
						<div><b>${esc(l.item_code)}</b> × ${l.qty} ${esc(l.uom || "")}
						${l.serial_no ? `<span class="text-muted">${esc(l.serial_no)}</span>` : ""}
						<div class="text-muted">→ ${esc(l.target_label)}</div></div>
						<button class="btn btn-xs btn-default" data-remove="${i}">✕</button>
					</div>`
				)
				.join("");
		} else if (this.mode === "move") {
			prompt = this.tote
				? __("Tote {0} (now at {1}): scan its new location", [
						`<b>${esc(this.tote.code)}</b>`,
						esc(this.tote.location || __("nowhere")),
				  ])
				: __("Scan a tote");
		} else if (this.pick) {
			const next = this.pick.rows.find((r) => r.picked < r.qty);
			prompt = this.at
				? __("At {0}: scan the items", [`<b>${esc(this.at.label)}</b>`])
				: next
				? __("Go to {0}, scan it, then the items", [
						`<b>${esc(next.tote || next.level || next.warehouse)}</b>`,
				  ])
				: __("All picked: Finish Pick");
			list = this.pick.rows
				.map((r) => {
					const where = [r.floor_name, ...(r.zone_path || []), r.slot_label]
						.filter(Boolean)
						.join(" › ");
					const done = r.picked >= r.qty;
					return `<div class="wms-row ${done ? "done" : r === next ? "next" : ""}">
						<div><b>${esc(r.item_code)}</b> ${esc(r.item_name || "")}
						<div class="text-muted">${esc(where)} / ${esc(r.level || r.warehouse)}${
						r.tote ? " · 🧺 " + esc(r.tote) : ""
					}</div></div>
						<div class="wms-count">${r.picked} / ${r.qty} ${esc(r.uom || "")}</div>
					</div>`;
				})
				.join("");
		} else {
			prompt = __("Choose a Pick List");
		}
		this.$body.find(".wms-prompt").html(prompt);
		this.$body.find(".wms-qty").toggle(this.mode !== "move");
		const $list = this.$body.find(".wms-list").html(list);
		$list.find("[data-remove]").on("click", (e) => {
			this.lines.splice(+$(e.currentTarget).attr("data-remove"), 1);
			this.render();
		});
	}

	add_style() {
		if (document.getElementById("wms-scan-style")) return;
		$(`<style id="wms-scan-style">
			.wms-scan { max-width: 640px; margin: 0 auto; padding: 8px 0 40px; }
			.wms-scan .wms-input input { font-size: 18px; height: 48px; }
			.wms-scan .wms-qty { max-width: 160px; }
			.wms-scan .wms-prompt { font-size: 15px; margin: 8px 0 12px; }
			.wms-scan .wms-row { display: flex; justify-content: space-between; align-items: center; gap: 8px;
				padding: 10px 12px; border: 1px solid var(--border-color); border-radius: 8px; margin-bottom: 6px; }
			.wms-scan .wms-row.next { border-color: var(--primary); }
			.wms-scan .wms-row.done { opacity: .55; }
			.wms-scan .wms-count { font-weight: 600; white-space: nowrap; }
		</style>`).appendTo("head");
	}
}
