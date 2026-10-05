"""Runtime configuration. Every value comes from the environment (prefix ZK_)."""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ZK_", env_file=".env", extra="ignore")

    env: str = "local"
    service_name: str = "zoikorum-api"
    database_url: str = "postgresql+asyncpg://zoikorum:zoikorum@localhost:5434/zoikorum"
    db_pool_size: int = 10

    jwt_secret: str = Field(default="dev-only-secret-change-me-32-bytes-minimum!!")
    field_encryption_key: str = Field(default="dev-only-field-key-change-me")
    jwt_issuer: str = "zoikorum"
    access_token_ttl_seconds: int = 900
    refresh_token_ttl_seconds: int = 14 * 24 * 3600
    step_up_max_age_seconds: int = 300

    event_bus: str = "inprocess"  # inprocess | kafka
    kafka_bootstrap: str = "localhost:9092"
    outbox_batch_size: int = 100
    consumer_max_attempts: int = 5

    payment_provider: str = "fake"
    webhook_secret: str = "dev-webhook-secret"
    platform_fee_bps: int = 1000  # 10.00% platform fee, basis points

    ai_provider: str = "offline"  # offline | anthropic
    ai_model: str = "claude-sonnet-5"
    anthropic_api_key: str | None = None

    rate_limit_enabled: bool = True


@lru_cache
def get_settings() -> Settings:
    return Settings()
