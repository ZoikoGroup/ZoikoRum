from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import ARRAY, BigInteger, Boolean, DateTime, Float, ForeignKey, Integer, LargeBinary, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import ARRAY as PG_ARRAY, JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from zoikorum.shared.db import Base, CreatedAt, Timestamps, UUIDPk, Versioned

SCHEMA = "identity"


class Identity(Base, UUIDPk, Timestamps, Versioned):
    """Aggregate root: one ZoikoID per human or service actor."""

    __tablename__ = "identities"
    __table_args__ = {"schema": SCHEMA}

    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False)
    email_confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    confirmation_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # last "resend the link"
    password_hash: Mapped[str | None] = mapped_column(String(255))
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    country: Mapped[str] = mapped_column(String(2), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="ACTIVE")  # ACTIVE|SUSPENDED|DELETED
    platform_roles: Mapped[list[str]] = mapped_column(ARRAY(String(50)), nullable=False, default=list)
    # Just-in-time staff roles: {role: ISO end time}. A role listed here stops counting at that time and is then removed
    # (identity/handlers.py); roles not listed are permanent until revoked.
    platform_role_expiry: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict, server_default="{}")
    # Marketplace account roles (shared.auth.Persona) - BUYER, PROFESSIONAL, FIRM_ADMIN, ENTERPRISE_ADMIN.
    personas: Mapped[list[str]] = mapped_column(ARRAY(String(30)), nullable=False, default=list)
    primary_persona: Mapped[str | None] = mapped_column(String(30))
    # Organization name captured at Firm/Enterprise signup. The firm/buyer domains create the
    # organization itself from the IDENTITY_CREATED event (next build step).
    signup_organization_name: Mapped[str | None] = mapped_column(String(200))
    mfa_secret_enc: Mapped[str | None] = mapped_column(String(500))  # AES-GCM encrypted TOTP secret
    mfa_enabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # The 30-second time step of the last authenticator code accepted: a code is good once (RFC 6238 section 5.2).
    mfa_totp_last_step: Mapped[int | None] = mapped_column(BigInteger)
    # One-time recovery codes for a lost authenticator: SHA-256 hashes only; each is removed when used.
    mfa_recovery_hashes: Mapped[list | None] = mapped_column(JSONB)
    failed_login_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    enterprise_federated: Mapped[bool] = mapped_column(default=False, nullable=False)
    # Profile details (Settings > Account). The phone number is personal data: encrypted at rest (Architecture 8.2).
    phone_enc: Mapped[str | None] = mapped_column(String(500))
    language: Mapped[str] = mapped_column(String(10), nullable=False, default="en", server_default="en")
    time_zone: Mapped[str | None] = mapped_column(String(64))

    def live_platform_roles(self, now: datetime) -> list[str]:
        """Staff roles in force now: a suspended account has none, and a time-limited grant past its end time no longer counts
        (even before the expiry timer has removed it)."""
        if self.status != "ACTIVE":
            return []
        expiry = self.platform_role_expiry or {}
        return sorted(r for r in (self.platform_roles or []) if r not in expiry or datetime.fromisoformat(expiry[r]) > now)


class Session(Base, UUIDPk, CreatedAt):
    """Refresh-token session. Refresh tokens rotate; reuse revokes the family."""

    __tablename__ = "sessions"
    __table_args__ = {"schema": SCHEMA}

    identity_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.identities.id"), nullable=False, index=True
    )
    family_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False, index=True)
    refresh_token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    auth_strength: Mapped[str] = mapped_column(String(20), nullable=False)
    auth_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    rotated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    user_agent: Mapped[str | None] = mapped_column(String(500))
    # ADMIN: signed in on the staff sign-in page, the only sessions in which platform roles take effect. APP: everything
    # else (customer sign-in, SSO, API clients). Refreshes and step-ups keep the audience of the sign-in they continue.
    audience: Mapped[str] = mapped_column(String(10), nullable=False, default="APP", server_default="APP")
    # How the sign-in behind this session was made: PASSWORD | PASSKEY | OIDC | SAML | GOOGLE | MICROSOFT (null: before
    # this was recorded). Organisation session policies may allow only some (identity/session_policy.py).
    idp: Mapped[str | None] = mapped_column(String(20))


