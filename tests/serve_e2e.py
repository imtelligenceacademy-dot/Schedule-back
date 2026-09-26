"""Disposable, migrated API instance for Playwright. Never runs in production."""

import os
from pathlib import Path
import sys
import tempfile

backend = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(backend))
os.chdir(backend)
folder = tempfile.TemporaryDirectory(prefix="schedule-e2e-")
os.environ.update(
    APP_ENV="test",
    DATABASE_URL="sqlite:///" + str(Path(folder.name) / "test.db"),
    JWT_SECRET="e2e-test-only-" + "c" * 48,
    FRONTEND_URL="http://127.0.0.1:5174",
    BOOTSTRAP_EMAIL="super@example.com",
    BOOTSTRAP_NAME="Test Super Admin",
    BOOTSTRAP_PASSWORD="E2e-password-2026",
)

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402

command.upgrade(Config(str(backend / "alembic.ini")), "head")

from app.cli import bootstrap  # noqa: E402

bootstrap(demo=True, non_interactive=True)

from app.database import SessionLocal, engine  # noqa: E402
from app.models import User  # noqa: E402
from app.security import hash_password  # noqa: E402
from sqlalchemy import select  # noqa: E402

with SessionLocal() as db:
    db.scalar(select(User)).must_change_password = False
    for role in ["ADMIN", "VIEWER"]:
        db.add(
            User(
                full_name="Test " + role.title(),
                email=role.lower() + "@example.com",
                role=role,
                password_hash=hash_password("E2e-password-2026"),
                must_change_password=False,
            )
        )
    db.commit()

import uvicorn  # noqa: E402

try:
    uvicorn.run("app.main:app", host="127.0.0.1", port=8001)
finally:
    engine.dispose()
    folder.cleanup()
