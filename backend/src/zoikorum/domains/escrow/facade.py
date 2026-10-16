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


async def money_by_professional(session: AsyncSession, professional_ids: list[uuid.UUID]) -> dict[uuid.UUID, dict[str, dict[str, int]]]:
    """Per professional and currency: funds held in escrow now, and released to date. Never converted between currencies."""
    from sqlalchemy import func

    if not professional_ids:
        return {}
    out: dict[uuid.UUID, dict[str, dict[str, int]]] = {}
    for pid, currency, held, released in (await session.execute(
            select(EscrowAccount.professional_id, EscrowAccount.currency, func.sum(EscrowAccount.held_minor),
                   func.sum(EscrowAccount.released_minor))
            .where(EscrowAccount.professional_id.in_(professional_ids))
            .group_by(EscrowAccount.professional_id, EscrowAccount.currency))).all():
        out.setdefault(pid, {})[currency] = {"held": int(held or 0), "released": int(released or 0)}
    return out


async def get_by_contract(session: AsyncSession, contract_id: uuid.UUID) -> EscrowSummary | None:
    a = await session.scalar(select(EscrowAccount).where(EscrowAccount.contract_id == contract_id))
    if a is None:
        return None
    allocs = (await session.scalars(select(Allocation).where(Allocation.account_id == a.id).order_by(Allocation.sequence))).all()
    return EscrowSummary(a.id, a.contract_id, a.organization_id, a.professional_id, a.currency, a.status, a.funded_minor, a.held_minor,
                         a.on_hold_minor, a.released_minor, a.refunded_minor, a.fees_minor,
                         tuple(AllocationSummary(x.milestone_id, x.amount_minor, x.state, x.released_minor, x.refunded_minor) for x in allocs))


@dataclass(frozen=True)
class ChargebackLoss:
    reference_id: uuid.UUID  # the reversed payment
    contract_id: uuid.UUID
    organization_id: uuid.UUID
    professional_id: uuid.UUID
    amount_minor: int
    currency: str
    booked_at: datetime


async def chargeback_losses(session: AsyncSession) -> list[ChargebackLoss]:
    """Chargebacks on money already released: the platform carried the loss (ledger PLATFORM_CHARGEBACK_LOSS)."""
    from sqlalchemy import func

    from zoikorum.domains.escrow.models import LedgerEntry

    rows = (await session.execute(
        select(LedgerEntry.reference_id, EscrowAccount.contract_id, EscrowAccount.organization_id,
               EscrowAccount.professional_id, func.sum(LedgerEntry.debit_minor), LedgerEntry.currency,
               func.min(LedgerEntry.created_at))
        .join(EscrowAccount, EscrowAccount.id == LedgerEntry.account_id)
        .where(LedgerEntry.ledger_account == "PLATFORM_CHARGEBACK_LOSS", LedgerEntry.debit_minor > 0)
        .group_by(LedgerEntry.reference_id, EscrowAccount.contract_id, EscrowAccount.organization_id,
                  EscrowAccount.professional_id, LedgerEntry.currency))).all()
    return [ChargebackLoss(*r) for r in rows]


IN_ESCROW = ("FUNDING", "HELD", "ON_HOLD", "RELEASE_PENDING_APPROVAL")


async def money_in_escrow(session: AsyncSession, contract_id: uuid.UUID) -> bool:
    """True while any milestone's money is being paid in, held, frozen or waiting for release approval."""
    return bool(await session.scalar(
        select(Allocation.id).join(EscrowAccount, EscrowAccount.id == Allocation.account_id)
        .where(EscrowAccount.contract_id == contract_id, Allocation.state.in_(IN_ESCROW)).limit(1)))


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
async def funding_open(session: AsyncSession, funding_id: uuid.UUID) -> bool:
    """Payments charges a funding only while the buyer's request is still open."""
    from zoikorum.domains.escrow.models import Funding

    f = await session.get(Funding, funding_id, with_for_update=True)  # the hourly funding check waits for this charge
    return f is not None and f.status == "REQUESTED"


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


async def ledger_for_contract(session: AsyncSession, contract_id: uuid.UUID) -> list[dict]:
    """The engagement's escrow ledger lines, oldest first (append-only, double-entry)."""
    from zoikorum.domains.escrow.models import LedgerEntry

    account = await session.scalar(select(EscrowAccount).where(EscrowAccount.contract_id == contract_id))
    if account is None:
        return []
    rows = (await session.scalars(select(LedgerEntry).where(LedgerEntry.account_id == account.id)
                                  .order_by(LedgerEntry.created_at))).all()
    return [{"at": r.created_at.isoformat(), "type": r.entry_type, "account": r.ledger_account, "debitMinor": r.debit_minor,
             "creditMinor": r.credit_minor, "currency": r.currency, "memo": r.memo} for r in rows]


async def account_id_for_contract(session: AsyncSession, contract_id: uuid.UUID) -> uuid.UUID | None:
    return await session.scalar(select(EscrowAccount.id).where(EscrowAccount.contract_id == contract_id))


async def kpis(session: AsyncSession, since, until) -> dict:
    """Money through escrow in the period (funded, released, fees, refunded) and held now, per currency."""
    from sqlalchemy import func

    from zoikorum.domains.escrow.models import Funding, Release

    out: dict[str, dict] = {}

    def row(ccy: str) -> dict:
        return out.setdefault(ccy, {"currency": ccy, "fundedMinor": 0, "releasedMinor": 0, "feesMinor": 0, "heldNowMinor": 0,
                                    "frozenNowMinor": 0})
    for ccy, total in (await session.execute(select(Funding.currency, func.sum(Funding.amount_minor)).where(
            Funding.status == "CAPTURED", Funding.captured_at >= since, Funding.captured_at < until).group_by(Funding.currency))).all():
        row(ccy)["fundedMinor"] = int(total or 0)
    for ccy, gross, fee in (await session.execute(select(Release.currency, func.sum(Release.gross_minor), func.sum(Release.fee_minor)).where(
            Release.created_at >= since, Release.created_at < until).group_by(Release.currency))).all():
        row(ccy)["releasedMinor"], row(ccy)["feesMinor"] = int(gross or 0), int(fee or 0)
    for ccy, held, frozen in (await session.execute(select(EscrowAccount.currency, func.sum(EscrowAccount.held_minor),
                                                           func.sum(EscrowAccount.on_hold_minor)).group_by(EscrowAccount.currency))).all():
        row(ccy)["heldNowMinor"], row(ccy)["frozenNowMinor"] = int(held or 0), int(frozen or 0)
    for r in out.values():
        r["takeRateBps"] = round(10000 * r["feesMinor"] / r["releasedMinor"]) if r["releasedMinor"] else None
    return {"byCurrency": sorted(out.values(), key=lambda r: r["currency"])}


async def release_stuck(session: AsyncSession, milestone_id: uuid.UUID) -> bool:
    """Accepted work whose payment is still held in escrow: the release was not approved or still waits for approval."""
    from zoikorum.domains.escrow.models import Release

    x = await session.scalar(select(Allocation).where(Allocation.milestone_id == milestone_id))
    return x is not None and x.state in ("HELD", "RELEASE_PENDING_APPROVAL") and not await session.scalar(
        select(Release.id).where(Release.milestone_id == milestone_id))
