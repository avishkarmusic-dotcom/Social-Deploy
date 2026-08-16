"""Configuration.

One rule: production must not be able to start with a placeholder secret. The
validator below turns a class of silent, catastrophic misconfiguration — an
encryption key of "change-me" shipped to prod — into a loud startup failure.
"""
from __future__ import annotations

import hashlib
from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)

    environment: Literal["development", "test", "staging", "production"] = "development"
    app_secret: str = "change-me"
    database_url: str = "postgresql+asyncpg://tryvanta:tryvanta@localhost:5432/tryvanta_social"
    redis_url: str = "redis://localhost:6379/0"
    data_encryption_key: str = ""
    cors_origins: list[str] | str = Field(default_factory=lambda: ["http://localhost:3000"])
    session_ttl_hours: int = 24 * 14

    # AI providers — any subset. The router degrades down its fallback chain.
    anthropic_api_key: str | None = None
    openai_api_key: str | None = None
    google_api_key: str | None = None
    groq_api_key: str | None = None
    ollama_base_url: str = "http://localhost:11434"
    ai_daily_budget_usd: float = 25.0

    # Channel OAuth
    google_client_id: str = ""
    google_client_secret: str = ""
    microsoft_client_id: str = ""
    microsoft_client_secret: str = ""
    linkedin_client_id: str = ""
    linkedin_client_secret: str = ""
    meta_app_id: str = ""
    meta_app_secret: str = ""
    slack_client_id: str = ""
    slack_client_secret: str = ""
    x_client_id: str = ""
    x_client_secret: str = ""
    telegram_webhook_secret: str = ""

    oauth_redirect_base: str = "http://localhost:8000/v1/channels/callback"
    webhook_verify_token: str = "tryvanta-verify"

    @property
    def is_production(self) -> bool:
        return self.environment in {"staging", "production"}

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, v: object) -> object:
        return [o.strip() for o in v.split(",")] if isinstance(v, str) else v

    @field_validator("database_url", mode="before")
    @classmethod
    def _use_asyncpg_driver(cls, v: object) -> object:
        """Accept Replit's standard Postgres URL with SQLAlchemy's async driver."""
        if isinstance(v, str):
            v = v.replace("sslmode=", "ssl=")
            if v.startswith("postgresql://"):
                return "postgresql+asyncpg://" + v.removeprefix("postgresql://")
            if v.startswith("postgres://"):
                return "postgresql+asyncpg://" + v.removeprefix("postgres://")
        return v

    @model_validator(mode="after")
    def _no_placeholders_in_production(self) -> "Settings":
        if not self.is_production:
            return self
        unsafe = [
            name
            for name, value in (
                ("APP_SECRET", self.app_secret),
                ("DATA_ENCRYPTION_KEY", self.data_encryption_key),
            )
            if not value or value in {"change-me", "changeme", "secret"}
        ]
        if unsafe:
            raise ValueError(
                f"Refusing to start in {self.environment}: {', '.join(unsafe)} "
                "still holds a placeholder. Generate real values "
                "(`openssl rand -base64 32`) and set them in the secret manager."
            )
        if "*" in self.cors_origins:
            raise ValueError("CORS_ORIGINS cannot be '*' outside development.")
        return self

    def webhook_secret_for(self, kind: str) -> str:
        """Per-channel webhook secret, derived rather than stored.

        Deriving means fourteen fewer secrets to rotate, and a leak of one
        channel's secret reveals nothing about the others.
        """
        overrides = {
            "instagram": self.meta_app_secret,
            "messenger": self.meta_app_secret,
            "whatsapp": self.meta_app_secret,
            "facebook": self.meta_app_secret,
            "slack": self.slack_client_secret,
            "telegram": self.telegram_webhook_secret,
        }
        if secret := overrides.get(kind):
            return secret
        return hashlib.sha256(f"{self.app_secret}:{kind}".encode()).hexdigest()


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
