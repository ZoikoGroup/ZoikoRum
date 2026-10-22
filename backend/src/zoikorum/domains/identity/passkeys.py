"""Passkeys (WebAuthn): sign in with the device's fingerprint, face or PIN instead of a password and code (ADR-008).

* Adding one needs the account password, so a borrowed signed-in browser cannot quietly add a way back in.
* A passkey sign-in counts as two-step (AuthStrength.PASSKEY): it is bound to this site and cannot be phished. The same
  rules as password sign-in apply: lockout, suspended or closed accounts, staff only on the staff sign-in page.
* A passkey can also confirm a sensitive action (step-up) instead of the 6-digit code.
* Every challenge is created by the server, kept server-side and works once, for five minutes.
* The relying party is ZK_WEBAUTHN_RP_ID (default: the web app's host name); the customer and staff app addresses are
  the accepted origins, so with separate apps the RP ID must be their shared parent domain (e.g. your-domain.com).
"""

from __future__ import annotations

import json
import secrets
import uuid
from datetime import timedelta
from urllib.parse import urlsplit

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from webauthn import (
    generate_authentication_options,
    generate_registration_options,
    options_to_json,
    verify_authentication_response,
    verify_registration_response,
)
from webauthn.helpers import base64url_to_bytes, bytes_to_base64url
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria,
    PublicKeyCredentialDescriptor,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

from zoikorum.config import get_settings, web_url
from zoikorum.domains.identity import service
from zoikorum.domains.identity.models import Identity, Passkey, PasskeyChallenge, Session
from zoikorum.domains.identity.schemas import AuthOut, PasskeyOut, TokenPair
from zoikorum.shared import clock
from zoikorum.shared.auth import Actor, AuthStrength
from zoikorum.shared.crypto import sha256_hex
from zoikorum.shared.errors import Conflict, Forbidden, NotFound, Unauthenticated, ValidationFailed
from zoikorum.shared.event_catalog import E
from zoikorum.shared.events import record_audit, record_event

CHALLENGE_TTL = timedelta(minutes=5)
MAX_PASSKEYS = 10
RP_NAME = "Zoikorum"


def relying_party() -> tuple[str, list[str]]:
    s = get_settings()
    rp_id = s.webauthn_rp_id or urlsplit(s.frontend_url).hostname or "localhost"
    return rp_id, sorted({web_url(staff=False), web_url(staff=True)})


def _options(opts) -> dict:
    return json.loads(options_to_json(opts))


async def _new_challenge(session: AsyncSession, purpose: str, identity_id: uuid.UUID | None = None) -> bytes:
    now = clock.now()
    # Expired challenges are never needed again: tidy a few on the way.
    stale = select(PasskeyChallenge.id).where(PasskeyChallenge.expires_at < now - timedelta(days=1)).limit(200).scalar_subquery()
    await session.execute(delete(PasskeyChallenge).where(PasskeyChallenge.id.in_(stale)))
    challenge = secrets.token_bytes(32)
    session.add(PasskeyChallenge(challenge_sha256=sha256_hex(challenge), purpose=purpose, identity_id=identity_id,
                                 expires_at=now + CHALLENGE_TTL))
    await session.flush()
    return challenge


async def _take_challenge(session: AsyncSession, credential: dict, purpose: str, identity_id: uuid.UUID | None = None) -> bytes:
    """The server-issued challenge this response answers; it works once and only for its purpose and account."""
    try:
        client_data = json.loads(base64url_to_bytes(credential["response"]["clientDataJSON"]))
        challenge = base64url_to_bytes(client_data["challenge"])
    except Exception as exc:  # noqa: BLE001 - malformed browser response
        raise ValidationFailed("The passkey response is not readable", code="PASSKEY_INVALID") from exc
    row = await session.scalar(select(PasskeyChallenge).where(
        PasskeyChallenge.challenge_sha256 == sha256_hex(challenge)).with_for_update())
    if (row is None or row.used_at is not None or row.expires_at < clock.now() or row.purpose != purpose
            or (identity_id is not None and row.identity_id != identity_id)):
        raise Unauthenticated("This passkey request has expired. Please try again.", code="PASSKEY_CHALLENGE_INVALID")
    row.used_at = clock.now()
    return challenge


def _out(p: Passkey) -> PasskeyOut:
    return PasskeyOut(id=p.id, name=p.name, backedUp=p.backed_up, createdAt=p.created_at, lastUsedAt=p.last_used_at)


# ---- Managing your passkeys ----------------------------------------------------------------------------------------------

async def list_passkeys(session: AsyncSession, actor: Actor) -> list[PasskeyOut]:
    rows = (await session.scalars(select(Passkey).where(Passkey.identity_id == actor.identity_id)
                                  .order_by(Passkey.created_at))).all()
    return [_out(p) for p in rows]


