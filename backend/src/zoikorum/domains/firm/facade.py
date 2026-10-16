"""Firm facade - read-only interface other domains use."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

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
