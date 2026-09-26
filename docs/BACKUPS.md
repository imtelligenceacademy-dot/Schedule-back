# Supabase PostgreSQL backups

Database backups preserve yearly schedules, teacher assignments, users and audit history. CSV/Excel exports are useful reports but are not full backups. Supabase recommends independent exports for Free projects; see [official backup guidance](https://supabase.com/docs/guides/platform/backups).

## Recommended schedule

Take an encrypted, off-site database dump every day that data changes, before migrations, and before archiving an academic year. Retain a practical rotation such as seven daily, four weekly and twelve monthly backups, plus an end-of-year copy. Limit access because a dump includes account password hashes and audit records. Do not commit backups to GitHub or place them in the frontend.

## Make a custom-format dump

Install PostgreSQL client tools of the same major version as Supabase, or newer. Use the **direct** connection where IPv6 is available or Supabase's **session pooler** on port 5432 for IPv4. Do not use the transaction pooler. Obtain the exact host/user from Supabase Connect and use SSL. See [Supabase migration connection options](https://supabase.com/docs/guides/platform/migrating-to-supabase/postgres).

Set the host, username, port and database through `PGHOST`, `PGUSER`, `PGPORT` and `PGDATABASE` in your backup environment; set `PGSSLMODE=require`. Store the password in the operating-system-protected PostgreSQL password file rather than command-line arguments or Git. On Windows, PostgreSQL uses `%APPDATA%\postgresql\pgpass.conf`; on Unix it uses `~/.pgpass` with mode 0600.

Then run:

```bash
pg_dump --format=custom --no-owner --no-privileges --schema=public --file=schedule-YYYY-MM-DD.dump
pg_restore --list schedule-YYYY-MM-DD.dump
```

This application stores its tables and Alembic revision in `public`; Supabase's managed `auth`/storage schemas are not needed for FastAPI authentication. Capture Supabase connection/configuration details separately in secure operational records. Encrypt the dump before uploading to your private backup storage. Confirm the dump command completed successfully; a list check alone is not a restore test.

## Restore drill

1. Create a separate, empty PostgreSQL test database. Do not restore over the live school database.
2. Point the PostgreSQL client environment to that database and run:

```bash
pg_restore --no-owner --no-privileges --single-transaction --clean --if-exists --dbname=postgres schedule-YYYY-MM-DD.dump
```

Use the actual target database name if it differs from `postgres`. **Only use `--clean` against the verified separate restore target**, because it replaces the dumped objects, including the pre-existing `public` schema. Keep credentials out of command history.

3. Configure a separate backend with the restored URL and `APP_ENV=production`, a new random `JWT_SECRET` and its own allowed HTTPS frontend. A new secret invalidates sessions from the backup.
4. Run `python -m alembic upgrade head` to bring the restored schema to the deployed revision.
5. Check school, teacher, assignment, session, year and audit counts against the source. Sign in, inspect archived years, run conflicts and export a filtered schedule.
6. Verify RLS remains enabled. A dump retains RLS definitions, but `--no-privileges` does not preserve privilege revocations. On a new Supabase project, revoke `anon`/`authenticated` access again for application tables, using the statements in `b21890cf50a1_protect_supabase_data_api.py`, or disable its Data API. Do not grant policies that expose app tables to the browser.
7. Document the successful restore date and restore duration. Keep this drill separate from the production site.

For an actual disaster, stop writes, restore into a replacement database, verify it using the drill, switch Render's `DATABASE_URL`, and restart. Preserve the old database and backup until verification is complete. Document the recovery point so staff know whether any sessions must be re-entered.
