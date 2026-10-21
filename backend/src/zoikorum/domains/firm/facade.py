"""Firm facade - read-only interface other domains use."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from zoikorum.domains.firm.models import Firm, FirmMember
from zoikorum.shared.auth import FirmRole


@dataclass(frozen=True)
class FirmSummary:
    id: uuid.UUID
    legal_name: str
    trading_name: str | None
    hq_country: str
    size_band: str | None  # 1-5 | 6-20 | 21-100 | 100+
    status: str  # PENDING_VERIFICATION | VERIFIED | SUSPENDED
    has_verified_representative: bool


@dataclass(frozen=True)
class Representative:
    identity_id: uuid.UUID
    display_name: str
    identity_verified: bool


async def representatives(session: AsyncSession, firm_id: uuid.UUID) -> list[Representative]:
    """Active members holding the Authorized Representative role, each with whether their own identity is verified
    (Onboarding s.10: verify the authorized representative's identity, same as the individual flow)."""
    from zoikorum.domains.professional import facade as professional_facade
    from zoikorum.domains.verification import facade as verification_facade

    rows = (await session.scalars(select(FirmMember).where(
        FirmMember.firm_id == firm_id, FirmMember.status == "ACTIVE",
        FirmMember.roles.contains([FirmRole.AUTHORIZED_REPRESENTATIVE])).order_by(FirmMember.display_name))).all()
    out = []
    for m in rows:
        pro = await professional_facade.get_professional_by_identity(session, m.identity_id)
        out.append(Representative(m.identity_id, m.display_name, await verification_facade.identity_verified(
            session, m.identity_id, pro.id if pro else None)))
    return out


async def get_firm(session: AsyncSession, firm_id: uuid.UUID) -> FirmSummary | None:
    f = await session.get(Firm, firm_id)
    if f is None:
        return None
    # Architecture 3.x invariant: a verified firm with at least one representative whose own identity is verified.
    has_rep = f.status == "VERIFIED" and any(r.identity_verified for r in await representatives(session, firm_id))
    return FirmSummary(f.id, f.legal_name, f.trading_name, f.hq_country, f.size_band, f.status, has_rep)


async def member_roles(session: AsyncSession, firm_id: uuid.UUID, identity_id: uuid.UUID) -> frozenset[str]:
    """FIRM_ADMIN | FIRM_MEMBER | AUTHORIZED_REPRESENTATIVE. Empty if not a member."""
    m = await session.scalar(select(FirmMember).where(
        FirmMember.firm_id == firm_id, FirmMember.identity_id == identity_id, FirmMember.status == "ACTIVE"))
    return frozenset(m.roles) if m else frozenset()


# ---- Staff admin console: firms listed beside buyer organisations (buyer.service.admin_organizations) ----------------

@dataclass(frozen=True)
class FirmAdminRow:
    id: uuid.UUID
    name: str  # trading name when set, else the legal name
    country: str
    category: str | None
    status: str  # ACTIVE | SUSPENDED (the console's organisation status)
    verification_status: str  # PENDING_VERIFICATION | VERIFIED | SUSPENDED (the firm's own status)
    member_count: int
    primary_contact: tuple[str, str] | None  # (name, email) of the longest-standing Firm Admin
    created_at: datetime


def _firm_filters(stmt, q: str | None, status: str | None):
    from sqlalchemy import func, or_

    if q and q.strip():
        term = "%" + q.strip().lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        stmt = stmt.where(or_(func.lower(Firm.legal_name).like(term, escape="\\"),
                              func.lower(func.coalesce(Firm.trading_name, "")).like(term, escape="\\")))
    if status == "SUSPENDED":
        stmt = stmt.where(Firm.status == "SUSPENDED")
    elif status:
        stmt = stmt.where(Firm.status != "SUSPENDED")
    return stmt


async def admin_rows(session: AsyncSession, q: str | None, status: str | None, cursor: str | None, limit: int) -> list[FirmAdminRow]:
    """Firms newest first after ``cursor``: up to ``limit`` + 1 rows, the extra one showing that a next page exists."""
    from sqlalchemy import func

    from zoikorum.shared.http import paginate

    stmt, _ = paginate(_firm_filters(select(Firm), q, status), Firm, cursor, limit)
    firms = list((await session.scalars(stmt)).all())
    ids = [f.id for f in firms]
    counts = dict((await session.execute(select(FirmMember.firm_id, func.count()).where(
        FirmMember.firm_id.in_(ids), FirmMember.status == "ACTIVE").group_by(FirmMember.firm_id))).all()) if ids else {}
    contacts: dict[uuid.UUID, tuple[str, str]] = {}
    for m in (await session.scalars(select(FirmMember).where(
            FirmMember.firm_id.in_(ids), FirmMember.status == "ACTIVE", FirmMember.roles.contains([FirmRole.FIRM_ADMIN]))
            .order_by(FirmMember.created_at))).all() if ids else []:
        contacts.setdefault(m.firm_id, (m.display_name, m.email))
    return [FirmAdminRow(f.id, f.trading_name or f.legal_name, f.hq_country, f.primary_category,
                         "SUSPENDED" if f.status == "SUSPENDED" else "ACTIVE", f.status, counts.get(f.id, 0),
                         contacts.get(f.id), f.created_at) for f in firms]


async def admin_counts(session: AsyncSession, since: datetime) -> dict[str, int]:
    """{"total", "suspended", "new"}: every firm, those suspended, and those created since ``since``."""
    from sqlalchemy import func

    total, suspended, new = (await session.execute(select(
        func.count(), func.count().filter(Firm.status == "SUSPENDED"), func.count().filter(Firm.created_at >= since))
        .select_from(Firm))).one()
    return {"total": total or 0, "suspended": suspended or 0, "new": new or 0}
