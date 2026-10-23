"""Identity commands. Pattern every domain follows:

    1. load aggregate (with row lock for state changes)
    2. authorize (RBAC/ABAC) and validate invariants -> raise DomainError
    3. mutate state
    4. record_event(...) in the same transaction (outbox)
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

import jwt
import pyotp
from argon2 import PasswordHasher
from argon2.exceptions import VerificationError
from sqlalchemy import any_, func, literal, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from zoikorum.config import get_settings
from zoikorum.domains.identity import tokens
from zoikorum.domains.identity.models import ConsentRecord, Identity, IdentityLink, Session
from zoikorum.domains.identity.schemas import (
    AuthOut, IdentityOut, LinkOut, MePatch, RegisterIn, SessionOut, StaffMemberOut, TokenPair, UserOut,
)
from zoikorum.shared import clock
from zoikorum.shared.auth import Actor, AuthStrength, Persona, PlatformRole
from zoikorum.shared.capabilities import Cap
from zoikorum.shared.crypto import decrypt_field, encrypt_field, sha256_hex
from zoikorum.shared.errors import Conflict, Forbidden, NotFound, RateLimited, Unauthenticated, ValidationFailed
from zoikorum.shared.event_catalog import E
from zoikorum.shared.events import record_audit, record_event
from zoikorum.shared.http import page_of, paginate

_hasher = PasswordHasher()
MAX_FAILED_LOGINS = 5
LOCKOUT = timedelta(minutes=15)
EMAIL_TOKEN_TTL = 3 * 24 * 3600
RESET_TOKEN_TTL = 30 * 60

# Where each account role lands after sign-in (frontend route keys).
_DASHBOARD = {
    Persona.ENTERPRISE_ADMIN: "enterprise",
    Persona.ENTERPRISE_MEMBER: "enterprise",
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
    if get_settings().mfa_bypass:
        return False  # development only (ZK_DEV_SKIP_MFA)
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
        mfaRequired=mfa_required(identity), mfaBypass=get_settings().mfa_bypass,
        personas=sorted(identity.personas or []),
        primaryPersona=identity.primary_persona,
        platformRoles=identity.live_platform_roles(clock.now()),
        organizationName=identity.signup_organization_name,
        defaultDashboard=default_dashboard(identity),
        links=[LinkOut(type=l.link_type, targetId=l.target_id, roles=sorted(l.roles), kind=l.target_kind) for l in links],
        phone=decrypt_field(identity.phone_enc) if identity.phone_enc else None,
        language=identity.language or "en", timeZone=identity.time_zone,
        createdAt=identity.created_at,
    )


async def _start_session(
    session: AsyncSession, identity: Identity, strength: str, user_agent: str | None,
    family_id: uuid.UUID | None = None, auth_time=None, audience: str = "APP", idp: str | None = None,
) -> TokenPair:
    from zoikorum.domains.identity import risk, session_policy

    s = get_settings()
    now = clock.now()
    refresh, refresh_hash = tokens.new_refresh_token()
    if family_id is not None and idp is None:  # a refresh or step-up keeps the sign-in method of the session it continues
        idp = await session.scalar(select(Session.idp).where(Session.family_id == family_id)
                                   .order_by(Session.created_at.desc()).limit(1))
    if family_id is None:  # a fresh sign-in (not a refresh or a step-up): tell the person if the device is new to us
        idp = idp or ("PASSKEY" if strength == AuthStrength.PASSKEY else "PASSWORD")
        await session_policy.check_new_sign_in(session, identity.id, idp, audience)
        await _announce_new_device(session, identity, user_agent)
    sess = Session(
        identity_id=identity.id,
        family_id=family_id or uuid.uuid4(),
        refresh_token_hash=refresh_hash,
        auth_strength=strength,
        auth_time=auth_time or now,
        expires_at=now + timedelta(seconds=s.refresh_token_ttl_seconds),
        user_agent=(user_agent or "")[:500],
        audience=audience,
        idp=idp,
    )
    session.add(sess)
    await session.flush()
    if family_id is None:
        await risk.assess(session, identity.id, sess.id, _device(user_agent))  # advisory signals, never blocking
    access, ttl = tokens.mint_access_token(
        identity, await _links(session, identity.id),
        session_id=sess.id, auth_strength=strength, auth_time=sess.auth_time, audience=audience,
    )
    return TokenPair(accessToken=access, refreshToken=refresh, expiresIn=ttl)


def _device(user_agent: str | None) -> str:
    """A readable name for a browser/device from its User-Agent, e.g. "Chrome on Windows"."""
    ua = user_agent or ""
    browser = next((name for key, name in (("Edg/", "Edge"), ("OPR/", "Opera"), ("Firefox/", "Firefox"), ("Chrome/", "Chrome"),
                                             ("Safari/", "Safari")) if key in ua), "A browser")
    system = next((name for key, name in (("Windows", "Windows"), ("Android", "Android"), ("iPhone", "iPhone"), ("iPad", "iPad"),
                                            ("Mac OS X", "macOS"), ("Linux", "Linux")) if key in ua), "an unknown device")
    return f"{browser} on {system}"


async def _announce_new_device(session: AsyncSession, identity: Identity, user_agent: str | None) -> None:
    """Handbook / onboarding: security alert on a sign-in from a device not seen before (first sign-in excluded)."""
    seen = (await session.scalars(select(Session.user_agent).where(Session.identity_id == identity.id).distinct())).all()
    if not seen or (user_agent or "")[:500] in seen:
        return
    when = clock.now()
    _evt(session, E.SESSION_CREATED, identity, newDevice=True, device=_device(user_agent),
         message=f"Your account was signed in from {_device(user_agent)} on {when:%d %b %Y at %H:%M} UTC. If this was not "
                 "you, change your password and sign out of other sessions under Security now.")


async def register(session: AsyncSession, data: RegisterIn, user_agent: str | None):
    from zoikorum.domains.admin import facade as admin_facade

    await admin_facade.require_on(session, "SIGN_UPS")
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


CONFIRMATION_RESEND_SECONDS = 60  # one new link a minute; the global rate limit still applies


async def resend_email_confirmation(session: AsyncSession, actor: Actor) -> str:
    """Sends a new confirmation link (the notification domain emails it; the link is minted at send time).
    Returns a link token for development and tests only (see api._expose_dev_tokens)."""
    identity = await session.get(Identity, actor.identity_id, with_for_update=True)
    if identity is None:
        raise NotFound("Identity not found")
    if identity.email_confirmed_at is not None:
        raise Conflict("Your email address is already confirmed", code="EMAIL_ALREADY_CONFIRMED")
    now = clock.now()
    wait = CONFIRMATION_RESEND_SECONDS - int((now - (identity.confirmation_requested_at or identity.created_at)).total_seconds())
    if wait > 0:
        raise RateLimited(f"A link was sent a moment ago. You can ask for another in {wait} seconds.", code="RESEND_TOO_SOON")
    identity.confirmation_requested_at = now
    _evt(session, E.EMAIL_CONFIRMATION_REQUESTED, identity)
    return tokens.mint_purpose_token(identity.id, "email_confirm", EMAIL_TOKEN_TTL)


async def email_confirmation_link_token(session: AsyncSession, actor: Actor) -> str:
    """A confirmation-link token without sending an email: local development and tests only (identity api)."""
    identity = await session.get(Identity, actor.identity_id)
    if identity is None:
        raise NotFound("Identity not found")
    if identity.email_confirmed_at is not None:
        raise Conflict("Your email address is already confirmed", code="EMAIL_ALREADY_CONFIRMED")
    return tokens.mint_purpose_token(identity.id, "email_confirm", EMAIL_TOKEN_TTL)


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


RECOVERY_CODES = 10


def _count_failure(identity: Identity) -> None:
    """Wrong password, authenticator code or recovery code: all count towards the same temporary lockout."""
    identity.failed_login_count += 1
    if identity.failed_login_count >= MAX_FAILED_LOGINS:
        identity.locked_until = clock.now() + LOCKOUT
        identity.failed_login_count = 0


def _recovery_hash(code: str) -> str:
    """Keyed hash: a copy of the database alone is not enough to try codes offline."""
    return hmac.new(get_settings().field_encryption_key.encode(), code.strip().lower().encode(), hashlib.sha256).hexdigest()


def _new_recovery_codes(identity: Identity) -> list[str]:
    codes = []
    for _ in range(RECOVERY_CODES):
        raw = secrets.token_hex(10)  # 80 random bits
        codes.append("-".join(raw[i:i + 5] for i in range(0, 20, 5)))
    identity.mfa_recovery_hashes = [_recovery_hash(c) for c in codes]
    return codes


def _totp_time() -> float:
    """Wall-clock seconds for authenticator codes (the phone app uses real time, not the domain clock)."""
    return time.time()


TOTP_REUSED = "That code was already used. Wait for the next code in your authenticator app."


async def _accept_totp(session: AsyncSession, identity: Identity, code: str) -> str | None:
    """Checks an authenticator code (the current 30-second step, or one either side for clock drift) and uses it up:
    each step is accepted once, so a code seen over someone's shoulder or replayed cannot sign in again. Returns None
    when accepted, otherwise the message to show."""
    totp = pyotp.TOTP(decrypt_field(identity.mfa_secret_enc))
    current = int(_totp_time()) // totp.interval
    step = next((s for s in (current - 1, current, current + 1) if hmac.compare_digest(totp.generate_otp(s), str(code))), None)
    if step is None:
        return "Authentication code is incorrect"
    # One conditional update, so two requests racing with the same code cannot both pass.
    used = await session.execute(update(Identity).where(
        Identity.id == identity.id, or_(Identity.mfa_totp_last_step.is_(None), Identity.mfa_totp_last_step < step),
    ).values(mfa_totp_last_step=step).execution_options(synchronize_session="fetch"))
    return None if used.rowcount == 1 else TOTP_REUSED


def _use_recovery_code(identity: Identity, code: str) -> bool:
    h = _recovery_hash(code)
    if h not in (identity.mfa_recovery_hashes or []):
        return False
    identity.mfa_recovery_hashes = [x for x in identity.mfa_recovery_hashes if x != h]  # one use only
    return True


async def login(
    session: AsyncSession, email: str, password: str, totp: str | None, user_agent: str | None,
    recovery_code: str | None = None, portal: str | None = None,
) -> AuthOut | LoginFailure:
    identity = await session.scalar(select(Identity).where(Identity.email == email.lower()).with_for_update())
    now = clock.now()
    if identity is None:
        _hasher.hash(password)  # equalise timing for unknown emails
        raise Unauthenticated("Email or password is incorrect")
    if identity.locked_until and identity.locked_until > now:
        raise Unauthenticated("Account temporarily locked after repeated failures", code="ACCOUNT_LOCKED")
    if identity.status not in ("ACTIVE", "SUSPENDED"):
        raise Forbidden("This account is not active", code="ACCOUNT_NOT_ACTIVE")
    try:
        _hasher.verify(identity.password_hash or "", password)
    except VerificationError:
        identity.failed_login_count += 1
        if identity.failed_login_count >= MAX_FAILED_LOGINS:
            identity.locked_until = now + LOCKOUT
            identity.failed_login_count = 0
        _evt(session, E.AUTHENTICATION_FAILED, identity, reason="BAD_PASSWORD", lockedUntil=identity.locked_until)
        # Returned, not raised: the failure counter and event must still commit.
        return LoginFailure("Email or password is incorrect")

    # Checked only after the password is right, so a stranger cannot learn which emails belong to staff.
    from zoikorum.domains.identity import sso
    if await sso.sso_required(session, identity):
        return LoginFailure("Your organisation signs in with single sign-on. Use “Sign in with SSO”.", "SSO_REQUIRED")
    staff = bool(identity.platform_roles)
    if portal == "staff" and not staff:
        return LoginFailure("This sign-in is for Zoikorum staff only. Customers and professionals sign in on the main "
                            "sign-in page.", "NOT_STAFF_ACCOUNT")
    if portal == "customer" and staff:
        return LoginFailure("Staff accounts sign in on the staff sign-in page.", "USE_STAFF_SIGN_IN")

    strength = AuthStrength.PASSWORD
    if identity.mfa_enabled_at is not None and not (get_settings().mfa_bypass and not (totp or recovery_code)):
        if recovery_code:  # lost authenticator: a one-time recovery code instead of the 6-digit code
            if not _use_recovery_code(identity, recovery_code):
                _count_failure(identity)
                _evt(session, E.AUTHENTICATION_FAILED, identity, reason="BAD_RECOVERY_CODE", lockedUntil=identity.locked_until)
                return LoginFailure("That recovery code is not valid or was already used", "MFA_INVALID")
            _evt(session, E.MFA_RECOVERY_CODE_USED, identity, remaining=len(identity.mfa_recovery_hashes or []))
        else:
            if not totp:
                raise Unauthenticated("Enter the 6-digit code from your authenticator", code="MFA_REQUIRED")
            if problem := await _accept_totp(session, identity, totp):
                _count_failure(identity)
                _evt(session, E.AUTHENTICATION_FAILED, identity, reason="REUSED_TOTP" if problem == TOTP_REUSED else "BAD_TOTP",
                     lockedUntil=identity.locked_until)
                return LoginFailure(problem, "MFA_INVALID")
        strength = AuthStrength.MFA

    identity.failed_login_count = 0
    identity.locked_until = None
    # Only the staff sign-in page starts an admin-audience session: staff tools refuse every other session.
    pair = await _start_session(session, identity, strength, user_agent, audience="ADMIN" if portal == "staff" else "APP")
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
    if identity is None or identity.status not in ("ACTIVE", "SUSPENDED"):
        raise Forbidden("This account is not active")
    from zoikorum.domains.identity import session_policy
    if broken := await session_policy.violation(session, sess, now):  # the organisation's session rules (identity/session_policy.py)
        await session.execute(
            update(Session).where(Session.family_id == sess.family_id, Session.revoked_at.is_(None)).values(revoked_at=now)
        )
        record_event(session, E.SESSION_REVOKED, aggregate_type="Session", aggregate_id=sess.id,
                     payload={"identityId": sess.identity_id, "familyId": sess.family_id, "reason": broken[0]})
        return LoginFailure(broken[1], broken[0])  # returned, so the revocation commits
    sess.rotated_at = now
    # Rotation keeps the original auth strength/time; step-up freshness still decays.
    return await _start_session(session, identity, sess.auth_strength, user_agent, sess.family_id, sess.auth_time, sess.audience)


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


async def verify_mfa(session: AsyncSession, actor: Actor, code: str) -> list[str]:
    """Turns two-step verification on. Returns the one-time recovery codes (shown once; only hashes are kept)."""
    identity = await _get_for_update(session, actor.identity_id)
    if not identity.mfa_secret_enc:
        raise Conflict("Start MFA enrollment first", code="MFA_NOT_ENROLLING")
    if problem := await _accept_totp(session, identity, code):
        raise ValidationFailed(problem, code="MFA_INVALID")
    if identity.mfa_enabled_at is not None:
        return []
    identity.mfa_enabled_at = clock.now()
    _evt(session, E.MFA_ENROLLED, identity, method="TOTP")
    return _new_recovery_codes(identity)


async def elevate_after_enrollment(session: AsyncSession, actor: Actor, user_agent: str | None) -> TokenPair:
    """The code that just turned two-step on also proves it: start a two-step session for this sign-in (same family and
    audience), so the person is not asked for a second code that the replay check would refuse anyway."""
    identity = await _get_for_update(session, actor.identity_id)
    family, audience = None, "APP"
    if actor.session_id:
        old = await session.get(Session, actor.session_id)
        family, audience = (old.family_id, old.audience) if old else (None, "APP")
    return await _start_session(session, identity, AuthStrength.MFA, user_agent, family_id=family, audience=audience)


async def regenerate_recovery_codes(session: AsyncSession, actor: Actor) -> list[str]:
    """New recovery codes replace all old ones. Needs a fresh two-step confirmation."""
    actor.require_step_up()
    identity = await _get_for_update(session, actor.identity_id)
    if identity.mfa_enabled_at is None:
        raise Conflict("Turn on two-step verification first", code="MFA_NOT_ENABLED")
    record_audit(session, "identity.mfa.recovery_codes_replaced", object_type="Identity", object_id=identity.id)
    return _new_recovery_codes(identity)


async def reset_mfa(session: AsyncSession, actor: Actor, identity_id: uuid.UUID, reason: str) -> Identity:
    """Support, after confirming who the person is by other means: removes two-step verification so they can set it up
    again. Platform Admin with a fresh confirmation; never for one's own account; signs the person out everywhere."""
    actor.require_capability(Cap.ACCOUNTS_RESET_MFA)
    actor.require_step_up()
    if identity_id == actor.identity_id:
        raise Forbidden("Another administrator must reset your own two-step verification", code="SELF_RESET")
    identity = await _get_for_update(session, identity_id)
    if identity.mfa_enabled_at is None:
        raise Conflict("Two-step verification is not on for this account", code="MFA_NOT_ENABLED")
    identity.mfa_secret_enc = identity.mfa_enabled_at = identity.mfa_recovery_hashes = None
    await session.execute(update(Session).where(Session.identity_id == identity_id, Session.revoked_at.is_(None))
                          .values(revoked_at=clock.now()))
    _evt(session, E.MFA_RESET, identity, resetBy=actor.identity_id)
    record_audit(session, "identity.mfa.reset", object_type="Identity", object_id=identity.id, details={"reason": reason.strip()[:500]})
    return identity


