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
from zoikorum.domains.identity.schemas import AuthOut, IdentityOut, LinkOut, RegisterIn, StaffMemberOut, TokenPair
from zoikorum.shared import clock
from zoikorum.shared.auth import Actor, AuthStrength, Persona, PlatformRole
from zoikorum.shared.crypto import decrypt_field, encrypt_field, sha256_hex
from zoikorum.shared.errors import Conflict, Forbidden, NotFound, Unauthenticated, ValidationFailed
from zoikorum.shared.event_catalog import E
from zoikorum.shared.events import record_event

_hasher = PasswordHasher()
MAX_FAILED_LOGINS = 5
LOCKOUT = timedelta(minutes=15)
EMAIL_TOKEN_TTL = 3 * 24 * 3600
RESET_TOKEN_TTL = 30 * 60

# Where each account role lands after sign-in (frontend route keys).
_DASHBOARD = {
    Persona.ENTERPRISE_ADMIN: "enterprise",
    Persona.FIRM_ADMIN: "firm",
    Persona.PROFESSIONAL: "professional",
    Persona.BUYER: "buyer",
}
# Roles whose accounts must use MFA (Architecture 11.4, Enterprise Policy s.11).
_MFA_PERSONAS = {Persona.ENTERPRISE_ADMIN, Persona.FIRM_ADMIN}


def default_dashboard(identity: Identity) -> str:
    if identity.platform_roles:
        return "ops"
    if identity.primary_persona in _DASHBOARD:
        return _DASHBOARD[identity.primary_persona]
    for persona, dash in _DASHBOARD.items():
        if persona in (identity.personas or []):
            return dash
    return "buyer"


def mfa_required(identity: Identity) -> bool:
    needs = bool(identity.platform_roles) or bool(_MFA_PERSONAS.intersection(identity.personas or []))
    return needs and identity.mfa_enabled_at is None


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
        mfaRequired=mfa_required(identity),
        personas=sorted(identity.personas or []),
        primaryPersona=identity.primary_persona,
        platformRoles=sorted(identity.platform_roles or []),
        organizationName=identity.signup_organization_name,
        defaultDashboard=default_dashboard(identity),
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
        personas=[Persona.FROM_ACCOUNT_TYPE[data.accountType]],
        primary_persona=Persona.FROM_ACCOUNT_TYPE[data.accountType],
        signup_organization_name=(data.organizationName or "").strip() or None,
    )
    session.add(identity)
    await session.flush()
    session.add(ConsentRecord(identity_id=identity.id, consent_type="TERMS", document_version=data.termsVersion))
    _evt(session, E.IDENTITY_CREATED, identity, email=email, country=identity.country,
         accountType=data.accountType, personas=identity.personas,
         organizationName=identity.signup_organization_name)
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
) -> AuthOut | LoginFailure:
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
    return AuthOut(tokens=pair, user=to_out(identity, await _links(session, identity.id)))


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


async def add_persona(session: AsyncSession, actor: Actor, account_type: str, user_agent: str | None) -> AuthOut:
    """Self-service: a buyer may also become a professional and vice versa.
    Firm/Enterprise admin roles come from creating or joining an organization."""
    identity = await _get_for_update(session, actor.identity_id)
    persona = Persona.FROM_ACCOUNT_TYPE[account_type]
    if persona not in (Persona.BUYER, Persona.PROFESSIONAL):
        raise Forbidden("Firm and Enterprise roles are granted through an organization")
    if persona not in identity.personas:
        identity.personas = sorted({*identity.personas, persona})
        _evt(session, E.PERSONA_ADDED, identity, persona=persona)
    family = None
    if actor.session_id:
        old = await session.get(Session, actor.session_id)
        family = old.family_id if old else None
    pair = await _start_session(session, identity, actor.auth_strength, user_agent, family, actor.auth_time)
    return AuthOut(tokens=pair, user=to_out(identity, await _links(session, identity.id)))


def _password_fingerprint(identity: Identity) -> str:
    # Binds a reset token to the current password hash, so the token dies once used.
    return sha256_hex(identity.password_hash or "")[:16]


