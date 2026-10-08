"""Runtime configuration. Every value comes from the environment (prefix ZK_)."""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ZK_", env_file=".env", extra="ignore")

    env: str = "local"
    service_name: str = "zoikorum-api"
    frontend_url: str = "http://localhost:5173"  # used to build links in invitations / emails
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
    stripe_secret_key: str | None = None
    stripe_webhook_secret: str | None = None
    stripe_api_version: str | None = None
    payment_operating_countries: list[str] = Field(default_factory=list)
    payment_flow_approved: bool = False  # Explicit partner/business approval of the configured funds flow.
    verification_provider: str = "fake"  # fake | manual | persona
    persona_api_key: str | None = None
    persona_template_id: str | None = None
    persona_webhook_secret: str | None = None
    webhook_secret: str = "dev-webhook-secret"
    webhook_tolerance_seconds: int = 300  # signed webhooks older than this are refused (replay protection)
    platform_fee_bps: int = 1000  # 10.00% platform fee, basis points
    payout_settlement_business_days: int = 2  # expected bank arrival after a payout starts (shown to professionals)
    provider_breaker_failures: int = 5  # consecutive provider errors before the circuit opens
    provider_breaker_reset_seconds: int = 30  # how long an open circuit waits before a trial call

    ai_provider: str = "offline"  # offline | anthropic
    trust_completion_half_life_days: int = Field(default=365, ge=1)
    trust_completion_full_credit: int = Field(default=10, ge=1)
    ai_model: str = "claude-sonnet-5"
    anthropic_api_key: str | None = None
    email_provider: str = "console"  # console | smtp
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_starttls: bool = True
    email_from: str = "notifications@zoikorum.com"

    rate_limit_enabled: bool = True
    storage_dir: str = "var/storage"  # LocalDiskStorage root (development); S3 bucket in production
    storage_provider: str = "local"  # local | s3
    s3_bucket: str | None = None
    aws_region: str = "us-east-1"
    s3_endpoint_url: str | None = None  # local S3-compatible service; not used for public file access
    s3_kms_key_id: str | None = None
    s3_object_lock_mode: str | None = None  # GOVERNANCE | COMPLIANCE, per the agreed retention policy
    s3_retention_days: int | None = Field(default=None, ge=1)

    # Contracts (Step 7). Platform defaults until enterprise policy profiles can override them.
    signature_deadline_days: int = 7  # unsigned contracts escalate after this
    acceptance_window_days: int = 5  # buyer's review window after a milestone is submitted

    # Disputes (Step 9). Direct resolution default is from the Dispute Resolution doc s.10; the evidence window is not
    # stated in the documents (management to confirm).
    dispute_evidence_days: int = 3
    dispute_direct_resolution_business_days: int = 5


@lru_cache
def get_settings() -> Settings:
    return Settings()
