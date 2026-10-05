"""Identity commands. Pattern every domain follows:

    1. load aggregate (with row lock for state changes)
    2. authorize (RBAC/ABAC) and validate invariants -> raise DomainError
    3. mutate state
    4. record_event(...) in the same transaction (outbox)
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import timedelta

import jwt
import pyotp
from argon2 import PasswordHasher
from argon2.exceptions import VerificationError
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from zoikorum.config import get_settings
from zoikorum.domains.identity import tokens
from zoikorum.domains.identity.models import ConsentRecord, Identity, IdentityLink, Session
from zoikorum.domains.identity.schemas import IdentityOut, LinkOut, RegisterIn, TokenPair
from zoikorum.shared import clock
from zoikorum.shared.auth import Actor, AuthStrength, PlatformRole
from zoikorum.shared.crypto import decrypt_field, encrypt_field, sha256_hex
from zoikorum.shared.errors import Conflict, Forbidden, NotFound, Unauthenticated, ValidationFailed
from zoikorum.shared.event_catalog import E
from zoikorum.shared.events import record_event

_hasher = PasswordHasher()
MAX_FAILED_LOGINS = 5
LOCKOUT = timedelta(minutes=15)
EMAIL_TOKEN_TTL = 3 * 24 * 3600


def _evt(session: AsyncSession, event_type: str, identity: Identity, **payload) -> None:
    record_event(session, event_type, aggregate_type="Identity", aggregate_id=identity.id,
                 payload={"identityId": identity.id, **payload})


async def _links(session: AsyncSession, identity_id: uuid.UUID) -> list[IdentityLink]:
    return list((await session.scalars(select(IdentityLink).where(IdentityLink.identity_id == identity_id))).all())


def to_out(identity: Identity, links: list[IdentityLink]) -> IdentityOut:
    return IdentityOut(
        id=identity.id,
        email=identity.email,
        displayName=identity.display_name,
        country=identity.country,
        status=identity.status,
        emailConfirmed=identity.email_confirmed_at is not None,
        mfaEnabled=identity.mfa_enabled_at is not None,
        platformRoles=sorted(identity.platform_roles or []),
        links=[LinkOut(type=l.link_type, targetId=l.target_id, roles=sorted(l.roles)) for l in links],
        createdAt=identity.created_at,
    )


async def _start_session(
    session: AsyncSession, identity: Identity, strength: str, user_agent: str | None,
    family_id: uuid.UUID | None = None, auth_time=None,
) -> TokenPair:
    s = get_settings()
    now = clock.now()
    refresh, refresh_hash = tokens.new_refresh_token()
    sess = Session(
        identity_id=identity.id,
        family_id=family_id or uuid.uuid4(),
        refresh_token_hash=refresh_hash,
        auth_strength=strength,
        auth_time=auth_time or now,
        expires_at=now + timedelta(seconds=s.refresh_token_ttl_seconds),
        user_agent=(user_agent or "")[:500],
    )
    session.add(sess)
    await session.flush()
    access, ttl = tokens.mint_access_token(
        identity, await _links(session, identity.id),
        session_id=sess.id, auth_strength=strength, auth_time=sess.auth_time,
    )
    return TokenPair(accessToken=access, refreshToken=refresh, expiresIn=ttl)


async def register(session: AsyncSession, data: RegisterIn, user_agent: str | None):
    email = data.email.lower()
    if await session.scalar(select(Identity.id).where(Identity.email == email)):
        raise Conflict("An account with this email already exists", code="EMAIL_TAKEN")
    identity = Identity(
        email=email,
        password_hash=_hasher.hash(data.password),
        display_name=data.displayName.strip(),
        country=data.country,
        platform_roles=[],
    )
    session.add(identity)
    await session.flush()
    session.add(ConsentRecord(identity_id=identity.id, consent_type="TERMS", document_version=data.termsVersion))
    _evt(session, E.IDENTITY_CREATED, identity, email=email, country=identity.country)
    pair = await _start_session(session, identity, AuthStrength.PASSWORD, user_agent)
    confirm = tokens.mint_purpose_token(identity.id, "email_confirm", EMAIL_TOKEN_TTL)
    return identity, pair, confirm


async def confirm_email(session: AsyncSession, token: str) -> Identity:
    try:
        identity_id = tokens.read_purpose_token(token, "email_confirm")
    except jwt.PyJWTError as exc:
        raise ValidationFailed("Confirmation link is invalid or expired", code="EMAIL_TOKEN_INVALID") from exc
    identity = await session.get(Identity, identity_id, with_for_update=True)
    if identity is None:
        raise NotFound("Identity not found")
    if identity.email_confirmed_at is None:
        identity.email_confirmed_at = clock.now()
        _evt(session, E.EMAIL_CONFIRMED, identity)
    return identity


@dataclass(frozen=True)
class LoginFailure:
    detail: str
    code: str = "UNAUTHENTICATED"


async def login(
    session: AsyncSession, email: str, password: str, totp: str | None, user_agent: str | None
) -> TokenPair | LoginFailure:
    identity = await session.scalar(select(Identity).where(Identity.email == email.lower()).with_for_update())
    now = clock.now()
    if identity is None:
        _hasher.hash(password)  # equalise timing for unknown emails
        raise Unauthenticated("Email or password is incorrect")
    if identity.locked_until and identity.locked_until > now:
        raise Unauthenticated("Account temporarily locked after repeated failures", code="ACCOUNT_LOCKED")
    if identity.status != "ACTIVE":
        raise Forbidden("This account is not active", code="ACCOUNT_NOT_ACTIVE")
    try:
        _hasher.verify(identity.password_hash or "", password)
    except VerificationError:
        identity.failed_login_count += 1
        if identity.failed_login_count >= MAX_FAILED_LOGINS:
            identity.locked_until = now + LOCKOUT
            identity.failed_login_count = 0
        _evt(session, E.AUTHENTICATION_FAILED, identity, reason="BAD_PASSWORD")
        # Returned, not raised: the failure counter and event must still commit.
        return LoginFailure("Email or password is incorrect")

    strength = AuthStrength.PASSWORD
    if identity.mfa_enabled_at is not None:
        if not totp:
            raise Unauthenticated("Enter the 6-digit code from your authenticator", code="MFA_REQUIRED")
        if not pyotp.TOTP(decrypt_field(identity.mfa_secret_enc)).verify(totp, valid_window=1):
            _evt(session, E.AUTHENTICATION_FAILED, identity, reason="BAD_TOTP")
            return LoginFailure("Authentication code is incorrect", "MFA_INVALID")
        strength = AuthStrength.MFA

    identity.failed_login_count = 0
    identity.locked_until = None
    pair = await _start_session(session, identity, strength, user_agent)
    _evt(session, E.AUTHENTICATION_SUCCEEDED, identity, authStrength=strength)
    return pair


async def refresh(session: AsyncSession, refresh_token: str, user_agent: str | None) -> TokenPair | LoginFailure:
    now = clock.now()
    sess = await session.scalar(
        select(Session).where(Session.refresh_token_hash == sha256_hex(refresh_token)).with_for_update()
    )
    if sess is None:
        raise Unauthenticated("Refresh token is invalid")
    if sess.rotated_at is not None or sess.revoked_at is not None:
        # Reuse of a rotated token => token theft suspected: revoke the whole family.
        await session.execute(
            update(Session).where(Session.family_id == sess.family_id, Session.revoked_at.is_(None)).values(revoked_at=now)
        )
        record_event(session, E.SESSION_REVOKED, aggregate_type="Session", aggregate_id=sess.id,
                     payload={"identityId": sess.identity_id, "familyId": sess.family_id, "reason": "REFRESH_REUSE"})
        # Returned, not raised, so the family revocation commits.
        return LoginFailure("Refresh token reuse detected; please sign in again", "REFRESH_REUSE")
    if sess.expires_at <= now:
        raise Unauthenticated("Session expired")
    identity = await session.get(Identity, sess.identity_id)
    if identity is None or identity.status != "ACTIVE":
        raise Forbidden("This account is not active")
    sess.rotated_at = now
    # Rotation keeps the original auth strength/time; step-up freshness still decays.
    return await _start_session(session, identity, sess.auth_strength, user_agent, sess.family_id, sess.auth_time)


async def logout(session: AsyncSession, actor: Actor) -> None:
    if actor.session_id is None:
        return
    sess = await session.get(Session, actor.session_id, with_for_update=True)
    if sess and sess.revoked_at is None:
        sess.revoked_at = clock.now()
        await session.execute(
            update(Session).where(Session.family_id == sess.family_id, Session.revoked_at.is_(None)).values(revoked_at=clock.now())
        )
        record_event(session, E.SESSION_REVOKED, aggregate_type="Session", aggregate_id=sess.id,
                     payload={"identityId": sess.identity_id, "sessionId": sess.id, "reason": "LOGOUT"})


async def enroll_mfa(session: AsyncSession, actor: Actor) -> tuple[str, str]:
    identity = await _get_for_update(session, actor.identity_id)
    if identity.mfa_enabled_at is not None:
        raise Conflict("MFA is already enabled", code="MFA_ALREADY_ENABLED")
    secret = pyotp.random_base32()
    identity.mfa_secret_enc = encrypt_field(secret)
    uri = pyotp.TOTP(secret).provisioning_uri(name=identity.email, issuer_name="Zoikorum")
    return secret, uri


async def verify_mfa(session: AsyncSession, actor: Actor, code: str) -> None:
    identity = await _get_for_update(session, actor.identity_id)
    if not identity.mfa_secret_enc:
        raise Conflict("Start MFA enrollment first", code="MFA_NOT_ENROLLING")
    if not pyotp.TOTP(decrypt_field(identity.mfa_secret_enc)).verify(code, valid_window=1):
        raise ValidationFailed("Authentication code is incorrect", code="MFA_INVALID")
    if identity.mfa_enabled_at is None:
        identity.mfa_enabled_at = clock.now()
        _evt(session, E.MFA_ENROLLED, identity, method="TOTP")


async def step_up(session: AsyncSession, actor: Actor, code: str, user_agent: str | None) -> TokenPair:
    """Elevate the current session (Architecture 11.4). New session in same family."""
    identity = await _get_for_update(session, actor.identity_id)
    if identity.mfa_enabled_at is None:
        raise Forbidden("Enable MFA before performing sensitive operations", code="MFA_NOT_ENABLED")
    if not pyotp.TOTP(decrypt_field(identity.mfa_secret_enc)).verify(code, valid_window=1):
        _evt(session, E.AUTHENTICATION_FAILED, identity, reason="BAD_TOTP_STEP_UP")
        raise Unauthenticated("Authentication code is incorrect", code="MFA_INVALID")
    family = None
    if actor.session_id:
        old = await session.get(Session, actor.session_id)
        family = old.family_id if old else None
    pair = await _start_session(session, identity, AuthStrength.MFA, user_agent, family_id=family)
    record_event(session, E.STEP_UP_COMPLETED, aggregate_type="Identity", aggregate_id=identity.id,
                 payload={"identityId": identity.id, "method": "TOTP"})
    return pair


async def grant_platform_role(session: AsyncSession, actor: Actor, identity_id: uuid.UUID, role: str) -> Identity:
    actor.require_platform_role(PlatformRole.PLATFORM_ADMIN)
    actor.require_step_up()
    if role not in PlatformRole.ALL:
        raise ValidationFailed(f"Unknown platform role {role}")
    identity = await _get_for_update(session, identity_id)
    if role not in identity.platform_roles:
        identity.platform_roles = sorted({*identity.platform_roles, role})
        _evt(session, E.PLATFORM_ROLE_GRANTED, identity, role=role, grantedBy=actor.identity_id)
    return identity


async def set_status(session: AsyncSession, identity_id: uuid.UUID, status: str, reason: str) -> None:
    """Called from enforcement events only - never directly from an HTTP handler."""
    identity = await _get_for_update(session, identity_id)
    if identity.status == status:
        return
    identity.status = status
    if status != "ACTIVE":
        await session.execute(
            update(Session).where(Session.identity_id == identity_id, Session.revoked_at.is_(None)).values(revoked_at=clock.now())
        )
        _evt(session, E.IDENTITY_SUSPENDED, identity, reason=reason)
    else:
        _evt(session, E.IDENTITY_REINSTATED, identity, reason=reason)


async def upsert_link(session: AsyncSession, identity_id: uuid.UUID, link_type: str, target_id: uuid.UUID, roles: list[str]) -> None:
    link = await session.scalar(
        select(IdentityLink).where(
            IdentityLink.identity_id == identity_id,
            IdentityLink.link_type == link_type,
            IdentityLink.target_id == target_id,
        )
    )
    if link is None:
        session.add(IdentityLink(identity_id=identity_id, link_type=link_type, target_id=target_id, roles=sorted(set(roles))))
    else:
        link.roles = sorted(set(roles))


async def remove_link(session: AsyncSession, identity_id: uuid.UUID, link_type: str, target_id: uuid.UUID) -> None:
    link = await session.scalar(
        select(IdentityLink).where(
            IdentityLink.identity_id == identity_id,
            IdentityLink.link_type == link_type,
            IdentityLink.target_id == target_id,
        )
    )
    if link is not None:
        await session.delete(link)


async def get_me(session: AsyncSession, actor: Actor) -> IdentityOut:
    identity = await session.get(Identity, actor.identity_id)
    if identity is None:
        raise NotFound("Identity not found")
    return to_out(identity, await _links(session, identity.id))


async def _get_for_update(session: AsyncSession, identity_id: uuid.UUID) -> Identity:
    identity = await session.get(Identity, identity_id, with_for_update=True)
    if identity is None:
        raise NotFound("Identity not found")
    return identity