async def step_up(session: AsyncSession, actor: Actor, code: str, user_agent: str | None) -> TokenPair | LoginFailure:
    """Elevate the current session (Architecture 11.4). New session in same family."""
    identity = await _get_for_update(session, actor.identity_id)
    if identity.mfa_enabled_at is None:
        raise Forbidden("Enable MFA before performing sensitive operations", code="MFA_NOT_ENABLED")
    if identity.locked_until and identity.locked_until > clock.now():
        raise Unauthenticated("Too many wrong codes. Try again in a few minutes.", code="ACCOUNT_LOCKED")
    if problem := await _accept_totp(session, identity, code):
        _count_failure(identity)
        _evt(session, E.AUTHENTICATION_FAILED, identity,
             reason="REUSED_TOTP_STEP_UP" if problem == TOTP_REUSED else "BAD_TOTP_STEP_UP", lockedUntil=identity.locked_until)
        return LoginFailure(problem, "MFA_INVALID")
    identity.failed_login_count = 0
    family, audience = None, "APP"
    if actor.session_id:
        old = await session.get(Session, actor.session_id)
        family, audience = (old.family_id, old.audience) if old else (None, "APP")
    pair = await _start_session(session, identity, AuthStrength.MFA, user_agent, family_id=family, audience=audience)
    record_event(session, E.STEP_UP_COMPLETED, aggregate_type="Identity", aggregate_id=identity.id,
                 payload={"identityId": identity.id, "method": "TOTP"})
    return pair


