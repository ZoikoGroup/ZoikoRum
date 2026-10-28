"""Runtime configuration. Every value comes from the environment (prefix ZK_)."""

from __future__ import annotations

import os
from functools import lru_cache

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # hide_input_in_errors: a configuration error must never print configuration values (passwords, keys).
    # env_ignore_empty: a blank line in an env file (ZK_SMTP_HOST=) means "use the default", as the templates show.
    model_config = SettingsConfigDict(env_prefix="ZK_", env_file=".env", extra="ignore", hide_input_in_errors=True,
                                      env_ignore_empty=True)

    env: str = "local"
    service_name: str = "zoikorum-api"
    release: str = "dev"  # build/version identifier, reported with errors
    log_level: str = "INFO"
    log_format: str | None = None  # json | text; default text in local development, json elsewhere
    sentry_dsn: str | None = None  # error reporting (needs backend[monitoring]); personal data is never sent
    tracing_endpoint: str | None = None  # OpenTelemetry collector (OTLP/HTTP traces URL); needs backend[tracing]
    tracing_sample_ratio: float = Field(default=0.1, ge=0, le=1)  # share of new traces kept
    # Requests whose path starts with one of these are always traced in full, whatever the ratio (money and legal flows).
    tracing_always_sample_paths: list[str] = Field(default_factory=lambda: [
        "/v1/payments", "/v1/payout-accounts", "/v1/escrow", "/v1/contracts", "/v1/milestones", "/v1/change-orders",
        "/v1/disputes", "/v1/resolution-proposals"])
    frontend_url: str = "http://localhost:5173"  # used to build links in invitations / emails
    # The API's public address, where identity providers post SAML sign-ins (<this>/v1/auth/saml/acs). Empty: frontend_url
    # (the web app's address forwards /v1 to the API).
    public_api_url: str | None = None
    # Sign in with Google / Microsoft (OpenID Connect apps registered with each; empty: the button is not shown).
    google_client_id: str | None = None
    # Browser push notifications (Web Push): a VAPID key pair (python -m zoikorum.cli new-push-keys) and a contact address.
    vapid_public_key: str | None = None
    vapid_private_key: str | None = None
    vapid_subject: str = "mailto:security@example.com"
    google_client_secret: str | None = None
    microsoft_client_id: str | None = None
    microsoft_client_secret: str | None = None
    # The separate staff web app (frontend VITE_PORTAL=staff). Links in emails to staff use it; empty: frontend_url.
    staff_frontend_url: str | None = None
    # Passkeys: the WebAuthn relying party (a domain). Empty: the web app's host name. With separate customer and staff
    # apps (app.your-domain.com, staff.your-domain.com) set their shared parent domain: your-domain.com.
    webauthn_rp_id: str | None = None
    database_url: str = "postgresql+asyncpg://zoikorum:zoikorum@localhost:5434/zoikorum"
    db_pool_size: int = 10
    # Separate analytics store (optional): reports and dashboards read from this database, normally a read replica of
    # the main one, so heavy reporting never slows down the platform. Empty: they read the main database.
    analytics_database_url: str | None = None
    # Production: two database users. Migrations run as the owner (ZK_MIGRATION_DATABASE_URL); the API and worker use
    # ZK_DATABASE_URL as ZK_DB_APP_ROLE, which may add to append-only tables (audit trail, ledger, evidence, signatures)
    # but never change or delete them, and cannot switch their protective triggers off (cli db-grants).
    migration_database_url: str | None = None
    db_app_role: str | None = None

    jwt_secret: str = Field(default="dev-only-secret-change-me-32-bytes-minimum!!")
    field_encryption_key: str = Field(default="dev-only-field-key-change-me")
    # Envelope encryption (production): data keys wrapped by a Cloud KMS key; only KMS can unwrap them.
    # field_data_keys = {"<key id>": "<wrapped key, base64>"} (python -m zoikorum.cli new-field-key makes one);
    # field_active_key is the id new values are encrypted with. Older ids stay listed so existing values decrypt.
    field_kms_key_name: str | None = None  # projects/<p>/locations/<l>/keyRings/<r>/cryptoKeys/<k>
    field_data_keys: dict[str, str] = Field(default_factory=dict)
    field_active_key: str | None = None
    jwt_issuer: str = "zoikorum"
    # Access/purpose token signing (identity/tokens.py, shared/signing_keys.py). hs256: the shared ZK_JWT_SECRET (default,
    # for existing deployments). rs256: an RSA key whose public half is published at /.well-known/jwks.json.
    # Keys: jwt_private_keys {"<kid>": "<PEM private key>"} with jwt_active_kid signing new tokens; rotate by adding a key,
    # switching the active kid, and moving the old one to jwt_public_keys {"<kid>": "<PEM public key>"} until its tokens
    # expire. Or jwt_kms_key_name: a Cloud KMS asymmetric signing key version (RSA_SIGN_PKCS1_2048_SHA256), which never
    # leaves KMS. jwt_accept_hs256: while switching to rs256, tokens signed with ZK_JWT_SECRET are still accepted.
    jwt_signing: str = Field(default="hs256", pattern="^(hs256|rs256)$")
    jwt_private_keys: dict[str, str] = Field(default_factory=dict)
    jwt_active_kid: str | None = None
    jwt_public_keys: dict[str, str] = Field(default_factory=dict)
    jwt_kms_key_name: str | None = None  # projects/<p>/locations/<l>/keyRings/<r>/cryptoKeys/<k>/cryptoKeyVersions/<n>
    jwt_accept_hs256: bool = True
    # Advisory sign-in risk signals (identity/risk.py): never block a sign-in, they are recorded and shown.
    sign_in_velocity_per_hour: int = Field(default=10, ge=1)  # more sign-ins than this to one account in an hour
    sign_in_max_travel_kmh: int = Field(default=900, ge=100)  # faster than an airliner between two sign-ins
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
    # GET /metrics (Prometheus) needs "Authorization: Bearer <this>"; empty: the page does not exist.
    metrics_token: str | None = None
    # Daily clean-up of bookkeeping rows (shared/housekeeping.py): replayed-request records, and events every consumer
    # has handled. Business records, audit and the money ledger are never touched.
    idempotency_retention_days: int = Field(default=30, ge=1)
    event_retention_days: int = Field(default=30, ge=7)

    ai_provider: str = "offline"  # offline | anthropic
    trust_completion_half_life_days: int = Field(default=365, ge=1)
    trust_completion_full_credit: int = Field(default=10, ge=1)
    ai_model: str = "claude-opus-5-5"
    # Built-in prompts switched off without a release (their feature uses its non-AI rules): any of search-intent,
    # document-check, spec-match (ai/claude.py BUILT_IN).
    ai_disabled_prompts: list[str] = Field(default_factory=list)
    anthropic_api_key: str | None = None
    email_provider: str = "console"  # console | smtp
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_starttls: bool = True
    email_from: str = "notifications@zoikorum.com"

    rate_limit_enabled: bool = True
    redis_url: str | None = None  # shared rate limits and read cache across API servers, e.g. redis://redis:6379/0
    # Read cache (shared/cache.py) for taxonomy, trust tiers, policy profiles, search facets. Redis when ZK_REDIS_URL is
    # set, else per process; if Redis fails the cache falls back to the database, never to an error.
    cache_enabled: bool = True
    cache_ttl_seconds: int = Field(default=300, ge=1, le=86_400)
    # Evidence retention (shared/storage.py): days to keep each evidence type, per jurisdiction (country) with a
    # "default", e.g. {"verification_document": {"default": 2555, "DE": 1825}, "data_export": {"default": 30}}. A type
    # not listed is never purged. The daily purge only reports until retention_purge_enabled is on, and never touches a
    # file under legal hold. Report: python -m zoikorum.cli retention-report
    retention_rules: dict[str, dict[str, int]] = Field(default_factory=dict)
    retention_purge_enabled: bool = False
    storage_dir: str = "var/storage"  # LocalDiskStorage root (development); S3 bucket in production
    storage_provider: str = "local"  # local | database (files in PostgreSQL) | r2 (Cloudflare R2, free tier) | gcs (Google Cloud Storage) | s3 (Amazon S3)
    r2_bucket: str | None = None  # Cloudflare R2 bucket (private; 10 GB free, no egress fees)
    r2_account_id: str | None = None  # builds https://<account>.r2.cloudflarestorage.com
    r2_endpoint_url: str | None = None  # overrides the account-based endpoint (e.g. an EU jurisdiction endpoint)
    gcs_bucket: str | None = None  # Google Cloud Storage bucket (object versioning on, public access prevented)
    malware_scanner: str = "none"  # clamav (production) | none (development only): every upload is scanned first
    clamav_host: str = "clamav"
    clamav_port: int = 3310
    # Optional customer-managed encryption key: projects/<p>/locations/<l>/keyRings/<r>/cryptoKeys/<k>
    gcs_kms_key_name: str | None = None
    s3_bucket: str | None = None
    aws_region: str = "us-east-1"
    s3_endpoint_url: str | None = None  # local S3-compatible service; not used for public file access
    s3_kms_key_id: str | None = None
    s3_object_lock_mode: str | None = None  # GOVERNANCE | COMPLIANCE, per the agreed retention policy
    s3_retention_days: int | None = Field(default=None, ge=1)

    # Contracts (Step 7). Platform defaults until enterprise policy profiles can override them.
    signature_deadline_days: int = 7  # unsigned contracts escalate after this
    request_response_hours: int = 72  # professionals are asked to answer a request within this; reminded a day before
    termination_response_days: int = 7  # a request to end an engagement by agreement lapses if not answered
    # Meetings in conversations: a link is generated here when the person does not paste their own (Zoom, Teams, Meet).
    # A self-hosted Jitsi address works too. Empty: people always paste their own link.
    meeting_base_url: str = "https://meet.jit.si/"
    max_professionals_per_request: int = 5  # one requirement sent to several chosen professionals at once (at most 10)
    acceptance_window_days: int = 5  # buyer's review window after a milestone is submitted
    # Accepted work whose payment release the buyer's approver refused (or let expire) is never left alone: every this
    # many days the organisation's approvers and admins and the professional are reminded, and either side can take it to
    # a payment-release dispute.
    release_block_escalation_days: int = 5
    funding_reminder_days: int = 7  # remind the buyer this many days before an unfunded milestone / retainer cycle is due
    # A signed engagement whose escrow was never funded this many days after activation expires: its allocations end as
    # EXPIRED and the engagement is terminated (nothing was ever paid in, so nothing moves).
    funding_expiry_days: int = Field(default=30, ge=1, le=365)

    # Disputes (Step 9). Direct resolution default is from the Dispute Resolution doc s.10; the evidence window is not
    # stated in the documents (management to confirm).
    dispute_evidence_days: int = 3
    dispute_retention_years: int = 7  # closed dispute records are kept at least this long (longer where policy or law says)
    erasure_cooling_off_days: int = 14  # account deletion can be cancelled until then
    data_export_days: int = 7  # how long a data export can be downloaded
    # Ethics code: no approval without human oversight. This share (0-100) of checks a partner approved automatically
    # gets a compliance officer's second look (confirm, or overturn with a reason).
    verification_second_look_pct: int = Field(default=10, ge=0, le=100)
    verification_appeal_days: int = 14
    enforcement_triage_hours: int = 48  # a new safety case is looked at within this (overdue cases show first)
    enforcement_appeal_days: int = 14  # time to appeal an enforcement action after it is applied
    enforcement_policy_version: str = "trust-safety-playbook@2026.1"  # recorded with every enforcement decision  # time to appeal a failed or revoked verification (Governance playbook s.11)
    # Maker-checker: a privileged staff request (role grants, switches, money exceptions, audit exports) waits this long
    # for a second person to approve it, then expires unused.
    approval_expiry_hours: int = Field(default=24, ge=1, le=168)
    dispute_direct_resolution_business_days: int = 5
    # Message abuse detection (messaging/abuse.py): extra terms on top of the built-in lists. Advisory flags only.
    messaging_abuse_terms: list[str] = Field(default_factory=list)
    messaging_circumvention_terms: list[str] = Field(default_factory=list)
    # Invoice tax by the buyer's country (their contracting legal entity, else the organisation). Amounts are tax-inclusive:
    # the invoice shows "of which <label> <rate>%" and the money moved does not change. Finance sets the rules, e.g.
    # {"IN": {"label": "GST", "rateBps": 1800, "basis": "FEE"}, "GB": {"label": "VAT", "rateBps": 2000, "basis": "TOTAL"}}
    # basis FEE: tax on Zoikorum's platform fee only; TOTAL: on the whole amount. Empty: invoices show no tax.
    tax_rules: dict[str, dict] = Field(default_factory=dict)
    # Spend limits in another currency: units of each currency per 1 USD, set by Finance, e.g. {"USD": 1, "EUR": 0.92}.
    # The converted amount gets this safety margin (basis points) and is rounded up. Empty: a limit in another currency
    # does not authorise the amount.
    fx_rates: dict[str, float] = Field(default_factory=dict)
    fx_margin_bps: int = Field(default=300, ge=0, le=5_000)
    # Days after acceptance in which accepted work may still be disputed. Its payment is held until the window ends, so
    # a defect found after acceptance can still be put right. 0: paid out at acceptance (an organisation's policy may set
    # its own window).
    dispute_challenge_window_days: int = Field(default=0, ge=0, le=90)

    @property
    def mfa_bypass(self) -> bool:
        return self.dev_skip_mfa and self.env in DEV_ENVS

    @model_validator(mode="after")
    def _environment_named(self):
        """Blank settings use their defaults, except the environment: a blank ZK_ENV (e.g. a secret that failed to load)
        would otherwise switch off every production safeguard by meaning "local"."""
        if os.environ.get("ZK_ENV") is not None and not os.environ["ZK_ENV"].strip():
            raise ValueError("ZK_ENV is set but blank; name the environment (local, staging or production)")
        return self

    @model_validator(mode="after")
    def _no_mfa_bypass_outside_development(self):
        if self.dev_skip_mfa and self.env not in (*DEV_ENVS, "test"):
            raise ValueError(f"ZK_DEV_SKIP_MFA is only allowed in development (env is {self.env!r}); remove it")
        if self.verification_provider == "simulated" and self.env not in (*DEV_ENVS, "test"):
            raise ValueError(f"ZK_VERIFICATION_PROVIDER=simulated is only allowed in development (env is {self.env!r})")
        return self

    @model_validator(mode="after")
    def _signing_keys_named(self):
        """rs256 needs a key to sign with: a KMS key, or an active kid that is in jwt_private_keys (development and tests
        may run without one: a temporary key is made per process)."""
        if self.jwt_signing != "rs256" or self.jwt_kms_key_name:
            return self
        if self.jwt_active_kid and self.jwt_active_kid not in self.jwt_private_keys:
            raise ValueError("ZK_JWT_ACTIVE_KID must name one of the keys in ZK_JWT_PRIVATE_KEYS")
        if self.env not in (*DEV_ENVS, "test") and not self.jwt_active_kid:
            raise ValueError(f"ZK_JWT_SIGNING=rs256 needs ZK_JWT_KMS_KEY_NAME or ZK_JWT_PRIVATE_KEYS with ZK_JWT_ACTIVE_KID in {self.env}")
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
        if self.staff_frontend_url and not self.staff_frontend_url.startswith("https://"):
            raise ValueError(f"ZK_STAFF_FRONTEND_URL must be an https:// address in {self.env}")
        return self


DEV_ENVS = ("local", "development")


@lru_cache
def get_settings() -> Settings:
    return Settings()


def web_url(staff: bool = False) -> str:
    """The web app address for links: the staff app for staff (ZK_STAFF_FRONTEND_URL), otherwise ZK_FRONTEND_URL."""
    s = get_settings()
    return ((s.staff_frontend_url if staff else None) or s.frontend_url).rstrip("/")
