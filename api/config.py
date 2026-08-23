"""Environment-backed configuration for the hosted API."""

from __future__ import annotations

from dataclasses import dataclass
import os


def _csv(name: str, default: str) -> tuple[str, ...]:
    return tuple(
        value.strip().rstrip("/")
        for value in os.environ.get(name, default).split(",")
        if value.strip()
    )


@dataclass(frozen=True)
class Settings:
    environment: str = os.environ.get("JARVIS_ENV", "development").lower()
    database_url: str = os.environ.get(
        "DATABASE_URL",
        "sqlite:///./tmp/jarvis_web.db",
    )
    redis_url: str = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
    jwt_secret: str = os.environ.get("JWT_SECRET", "local-development-only-change-me")
    encryption_key: str = os.environ.get("JARVIS_ENCRYPTION_KEY", "")
    access_token_minutes: int = int(os.environ.get("ACCESS_TOKEN_MINUTES", "1440"))
    cors_origins: tuple[str, ...] = _csv(
        "CORS_ORIGINS",
        "http://localhost:3000,http://127.0.0.1:3000",
    )
    chat_model: str = os.environ.get("JARVIS_CHAT_MODEL", "gemini-2.5-flash")
    auto_create_tables: bool = os.environ.get("AUTO_CREATE_TABLES", "1").lower() in {
        "1", "true", "yes", "on",
    }
    redis_required: bool = os.environ.get("REDIS_REQUIRED", "0").lower() in {
        "1", "true", "yes", "on",
    }

    def validate_production(self) -> None:
        if self.environment != "production":
            return
        if self.jwt_secret == "local-development-only-change-me":
            raise RuntimeError("JWT_SECRET must be configured in production")
        if not self.encryption_key:
            raise RuntimeError("JARVIS_ENCRYPTION_KEY must be configured in production")
        if not self.database_url.startswith(("postgresql://", "postgres://", "postgresql+")):
            raise RuntimeError("Production DATABASE_URL must point to Postgres")


settings = Settings()