# ---- Staff roles: granted and revoked only through an approved maker-checker request (admin/approvals.py) ------------

ROLE_EXPIRY_TIMER = "identity.platform_role_expiry"


async def check_platform_role_change(session: AsyncSession, requested_by: uuid.UUID, identity_id: uuid.UUID, role: str,
                                     grant: bool, expires_at=None, *, lock: bool = False) -> Identity:
    """The rules a role change must meet, both when it is requested and again when it is applied: nobody grants a staff
    role to themselves or removes their own Platform Admin role."""
    if role not in PlatformRole.ALL:
        raise ValidationFailed(f"Unknown platform role {role}", code="UNKNOWN_ROLE")
    identity = await session.get(Identity, identity_id, with_for_update=lock)
    if identity is None:
        raise NotFound("Identity not found")
    if grant:
        if identity_id == requested_by:
            raise Forbidden("Another administrator must grant you a staff role", code="SELF_GRANT")
        if identity.status != "ACTIVE":
            raise Conflict("Staff roles can only be granted to an active account", code="ACCOUNT_NOT_ACTIVE")
        if expires_at is not None and expires_at <= clock.now():
            raise ValidationFailed("The end time of a time-limited role must be in the future", code="EXPIRY_IN_PAST")
        if role in identity.platform_roles and role not in (identity.platform_role_expiry or {}):
            raise Conflict("This account already holds the role permanently", code="ROLE_ALREADY_HELD")
    else:
        if role == PlatformRole.PLATFORM_ADMIN and identity_id == requested_by:
            raise Conflict("You cannot remove your own Platform Admin role", code="SELF_DEMOTION")
        if role not in identity.platform_roles:
            raise Conflict("This account does not hold that role", code="ROLE_NOT_HELD")
    return identity


