"""Create ignored development configuration at this backend repository root."""

from pathlib import Path
import secrets

root = Path(__file__).resolve().parents[1]
env = root / ".env"
if env.exists():
    print(".env already exists; left unchanged.")
else:
    folder = root / ".local"
    folder.mkdir(exist_ok=True)
    password = secrets.token_urlsafe(18)
    env.write_text(
        "\n".join(
            [
                "APP_ENV=development",
                "DATABASE_URL=sqlite:///./schedule-dev.db",
                "JWT_SECRET=" + secrets.token_urlsafe(48),
                "FRONTEND_URL=http://127.0.0.1:5173",
                "TIMEZONE=Asia/Beirut",
                "SESSION_HOURS=8",
                "BOOTSTRAP_EMAIL=admin@example.com",
                "BOOTSTRAP_NAME=Development Administrator",
                "BOOTSTRAP_PASSWORD=" + password,
                "",
            ]
        ),
        encoding="utf-8",
    )
    (folder / "development-login.txt").write_text(
        "DEVELOPMENT ONLY\nEmail: admin@example.com\nTemporary password: "
        + password
        + "\nChange this password on first sign-in.\n",
        encoding="utf-8",
    )
    print("Created .env and .local/development-login.txt (both ignored by Git).")
