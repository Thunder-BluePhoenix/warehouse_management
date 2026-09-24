### Warehouse Management System

A storage layer on top of ERPNext's Warehouse tree and stock ledger. It works on its own and needs only ERPNext; it adds no stock ledger of its own.

**Layout.** Tag warehouses with a role: **Building → Floor → Zone → Slot → Level**. Zones nest to any depth (zone › aisle › rack), so the tree grows with the business. A Level is one storage level or bay. Each Floor draws as **Rack** (levels stacked on a pillar) or **Parking** (bays side by side on the ground).

**3D/2D view** (`/app/warehouse-3d` in desk, `/warehouse-3d` standalone):
- Fill per level is the highest of its UOM capacities and its weight limit. Over 100 % shows as *Over*; stock with no capacity set shows as *No capacity*.
- Search by item, **serial no** or **batch** across all floors; a hit opens its floor and level.
- Refreshes live when stock posts (realtime in desk, 30-second poll standalone).
- Edit floor plans, slot positions, capacities and warehouses; a setup wizard maps an existing tree to roles.

**Rules on stock postings** (Stock Entry, Purchase Receipt, Purchase Invoice, Stock Reconciliation):
- **Bay Type**: an Item with a *Required Bay Type* may only go into levels of that type.
- **Weight limit** per level in kg (from the item's weight or kg UOM), with *Warn* or *Block*.
- **WMS Settings** can switch every Block to a warning (alarm mode) and add an early alarm at a chosen % of the limit.

**Totes (Storage Bin).** A movable, barcoded box with its own warehouse, so its contents are ordinary ERPNext stock. To move a tote, scan it and then its new location; no stock entry is needed, and every move is logged (Storage Bin Movement). Tote contents count at the tote's level for the 3D view, search and the rules above.

**WMS Scan** (`/app/wms-scan`, for phones and scanners):
- **Put away**: scan the item, then a level or tote. It suggests a place from Putaway Rules or where the item already is, and posts one Material Transfer.
- **Move tote**: scan the tote, then its new location.
- **Pick**: work through an ERPNext Pick List in walking order. Finishing ships what was picked, drafts the Delivery Note, and tells the customer by comment and email what is not in this shipment.

**Also:**
- Floor areas with length × breadth and a computed area. **Split Area** (on the Warehouse form or in 3D) carves out a new area beside an existing one and moves stock into it.
- **Putaway Rule sync** from level capacities.
- **Gate Entry**: a generic In/Out register that posts a Material Receipt or Issue, with *Suggest Free Bay*.

**Not in this app:** packing (use ERPNext's Packing Slip) and label printing.

Access follows ERPNext permissions: viewing needs read on **Warehouse** and ERPNext's **Bin** (stock balances); editing needs write on **Warehouse** (Item Manager by default). Adjust in Role Permission Manager.

### Installation

You can install this app using the [bench](https://github.com/frappe/bench) CLI:

```bash
cd $PATH_TO_YOUR_BENCH
bench get-app $URL_OF_THIS_REPO --branch develop
bench install-app warehouse_management
```

### Contributing

This app uses `pre-commit` for code formatting and linting. Please [install pre-commit](https://pre-commit.com/#installation) and enable it for this repository:

```bash
cd apps/warehouse_management
pre-commit install
```

Pre-commit is configured to use the following tools for checking and formatting your code:

- ruff
- eslint
- prettier
- pyupgrade
### CI

This app can use GitHub Actions for CI. The following workflows are configured:

- CI: Installs this app and runs unit tests on every push to `develop` branch.
- Linters: Runs [Frappe Semgrep Rules](https://github.com/frappe/semgrep-rules) and [pip-audit](https://pypi.org/project/pip-audit/) on every pull request.


### License

gpl-3.0

### Warehouse 3D

3D/2D storage visualization of the ERPNext Warehouse tree (Building → Floor → Zone → Slot → Level).
Open it from the desk at `/app/warehouse-3d` or standalone at `/warehouse-3d`. Requires ERPNext.
