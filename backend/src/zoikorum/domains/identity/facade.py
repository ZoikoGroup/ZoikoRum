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
    staff: bool = False  # has a platform role: uses the staff web app


def _summary(i: Identity) -> IdentitySummary:
    return IdentitySummary(
        id=i.id, email=i.email, display_name=i.display_name, country=i.country, status=i.status,
        email_confirmed=i.email_confirmed_at is not None, mfa_enabled=i.mfa_enabled_at is not None,
        staff=bool(i.platform_roles),
    )


async def get_identity(session: AsyncSession, identity_id: uuid.UUID) -> IdentitySummary | None:
    i = await session.get(Identity, identity_id)
    return _summary(i) if i else None


async def live_platform_roles(session: AsyncSession, identity_id: uuid.UUID) -> frozenset[str]:
    """Staff roles in force now: none while the account is suspended or restricted, and never a time-limited grant past
    its end."""
    from zoikorum.shared import clock
    i = await session.get(Identity, identity_id)
    return frozenset(i.live_platform_roles(clock.now())) if i and await account_is_active(session, identity_id) else frozenset()


async def account_is_active(session: AsyncSession, identity_id: uuid.UUID) -> bool:
    """Authorization sees restrictions immediately, before status projection catches up."""
    from zoikorum.domains.admin import facade as admin
    account = await get_identity(session, identity_id)
    return bool(account and account.status == "ACTIVE" and not set(await admin.active_restrictions(
        session, "IDENTITY", identity_id)).intersection({"SUSPEND_ACCOUNT", "OFFBOARD"}))


async def validate_session_actor(session: AsyncSession, actor, *, allow_restricted=False, staff_path=False):
    """Checks the session behind an access token on every request and fills in the authority in force now. Platform roles
    take effect only in sessions from the staff sign-in page (admin audience): a staff member's other sessions work as a
    customer account, and staff-only paths (``staff_path``) refuse them outright."""
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
    admin = s.audience == "ADMIN"
    if staff_path and not admin and i.platform_roles:
        raise Forbidden("Staff tools need a staff sign-in. Sign in on the staff sign-in page.", code="ADMIN_SESSION_REQUIRED")
    return replace(actor, platform_roles=frozenset(i.live_platform_roles(clock.now())) if admin else frozenset(),
                   admin_session=admin)


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
    from zoikorum.config import web_url
    return web_url(staff=bool(identity.platform_roles)) + path + '?' + urlencode({'token': token})


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


async def two_step_enabled(session: AsyncSession, identity_id: uuid.UUID) -> bool:
    """An authenticator app or at least one passkey."""
    from sqlalchemy import func

    from zoikorum.domains.identity.models import Passkey

    i = await session.get(Identity, identity_id)
    if i is None:
        return False
    return i.mfa_enabled_at is not None or bool(await session.scalar(
        select(func.count()).select_from(Passkey).where(Passkey.identity_id == identity_id)))


async def personas_of(session: AsyncSession, identity_id: uuid.UUID) -> frozenset[str]:
    i = await session.get(Identity, identity_id)
    return frozenset(i.personas or []) if i else frozenset()


# ---- Staff roles through maker-checker approval (admin/approvals.py) --------------------------------------------------

async def check_platform_role_change(session: AsyncSession, requested_by: uuid.UUID, identity_id: uuid.UUID, role: str,
                                     grant: bool, expires_at: datetime | None = None) -> IdentitySummary:
    """Refuses a role change that could never be applied (unknown role, self-grant, own Platform Admin removal, role not
    held ...). Returns the account it is for."""
    from zoikorum.domains.identity import service
    return _summary(await service.check_platform_role_change(session, requested_by, identity_id, role, grant, expires_at))


async def apply_platform_role_change(session: AsyncSession, identity_id: uuid.UUID, role: str, grant: bool,
                                     expires_at: datetime | None, requested_by: uuid.UUID, approved_by: uuid.UUID) -> list[str]:
    """Carries out an approved grant (optionally time-limited) or revocation; returns the account's staff roles after it."""
    from zoikorum.domains.identity import service
    if grant:
        identity = await service.apply_platform_role_grant(session, identity_id, role, expires_at, requested_by, approved_by)
    else:
        identity = await service.apply_platform_role_revoke(session, identity_id, role, requested_by, approved_by)
    return sorted(identity.platform_roles)


async def staff_holding(session: AsyncSession, roles: tuple[str, ...]) -> list[uuid.UUID]:
    """Active staff who hold one of ``roles`` now (approvers to notify)."""
    from sqlalchemy import any_, literal, or_
    from zoikorum.shared import clock

    rows = (await session.scalars(select(Identity).where(or_(*(literal(r) == any_(Identity.platform_roles) for r in roles)),
                                                         Identity.status == "ACTIVE").limit(500))).all()
    now = clock.now()
    return [i.id for i in rows if set(i.live_platform_roles(now)).intersection(roles)]


# ---- Staff console search (admin/search.py) --------------------------------------------------------------------------

async def staff_search_accounts(session: AsyncSession, term: str, exact_id: uuid.UUID | None, limit: int) -> list[IdentitySummary]:
    """Accounts whose name or email contains ``term`` (or whose id is ``exact_id``), names A-Z. The caller checks the
    staff member may see accounts and masks the email before showing it."""
    from sqlalchemy import func, or_

    like = "%" + term.strip().lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
    match = [func.lower(Identity.display_name).like(like, escape="\\"), func.lower(Identity.email).like(like, escape="\\")]
    if exact_id:
        match.append(Identity.id == exact_id)
    rows = (await session.scalars(select(Identity).where(or_(*match)).order_by(Identity.display_name, Identity.id).limit(limit))).all()
    return [_summary(i) for i in rows]


async def duplicate_exists(session: AsyncSession, suspicion_id: uuid.UUID) -> bool:
    """A duplicate-account suspicion with this id (staff case ownership checks the case is real)."""
    from zoikorum.domains.identity.models import DuplicateSuspicion

    return await session.get(DuplicateSuspicion, suspicion_id) is not None


async def staff_with_roles(session: AsyncSession, roles: frozenset[str] | set[str]) -> list[tuple[IdentitySummary, frozenset[str]]]:
    """Active staff holding at least one of ``roles``, by name, with all their platform roles (who can own a case)."""
    from sqlalchemy import any_, literal, or_

    if not roles:
        return []
    rows = (await session.scalars(select(Identity).where(or_(*(literal(r) == any_(Identity.platform_roles) for r in sorted(roles))),
                                                         Identity.status == "ACTIVE").order_by(Identity.display_name).limit(500))).all()
    return [(_summary(i), frozenset(i.platform_roles)) for i in rows]
