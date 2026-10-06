"""Escrow facade - CONTRACT. Signatures and DTOs are fixed."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from zoikorum.domains.escrow.models import Allocation, EscrowAccount


@dataclass(frozen=True)
class AllocationSummary:
    milestone_id: uuid.UUID
    amount_minor: int
    state: str  # UNFUNDED|FUNDING|HELD|ON_HOLD|RELEASE_PENDING_APPROVAL|RELEASED|PARTIALLY_RELEASED|REFUNDED
    released_minor: int
    refunded_minor: int


@dataclass(frozen=True)
class EscrowSummary:
    id: uuid.UUID
    contract_id: uuid.UUID
    organization_id: uuid.UUID
    professional_id: uuid.UUID
    currency: str
    status: str  # UNFUNDED|FUNDED|PARTIALLY_RELEASED|FULLY_RELEASED|DISPUTED|REFUNDED|CLOSED
    funded_minor: int
    held_minor: int  # funds currently protected (incl. on hold)
    on_hold_minor: int  # frozen by dispute
    released_minor: int
    refunded_minor: int
    fees_minor: int
    allocations: tuple[AllocationSummary, ...]


async def get_by_contract(session: AsyncSession, contract_id: uuid.UUID) -> EscrowSummary | None:
    a = await session.scalar(select(EscrowAccount).where(EscrowAccount.contract_id == contract_id))
    if a is None:
        return None
    allocs = (await session.scalars(select(Allocation).where(Allocation.account_id == a.id).order_by(Allocation.sequence))).all()
    return EscrowSummary(a.id, a.contract_id, a.organization_id, a.professional_id, a.currency, a.status, a.funded_minor, a.held_minor,
                         a.on_hold_minor, a.released_minor, a.refunded_minor, a.fees_minor,
                         tuple(AllocationSummary(x.milestone_id, x.amount_minor, x.state, x.released_minor, x.refunded_minor) for x in allocs))


async def ledger_totals(session: AsyncSession, since: datetime, until: datetime) -> dict[str, int]:
    """Totals per entry type (BUYER_FUNDING, ESCROW_RELEASE, PLATFORM_FEE, REFUND, PAYOUT) per
    currency, keyed "<TYPE>:<CCY>", for daily reconciliation against payments."""
    from zoikorum.domains.escrow.service import totals

    return await totals(session, since, until)
