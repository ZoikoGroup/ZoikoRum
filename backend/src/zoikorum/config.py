"""Runtime configuration. Every value comes from the environment (prefix ZK_)."""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # hide_input_in_errors: a configuration error must never print configuration values (passwords, keys).
    model_config = SettingsConfigDict(env_prefix="ZK_", env_file=".env", extra="ignore", hide_input_in_errors=True)

    env: str = "local"
    service_name: str = "zoikorum-api"
    release: str = "dev"  # build/version identifier, reported with errors
    log_level: str = "INFO"
    log_format: str | None = None  # json | text; default text in local development, json elsewhere
    sentry_dsn: str | None = None  # error reporting (needs backend[monitoring]); personal data is never sent
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
    stripe_secret_key: str | None = None
    stripe_webhook_secret: str | None = None
    stripe_api_version: str | None = None
    payment_operating_countries: list[str] = Field(default_factory=list)
    payment_flow_approved: bool = False  # Explicit partner/business approval of the configured funds flow.
    # fake | simulated | manual | persona | veriff. persona and veriff run the identity check in the partner's hosted flow;
    # simulated (development only) does the same with a page where you pick the partner's answer.
    verification_provider: str = "fake"
    persona_api_key: str | None = None
    persona_template_id: str | None = None
    persona_webhook_secret: str | None = None
    veriff_api_key: str | None = None
    veriff_shared_secret: str | None = None  # signs requests to Veriff and verifies its webhooks
    veriff_base_url: str = "https://stationapi.veriff.com"
    webhook_secret: str = "dev-webhook-secret"
    webhook_tolerance_seconds: int = 300  # signed webhooks older than this are refused (replay protection)
    platform_fee_bps: int = 1000  # 10.00% platform fee, basis points
    payout_settlement_business_days: int = 2  # expected bank arrival after a payout starts (shown to professionals)
    provider_breaker_failures: int = 5  # consecutive provider errors before the circuit opens
    provider_breaker_reset_seconds: int = 30  # how long an open circuit waits before a trial call

    ai_provider: str = "offline"  # offline | anthropic
    trust_completion_half_life_days: int = Field(default=365, ge=1)
    trust_completion_full_credit: int = Field(default=10, ge=1)
    ai_model: str = "claude-opus-5-5"
    anthropic_api_key: str | None = None
    email_provider: str = "console"  # console | smtp
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_starttls: bool = True
    email_from: str = "notifications@zoikorum.com"

    rate_limit_enabled: bool = True
    redis_url: str | None = None  # shared rate limits across API servers, e.g. redis://redis:6379/0
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
    funding_reminder_days: int = 7  # remind the buyer this many days before an unfunded milestone / retainer cycle is due

    # Disputes (Step 9). Direct resolution default is from the Dispute Resolution doc s.10; the evidence window is not
    # stated in the documents (management to confirm).
    dispute_evidence_days: int = 3
    erasure_cooling_off_days: int = 14  # account deletion can be cancelled until then
    data_export_days: int = 7  # how long a data export can be downloaded
    verification_appeal_days: int = 14  # time to appeal a failed or revoked verification (Governance playbook s.11)
    dispute_direct_resolution_business_days: int = 5
    # Days after acceptance in which accepted work may still be disputed. 0 until management sets one (not enforced yet).
    dispute_challenge_window_days: int = 0

    @property
    def mfa_bypass(self) -> bool:
        return self.dev_skip_mfa and self.env in DEV_ENVS

    @model_validator(mode="after")
    def _no_mfa_bypass_outside_development(self):
        if self.dev_skip_mfa and self.env not in (*DEV_ENVS, "test"):
            raise ValueError(f"ZK_DEV_SKIP_MFA is only allowed in development (env is {self.env!r}); remove it")
        if self.verification_provider == "simulated" and self.env not in (*DEV_ENVS, "test"):
            raise ValueError(f"ZK_VERIFICATION_PROVIDER=simulated is only allowed in development (env is {self.env!r})")
        return self

    @model_validator(mode="after")
    def _real_secrets_outside_development(self):
        """Staging and production refuse to start with the development defaults: anyone could forge sign-ins with them."""
        if self.env in (*DEV_ENVS, "test"):
            return self
        defaults = {name: field.default for name, field in type(self).model_fields.items()}
        for name in ("jwt_secret", "field_encryption_key", "webhook_secret"):
            value = getattr(self, name)
            if value == defaults[name] or len(value) < 32:
                raise ValueError(f"ZK_{name.upper()} must be set to a long random value (32+ characters) in {self.env}")
        if not self.frontend_url.startswith("https://"):
            raise ValueError(f"ZK_FRONTEND_URL must be the public https:// address in {self.env} (it is used in email links)")
        return self


DEV_ENVS = ("local", "development")


@lru_cache
def get_settings() -> Settings:
    return Settings()
