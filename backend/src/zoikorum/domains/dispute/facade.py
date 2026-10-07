"""Dispute facade - CONTRACT. Signatures and DTOs are fixed."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from zoikorum.domains.dispute.models import DisputeCase


@dataclass(frozen=True)
class DisputeSummary:
    id: uuid.UUID
    contract_id: uuid.UUID
    milestone_ids: tuple[uuid.UUID, ...]
    category: str
    status: str
    initiated_by_identity_id: uuid.UUID | None  # None for automated platform triggers


def _summary(c: DisputeCase) -> DisputeSummary:
    return DisputeSummary(c.id, c.contract_id, tuple(uuid.UUID(m) for m in c.milestone_ids), c.category, c.status, c.initiated_by)


async def get_dispute(session: AsyncSession, dispute_id: uuid.UUID) -> DisputeSummary | None:
    c = await session.get(DisputeCase, dispute_id)
    return _summary(c) if c else None


async def open_disputes_for_contract(session: AsyncSession, contract_id: uuid.UUID) -> list[DisputeSummary]:
    from zoikorum.domains.dispute.service import open_for_contract

    return [_summary(c) for c in await open_for_contract(session, contract_id)]
