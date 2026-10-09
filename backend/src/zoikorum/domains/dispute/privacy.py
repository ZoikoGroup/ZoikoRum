"""Disputes the person is party to (shared/privacy.py). Kept; an open dispute blocks account deletion."""

from __future__ import annotations

import uuid

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from zoikorum.domains.dispute.models import DisputeCase
from zoikorum.domains.professional import facade as professional_facade
from zoikorum.shared import privacy


async def _party(session: AsyncSession, identity_id: uuid.UUID):
    pro = await professional_facade.get_professional_by_identity(session, identity_id)
    return or_(DisputeCase.initiated_by == identity_id, *([DisputeCase.professional_id == pro.id] if pro else []))


async def export(session: AsyncSession, identity_id: uuid.UUID) -> dict:
    return {"disputes": await privacy.rows(session, DisputeCase, await _party(session, identity_id))}


async def blockers(session: AsyncSession, identity_id: uuid.UUID) -> list[str]:
    n = await session.scalar(select(func.count()).select_from(DisputeCase).where(
        await _party(session, identity_id), DisputeCase.status != "CLOSED"))
    return [f"{n} dispute(s) are still open."] if n else []


privacy.register("dispute", export=export, blockers=blockers,
                 retained="Dispute cases, evidence and decisions (legal record keeping).")
