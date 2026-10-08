"""Runtime configuration. Every value comes from the environment (prefix ZK_)."""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field, model_validator
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
    # Development only: switch off authenticator-app codes (login, step-up, staff MFA) while building features.
    # Active only when env is "local" or "development". Ignored in "test" (tests always use real MFA, even when a
    # developer's .env has it on); the app refuses to start if it is set in any other environment (staging, production).
    dev_skip_mfa: bool = False

    event_bus: str = "inprocess"  # inprocess | kafka
    kafka_bootstrap: str = "localhost:9092"
    outbox_batch_size: int = 100
    consumer_max_attempts: int = 5

    payment_provider: str = "fake"
    webhook_secret: str = "dev-webhook-secret"
    webhook_tolerance_seconds: int = 300  # signed webhooks older than this are refused (replay protection)
    platform_fee_bps: int = 1000  # 10.00% platform fee, basis points
    payout_settlement_business_days: int = 2  # expected bank arrival after a payout starts (shown to professionals)
    provider_breaker_failures: int = 5  # consecutive provider errors before the circuit opens
    provider_breaker_reset_seconds: int = 30  # how long an open circuit waits before a trial call

    ai_provider: str = "offline"  # offline | anthropic
    ai_model: str = "claude-opus-5-5"
    anthropic_api_key: str | None = None

    rate_limit_enabled: bool = True
    storage_dir: str = "var/storage"  # LocalDiskStorage root (development); S3 bucket in production

    # Contracts (Step 7). Platform defaults until enterprise policy profiles can override them.
    signature_deadline_days: int = 7  # unsigned contracts escalate after this
    acceptance_window_days: int = 5  # buyer's review window after a milestone is submitted
    funding_reminder_days: int = 7  # remind the buyer this many days before an unfunded milestone / retainer cycle is due

    # Disputes (Step 9). Direct resolution default is from the Dispute Resolution doc s.10; the evidence window is not
    # stated in the documents (management to confirm).
    dispute_evidence_days: int = 3
    verification_appeal_days: int = 14  # time to appeal a failed or revoked verification (Governance playbook s.11)
    dispute_direct_resolution_business_days: int = 5

    @property
    def mfa_bypass(self) -> bool:
        return self.dev_skip_mfa and self.env in DEV_ENVS

    @model_validator(mode="after")
    def _no_mfa_bypass_outside_development(self):
        if self.dev_skip_mfa and self.env not in (*DEV_ENVS, "test"):
            raise ValueError(f"ZK_DEV_SKIP_MFA is only allowed in development (env is {self.env!r}); remove it")
        return self


DEV_ENVS = ("local", "development")


@lru_cache
def get_settings() -> Settings:
    return Settings()
