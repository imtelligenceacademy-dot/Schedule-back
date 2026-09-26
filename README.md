# IM-Telligence Schedule Manager — Backend

FastAPI API for the shared robotics scheduling platform. Deploy this repository to **Render Free** and connect it to **Supabase PostgreSQL**. The [React frontend](https://github.com/imtelligenceacademy-dot/Schedule-Front) is deployed separately on Vercel.

**[Complete deployment instructions](docs/DEPLOYMENT.md)** · **[Backups and restore](docs/BACKUPS.md)** · **[Testing notes](docs/TESTING.md)**

## Deployment

Select `imtelligenceacademy-dot/Schedule-back` in Render. **Leave Root Directory blank** because `app`, `requirements.txt`, `alembic.ini` and `render.yaml` are at this repository root.

- Runtime: Python; plan: Free.
- Build command: `pip install -r requirements.txt`
- Health check: `/api/health`
- Start command:

```bash
python -m alembic upgrade head && python -m app.cli bootstrap --non-interactive && uvicorn app.main:app --host 0.0.0.0 --port $PORT --workers 1 --proxy-headers
```

The included `render.yaml` also supports a Render Blueprint. It defines only the API, with no Render database.

Set `APP_ENV=production`, `DATABASE_URL` to Supabase's session pooler with SSL, a random `JWT_SECRET`, and `FRONTEND_URL` to the exact HTTPS Vercel origin. Set `BOOTSTRAP_EMAIL`, `BOOTSTRAP_NAME` and `BOOTSTRAP_PASSWORD` for first-admin creation. Remove the bootstrap password after first login. See the deployment guide for every variable and configuration step.

## Local development

Run these commands from this repository root:

```powershell
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements-dev.txt
python scripts/setup-dev.py
.venv/Scripts/python -m alembic upgrade head
.venv/Scripts/python -m app.cli bootstrap --non-interactive
.venv/Scripts/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

The setup script creates an ignored `.env` and writes randomly generated development login details to `.local/development-login.txt`. For synthetic example schedules in a fresh development database, add `--demo` to the bootstrap command. Production refuses demo seeding and SQLite.

Clone the frontend into a sibling folder named `frontend` if you want to run the full application and browser tests. On Linux/macOS, use `.venv/bin/python` instead of `.venv/Scripts/python`.

## API features

- Argon2 password hashing, JWT sessions, revocation, temporary-password replacement and login throttling.
- Server-enforced Super Admin / Admin / Viewer permissions.
- Schools, teachers, classes and year-specific assignments.
- One school per teacher per academic year, enforced by database constraints.
- Weekly sessions, backend filters, teacher/class overlaps and dashboard statistics.
- Versioned edits and deletes that reject stale saves with HTTP 409.
- Transactional audit history and session edit attribution.
- Atomic CSV/Excel validation/import and filtered CSV/Excel export.
- Academic-year activation and read-only archives.
- Alembic migrations, Supabase Data API restrictions and a small PostgreSQL connection pool.

Authentication is the FastAPI option backed by Supabase PostgreSQL. Supabase Auth and its service-role key are not required. The production frontend calls the API using bearer tokens. Important schedule data is never stored in browser storage.

Development API docs: `http://127.0.0.1:8000/api/docs`. All data routes require sign-in. Production API documentation endpoints are disabled.

## Checks

```powershell
.venv/Scripts/python -m pytest -q
.venv/Scripts/python -m ruff check app tests alembic
.venv/Scripts/python -m alembic check
```

The test suite uses disposable SQLite by default. Set `TEST_POSTGRES_URL` to a dedicated test PostgreSQL database to run the same suite against isolated PostgreSQL schemas. Never use the live scheduling database for tests.
