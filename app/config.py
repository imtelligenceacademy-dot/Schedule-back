from functools import lru_cache
from zoneinfo import ZoneInfo

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    app_env: str = "development"
    database_url: str
    jwt_secret: str
    frontend_url: str = "http://127.0.0.1:5173"
    timezone: str = "Asia/Beirut"
    session_hours: int = 8
    bootstrap_email: str = ""
    bootstrap_name: str = ""
    bootstrap_password: str = ""

    @model_validator(mode="after")
    def validate_runtime(self):
        if self.app_env not in {"development", "test", "production"}:
            raise ValueError("APP_ENV must be development, test or production")
        if len(self.jwt_secret) < 32 or self.jwt_secret.startswith("replace-"):
            raise ValueError("Set JWT_SECRET to a random secret of at least 32 characters")
        if not 1 <= self.session_hours <= 24:
            raise ValueError("SESSION_HOURS must be between 1 and 24")
        ZoneInfo(self.timezone)
        if self.production:
            if not self.database_url.startswith(("postgres://", "postgresql://", "postgresql+psycopg://")):
                raise ValueError("Production requires PostgreSQL. SQLite is development/test only.")
            if not self.origins or any(not origin.startswith("https://") for origin in self.origins):
                raise ValueError("Production FRONTEND_URL must use HTTPS")
        return self

    @property
    def production(self):
        return self.app_env == "production"

    @property
    def origins(self):
        return [origin.strip().rstrip("/") for origin in self.frontend_url.split(",")]

    @property
    def sqlalchemy_url(self):
        url = self.database_url
        if url.startswith("postgres://"):
            return url.replace("postgres://", "postgresql+psycopg://", 1)
        if url.startswith("postgresql://"):
            return url.replace("postgresql://", "postgresql+psycopg://", 1)
        return url


@lru_cache
def get_settings():
    return Settings()
