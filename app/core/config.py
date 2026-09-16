"""Application configuration, loaded from environment variables / ``.env``."""

from __future__ import annotations

import re
from enum import StrEnum
from functools import lru_cache

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.exceptions import ConfigurationError

_API_VERSION_RE = re.compile(r"^v\d+\.\d+$")


class ProviderName(StrEnum):
    MOCK = "mock"
    META = "meta"


class NotificationName(StrEnum):
    NONE = "none"
    CONSOLE = "console"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore", case_sensitive=False
    )

    # --- Application -------------------------------------------------------
    app_env: str = "development"
    log_level: str = "INFO"
    log_format: str = Field(default="json", pattern="^(json|text)$")

    # --- Database ----------------------------------------------------------
    database_url: str = "postgresql+psycopg://fpm:fpm@localhost:5432/northern_news_monitor"

    # --- Data provider -----------------------------------------------------
    data_provider: ProviderName = ProviderName.MOCK

    meta_access_token: SecretStr | None = None
    meta_api_version: str | None = None
    meta_app_id: str | None = None
    meta_app_secret: SecretStr | None = None
    meta_graph_base_url: str = "https://graph.facebook.com"
    meta_page_size: int = Field(default=100, ge=1, le=100)
    meta_max_pages: int = Field(default=10, ge=1, le=100)

    http_timeout_seconds: float = Field(default=30.0, gt=0)
    provider_max_retries: int = Field(default=3, ge=0, le=10)
    provider_backoff_base_seconds: float = Field(default=2.0, ge=0)
    provider_backoff_max_seconds: float = Field(default=60.0, ge=0)

    # --- Collection --------------------------------------------------------
    fetch_overlap_minutes: int = Field(default=10, ge=0, le=24 * 60)
    initial_lookback_hours: int = Field(default=24, ge=1, le=24 * 30)
    collection_run_stale_minutes: int = Field(default=180, ge=1)
    store_raw_text: bool = False
    remove_urls: bool = False

    # --- Notifications -----------------------------------------------------
    notification_provider: NotificationName = NotificationName.CONSOLE

    # --- API / security ----------------------------------------------------
    internal_api_key: SecretStr | None = None
    cors_allowed_origins: str = ""
    max_request_body_bytes: int = Field(default=1_048_576, ge=1024)
    csv_escape_formulas: bool = True

    # --- News / weather sources ---------------------------------------------
    news_enabled: bool = True
    news_user_agent: str = "northern-news-monitor/0.1 (northern-areas weather news monitor)"
    news_max_response_bytes: int = Field(default=5_000_000, ge=10_000)
    news_summary_chars: int = Field(default=600, ge=0, le=5000)
    weather_snowfall_cm: float = Field(default=2.0, ge=0)
    weather_precipitation_mm: float = Field(default=25.0, ge=0)
    weather_wind_gust_kmh: float = Field(default=60.0, ge=0)
    weather_forecast_days: int = Field(default=3, ge=1, le=7)

    @field_validator("meta_api_version")
    @classmethod
    def _check_api_version(cls, value: str | None) -> str | None:
        if value in (None, ""):
            return None
        if not _API_VERSION_RE.match(value):
            raise ValueError("META_API_VERSION must look like 'v23.0'")
        return value

    @field_validator("meta_access_token", "meta_app_secret", "internal_api_key", mode="before")
    @classmethod
    def _blank_secret_is_none(cls, value: object) -> object:
        return None if value == "" else value

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.cors_allowed_origins.split(",") if o.strip()]

    def secret_values(self) -> list[str]:
        """Raw secret strings, used by the log redaction filter."""
        secrets = [self.meta_access_token, self.meta_app_secret, self.internal_api_key]
        return [s.get_secret_value() for s in secrets if s and s.get_secret_value()]

    def validate_for_provider(self) -> None:
        """Raise :class:`ConfigurationError` listing every missing required variable."""
        missing: list[str] = []
        if not self.database_url:
            missing.append("DATABASE_URL")
        if self.data_provider is ProviderName.META:
            if self.meta_access_token is None:
                missing.append("META_ACCESS_TOKEN")
            if not self.meta_api_version:
                missing.append("META_API_VERSION")
        if missing:
            raise ConfigurationError(
                "Missing required environment variables: " + ", ".join(missing),
                details={"missing": missing, "data_provider": self.data_provider.value},
            )

    def validate_for_api(self) -> None:
        if self.internal_api_key is None:
            raise ConfigurationError(
                "INTERNAL_API_KEY is not set; protected endpoints are disabled.",
                details={"missing": ["INTERNAL_API_KEY"]},
            )


@lru_cache
def get_settings() -> Settings:
    return Settings()
