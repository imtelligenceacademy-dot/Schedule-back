# Validation

The API tests exercise authentication, every role boundary, shared data through independent users, database-enforced assignment constraints, concurrent edits, audit snapshots, conflicts, filters, formula-safe exports, CSV/Excel imports, archive behavior, resets, revocation, CORS, CSRF and throttling.

The Playwright tests use separate browser contexts for Super Admin, Admin and Viewer, a separate frontend/API origin (ports 5174 and 8001), and a disposable database upgraded through Alembic. They exercise cross-origin bearer authentication/CORS, add/edit forms, cross-user refresh and reload, stale saves and reload-latest, hidden Viewer actions, school color consistency, audit history, mobile import/export, account creation, temporary-password replacement and Render-style slow startup/retries.

## Run against PostgreSQL

Install the development requirements. Create a **dedicated disposable test database** in a local or test PostgreSQL instance. The optional PostgreSQL fixture creates a unique schema per test, uses it through `search_path`, and drops only that schema afterward. It does not clear existing public tables, but you should still never point it to production.

```powershell
Set-Location backend
# Set this URL privately in your shell; example shows a test-only local connection.
$env:TEST_POSTGRES_URL = 'postgresql+psycopg://schedule_test@127.0.0.1:55432/schedule_test'
.venv/Scripts/python -m pytest -q
Remove-Item Env:TEST_POSTGRES_URL
```

Fixture IDs are fixed for readability; PostgreSQL sequences are advanced after seeding. Tests remain isolated across both backends.

For production migration validation, deploy to a Supabase **test** project first. Run Alembic upgrade/check, bootstrap, the production walkthrough from the deployment guide, and confirm RLS blocks Supabase browser roles. Local PostgreSQL testing verifies SQL and concurrency semantics but cannot verify credentials, network routing, Supabase project policies or the actual hosted service until accounts are configured.

## Completed checks — 26 September 2026

| Check | Result |
|---|---|
| API suite on disposable SQLite | 33 passed |
| Same API suite on isolated PostgreSQL 17.11 schemas | 33 passed |
| Browser suite in Microsoft Edge, separate frontend/API origins | 5 passed |
| TypeScript strict checks and Vite production build | Passed |
| Ruff checks | Passed |
| Alembic upgrade and schema-drift check on SQLite and PostgreSQL | Passed |
| Idempotent PostgreSQL first-admin bootstrap | Passed |
| PostgreSQL RLS and denial of `anon`/`authenticated` reads | Passed |
| Native PostgreSQL dump and restore into a separate test database | Passed |

The import tests cover automatic setup by Super Admins, preview rollback, atomic failure rollback, audit records, existing assignments, one-school-per-year enforcement, duplicate teacher names, inactive records and Admin permission boundaries. The browser suite checks the creation option and preview before importing into a new school. The complete 77-lesson user workbook also passed an import into an empty disposable database: 3 schools, 27 teachers, 27 assignments and 73 classes were created.

Validation performs no database writes and its query count stays constant as the file grows. Regression tests compare 1-row and 200-row previews and verify preview/import conflict results agree. On local PostgreSQL with 100 ms of simulated latency per SQL statement, the 77-lesson workbook used 8 read statements for validation (0.84 seconds) and 15 statements for importing, including 6 batched inserts (1.57 seconds). These are controlled test timings, not measured production latency.

PostgreSQL validation used a local isolated test server, which was shut down afterward. The deployment walkthrough remains the hosted acceptance check for actual Supabase credentials, routing and project policies. The API suite emits one dependency deprecation warning from Starlette's current `httpx` test-client integration; it does not affect the passing application tests.