class Passkey(Base, UUIDPk, CreatedAt):
    """A WebAuthn credential (identity/passkeys.py). The public key only: the private key never leaves the device."""

    __tablename__ = "passkeys"
    __table_args__ = {"schema": SCHEMA}

    identity_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.identities.id"), nullable=False, index=True
    )
    credential_id: Mapped[str] = mapped_column(String(1400), unique=True, nullable=False)  # base64url
    public_key: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)  # COSE key
    sign_count: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    transports: Mapped[list[str]] = mapped_column(ARRAY(String(20)), nullable=False, default=list)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    backed_up: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)  # synced (e.g. iCloud Keychain)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PasskeyChallenge(Base, UUIDPk, CreatedAt):
    """A server-issued WebAuthn challenge: single use, five minutes, for one purpose (and account)."""

    __tablename__ = "passkey_challenges"
    __table_args__ = {"schema": SCHEMA}

    challenge_sha256: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    purpose: Mapped[str] = mapped_column(String(20), nullable=False)  # register | login | step_up
    identity_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class IdentityLink(Base, UUIDPk, Timestamps):
    """Projection of the actor's memberships in other domains, built from their
    events. Used only to mint token claims - the owning domain stays authoritative."""

    __tablename__ = "identity_links"
    __table_args__ = (UniqueConstraint("identity_id", "link_type", "target_id"), {"schema": SCHEMA})

    identity_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.identities.id"), nullable=False, index=True
    )
    link_type: Mapped[str] = mapped_column(String(30), nullable=False)  # PROFESSIONAL | ORG_MEMBER | FIRM_MEMBER
    target_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    roles: Mapped[list[str]] = mapped_column(ARRAY(String(50)), nullable=False, default=list)
    # What the target is: INDIVIDUAL | BUSINESS | ENTERPRISE (organizations), FIRM, PROFESSIONAL.
    target_kind: Mapped[str | None] = mapped_column(String(20))


class ConsentRecord(Base, UUIDPk, CreatedAt):
    __tablename__ = "consent_records"
    __table_args__ = {"schema": SCHEMA}

    identity_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.identities.id"), nullable=False, index=True
    )
    consent_type: Mapped[str] = mapped_column(String(50), nullable=False)  # TERMS | PRIVACY | MARKETING
    document_version: Mapped[str] = mapped_column(String(50), nullable=False)


class DataRequest(Base, UUIDPk, Timestamps):
    """A person's privacy request (GDPR/CCPA access or erasure). Logged and handled by staff (Regulator pack s.9)."""

    __tablename__ = "data_requests"
    __table_args__ = {"schema": SCHEMA}

    identity_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.identities.id"), nullable=False, index=True
    )
    request_type: Mapped[str] = mapped_column(String(20), nullable=False)  # ACCESS | ERASURE
    # ACCESS: RECEIVED -> COMPLETED (export ready). ERASURE: SCHEDULED -> COMPLETED | BLOCKED | CANCELLED.
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="RECEIVED")
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    scheduled_for: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # erasure after the cooling-off period
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # export download link
    export_key: Mapped[str | None] = mapped_column(String(300))  # blob storage key of the export file
    detail: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict, server_default="{}")  # reasons / summary


class DuplicateSuspicion(Base, UUIDPk, Timestamps):
    """Two accounts that look like the same person (Onboarding s.20). OPEN -> ANSWERED -> MERGED | NOT_DUPLICATE."""

    __tablename__ = "duplicate_suspicions"
    __table_args__ = (UniqueConstraint("identity_id", "other_identity_id", name="uq_duplicate_pair"), {"schema": "identity"})

    identity_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False, index=True)  # the account that triggered it
    other_identity_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False, index=True)
    signal: Mapped[str] = mapped_column(String(40), nullable=False)  # SAME_ID_DOCUMENT
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="OPEN")
    user_answer: Mapped[str | None] = mapped_column(String(20))  # MERGE_REQUESTED | NOT_ME
    user_note: Mapped[str | None] = mapped_column(String(500))
    resolved_by: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolution_note: Mapped[str | None] = mapped_column(String(500))
    kept_identity_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True))


