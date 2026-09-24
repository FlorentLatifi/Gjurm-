"""Application configuration.

All configuration comes from environment variables (12-factor). ``Settings.validate_for_env``
enforces production invariants so that a mis-configured deployment fails at startup instead of
running insecurely.
"""

from __future__ import annotations

from enum import StrEnum
from functools import lru_cache
from typing import Annotated, Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Environment(StrEnum):
    DEVELOPMENT = "development"
    TEST = "test"
    STAGING = "staging"
    PRODUCTION = "production"


class ConfigError(RuntimeError):
    """Raised when configuration is unsafe for the current environment."""


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- general ---------------------------------------------------------------------------
    gjurme_env: Environment = Environment.DEVELOPMENT
    log_level: str = "INFO"
    log_format: Literal["json", "text"] = "json"
    public_base_url: str = "http://localhost:5173"
    contact_url: str = "https://github.com/FlorentLatifi/Gjurm-"
    timezone: str = "Europe/Tirane"

    # --- database --------------------------------------------------------------------------
    database_url: str = "postgresql+psycopg://gjurme:gjurme@localhost:5432/gjurme"
    db_pool_size: int = Field(default=5, ge=1, le=50)
    db_max_overflow: int = Field(default=5, ge=0, le=50)
    db_statement_timeout_ms: int = Field(default=15_000, ge=100)

    # --- ingestion -------------------------------------------------------------------------
    http_timeout_seconds: float = Field(default=15.0, gt=0)
    http_max_bytes: int = Field(default=5_000_000, gt=0)
    http_user_agent: str = (
        "GjurmeBot/1.0 (+https://github.com/FlorentLatifi/Gjurm-; news-intelligence; RSS only)"
    )
    fetch_concurrency: int = Field(default=4, ge=1, le=16)
    respect_robots_txt: bool = True
    source_failure_disable_threshold: int = Field(default=20, ge=1)
    max_item_age_days: int = Field(default=14, ge=1)
    excerpt_max_chars: int = Field(default=1200, ge=100)

    # --- enrichment / LLM ------------------------------------------------------------------
    llm_provider: Literal["anthropic", "fake"] = "anthropic"
    llm_model: str = "claude-sonnet-5"
    anthropic_api_key: SecretStr | None = None
    # Explicit so an ambient ANTHROPIC_BASE_URL can never silently redirect production traffic.
    anthropic_base_url: str = "https://api.anthropic.com"
    llm_timeout_seconds: float = Field(default=60.0, gt=0)
    llm_sdk_max_retries: int = Field(default=2, ge=0, le=5)
    llm_max_output_tokens: int = Field(default=1500, ge=256)
    llm_daily_budget_usd: float = Field(default=2.0, ge=0)
    enrich_max_per_run: int = Field(default=150, ge=0)
    enrich_concurrency: int = Field(default=4, ge=1, le=16)
    enrich_max_attempts: int = Field(default=3, ge=1, le=10)
    enrich_circuit_breaker_threshold: int = Field(default=5, ge=1)
    enrichment_enabled: bool = True
    allow_fake_llm_in_production: bool = False

    # --- scheduler -------------------------------------------------------------------------
    scheduler_interval_minutes: int = Field(default=15, ge=1)
    retention_raw_payload_days: int = Field(default=30, ge=1)
    retention_excerpt_days: int = Field(default=90, ge=1)

    # --- API -------------------------------------------------------------------------------
    admin_api_token: SecretStr | None = None
    cors_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:5173"]
    )
    rate_limit_per_minute: int = Field(default=120, ge=1)
    rate_limit_search_per_minute: int = Field(default=30, ge=1)
    api_cache_ttl_seconds: int = Field(default=120, ge=0)
    trust_proxy_headers: bool = False
    expose_docs: bool = True

    # --- alerting --------------------------------------------------------------------------
    alert_webhook_url: SecretStr | None = None
    alert_webhook_format: Literal["slack", "discord", "ntfy", "generic"] = "generic"
    alert_dedup_hours: int = Field(default=6, ge=0)
    alert_stale_pipeline_minutes: int = Field(default=120, ge=5)

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    @property
    def is_production(self) -> bool:
        return self.gjurme_env == Environment.PRODUCTION

    @property
    def is_deployed(self) -> bool:
        return self.gjurme_env in (Environment.STAGING, Environment.PRODUCTION)

    def validate_for_env(self) -> None:
        """Fail fast on configuration that is unsafe for a deployed environment."""
        if not self.is_deployed:
            return
        problems: list[str] = []
        token = self.admin_api_token.get_secret_value() if self.admin_api_token else ""
        if len(token) < 32:
            problems.append("ADMIN_API_TOKEN must be set and at least 32 characters")
        if "*" in self.cors_origins:
            problems.append("CORS_ORIGINS must not contain '*' in a deployed environment")
        if self.llm_provider == "fake" and not self.allow_fake_llm_in_production:
            problems.append("LLM_PROVIDER=fake is not allowed in a deployed environment")
        if "gjurme:gjurme@" in self.database_url:
            problems.append("DATABASE_URL uses the default development password")
        if problems:
            raise ConfigError("Unsafe configuration: " + "; ".join(problems))


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