async def apply_platform_role_grant(session: AsyncSession, identity_id: uuid.UUID, role: str, expires_at,
                                    requested_by: uuid.UUID, approved_by: uuid.UUID) -> Identity:
    """Carries out an approved grant. With ``expires_at`` the role is just-in-time: it stops counting at that time and a
    timer then removes it; without, it is permanent (and replaces an earlier time limit)."""
    from zoikorum.shared.relay import cancel_timer, schedule_timer

    identity = await check_platform_role_change(session, requested_by, identity_id, role, True, expires_at, lock=True)
    expiry = dict(identity.platform_role_expiry or {})
    key = f"{identity_id}:{role}"
    if expires_at is not None:
        expiry[role] = expires_at.isoformat()
        await schedule_timer(session, ROLE_EXPIRY_TIMER, key, expires_at)
    else:
        expiry.pop(role, None)
        await cancel_timer(session, ROLE_EXPIRY_TIMER, key)
    identity.platform_roles = sorted({*identity.platform_roles, role})
    identity.platform_role_expiry = expiry
    _evt(session, E.PLATFORM_ROLE_GRANTED, identity, role=role, grantedBy=requested_by, approvedBy=approved_by,
         expiresAt=expires_at)
    return identity


async def expire_platform_role(session: AsyncSession, identity_id: uuid.UUID, role: str) -> None:
    """Timer: a just-in-time role reached its end time. It already stopped counting then (live_platform_roles); this removes
    it and records that it ended. A grant renewed in the meantime moved the end time, so nothing happens."""
    identity = await session.get(Identity, identity_id, with_for_update=True)
    if identity is None or role not in (identity.platform_role_expiry or {}):
        return
    ends = datetime.fromisoformat(identity.platform_role_expiry[role])
    if ends > clock.now():
        return
    identity.platform_roles = sorted(set(identity.platform_roles) - {role})
    identity.platform_role_expiry = {r: t for r, t in identity.platform_role_expiry.items() if r != role}
    _evt(session, E.PLATFORM_ROLE_EXPIRED, identity, role=role, endedAt=ends,
         message=f"Your time-limited {role.replace('_', ' ').title()} role ended at {ends:%d %b %Y %H:%M} UTC.")
    record_audit(session, "identity.platform_role.expired", object_type="Identity", object_id=identity.id,
                 details={"role": role, "endedAt": ends.isoformat()})


