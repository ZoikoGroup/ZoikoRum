"""Public, read-only interface of the identity domain for other domains.

Returns plain DTOs - never ORM objects. In a split deployment this module
becomes an HTTP/gRPC client with the same signatures.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from zoikorum.domains.identity.models import Identity


@dataclass(frozen=True)
class IdentitySummary:
    id: uuid.UUID
    email: str
    display_name: str
    country: str
    status: str
    email_confirmed: bool
    mfa_enabled: bool


def _summary(i: Identity) -> IdentitySummary:
    return IdentitySummary(
        id=i.id, email=i.email, display_name=i.display_name, country=i.country, status=i.status,
        email_confirmed=i.email_confirmed_at is not None, mfa_enabled=i.mfa_enabled_at is not None,
    )


async def get_identity(session: AsyncSession, identity_id: uuid.UUID) -> IdentitySummary | None:
    i = await session.get(Identity, identity_id)
    return _summary(i) if i else None


async def live_platform_roles(session: AsyncSession, identity_id: uuid.UUID) -> frozenset[str]:
    i = await session.get(Identity, identity_id)
    return frozenset(i.platform_roles) if i and await account_is_active(session, identity_id) else frozenset()


async def account_is_active(session: AsyncSession, identity_id: uuid.UUID) -> bool:
    """Authorization sees restrictions immediately, before status projection catches up."""
    from zoikorum.domains.admin import facade as admin
    account = await get_identity(session, identity_id)
    return bool(account and account.status == "ACTIVE" and not set(await admin.active_restrictions(
        session, "IDENTITY", identity_id)).intersection({"SUSPEND_ACCOUNT", "OFFBOARD"}))


async def validate_session_actor(session: AsyncSession, actor, *, allow_restricted=False):
    from dataclasses import replace
    from zoikorum.domains.identity.models import Session
    from zoikorum.shared.errors import Unauthenticated, Forbidden
    from zoikorum.shared import clock
    i = await session.get(Identity, actor.identity_id)
    s = await session.get(Session, actor.session_id) if actor.session_id else None
    if not i or not s or s.identity_id != i.id or s.expires_at <= clock.now():
        raise Unauthenticated("Your session has ended")
    if i.status != "ACTIVE" and not (allow_restricted and i.status == "SUSPENDED"):
        raise Forbidden("This account is restricted", code="ACCOUNT_NOT_ACTIVE")
    if s.revoked_at:
        raise Unauthenticated("Your session has ended")
    return replace(actor, platform_roles=frozenset(i.platform_roles) if i.status == "ACTIVE" else frozenset())


async def notification_account_link(session: AsyncSession, identity_id: uuid.UUID, purpose: str, requested_at=None) -> str | None:
    """Tokens are minted only for delivery, never persisted in events or audit records."""
    from urllib.parse import urlencode
    from zoikorum.config import get_settings
    from zoikorum.domains.identity import tokens
    from zoikorum.domains.identity.service import EMAIL_TOKEN_TTL, RESET_TOKEN_TTL, _password_fingerprint
    identity = await session.get(Identity, identity_id)
    if not identity or (identity.status != 'ACTIVE' and not (purpose == 'password_reset' and identity.status == 'SUSPENDED')):
        return None
    if purpose == 'email_confirm':
        if identity.email_confirmed_at:
            return None
        token = tokens.mint_purpose_token(identity.id, purpose, EMAIL_TOKEN_TTL)
        path = '/confirm-email'
    elif purpose == 'password_reset':
        if requested_at is not None and identity.updated_at > requested_at:
            return None
        token = tokens.mint_purpose_token(identity.id, purpose, RESET_TOKEN_TTL, extra={'pwf': _password_fingerprint(identity)})
        path = '/reset-password'
    else:
        return None
    return get_settings().frontend_url.rstrip('/') + path + '?' + urlencode({'token': token})


async def get_identities(session: AsyncSession, ids: list[uuid.UUID]) -> dict[uuid.UUID, IdentitySummary]:
    if not ids:
        return {}
    rows = (await session.scalars(select(Identity).where(Identity.id.in_(ids)))).all()
    return {r.id: _summary(r) for r in rows}


async def find_by_email(session: AsyncSession, email: str) -> IdentitySummary | None:
    i = await session.scalar(select(Identity).where(Identity.email == email.lower()))
    return _summary(i) if i else None


async def count_accounts(session: AsyncSession) -> dict[str, int]:
    """Platform totals for the operations dashboard: all accounts and accounts per account role."""
    from sqlalchemy import func

    total = await session.scalar(select(func.count()).select_from(Identity)) or 0
    persona = func.unnest(Identity.personas).label("persona")
    rows = (await session.execute(select(persona, func.count()).group_by(persona))).all()
    return {"total": total, **{p: n for p, n in rows}}


async def last_active(session: AsyncSession, ids: list[uuid.UUID]) -> dict[uuid.UUID, datetime]:
    """Most recent sign-in or token refresh per identity (team lists: "Last active")."""
    from sqlalchemy import func

    from zoikorum.domains.identity.models import Session

    if not ids:
        return {}
    rows = await session.execute(select(Session.identity_id, func.max(Session.created_at))
                                 .where(Session.identity_id.in_(ids)).group_by(Session.identity_id))
    return dict(rows.all())
