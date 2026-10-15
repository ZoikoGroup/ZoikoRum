"""Organisation API keys (Enterprise: connect your own systems; client rate tier).

* A key acts as the Organisation Admin who created it, never with more rights: if that person leaves the organisation or
  loses the admin role, the key stops working. READ keys may only read; WRITE keys may also create and change.
* A key never satisfies two-step confirmation, so signing, releases and other confirmed actions stay with people.
* Sign-in, account, staff and key-management endpoints are refused for keys.
* Each key has its own request budget: STANDARD, or ENTERPRISE when staff raise it.
* The key is shown once; only its SHA-256 fingerprint is stored. Creating and revoking keys is audited.
"""

from __future__ import annotations

import hashlib
import secrets
import time
import uuid
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from zoikorum.domains.buyer.models import ApiKey, OrgMember, Organization
from zoikorum.shared import clock
from zoikorum.shared.auth import Actor, AuthStrength, OrgRole, PlatformRole
from zoikorum.shared.errors import Conflict, Forbidden, NotFound, Unauthenticated
from zoikorum.shared.events import record_audit

PREFIX = "zk_"
BLOCKED_PATHS = ("/v1/auth", "/v1/me", "/v1/admin", "/v1/ops", "/v1/staff", "/v1/flags")
TIER_LIMITS = {"STANDARD": (120, 240), "ENTERPRISE": (1200, 2400)}  # requests per minute, burst
MAX_KEYS = 25


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _out(k: ApiKey) -> dict:
    return {"id": k.id, "name": k.name, "prefix": k.prefix, "scope": k.scope, "tier": k.tier, "createdBy": k.created_by,
            "createdAt": k.created_at, "expiresAt": k.expires_at, "lastUsedAt": k.last_used_at, "revokedAt": k.revoked_at,
            "active": k.revoked_at is None and (k.expires_at is None or k.expires_at > clock.now())}


async def _require_admin(session: AsyncSession, actor: Actor, org_id: uuid.UUID) -> None:
    from zoikorum.domains.buyer.service import _require_member
    await _require_member(session, actor, org_id, OrgRole.ORG_ADMIN)


async def list_keys(session: AsyncSession, actor: Actor, org_id: uuid.UUID) -> list[dict]:
    await _require_admin(session, actor, org_id)
    rows = (await session.scalars(select(ApiKey).where(ApiKey.organization_id == org_id).order_by(ApiKey.created_at.desc()))).all()
    return [_out(k) for k in rows]


async def create_key(session: AsyncSession, actor: Actor, org_id: uuid.UUID, name: str, scope: str, expires_days: int | None) -> dict:
    await _require_admin(session, actor, org_id)
    actor.require_step_up()
    active = [k for k in (await session.scalars(select(ApiKey).where(ApiKey.organization_id == org_id, ApiKey.revoked_at.is_(None)))).all()]
    if len(active) >= MAX_KEYS:
        raise Conflict(f"An organisation can have {MAX_KEYS} active keys; revoke one first", code="TOO_MANY_KEYS")
    prefix = PREFIX + secrets.token_hex(4)
    token = f"{prefix}_{secrets.token_urlsafe(32)}"
    k = ApiKey(organization_id=org_id, name=name.strip(), prefix=prefix, key_hash=_hash(token), scope=scope, tier="STANDARD",
               created_by=actor.identity_id, expires_at=clock.now() + timedelta(days=expires_days) if expires_days else None)
    session.add(k)
    await session.flush()
    record_audit(session, "buyer.api_key.created", object_type="ApiKey", object_id=k.id, tenant_id=org_id,
                 details={"name": k.name, "scope": scope, "prefix": prefix})
    return {**_out(k), "key": token, "note": "Copy this key now: it is not shown again."}


