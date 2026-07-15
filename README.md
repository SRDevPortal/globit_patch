### Globit Patch

Frappe integration app for Globit's Patient Encounter workflow.

The app currently:

- creates the `channel_id` and `doc_id` custom fields on Patient Encounter;
- ensures Patient Encounter is included in Vobiz Settings > Allowed DocTypes; and
- relies on `vobiz_click_to_call` for its native Patient Encounter queue and user-mapping support;
- filters the native Patient Encounter console queue through Frappe read permissions and
  `created_by_agent` ownership for non-manager users; and
- provides a secure, idempotent destination API for synchronizing a Patient and Patient
  Encounter from explicitly allowed source sites through n8n.

Setup runs after installation and after every migration. Older releases installed
a restrictive Queue Source property setter; migrations remove that exact legacy
setter while preserving administrator-defined customizations.

Installation and migration validate the required Vobiz queue-source and console API
capabilities. An incompatible Vobiz release stops setup with an actionable error instead
of leaving a partially working console.

### Requirements

- Healthcare
- Vobiz Click To Call with native Patient Encounter queue support

### Patient Encounter synchronization

Destination endpoint:

```text
POST /api/method/globit_patch.api.patient_encounter_sync.sync_patient_encounter
```

The API requires an authenticated user with the `Globit Integration User` role and an
HMAC signature. Enable and configure `Globit Integration Settings` after deployment.
Production deployments should provide the signing secret through site configuration:

```json
{
  "globit_sync_signing_secret": "<secret-managed-outside-source-control>"
}
```

n8n must send:

```text
X-Globit-Event-ID: <required; must equal event_id in the JSON body>
X-Globit-Timestamp: <current Unix timestamp>
X-Globit-Signature: sha256=<hex HMAC-SHA256>
```

The signature input is the exact byte sequence:

```text
<timestamp>\n<event_id>\n<raw HTTP request body>
```

In n8n, serialize the payload once, calculate the signature from that string, and send
the same string as the raw HTTP body. Signing an object and allowing a later node to
serialize it again can produce a different byte sequence and an invalid signature.

The request body contains `schema_version`, event and trace identifiers, source metadata,
and the source Patient Encounter document. The destination validates its own idempotency
key and payload hash; clients may omit those two derived fields.

Patient identity resolution checks the permanent external mapping first, followed by
verified Contact, Customer, and Patient relationships. Ambiguous identities return
`PATIENT_IDENTITY_CONFLICT` instead of bypassing the destination duplicate validator.

The integration starts disabled and in dry-run mode. Dry-run executes destination Link
validation and normal Patient/Encounter hooks inside a database savepoint, then rolls
all changes back. Before enabling writes:

1. configure one trusted hostname per line in Allowed Source Sites and set the signing secret;
2. create a dedicated API user with the integration role;
3. populate `Integration Value Mapping` for Link values that differ between sites;
4. validate the n8n signature and error branches in staging; and
5. turn off dry-run only after a successful reconciliation test.

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
