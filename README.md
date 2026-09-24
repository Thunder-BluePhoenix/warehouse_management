### Warehouse Management System

A storage layer on top of ERPNext's Warehouse tree and stock ledger. It works on its own and needs only ERPNext; it adds no stock ledger of its own.

**Layout.** Tag warehouses with a role: **Building → Floor → Zone → Slot → Bin**. Zones nest to any depth (zone › aisle › rack), so the tree grows with the business. A Bin is one storage level or bay. Each Floor draws as **Rack** (levels stacked on a pillar) or **Parking** (bays side by side on the ground).

**3D/2D view** (`/app/warehouse-3d` in desk, `/warehouse-3d` standalone):
- Fill per level is the highest of its UOM capacities and its weight limit. Over 100 % shows as *Over*; stock with no capacity set shows as *No capacity*.
- Search by item, **serial no** or **batch** across all floors; a hit opens its floor and level.
- Refreshes live when stock posts (realtime in desk, 30-second poll standalone).
- Edit floor plans, slot positions, capacities and warehouses; a setup wizard maps an existing tree to roles.

**Rules on stock postings** (Stock Entry, Purchase Receipt, Purchase Invoice, Stock Reconciliation):
- **Bay Type**: an Item with a *Required Bay Type* may only go into levels of that type.
- **Weight limit** per level in kg (from the item's weight or kg UOM), with *Warn* or *Block*.

**Also:**
- Floor areas with length × breadth, computed area and a *split from* link (e.g. scrap piles).
- **Putaway Rule sync** from level capacities.
- **Gate Entry**: a generic In/Out register that posts a Material Receipt or Issue, with *Suggest Free Bay*.

**Not in this app:** movable totes, pick, pack and dispatch. Use ERPNext's Pick List, Packing Slip and Delivery Note.

Access follows ERPNext permissions: viewing needs read on **Warehouse** and **Bin**; editing needs write on **Warehouse** (Item Manager by default). Adjust in Role Permission Manager.

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

### Credits

The 3D view is derived from Warehouse Theatre 3D (MIT). three.js r128 and Vue 3.5.13 are bundled locally. See `THIRD_PARTY_NOTICES.md`.