async def set_status(session: AsyncSession, identity_id: uuid.UUID, status: str, reason: str) -> None:
    """Called from enforcement events, or when support confirms a duplicate account (duplicates.resolve)."""
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


async def upsert_link(
    session: AsyncSession, identity_id: uuid.UUID, link_type: str, target_id: uuid.UUID, roles: list[str],
    target_kind: str | None = None,
) -> None:
    link = await session.scalar(
        select(IdentityLink).where(
            IdentityLink.identity_id == identity_id,
            IdentityLink.link_type == link_type,
            IdentityLink.target_id == target_id,
        )
    )
    if link is None:
        session.add(IdentityLink(identity_id=identity_id, link_type=link_type, target_id=target_id,
                                 roles=sorted(set(roles)), target_kind=target_kind))
    else:
        link.roles = sorted(set(roles))
        link.target_kind = target_kind or link.target_kind
    await session.flush()
    await recompute_personas(session, identity_id)


def _derived_personas(links: list[IdentityLink]) -> set[str]:
    """Account roles that follow from memberships (Enterprise Policy s.11, Firm domain)."""
    out: set[str] = set()
    for link in links:
        if link.link_type == "ORG_MEMBER" and link.target_kind in ("ENTERPRISE", "BUSINESS"):
            out.add(Persona.ENTERPRISE_ADMIN if "ORG_ADMIN" in link.roles else Persona.ENTERPRISE_MEMBER)
        elif link.link_type == "FIRM_MEMBER":
            out.add(Persona.PROFESSIONAL)  # firm members offer services as professionals
            if "FIRM_ADMIN" in link.roles:
                out.add(Persona.FIRM_ADMIN)
    return out


