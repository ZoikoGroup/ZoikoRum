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


async def get_allocation_states_for_amendment(
    session: AsyncSession, contract_id: uuid.UUID, milestone_ids: set[uuid.UUID]
) -> dict[uuid.UUID, str] | None:
    """Lock the account and selected allocations while a contract amendment is validated."""
    account = await session.scalar(
        select(EscrowAccount).where(EscrowAccount.contract_id == contract_id).with_for_update()
    )
    if account is None:
        return None
    allocations = (await session.scalars(
        select(Allocation)
        .where(Allocation.account_id == account.id, Allocation.milestone_id.in_(milestone_ids))
        .order_by(Allocation.milestone_id)
        .with_for_update()
    )).all()
    return {allocation.milestone_id: allocation.state for allocation in allocations}
async def ledger_movements(session: AsyncSession, since: datetime, until: datetime) -> dict[tuple[str, str], tuple[int, int]]:
    """Daily reconciliation input: (ledger account, currency) -> (debits, credits) posted in [since, until).
    Accounts: BUYER_CLEARING, ESCROW_HELD, PRO_PAYABLE, PLATFORM_REVENUE, BUYER_REFUND_PAYABLE, CHARGEBACK_REVERSAL, ..."""
    from zoikorum.domains.escrow.service import movements

    return await movements(session, since, until)


async def ledger_totals(session: AsyncSession, since: datetime, until: datetime) -> dict[str, int]:
    """Totals per entry type (BUYER_FUNDING, ESCROW_RELEASE, PLATFORM_FEE, REFUND, PAYOUT) per
    currency, keyed "<TYPE>:<CCY>", for daily reconciliation against payments."""
    from zoikorum.domains.escrow.service import totals

    return await totals(session, since, until)
