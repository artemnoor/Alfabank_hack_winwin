# Documents storage setup

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