async def recompute_personas(session: AsyncSession, identity_id: uuid.UUID) -> None:
    identity = await session.get(Identity, identity_id, with_for_update=True)
    if identity is None:
        return
    links = await _links(session, identity_id)
    self_chosen = set(identity.personas or []) & Persona.SELF_SERVICE
    personas = sorted(self_chosen | _derived_personas(links))
    if personas != sorted(identity.personas or []):
        added = set(personas) - set(identity.personas or [])
        identity.personas = personas
        for persona in sorted(added):
            _evt(session, E.PERSONA_ADDED, identity, persona=persona, source="MEMBERSHIP")
    if identity.primary_persona not in personas:
        identity.primary_persona = next(
            (p for p in (Persona.ENTERPRISE_ADMIN, Persona.FIRM_ADMIN, Persona.ENTERPRISE_MEMBER,
                         Persona.PROFESSIONAL, Persona.BUYER) if p in personas), None)


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
        await session.flush()
        await recompute_personas(session, identity_id)


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
    family, audience = None, "APP"
    if actor.session_id:
        old = await session.get(Session, actor.session_id)
        family, audience = (old.family_id, old.audience) if old else (None, "APP")
    pair = await _start_session(session, identity, actor.auth_strength, user_agent, family, actor.auth_time, audience)
    return AuthOut(tokens=pair, user=to_out(identity, await _links(session, identity.id)))


def _password_fingerprint(identity: Identity) -> str:
    # Binds a reset token to the current password hash, so the token dies once used.
    return sha256_hex(identity.password_hash or "")[:16]


async def request_password_reset(session: AsyncSession, email: str) -> str | None:
    """Returns the reset token (to be emailed). Unknown emails return None silently."""
    identity = await session.scalar(select(Identity).where(Identity.email == email.lower()))
    if identity is None or identity.status not in ("ACTIVE", "SUSPENDED"):
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


