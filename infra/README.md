# Owner storage setup

T04 adds the Documents owner schema to the pinned local PostgreSQL instance.
The schema has a non-login `documents_owner` role for API SQL and a separate
non-login `documents_migrator` role that owns the schema and tables. Profile
logins receive membership only in `documents_owner`; migrations run with the
administrator credential and immediately `SET ROLE documents_migrator`.

For each development or testing database, provision the roles as a PostgreSQL
administrator, then apply the migration:

```powershell
$admin = [Uri]($env:ALFALAB_MIGRATION_DATABASE_URL -replace '^postgresql\+psycopg://', 'postgresql://')
$adminUser = [Uri]::UnescapeDataString($admin.UserInfo.Split(':', 2)[0])
$database = [Uri]::UnescapeDataString($admin.AbsolutePath.TrimStart('/'))
psql -h $admin.Host -p $admin.Port -U $adminUser -d $database -W -v ON_ERROR_STOP=1 -f infra/bootstrap/documents_roles.sql
uv run --locked alembic -c infra/alembic.ini upgrade head
```

`ALFALAB_MIGRATION_DATABASE_URL` must come from the local administrator
credential in `.local`. `psql -W` prompts for its password so the URL and
password are not placed in the process argument list or command transcript.
Do not put the URL in a tracked profile or process log. The Alembic environment requires that variable, sets the
session role to `documents_migrator`, and does not print the connection URL.
The runtime engine uses the separately configured development/testing profile
and issues `SET ROLE documents_owner` when opening each pooled connection. The
owner role can update only `documents.current_revision`; immutable versions,
receipts, and audit entries are insert-only through the API role. Integration
tests use `ALFALAB_T04_ADMIN_DSN` for migrations and can use
`ALFALAB_T04_OWNER_DSN` to exercise the profile login's owner-role membership.
PostgreSQL also enforces same-scope version-parent and receipt-to-audit links,
so orphan references and references across tenants or sandboxes are rejected.

Document artifacts are immutable JSON files below
`.local/artifacts/<environment>/<tenant>/<sandbox>/<sha256>.json`. PostgreSQL
stores scoped references and verifies their hashes on every read. T04 has no
production profile and does not use an external object store.

## Known contract follow-up

The Documents.read as-of card asks for a warning when `published_at` is absent,
but the approved `DocumentVersion` and `DocumentResult` OpenAPI schemas have no
warning field. T04 includes versions with unknown publication time in the
as-of result without inventing a date or changing the schema. A warning remains
deferred until a typed response channel is approved.

## Runs owner (T05)

Runs uses a separate non-login `runs_owner` runtime role and `runs_migrator`
DDL role. Its migration tree and Alembic version table live in the `runs`
schema, independent of Documents. Profile logins receive membership in
`runs_owner`; the application engine assumes that role and sets trusted tenant
and sandbox values locally for each transaction. PostgreSQL row-level security
scopes runs, spans, dependencies, and artifacts. `runs_owner` has no Documents
schema grant.

Provision and migrate Runs from the repository root as a database administrator:

```powershell
$env:ALFALAB_RUNS_MIGRATION_DATABASE_URL = "<local administrator PostgreSQL URL>"
psql -h 127.0.0.1 -p <port> -U postgres -d <database> -W -v ON_ERROR_STOP=1 -f infra/bootstrap/runs_roles.sql
uv run --locked alembic -c infra/runs/alembic.ini upgrade head
```

Keep the administrator URL in the process environment only while migrating.
At runtime the API and CLI read the ignored `.local/development.json` or
`.local/testing.json` profile, or `ALFALAB_RUNS_DATABASE_URL`; profile logins
assume only `runs_owner`. PostgreSQL integration tests use
`ALFALAB_T05_ADMIN_DSN` to create a uniquely named temporary database, run the
upgrade/downgrade/upgrade cycle, and drop that database after the test session.

Runs stores artifact metadata and relative keys in the owner schema; immutable
content-addressed JSON files use the scoped `.local/artifacts/<environment>/<tenant>/<sandbox>/`
tree. Full content is written only after a trusted server resolver approves the
exact payload hash for full recording. Caller `data_declaration` is not a trust
signal. Unregistered, mismatched, or unverified inputs are processed locally
only when allowed and are recorded with metadata and hashes. No artifact body
column exists in PostgreSQL. No external provider is registered in this runtime,
so unknown data cannot cause egress.