async def registration_options(session: AsyncSession, actor: Actor, password: str) -> dict:
    identity = await service._get_for_update(session, actor.identity_id)
    try:
        service._hasher.verify(identity.password_hash or "", password)
    except Exception as exc:  # noqa: BLE001 - argon2 VerificationError and friends
        raise Unauthenticated("Your password is incorrect", code="PASSWORD_INCORRECT") from exc
    existing = (await session.scalars(select(Passkey.credential_id).where(Passkey.identity_id == identity.id))).all()
    if len(existing) >= MAX_PASSKEYS:
        raise Conflict(f"You can have up to {MAX_PASSKEYS} passkeys. Remove one first.", code="TOO_MANY_PASSKEYS")
    rp_id, _ = relying_party()
    challenge = await _new_challenge(session, "register", identity.id)
    return _options(generate_registration_options(
        rp_id=rp_id, rp_name=RP_NAME, user_id=identity.id.bytes, user_name=identity.email,
        user_display_name=identity.display_name, challenge=challenge, timeout=300_000,
        exclude_credentials=[PublicKeyCredentialDescriptor(id=base64url_to_bytes(c)) for c in existing],
        authenticator_selection=AuthenticatorSelectionCriteria(
            resident_key=ResidentKeyRequirement.REQUIRED, user_verification=UserVerificationRequirement.REQUIRED)))


async def register(session: AsyncSession, actor: Actor, name: str, credential: dict) -> PasskeyOut:
    identity = await service._get_for_update(session, actor.identity_id)
    challenge = await _take_challenge(session, credential, "register", identity.id)
    rp_id, origins = relying_party()
    try:
        v = verify_registration_response(credential=credential, expected_challenge=challenge, expected_rp_id=rp_id,
                                         expected_origin=origins, require_user_verification=True)
    except Exception as exc:  # noqa: BLE001 - InvalidRegistrationResponse and malformed input
        raise ValidationFailed("The passkey could not be verified. Please try again.", code="PASSKEY_INVALID") from exc
    credential_id = bytes_to_base64url(v.credential_id)
    if await session.scalar(select(Passkey.id).where(Passkey.credential_id == credential_id)):
        raise Conflict("This passkey is already added", code="PASSKEY_EXISTS")
    transports = [t for t in (credential.get("response", {}).get("transports") or []) if isinstance(t, str)][:6]
    p = Passkey(identity_id=identity.id, credential_id=credential_id, public_key=v.credential_public_key,
                sign_count=v.sign_count, transports=transports, name=(name or "").strip()[:100] or "Passkey",
                backed_up=bool(v.credential_backed_up))
    session.add(p)
    await session.flush()
    service._evt(session, E.PASSKEY_ADDED, identity, passkeyId=p.id, name=p.name)
    record_audit(session, "identity.passkey.added", object_type="Passkey", object_id=p.id, details={"name": p.name})
    return _out(p)


async def remove(session: AsyncSession, actor: Actor, passkey_id: uuid.UUID) -> None:
    p = await session.get(Passkey, passkey_id, with_for_update=True)
    if p is None or p.identity_id != actor.identity_id:
        raise NotFound("Passkey not found")
    identity = await service._get_for_update(session, actor.identity_id)
    await session.delete(p)
    service._evt(session, E.PASSKEY_REMOVED, identity, passkeyId=passkey_id, name=p.name)
    record_audit(session, "identity.passkey.removed", object_type="Passkey", object_id=passkey_id, details={"name": p.name})


# ---- Signing in ---------------------------------------------------------------------------------------------------------

async def login_options(session: AsyncSession) -> dict:
    """No account named: the browser offers the passkeys it holds for this site (discoverable credentials)."""
    rp_id, _ = relying_party()
    challenge = await _new_challenge(session, "login")
    return _options(generate_authentication_options(rp_id=rp_id, challenge=challenge, timeout=300_000,
                                                    user_verification=UserVerificationRequirement.REQUIRED))


async def _verify(session: AsyncSession, credential: dict, p: Passkey, challenge: bytes) -> bool:
    rp_id, origins = relying_party()
    try:
        v = verify_authentication_response(credential=credential, expected_challenge=challenge, expected_rp_id=rp_id,
                                           expected_origin=origins, credential_public_key=p.public_key,
                                           credential_current_sign_count=p.sign_count, require_user_verification=True)
    except Exception:  # noqa: BLE001 - wrong signature, origin, counter going backwards (a cloned key), malformed
        return False
    p.sign_count, p.last_used_at = v.new_sign_count, clock.now()
    return True


