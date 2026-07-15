### Globit Patch

Frappe integration app for Globit's Patient Encounter workflow.

The app currently:

- creates the `channel_id` and `doc_id` custom fields on Patient Encounter;
- ensures Patient Encounter is included in Vobiz Settings > Allowed DocTypes; and
- relies on `vobiz_click_to_call` for its native Patient Encounter queue and user-mapping support; and
- filters the native Patient Encounter console queue through Frappe read permissions and
  `created_by_agent` ownership for non-manager users.

Setup runs after installation and after every migration. Older releases installed
a restrictive Queue Source property setter; migrations remove that exact legacy
setter while preserving administrator-defined customizations.

Installation and migration validate the required Vobiz queue-source and console API
capabilities. An incompatible Vobiz release stops setup with an actionable error instead
of leaving a partially working console.

### Requirements

- Healthcare
- Vobiz Click To Call with native Patient Encounter queue support

### Installation

You can install this app using the [bench](https://github.com/frappe/bench) CLI:

```bash
cd $PATH_TO_YOUR_BENCH
bench get-app $URL_OF_THIS_REPO --branch develop
bench install-app globit_patch
```

### Contributing

This app uses `pre-commit` for code formatting and linting. Please [install pre-commit](https://pre-commit.com/#installation) and enable it for this repository:

```bash
cd apps/globit_patch
pre-commit install
```

Pre-commit is configured to use the following tools for checking and formatting your code:

- ruff
- eslint
- prettier
- pyupgrade

### License

MIT
