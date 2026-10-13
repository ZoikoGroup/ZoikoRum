"""Firm memberships (shared/privacy.py). The sole administrator of a firm with members must hand over first."""

from __future__ import annotations

import uuid

from sqlalchemy import any_, func, literal, select
from sqlalchemy.ext.asyncio import AsyncSession

from zoikorum.domains.firm.models import Firm, FirmMember
from zoikorum.shared import privacy
from zoikorum.shared.auth import FirmRole


async def export(session: AsyncSession, identity_id: uuid.UUID) -> dict:
    return {"firmMemberships": await privacy.rows(session, FirmMember, FirmMember.identity_id == identity_id)}


async def blockers(session: AsyncSession, identity_id: uuid.UUID) -> list[str]:
    reasons = []
    admin = literal(FirmRole.FIRM_ADMIN) == any_(FirmMember.roles)
    mine = (await session.execute(select(Firm.id, Firm.legal_name).join(FirmMember, FirmMember.firm_id == Firm.id)
                                  .where(FirmMember.identity_id == identity_id, FirmMember.status == "ACTIVE", admin))).all()
    for firm_id, name in mine:
        others = select(func.count()).select_from(FirmMember).where(
            FirmMember.firm_id == firm_id, FirmMember.status == "ACTIVE", FirmMember.identity_id != identity_id)
        if not await session.scalar(others.where(admin)) and await session.scalar(others):
            reasons.append(f"You are the only administrator of {name}. Make another member an administrator first.")
    return reasons


privacy.register("firm", export=export, blockers=blockers)
