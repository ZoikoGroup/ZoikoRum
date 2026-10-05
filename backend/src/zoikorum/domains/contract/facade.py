"""Contract facade - CONTRACT. Signatures and DTOs are fixed; implement bodies."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime

from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True)
class MilestoneSummary:
    id: uuid.UUID
    contract_id: uuid.UUID
    sequence: int
    title: str
    amount_minor: int
    currency: str
    status: str  # PENDING_FUNDING|IN_PROGRESS|SUBMITTED|REVISION_REQUESTED|ACCEPTANCE_PENDING_APPROVAL|ACCEPTED|DISPUTED|CANCELLED
    due_date: date | None
    accepted_at: datetime | None


@dataclass(frozen=True)
class ContractSummary:
    id: uuid.UUID
    proposal_id: uuid.UUID
    request_id: uuid.UUID
    organization_id: uuid.UUID
    buyer_identity_id: uuid.UUID
    professional_id: uuid.UUID
    status: str  # GENERATED|PENDING_SIGNATURE|ACTIVE|COMPLETED|TERMINATED|DISPUTED
    currency: str
    total_minor: int
    terms_hash: str
    contract_version: int
    policy_version_id: uuid.UUID | None
    milestones: tuple[MilestoneSummary, ...]


async def get_contract(session: AsyncSession, contract_id: uuid.UUID) -> ContractSummary | None:
    raise NotImplementedError


async def get_contract_by_proposal(session: AsyncSession, proposal_id: uuid.UUID) -> ContractSummary | None:
    raise NotImplementedError


async def get_milestone(session: AsyncSession, milestone_id: uuid.UUID) -> MilestoneSummary | None:
    raise NotImplementedError
