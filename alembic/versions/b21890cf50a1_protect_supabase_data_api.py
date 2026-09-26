"""Protect app tables from Supabase's browser-facing Data API.

Revision ID: b21890cf50a1
Revises: a49347e291c4
"""

from alembic import op

revision = "b21890cf50a1"
down_revision = "a49347e291c4"
branch_labels = None
depends_on = None

TABLES = (
    "users",
    "schools",
    "teachers",
    "classes",
    "academic_years",
    "teacher_school_assignments",
    "schedule_entries",
    "audit_logs",
    "auth_sessions",
    "login_throttles",
    "alembic_version",
)


def upgrade():
    if op.get_context().dialect.name != "postgresql":
        return
    # The server connects as database owner. No browser-facing policies are created.
    for table in TABLES:
        op.execute(f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY")
        for role in ("anon", "authenticated"):
            op.execute(f"""DO $$ BEGIN
                IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{role}') THEN
                    REVOKE ALL ON TABLE public.{table} FROM {role};
                END IF;
            END $$;""")


def downgrade():
    # Rollbacks never implicitly weaken browser-facing security.
    pass