async def apply_platform_role_revoke(session: AsyncSession, identity_id: uuid.UUID, role: str, requested_by: uuid.UUID,
                                     approved_by: uuid.UUID) -> Identity:
    """Carries out an approved revocation. The person is signed out everywhere so the role disappears at once."""
    from zoikorum.shared.relay import cancel_timer

    identity = await check_platform_role_change(session, requested_by, identity_id, role, False, lock=True)
    identity.platform_roles = sorted(set(identity.platform_roles) - {role})
    identity.platform_role_expiry = {r: t for r, t in (identity.platform_role_expiry or {}).items() if r != role}
    await cancel_timer(session, ROLE_EXPIRY_TIMER, f"{identity_id}:{role}")
    await session.execute(
        update(Session).where(Session.identity_id == identity_id, Session.revoked_at.is_(None)).values(revoked_at=clock.now())
    )
    _evt(session, E.PLATFORM_ROLE_REVOKED, identity, role=role, revokedBy=requested_by, approvedBy=approved_by)
    return identity


async def list_staff(session: AsyncSession, actor: Actor) -> list[StaffMemberOut]:
    actor.require_capability(Cap.IAM_READ)
    rows = (
        await session.scalars(
            select(Identity).where(Identity.platform_roles != []).order_by(Identity.display_name).limit(500)
        )
    ).all()
    return [_staff_out(i) for i in rows]


def _staff_out(i: Identity) -> StaffMemberOut:
    return StaffMemberOut(id=i.id, email=i.email, displayName=i.display_name, platformRoles=sorted(i.platform_roles),
                          mfaEnabled=i.mfa_enabled_at is not None, status=i.status,
                          roleExpiries={r: datetime.fromisoformat(t) for r, t in (i.platform_role_expiry or {}).items()})


async def create_platform_admin(session: AsyncSession, email: str, password: str, display_name: str, country: str,
                                extra_roles: tuple[str, ...] = ()) -> Identity:
    """Bootstrap only (CLI, run by whoever operates the servers). Creates the first Platform Admin or promotes an
    existing account; ``extra_roles`` adds other staff roles at the same time (nobody can grant roles to themselves in
    the app)."""
    unknown = sorted(set(extra_roles) - set(PlatformRole.ALL))
    if unknown:
        raise ValidationFailed(f"Unknown platform role(s): {', '.join(unknown)}")
    identity = await session.scalar(select(Identity).where(Identity.email == email.lower()).with_for_update())
    if identity is None:
        identity = Identity(
            email=email.lower(), password_hash=_hasher.hash(password), display_name=display_name,
            country=country, platform_roles=[PlatformRole.PLATFORM_ADMIN], personas=[], email_confirmed_at=clock.now(),
        )
        session.add(identity)
        await session.flush()
        _evt(session, E.IDENTITY_CREATED, identity, email=identity.email, country=country, accountType="STAFF")
        _evt(session, E.PLATFORM_ROLE_GRANTED, identity, role=PlatformRole.PLATFORM_ADMIN, grantedBy="bootstrap-cli")
    elif PlatformRole.PLATFORM_ADMIN not in identity.platform_roles:
        identity.platform_roles = sorted({*identity.platform_roles, PlatformRole.PLATFORM_ADMIN})
        _evt(session, E.PLATFORM_ROLE_GRANTED, identity, role=PlatformRole.PLATFORM_ADMIN, grantedBy="bootstrap-cli")
    # Run again (e.g. on every deploy) it changes nothing: the password, two-step sign-in and existing roles are kept.
    for role in extra_roles:
        if role not in identity.platform_roles:
            identity.platform_roles = sorted({*identity.platform_roles, role})
            _evt(session, E.PLATFORM_ROLE_GRANTED, identity, role=role, grantedBy="bootstrap-cli")
    return identity


async def lookup_by_email(session: AsyncSession, actor: Actor, email: str) -> StaffMemberOut:
    actor.require_capability(Cap.IAM_READ)
    i = await session.scalar(select(Identity).where(Identity.email == email.strip().lower()))
    if i is None:
        raise NotFound("No account with that email")
    return _staff_out(i)


def _like_escape(text: str) -> str:
    """Searches match literally: % and _ typed by staff are not wildcards."""
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


USER_FILTERS = {"BUYER", "PROFESSIONAL", "FIRM_ADMIN", "ENTERPRISE_ADMIN", "ENTERPRISE_MEMBER", "STAFF"}


