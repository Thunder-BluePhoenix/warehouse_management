### Warehouse Management System

A comprehensive warehouse management system for inventory, storage locations, stock movements, receiving, picking, packing, and dispatch operations, with 3D and 2D warehouse storage visualization.

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

3D/2D storage visualization of the ERPNext Warehouse tree (Building → Floor → Slot → Bin).
Open it from the desk at `/app/warehouse-3d` or standalone at `/warehouse-3d`. Requires ERPNext.
Derived from Warehouse Theatre 3D (MIT) — see `THIRD_PARTY_NOTICES.md`.