class SsoConnection(Base, UUIDPk, Timestamps):
    """An organisation's identity provider, OpenID Connect or SAML 2.0 (identity/sso.py, identity/saml.py), and SCIM token
    (identity/scim.py)."""
    __tablename__ = "sso_connections"
    __table_args__ = {"schema": SCHEMA}
    organization_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False, unique=True)
    issuer: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    client_id: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    client_secret_enc: Mapped[str] = mapped_column(String(2000), nullable=False)
    email_domains: Mapped[list[str]] = mapped_column(PG_ARRAY(String(253)), nullable=False, default=list)
    enforce: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    jit: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    default_roles: Mapped[list[str]] = mapped_column(ARRAY(String(40)), nullable=False, default=list)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    scim_token_hash: Mapped[str | None] = mapped_column(String(64), unique=True)
    created_by: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    protocol: Mapped[str] = mapped_column(String(10), nullable=False, default="OIDC", server_default="OIDC")  # OIDC | SAML
    # SAML: the identity provider's entity id, its single sign-on (HTTP-Redirect) address and its signing certificates
    # (PEM), from its uploaded metadata.
    saml_idp_entity_id: Mapped[str | None] = mapped_column(String(500))
    saml_sso_url: Mapped[str | None] = mapped_column(String(1000))
    saml_certificates: Mapped[list] = mapped_column(JSONB, nullable=False, default=list, server_default="[]")
    # SCIM groups: {group display name: organisation role}. A group named after a role (e.g. "APPROVER") maps to it anyway.
    group_role_map: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict, server_default="{}")


class SsoLogin(Base, UUIDPk, CreatedAt):
    """One sign-in attempt: its id is the OAuth state; nonce and PKCE verifier never leave the server."""
    __tablename__ = "sso_logins"
    __table_args__ = {"schema": SCHEMA}
    connection_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    provider: Mapped[str] = mapped_column(String(20), nullable=False)  # org | google | microsoft
    nonce: Mapped[str] = mapped_column(String(100), nullable=False)
    code_verifier: Mapped[str] = mapped_column(String(200), nullable=False)
    link_identity_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # SAML: the verified assertion (email, name, subject, issuer) between the identity provider's post and the web app
    # finishing the sign-in with the one-time code (whose SHA-256 is then in code_verifier).
    assertion: Mapped[dict | None] = mapped_column(JSONB)


class ExternalLogin(Base, UUIDPk, CreatedAt):
    """An identity provider account (issuer|subject) connected to a Zoikorum account."""
    __tablename__ = "external_logins"
    __table_args__ = {"schema": SCHEMA}
    identity_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.identities.id"), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(20), nullable=False)
    subject: Mapped[str] = mapped_column(String(600), nullable=False, unique=True)


class OrgSessionPolicy(Base, UUIDPk, Timestamps):
    """An organisation's rules for its members' sessions (identity/session_policy.py), applied when a session refreshes.
    A person in several organisations gets the strictest of them."""
    __tablename__ = "org_session_policies"
    __table_args__ = {"schema": SCHEMA}
    organization_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False, unique=True)
    max_session_seconds: Mapped[int | None] = mapped_column(Integer)  # from sign-in, whatever the refreshes
    idle_timeout_seconds: Mapped[int | None] = mapped_column(Integer)  # since the last refresh
    require_mfa: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Sign-in methods allowed (PASSWORD, PASSKEY, OIDC, SAML, GOOGLE, MICROSOFT); empty: any.
    allowed_idps: Mapped[list[str]] = mapped_column(ARRAY(String(20)), nullable=False, default=list)
    updated_by: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)


class ScimGroup(Base, UUIDPk, Timestamps):
    """A SCIM 2.0 group pushed by an organisation's identity provider (identity/scim.py). Its members get the organisation
    role the group maps to."""
    __tablename__ = "scim_groups"
    __table_args__ = (UniqueConstraint("organization_id", "display_name", name="uq_scim_group_name"), {"schema": SCHEMA})
    organization_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False, index=True)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    external_id: Mapped[str | None] = mapped_column(String(200))
    member_ids: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(PG_UUID(as_uuid=True)), nullable=False, default=list)


class SignInSignal(Base, UUIDPk, CreatedAt):
    """Advisory risk signals of one sign-in (identity/risk.py): velocity, new device, impossible travel. Never blocks."""
    __tablename__ = "sign_in_signals"
    __table_args__ = {"schema": SCHEMA}
    identity_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False, index=True)
    session_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    ip_hash: Mapped[str | None] = mapped_column(String(64))  # keyed hash, never the address itself
    country: Mapped[str | None] = mapped_column(String(2))
    latitude: Mapped[float | None] = mapped_column(Float)  # city level, from the load balancer
    longitude: Mapped[float | None] = mapped_column(Float)
    device: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    signals: Mapped[list[str]] = mapped_column(ARRAY(String(30)), nullable=False, default=list)
    risk: Mapped[str] = mapped_column(String(10), nullable=False, default="LOW")  # LOW | MEDIUM | HIGH