async def revoke_key(session: AsyncSession, actor: Actor, org_id: uuid.UUID, key_id: uuid.UUID) -> dict:
    await _require_admin(session, actor, org_id)
    actor.require_step_up()
    k = await session.get(ApiKey, key_id, with_for_update=True)
    if k is None or k.organization_id != org_id:
        raise NotFound("API key not found")
    if k.revoked_at is None:
        k.revoked_at = clock.now()
        record_audit(session, "buyer.api_key.revoked", object_type="ApiKey", object_id=k.id, tenant_id=org_id, details={"prefix": k.prefix})
        _cache.pop(k.key_hash, None)
    await session.flush()
    return _out(k)


async def set_tier(session: AsyncSession, actor: Actor, key_id: uuid.UUID, tier: str) -> dict:
    """Staff raise or lower a key's request budget (the client rate tier agreed with the organisation)."""
    actor.require_platform_role(PlatformRole.PLATFORM_ADMIN)
    actor.require_step_up()
    k = await session.get(ApiKey, key_id, with_for_update=True)
    if k is None:
        raise NotFound("API key not found")
    k.tier = tier
    _cache.pop(k.key_hash, None)
    record_audit(session, "buyer.api_key.tier_changed", object_type="ApiKey", object_id=k.id, tenant_id=k.organization_id, details={"tier": tier})
    await session.flush()
    return _out(k)


# ---- Using a key ---------------------------------------------------------------------------------------------------

_cache: dict[str, tuple[float, str | None, str]] = {}  # hash -> (cached at, prefix if valid, tier); 60 s


async def budget_of(session: AsyncSession, token: str) -> tuple[str, tuple[int, int]] | None:
    """(prefix, (requests per minute, burst)) of a valid key, for its rate budget; None for anything else.
    Cached for a minute, so a request does not cost a database read."""
    h = _hash(token)
    hit = _cache.get(h)
    if not hit or time.monotonic() - hit[0] >= 60:
        k = await session.scalar(select(ApiKey).where(ApiKey.key_hash == h))
        valid = k is not None and k.revoked_at is None and (k.expires_at is None or k.expires_at > clock.now())
        hit = _cache[h] = (time.monotonic(), k.prefix if valid else None, k.tier if valid else "STANDARD")
    return (hit[1], TIER_LIMITS.get(hit[2], TIER_LIMITS["STANDARD"])) if hit[1] else None


async def principal(session: AsyncSession, token: str, path: str, method: str) -> Actor:
    """The actor a key stands for: its creator, with only the creator's current roles in that one organisation."""
    from zoikorum.domains.identity import facade as identity_facade

    k = await session.scalar(select(ApiKey).where(ApiKey.key_hash == _hash(token)))
    if k is None or k.revoked_at is not None or (k.expires_at and k.expires_at <= clock.now()):
        raise Unauthenticated("Invalid or revoked API key")
    if path.startswith(BLOCKED_PATHS) or "/api-keys" in path:
        raise Forbidden("API keys cannot use this endpoint", code="API_KEY_NOT_ALLOWED")
    if method not in ("GET", "HEAD", "OPTIONS") and k.scope != "WRITE":
        raise Forbidden("This API key is read-only", code="API_KEY_READ_ONLY")
    member = await session.scalar(select(OrgMember).where(OrgMember.organization_id == k.organization_id,
                                                          OrgMember.identity_id == k.created_by, OrgMember.status == "ACTIVE"))
    org = await session.get(Organization, k.organization_id)
    account = await identity_facade.get_identity(session, k.created_by)
    if not member or OrgRole.ORG_ADMIN not in member.roles or not org or org.status != "ACTIVE" or not account or account.status != "ACTIVE":
        raise Unauthenticated("This API key's owner no longer administers the organisation; create a new key")
    if not k.last_used_at or clock.now() - k.last_used_at > timedelta(minutes=1):
        k.last_used_at = clock.now()
        await session.commit()
    return Actor(identity_id=k.created_by, session_id=None, email=account.email,
                 personas=await identity_facade.personas_of(session, k.created_by),
                 org_roles={str(k.organization_id): frozenset(member.roles)}, auth_strength=AuthStrength.PASSWORD, auth_time=None)
