# Deploy to Vercel + Render Free + Supabase Free

Deploy the services from two GitHub repositories: [Schedule-back](https://github.com/imtelligenceacademy-dot/Schedule-back) for Render and [Schedule-Front](https://github.com/imtelligenceacademy-dot/Schedule-Front) for Vercel. The database lives only on Supabase. This guide deliberately does not create Render PostgreSQL.

```text
Staff browser
    ↓ HTTPS
Vercel React frontend
    ↓ HTTPS / Authorization bearer token
Render Free FastAPI API
    ↓ PostgreSQL over SSL / SQLAlchemy + psycopg
Supabase PostgreSQL (session pooler)
```

## 1. GitHub repositories and local layout

The backend and frontend are independent repositories with their service files at the repository root. To recreate the local workspace on another computer, run these commands in an empty workspace folder:

```powershell
git clone https://github.com/imtelligenceacademy-dot/Schedule-back.git backend
git clone https://github.com/imtelligenceacademy-dot/Schedule-Front.git frontend
```

This preserves the sibling `backend` / `frontend` layout used by browser tests. Each repository has its own `.gitignore`. Before committing changes, confirm `.env`, `.local`, `.venv`, `node_modules`, database files and test artifacts are absent from `git status`. Actual passwords and database URLs belong in hosting environment settings, never in Git. Run Git commands inside the service folder you are updating.

## 2. Set up Supabase PostgreSQL

1. Create a Free project in [Supabase](https://supabase.com/dashboard). Choose the region nearest your users and Render service. Save the database password securely.
2. Click **Connect**, choose **Session pooler**, and copy the **exact** connection string. Use port **5432**, not transaction-pooler port 6543. The session pooler supports IPv4; the direct Free database endpoint generally requires IPv6. See [Supabase connection guidance](https://supabase.com/docs/guides/database/connecting-to-postgres).
3. Replace the password placeholder with the URL-encoded database password. Add `?sslmode=require` (or `&sslmode=require` if the URI already has a query). Example shape only:

```text
postgresql://postgres.PROJECT_REF:URL_ENCODED_PASSWORD@EXACT_POOLER_HOST:5432/postgres?sslmode=require
```

Copy the host and username from Connect; do not guess them from the region. The backend normalizes this URL to `postgresql+psycopg://`.

4. The app uses FastAPI authentication and accesses PostgreSQL directly. You do **not** need to configure Supabase Auth, create users in Supabase Auth, or expose Supabase keys to the browser. `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY` are optional, unused placeholders for a future Auth integration.
5. The second Alembic migration enables RLS on application tables and revokes Data API privileges from Supabase's `anon` and `authenticated` roles. No browser policies are installed. The backend's owner connection can still access its tables. Keep these restrictions in place.

The app uses a small SQLAlchemy pool: two persistent connections plus one overflow connection per worker; a single Uvicorn worker is configured for Render Free. Connections are checked on reuse and recycled after five minutes. Prepared statements are disabled for pooler compatibility. See [Supabase pooling guidance](https://supabase.com/docs/guides/database/connecting-to-postgres/pooling-and-limits).

## 3. Database migrations

The Render start command runs migrations automatically **before serving traffic**:

```bash
python -m alembic upgrade head
```

It uses the Render `DATABASE_URL` from step 5. This supports Free Web Services without a paid pre-deploy job or interactive shell. Subsequent restarts see the existing Alembic revision and do not reset data.

For a migration run from your own computer instead, set a separate local `backend/.env` with the Supabase URL, a random `JWT_SECRET`, `APP_ENV=production` and your HTTPS frontend URL, then:

```powershell
Set-Location backend
.venv/Scripts/python -m alembic upgrade head
.venv/Scripts/python -m alembic current
.venv/Scripts/python -m alembic check
```

Use a direct connection for native administrative tasks if your network supports it, or the session-pooler alternative over IPv4. Never run tests against the live schedule database. Do not run `create_all`, drop tables or migrations in the browser.

## 4. Deploy the Render FastAPI backend

In [Render](https://dashboard.render.com), choose **New → Web Service**, connect GitHub and select **imtelligenceacademy-dot/Schedule-back**. Use:

| Setting | Value |
|---|---|
| Name | `im-telligence-schedule-api` (or an available name) |
| Branch | `main` |
| Root Directory | Leave blank (repository root) |
| Runtime | Python |
| Instance Type | **Free** |
| Build Command | `pip install -r requirements.txt` |
| Health Check Path | `/api/health` |

Start Command (paste as one line):

```bash
python -m alembic upgrade head && python -m app.cli bootstrap --non-interactive && uvicorn app.main:app --host 0.0.0.0 --port $PORT --workers 1 --proxy-headers
```

Alternatively use **New → Blueprint** with the repository's `render.yaml`, which defines only the backend. Supply the same environment values below. There is no `databases:` section. The `$PORT` value comes from Render.

See [Render Web Service settings](https://render.com/docs/web-services).

## 5. Render environment variables

Add these **before the first deploy**:

| Variable | Value |
|---|---|
| `PYTHON_VERSION` | `3.13.15` |
| `APP_ENV` | `production` |
| `DATABASE_URL` | Supabase session-pooler URL, with SSL |
| `JWT_SECRET` | A fresh random secret of at least 32 characters |
| `FRONTEND_URL` | `https://YOUR-VERCEL-PROJECT.vercel.app` |
| `TIMEZONE` | `Asia/Beirut` |
| `SESSION_HOURS` | `8` |
| `BOOTSTRAP_EMAIL` | Your first Super Admin's real email |
| `BOOTSTRAP_NAME` | Their full name |
| `BOOTSTRAP_PASSWORD` | A random temporary password, 12–256 characters |
| `SUPABASE_URL` | Optional; unused in the selected authentication implementation |
| `SUPABASE_SERVICE_ROLE_KEY` | **Omit**; not needed for SQLAlchemy authentication |

Generate `JWT_SECRET` locally:

```powershell
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

The Blueprint generates `JWT_SECRET` automatically. Keep it stable across routine deploys; rotating it signs everyone out. Remove `BOOTSTRAP_PASSWORD` after first login. Bootstrap is idempotent: once an active Super Admin exists, subsequent restarts do not reset their password. If no admin exists and bootstrap values are missing, startup stops with an actionable message.

If you do not yet know your Vercel URL, create the Vercel project in step 6 first, obtain its production domain, then set `FRONTEND_URL` and redeploy Render. The Vercel page can be created before the API is live; it will show a loading/retry state until the API is configured.

After deploy, Render provides `https://YOUR-BACKEND.onrender.com`. Open `https://YOUR-BACKEND.onrender.com/api/health` and allow time for wake-up. Expect `{"status":"ok"}`. Do not copy a localhost URL into Vercel.

## 6. Deploy the Vercel frontend

In [Vercel](https://vercel.com/new), import **imtelligenceacademy-dot/Schedule-Front**:

| Setting | Value |
|---|---|
| Root Directory | `.` (repository root) |
| Framework Preset | Vite |
| Install Command | `npm ci` |
| Build Command | `npm run build` |
| Output Directory | `dist` |

The checked-in `vercel.json` at the frontend repository root contains SPA routing and security headers. Its CSP permits API requests to HTTPS Render domains. If you later put the backend on a custom domain, add that exact HTTPS origin to the CSP `connect-src` before deploying the frontend. See [Vite on Vercel](https://vercel.com/docs/frameworks/frontend/vite).

## 7. Vercel environment variables

Add to the **Production** environment:

| Variable | Value |
|---|---|
| `VITE_API_URL` | `https://YOUR-BACKEND.onrender.com` (without `/api`) |
| `VITE_SUPABASE_URL` | Leave unset; unused with FastAPI authentication |
| `VITE_SUPABASE_ANON_KEY` | Leave unset; unused with FastAPI authentication |

Never add `DATABASE_URL`, `JWT_SECRET`, `BOOTSTRAP_PASSWORD` or `SUPABASE_SERVICE_ROLE_KEY` to Vercel. Anything prefixed `VITE_` is public browser code. Environment changes require a **frontend redeploy** because Vite embeds them at build time. See [Vercel environment settings](https://vercel.com/kb/guide/how-to-add-vercel-environment-variables).

## 8. Configure CORS

Set Render's `FRONTEND_URL` to the exact Vercel **production** origin, including `https://`, and redeploy Render. No trailing path and no wildcard:

```text
FRONTEND_URL=https://YOUR-VERCEL-PROJECT.vercel.app
```

If you use a custom frontend domain, add it explicitly as a comma-separated origin:

```text
FRONTEND_URL=https://schedule.im-telligence.com,https://YOUR-VERCEL-PROJECT.vercel.app
```

Preview deployments are not automatically allowed. Add specific preview origins only if you intend to authorize them. Production rejects HTTP origins and SQLite URLs at startup. CORS allows `Authorization` and `Content-Type` headers. Requests authenticate with bearer tokens, so login works without cross-site cookies.

## 9. Create the first admin

The start command runs:

```bash
python -m app.cli bootstrap --non-interactive
```

On a fresh migrated database it creates the Super Admin from the bootstrap variables and creates the initial academic year. It hashes the password with Argon2; it does not print or store the plain password in an app table or audit record. Production does not create sample schedules.

1. Open the Vercel site and sign in using `BOOTSTRAP_EMAIL` and `BOOTSTRAP_PASSWORD`.
2. Replace the temporary password when prompted.
3. Remove `BOOTSTRAP_PASSWORD` from Render and deploy again.
4. In **Schools**, add schools with colors and classes.
5. In **Teachers**, add teachers and assign each to one school for the selected year.
6. In **All Schedules**, add sessions; or use **Data Import** to download the template, validate and import a CSV/Excel file.

Super Admin imports can create missing schools, teachers, classes and teacher-school assignments for the selected year. The **Create missing schools, teachers and yearly assignments** option is enabled by default. Validation previews the new records without saving anything; clicking Import saves the setup and sessions in one transaction. Invalid rows roll back all records. Existing teacher names must identify one teacher, inactive records are rejected, and a teacher already assigned to another school cannot be reassigned by import. Admins can import sessions and new classes but must use schools, teachers and assignments already configured by a Super Admin.
7. In **Users**, create separate Admin/Viewer accounts; do not share the Super Admin login. New users must replace their temporary password on first login.

To create the first admin interactively from your machine instead, configure `backend/.env` for the target database and run `python -m app.cli bootstrap`. The password prompt is hidden. Do not use `--demo` in production.

## 10. Test the production deployment

Use two browsers or separate private browser sessions; the same email in two tabs is not an adequate permission test.

1. Open the website while Render is asleep. After five seconds the frontend should say **Starting schedule server...** and continue waiting; it allows 120 seconds and retries transient startup failures. Render Free services can sleep after 15 idle minutes. See [Render Free behavior](https://render.com/docs/free).
2. Sign in as Super Admin, change the temporary password and create an Admin plus a Viewer. Confirm Viewer navigation omits Users, Audit Log, Settings and Data Import.
3. Assign two teachers to School A in the same year. Confirm assigning either one to School B returns a clear error. Assigning the teacher to a different school in a new year should work.
4. Admin adds a session. Viewer refreshes and sees it, with the same school color; reload and filter by that teacher.
5. Viewer cannot add/edit/import. Admin cannot manage users or delete sessions. Enable Viewer export and check it works.
6. Open the same session in two editor browsers. Save in the first, then save in the second. Expect the “modified by another user” message. Reload the latest session before saving again.
7. Create overlapping sessions for a teacher or class and review Conflicts. Parallel sessions with different classes and teachers at the same school should stay clear.
8. Validate a CSV and an Excel file. Confirm validation saves nothing. Include an invalid row and confirm the entire import remains unsaved. Correct it, import and check the Viewer sees the new sessions.
9. Export a filtered CSV and Excel file; confirm only the filtered sessions are included.
10. Confirm Audit Log records the editor, timestamp and before/after values. Disable a user and confirm their existing session is rejected.
11. Add/activate the next academic year, archive the previous year, and confirm its sessions remain visible but cannot be changed.
12. Redeploy Render and confirm all records survive. They reside on Supabase, not Render's ephemeral filesystem.
13. Verify Supabase Data API access to application tables with an anonymous key is denied. Inspect the migration and RLS/privileges in Supabase.
14. Make a backup and test restoring it to a separate database using [the backup guide](BACKUPS.md).

## Ongoing operation

Render Free can sleep and has usage limits. Supabase Free is not a guarantee of indefinite unattended archival: low-activity projects may pause, and free projects need independent backups. Monitor project status, especially over school holidays. See [Supabase Free pausing](https://supabase.com/docs/guides/platform/free-project-pausing) and [backup guidance](https://supabase.com/docs/guides/platform/backups). None of this changes the shared PostgreSQL architecture or introduces a Render database.

Keep at least one trusted active Super Admin. Schools, teachers and users are deactivated to preserve historical references. The selected application scope is weekly recurring schedules; holidays and one-off cancellations require a future date-specific scheduling feature.
