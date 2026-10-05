"""Escrow facade - CONTRACT. Signatures and DTOs are fixed; implement bodies."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession


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
    raise NotImplementedError


async def ledger_totals(session: AsyncSession, since: datetime, until: datetime) -> dict[str, int]:
    """Totals per entry type (BUYER_FUNDING, ESCROW_RELEASE, PLATFORM_FEE, REFUND, PAYOUT) per
    currency, keyed "<TYPE>:<CCY>", for daily reconciliation against payments."""
    raise NotImplementedError
