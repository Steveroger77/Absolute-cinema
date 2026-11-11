"""Typed application settings loaded from environment variables."""

from __future__ import annotations

import secrets
from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_DIR = Path(__file__).resolve().parents[2]
DEFAULT_SQLITE_URL = f"sqlite:///{(ROOT_DIR / 'backend' / 'cinema_dev.db').as_posix()}"


def normalize_database_url(url: str) -> str:
    """Convert Render/Heroku postgres:// or plain postgresql:// URLs to SQLAlchemy psycopg3 dialect."""
    raw = (url or "").strip()
    if raw.startswith("postgres://"):
        return "postgresql+psycopg://" + raw[len("postgres://") :]
    if raw.startswith("postgresql://"):
        return "postgresql+psycopg://" + raw[len("postgresql://") :]
    return raw


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(ROOT_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: str = Field(
        default="development",
        validation_alias=AliasChoices("APP_ENV", "ENV"),
    )
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    database_url: str = Field(default=DEFAULT_SQLITE_URL, alias="DATABASE_URL")

    jwt_secret_key: str = Field(
        default_factory=lambda: secrets.token_urlsafe(48),
        validation_alias=AliasChoices("JWT_SECRET_KEY", "SECRET_KEY"),
    )
    jwt_refresh_secret_key: str = Field(
        default_factory=lambda: secrets.token_urlsafe(48),
        alias="JWT_REFRESH_SECRET_KEY",
    )
    access_token_expire_minutes: int = Field(default=15, alias="ACCESS_TOKEN_EXPIRE_MINUTES")
    refresh_token_expire_days: int = Field(default=7, alias="REFRESH_TOKEN_EXPIRE_DAYS")

    cookie_secure: bool = Field(default=False, alias="COOKIE_SECURE")
    cookie_samesite: str = Field(default="lax", alias="COOKIE_SAMESITE")
    cors_origins: str = Field(
        default="http://localhost:5173,http://127.0.0.1:5173,http://localhost:8080",
        validation_alias=AliasChoices("CORS_ORIGINS", "ALLOWED_ORIGINS"),
    )
    frontend_url: str = Field(default="", alias="FRONTEND_URL")

    model_artifacts_dir: str = Field(default=str(ROOT_DIR / "ml" / "artifacts"), alias="MODEL_ARTIFACTS_DIR")
    processed_data_dir: str = Field(
        default=str(ROOT_DIR / "ml" / "data" / "processed"), alias="PROCESSED_DATA_DIR"
    )
    admin_email: str = Field(default="curator@absolutecinema.org", alias="ADMIN_EMAIL")
    admin_password: str = Field(default="", alias="ADMIN_PASSWORD")
    google_client_id: str = Field(default="", alias="GOOGLE_CLIENT_ID")

    @field_validator("cookie_samesite")
    @classmethod
    def validate_samesite(cls, v: str) -> str:
        low = v.strip().lower()
        if low not in {"lax", "strict", "none"}:
            raise ValueError("COOKIE_SAMESITE must be one of lax, strict, none")
        return low

    @property
    def normalized_database_url(self) -> str:
        return normalize_database_url(self.database_url)

    @property
    def cors_origin_list(self) -> list[str]:
        origins = [o.strip().rstrip("/") for o in self.cors_origins.split(",") if o.strip()]
        fe = self.frontend_url.strip().rstrip("/")
        if fe and fe not in origins:
            origins.append(fe)
        return origins

    @property
    def is_production(self) -> bool:
        return self.app_env.strip().lower() == "production"

    def validate_runtime_security(self) -> None:
        if self.is_production:
            for key_name, val in [
                ("JWT_SECRET_KEY", self.jwt_secret_key),
                ("JWT_REFRESH_SECRET_KEY", self.jwt_refresh_secret_key),
            ]:
                if len(val) < 32 or any(
                    tok in val for tok in ("replace_with", "change_me", "dev-access", "dev-refresh")
                ):
                    raise RuntimeError(
                        f"Unsafe {key_name} in production. Provide >= 32 random chars via environment."
                    )
            if self.jwt_secret_key == self.jwt_refresh_secret_key:
                raise RuntimeError("JWT_SECRET_KEY and JWT_REFRESH_SECRET_KEY must be distinct.")
            if "*" in self.cors_origin_list:
                raise RuntimeError(
                    "Wildcard '*' in CORS_ORIGINS / ALLOWED_ORIGINS is disallowed in production."
                )
            if self.cookie_samesite == "none" and not self.cookie_secure:
                raise RuntimeError("COOKIE_SAMESITE=none requires COOKIE_SECURE=true in production.")


@lru_cache
def get_settings() -> Settings:
    return Settings()
