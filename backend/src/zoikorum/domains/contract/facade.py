"""Contract facade - CONTRACT. Signatures and DTOs are fixed."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from zoikorum.domains.contract.models import Contract, Milestone


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
    reference: str = ""  # human reference, e.g. ZK-ENG-1A2B3C4D


def _milestone(m: Milestone) -> MilestoneSummary:
    return MilestoneSummary(m.id, m.contract_id, m.sequence, m.title, m.amount_minor, m.currency, m.status, m.due_date, m.accepted_at)


async def _summary(session: AsyncSession, c: Contract | None) -> ContractSummary | None:
    if c is None:
        return None
    ms = (await session.scalars(select(Milestone).where(Milestone.contract_id == c.id).order_by(Milestone.sequence))).all()
    return ContractSummary(c.id, c.proposal_id, c.request_id, c.organization_id, c.buyer_identity_id, c.professional_id, c.status,
                           c.currency, c.total_minor, c.terms_hash, c.contract_version, c.policy_version_id, tuple(_milestone(m) for m in ms),
                           c.reference)


async def get_contract(session: AsyncSession, contract_id: uuid.UUID) -> ContractSummary | None:
    return await _summary(session, await session.get(Contract, contract_id))


async def get_contract_by_request(session: AsyncSession, request_id: uuid.UUID) -> ContractSummary | None:
    return await _summary(session, await session.scalar(select(Contract).where(Contract.request_id == request_id)))


async def get_contract_by_proposal(session: AsyncSession, proposal_id: uuid.UUID) -> ContractSummary | None:
    return await _summary(session, await session.scalar(select(Contract).where(Contract.proposal_id == proposal_id)))


async def get_milestone(session: AsyncSession, milestone_id: uuid.UUID) -> MilestoneSummary | None:
    m = await session.get(Milestone, milestone_id)
    return _milestone(m) if m else None


async def milestone_acceptor(session: AsyncSession, milestone_id: uuid.UUID) -> uuid.UUID | None:
    milestone = await session.get(Milestone, milestone_id)
    return milestone.accepted_by if milestone else None


async def policy_controls(session: AsyncSession, contract_id: uuid.UUID) -> dict:
    contract = await session.get(Contract, contract_id)
    return dict(contract.terms.get("policySettings", {})) if contract else {}


async def delivery_stats(session: AsyncSession, professional_id: uuid.UUID) -> dict[str, int]:
    """Platform history for a professional's public profile: completed engagements and on-time milestone delivery."""
    from sqlalchemy import func

    completed = await session.scalar(select(func.count()).select_from(Contract).where(
        Contract.professional_id == professional_id, Contract.status == "COMPLETED")) or 0
    rows = (await session.execute(select(Milestone.submitted_at, Milestone.due_date).join(Contract, Contract.id == Milestone.contract_id).where(
        Contract.professional_id == professional_id, Milestone.status == "ACCEPTED", Milestone.due_date.is_not(None)))).all()
    on_time = sum(1 for submitted, due in rows if submitted is not None and submitted.date() <= due)
    return {"completed": int(completed), "milestonesWithDueDate": len(rows), "onTime": on_time}