async def request_password_reset(session: AsyncSession, email: str) -> str | None:
    """Returns the reset token (to be emailed). Unknown emails return None silently."""
    identity = await session.scalar(select(Identity).where(Identity.email == email.lower()))
    if identity is None or identity.status != "ACTIVE":
        return None
    _evt(session, E.PASSWORD_RESET_REQUESTED, identity)
    return tokens.mint_purpose_token(
        identity.id, "password_reset", RESET_TOKEN_TTL, extra={"pwf": _password_fingerprint(identity)}
    )


async def reset_password(session: AsyncSession, token: str, new_password: str) -> None:
    try:
        claims = tokens.read_purpose_claims(token, "password_reset")
    except jwt.PyJWTError as exc:
        raise ValidationFailed("Reset link is invalid or expired", code="RESET_TOKEN_INVALID") from exc
    identity = await _get_for_update(session, uuid.UUID(claims["sub"]))
    if claims.get("pwf") != _password_fingerprint(identity):
        raise ValidationFailed("Reset link was already used", code="RESET_TOKEN_INVALID")
    identity.password_hash = _hasher.hash(new_password)
    identity.failed_login_count = 0
    identity.locked_until = None
    await session.execute(
        update(Session).where(Session.identity_id == identity.id, Session.revoked_at.is_(None)).values(revoked_at=clock.now())
    )
    _evt(session, E.PASSWORD_CHANGED, identity, method="RESET")


async def revoke_platform_role(session: AsyncSession, actor: Actor, identity_id: uuid.UUID, role: str) -> Identity:
    actor.require_platform_role(PlatformRole.PLATFORM_ADMIN)
    actor.require_step_up()
    identity = await _get_for_update(session, identity_id)
    if role == PlatformRole.PLATFORM_ADMIN and identity_id == actor.identity_id:
        raise Conflict("You cannot remove your own Platform Admin role", code="SELF_DEMOTION")
    if role in identity.platform_roles:
        identity.platform_roles = sorted(set(identity.platform_roles) - {role})
        await session.execute(
            update(Session).where(Session.identity_id == identity_id, Session.revoked_at.is_(None)).values(revoked_at=clock.now())
        )
        _evt(session, E.PLATFORM_ROLE_REVOKED, identity, role=role, revokedBy=actor.identity_id)
    return identity


async def list_staff(session: AsyncSession, actor: Actor) -> list[StaffMemberOut]:
    actor.require_platform_role(PlatformRole.PLATFORM_ADMIN)
    rows = (
        await session.scalars(
            select(Identity).where(Identity.platform_roles != []).order_by(Identity.display_name).limit(500)
        )
    ).all()
    return [
        StaffMemberOut(id=i.id, email=i.email, displayName=i.display_name, platformRoles=sorted(i.platform_roles),
                       mfaEnabled=i.mfa_enabled_at is not None, status=i.status)
        for i in rows
    ]


async def create_platform_admin(session: AsyncSession, email: str, password: str, display_name: str, country: str) -> Identity:
    """Bootstrap only (CLI). Creates the first Platform Admin or promotes an existing account."""
    identity = await session.scalar(select(Identity).where(Identity.email == email.lower()).with_for_update())
    if identity is None:
        identity = Identity(
            email=email.lower(), password_hash=_hasher.hash(password), display_name=display_name,
            country=country, platform_roles=[PlatformRole.PLATFORM_ADMIN], personas=[], email_confirmed_at=clock.now(),
        )
        session.add(identity)
        await session.flush()
        _evt(session, E.IDENTITY_CREATED, identity, email=identity.email, country=country, accountType="STAFF")
    elif PlatformRole.PLATFORM_ADMIN not in identity.platform_roles:
        identity.platform_roles = sorted({*identity.platform_roles, PlatformRole.PLATFORM_ADMIN})
    _evt(session, E.PLATFORM_ROLE_GRANTED, identity, role=PlatformRole.PLATFORM_ADMIN, grantedBy="bootstrap-cli")
    return identity


async def lookup_by_email(session: AsyncSession, actor: Actor, email: str) -> StaffMemberOut:
    actor.require_platform_role(PlatformRole.PLATFORM_ADMIN)
    i = await session.scalar(select(Identity).where(Identity.email == email.strip().lower()))
    if i is None:
        raise NotFound("No account with that email")
    return StaffMemberOut(id=i.id, email=i.email, displayName=i.display_name, platformRoles=sorted(i.platform_roles),
                          mfaEnabled=i.mfa_enabled_at is not None, status=i.status)