async def login(session: AsyncSession, credential: dict, user_agent: str | None, portal: str | None) -> AuthOut | service.LoginFailure:
    p = await session.scalar(select(Passkey).where(Passkey.credential_id == str(credential.get("id", ""))).with_for_update())
    if p is None:
        raise Unauthenticated("This passkey is not registered with Zoikorum. Sign in with your password.", code="PASSKEY_UNKNOWN")
    identity = await session.scalar(select(Identity).where(Identity.id == p.identity_id).with_for_update())
    challenge = await _take_challenge(session, credential, "login")
    if identity.locked_until and identity.locked_until > clock.now():
        raise Unauthenticated("Account temporarily locked after repeated failures", code="ACCOUNT_LOCKED")
    if identity.status not in ("ACTIVE", "SUSPENDED"):
        raise Forbidden("This account is not active", code="ACCOUNT_NOT_ACTIVE")
    if not await _verify(session, credential, p, challenge):
        service._count_failure(identity)
        service._evt(session, E.AUTHENTICATION_FAILED, identity, reason="BAD_PASSKEY", lockedUntil=identity.locked_until)
        return service.LoginFailure("The passkey could not be verified", "PASSKEY_INVALID")
    staff = bool(identity.platform_roles)  # checked after the signature, as with passwords
    if portal == "staff" and not staff:
        return service.LoginFailure("This sign-in is for Zoikorum staff only. Customers and professionals sign in on the "
                                    "main sign-in page.", "NOT_STAFF_ACCOUNT")
    if portal == "customer" and staff:
        return service.LoginFailure("Staff accounts sign in on the staff sign-in page.", "USE_STAFF_SIGN_IN")
    identity.failed_login_count, identity.locked_until = 0, None
    pair = await service._start_session(session, identity, AuthStrength.PASSKEY, user_agent,
                                        audience="ADMIN" if portal == "staff" else "APP")
    service._evt(session, E.AUTHENTICATION_SUCCEEDED, identity, authStrength=AuthStrength.PASSKEY)
    return AuthOut(tokens=pair, user=service.to_out(identity, await service._links(session, identity.id)))


# ---- Confirming a sensitive action (step-up) ----------------------------------------------------------------------------

async def step_up_options(session: AsyncSession, actor: Actor) -> dict:
    mine = (await session.scalars(select(Passkey.credential_id).where(Passkey.identity_id == actor.identity_id))).all()
    if not mine:
        raise Conflict("Add a passkey first, or use the code from your authenticator app", code="NO_PASSKEY")
    rp_id, _ = relying_party()
    challenge = await _new_challenge(session, "step_up", actor.identity_id)
    return _options(generate_authentication_options(
        rp_id=rp_id, challenge=challenge, timeout=300_000, user_verification=UserVerificationRequirement.REQUIRED,
        allow_credentials=[PublicKeyCredentialDescriptor(id=base64url_to_bytes(c)) for c in mine]))


async def step_up(session: AsyncSession, actor: Actor, credential: dict, user_agent: str | None) -> TokenPair | service.LoginFailure:
    p = await session.scalar(select(Passkey).where(Passkey.credential_id == str(credential.get("id", "")),
                                                   Passkey.identity_id == actor.identity_id).with_for_update())
    if p is None:
        raise Unauthenticated("Use one of your own passkeys", code="PASSKEY_UNKNOWN")
    identity = await service._get_for_update(session, actor.identity_id)
    challenge = await _take_challenge(session, credential, "step_up", actor.identity_id)
    if identity.locked_until and identity.locked_until > clock.now():
        raise Unauthenticated("Too many failed attempts. Try again in a few minutes.", code="ACCOUNT_LOCKED")
    if not await _verify(session, credential, p, challenge):
        service._count_failure(identity)
        service._evt(session, E.AUTHENTICATION_FAILED, identity, reason="BAD_PASSKEY_STEP_UP", lockedUntil=identity.locked_until)
        return service.LoginFailure("The passkey could not be verified", "PASSKEY_INVALID")
    identity.failed_login_count = 0
    family, audience = None, "APP"
    if actor.session_id:
        old = await session.get(Session, actor.session_id)
        family, audience = (old.family_id, old.audience) if old else (None, "APP")
    pair = await service._start_session(session, identity, AuthStrength.PASSKEY, user_agent, family_id=family, audience=audience)
    record_event(session, E.STEP_UP_COMPLETED, aggregate_type="Identity", aggregate_id=identity.id,
                 payload={"identityId": identity.id, "method": "PASSKEY"})
    return pair


async def count(session: AsyncSession, identity_id: uuid.UUID) -> int:
    return await session.scalar(select(func.count()).select_from(Passkey).where(Passkey.identity_id == identity_id)) or 0
