"""Dispute facade - CONTRACT. Signatures and DTOs are fixed; implement bodies."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True)
class DisputeSummary:
    id: uuid.UUID
    contract_id: uuid.UUID
    milestone_ids: tuple[uuid.UUID, ...]
    category: str
    status: str
    initiated_by_identity_id: uuid.UUID | None  # None for automated platform triggers


async def get_dispute(session: AsyncSession, dispute_id: uuid.UUID) -> DisputeSummary | None:
    raise NotImplementedError


async def open_disputes_for_contract(session: AsyncSession, contract_id: uuid.UUID) -> list[DisputeSummary]:
    raise NotImplementedError