async def list_users(session: AsyncSession, actor: Actor, q: str | None, role: str | None, status: str | None,
                     cursor: str | None, limit: int | None) -> dict:
    """Staff Users list: search by name or email, filter by role and status, newest first. Every read is audited.
    Suspending is not done here: it goes through an evidence-based safety case (admin domain, four-eyes)."""
    actor.require_capability(Cap.ACCOUNTS_READ)
    stmt = select(Identity)
    if q and q.strip():
        term = "%" + _like_escape(q.strip().lower()) + "%"
        stmt = stmt.where(or_(func.lower(Identity.email).like(term, escape="\\"),
                              func.lower(Identity.display_name).like(term, escape="\\")))
    if role == "STAFF":
        stmt = stmt.where(Identity.platform_roles != [])
    elif role in USER_FILTERS:
        stmt = stmt.where(literal(role) == any_(Identity.personas))
    elif role:
        raise ValidationFailed("Unknown role filter", code="INVALID_FILTER")
    if status:
        stmt = stmt.where(Identity.status == status)
    stmt, lim = paginate(stmt, Identity, cursor, limit)
    rows = (await session.scalars(stmt)).all()
    last = dict((await session.execute(select(Session.identity_id, func.max(Session.auth_time))
                                       .where(Session.identity_id.in_([i.id for i in rows])).group_by(Session.identity_id))).all())
    record_audit(session, "identity.admin.users_listed", object_type="Identity", object_id=actor.identity_id,
                 details={"search": bool(q and q.strip()), "role": role, "status": status, "count": min(len(rows), lim)})
    return page_of(list(rows), lim, lambda i: UserOut(
        id=i.id, email=i.email, displayName=i.display_name, country=i.country, personas=sorted(i.personas),
        platformRoles=sorted(i.platform_roles), status=i.status, emailConfirmed=i.email_confirmed_at is not None,
        mfaEnabled=i.mfa_enabled_at is not None, createdAt=i.created_at, lastSignInAt=last.get(i.id)))


# ---- Settings: profile details, sessions, privacy requests ---------------------------

async def update_me(session: AsyncSession, actor: Actor, patch: MePatch) -> IdentityOut:
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

    identity = await _get_for_update(session, actor.identity_id)
    changed = []
    if patch.displayName and patch.displayName.strip() != identity.display_name:
        identity.display_name = patch.displayName.strip()
        changed.append("displayName")
    if patch.phone is not None:
        identity.phone_enc = encrypt_field(patch.phone) if patch.phone else None
        changed.append("phone")
    if patch.language and patch.language != identity.language:
        identity.language = patch.language
        changed.append("language")
    if patch.timeZone is not None and patch.timeZone != identity.time_zone:
        if patch.timeZone:
            try:
                ZoneInfo(patch.timeZone)
            except (ZoneInfoNotFoundError, ValueError) as exc:
                raise ValidationFailed("Unknown time zone", code="INVALID_TIME_ZONE") from exc
        identity.time_zone = patch.timeZone or None
        changed.append("timeZone")
    if changed:
        # Field names only: personal values stay out of the event stream.
        _evt(session, E.IDENTITY_PROFILE_UPDATED, identity, changes=changed)
    return to_out(identity, await _links(session, identity.id))


async def list_sessions(session: AsyncSession, actor: Actor) -> list[SessionOut]:
    now = clock.now()
    rows = (await session.scalars(select(Session).where(
        Session.identity_id == actor.identity_id, Session.revoked_at.is_(None), Session.rotated_at.is_(None),
        Session.expires_at > now).order_by(Session.auth_time.desc()).limit(50))).all()
    return [SessionOut(id=s.id, device=s.user_agent, authStrength=s.auth_strength, signedInAt=s.auth_time,
                       current=s.id == actor.session_id) for s in rows]


async def sign_in_signals(session: AsyncSession, actor: Actor, identity_id: uuid.UUID | None = None) -> list[dict]:
    """Recent sign-ins with their advisory risk signals (identity/risk.py): the person's own, or (staff with account
    access) another account's."""
    from zoikorum.domains.identity import risk

    if identity_id is not None and identity_id != actor.identity_id:
        actor.require_capability(Cap.ACCOUNTS_READ)
    return await risk.recent(session, identity_id or actor.identity_id)


async def revoke_session(session: AsyncSession, actor: Actor, session_id: uuid.UUID) -> None:
    s = await session.get(Session, session_id, with_for_update=True)
    if s is None or s.identity_id != actor.identity_id:
        raise NotFound("Session not found")
    if s.revoked_at is None:
        s.revoked_at = clock.now()
        record_event(session, E.SESSION_REVOKED, aggregate_type="Session", aggregate_id=s.id,
                     payload={"identityId": actor.identity_id, "sessionId": s.id, "reason": "USER_SIGNED_OUT_DEVICE"})


