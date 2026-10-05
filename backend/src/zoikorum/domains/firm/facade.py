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


async def get_firm(session: AsyncSession, firm_id: uuid.UUID) -> FirmSummary | None:
    f = await session.get(Firm, firm_id)
    if f is None:
        return None
    # A representative only counts as verified once firm verification exists (later step).
    has_rep = f.status == "VERIFIED" and bool(await session.scalar(
        select(FirmMember.id).where(FirmMember.firm_id == firm_id, FirmMember.status == "ACTIVE",
                                    FirmMember.roles.contains([FirmRole.AUTHORIZED_REPRESENTATIVE]))
    ))
    return FirmSummary(f.id, f.legal_name, f.trading_name, f.hq_country, f.size_band, f.status, has_rep)


async def member_roles(session: AsyncSession, firm_id: uuid.UUID, identity_id: uuid.UUID) -> frozenset[str]:
    """FIRM_ADMIN | FIRM_MEMBER | AUTHORIZED_REPRESENTATIVE. Empty if not a member."""
    m = await session.scalar(select(FirmMember).where(
        FirmMember.firm_id == firm_id, FirmMember.identity_id == identity_id, FirmMember.status == "ACTIVE"))
    return frozenset(m.roles) if m else frozenset()
