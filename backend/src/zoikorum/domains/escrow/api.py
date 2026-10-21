from __future__ import annotations

import uuid

from fastapi import APIRouter, Query

from zoikorum.domains.escrow import service
from zoikorum.domains.escrow.schemas import (
    AdminEscrowRowOut, AdminEscrowSummaryOut, AutoFundingIn, BulkFundIn, EscrowOut, FundIn, LedgerLineOut,
)
from zoikorum.shared.auth import CurrentActor
from zoikorum.shared.db import DbSession
from zoikorum.shared.http import Page
from zoikorum.shared.idempotency import IdempotencyKey

router = APIRouter(prefix="/v1/escrow", tags=["escrow"])
# Deliberately no endpoint releases money: release happens only when a milestone is accepted (MILESTONE_ACCEPTED).


@router.get("/organization/{org_id}/overview")
async def organization_overview(org_id: uuid.UUID, actor: CurrentActor, session: DbSession) -> dict:
    """Enterprise payments dashboard: money held and frozen per vendor, what awaits funding, the release timeline."""
    return await service.organization_overview(session, actor, org_id)


@router.post("/bulk-fund")
async def bulk_fund(body: BulkFundIn, actor: CurrentActor, session: DbSession, idem: IdempotencyKey) -> dict:
    """Fund milestones on several engagements at once; each one is checked and funded separately."""
    return await idem.run(session, actor, lambda: service.bulk_fund(session, actor, body))


@router.get("/by-contract/{contract_id}", response_model=EscrowOut)
async def by_contract(contract_id: uuid.UUID, actor: CurrentActor, session: DbSession):
    return await service.get_by_contract(session, actor, contract_id)


@router.get("/{account_id}", response_model=EscrowOut)
async def get_account(account_id: uuid.UUID, actor: CurrentActor, session: DbSession):
    return await service.get_account(session, actor, account_id)


@router.get("/{account_id}/ledger", response_model=list[LedgerLineOut])
async def ledger(account_id: uuid.UUID, actor: CurrentActor, session: DbSession):
    return await service.ledger(session, actor, account_id)


@router.post("/{account_id}/fund", response_model=EscrowOut)
async def fund(account_id: uuid.UUID, body: FundIn, actor: CurrentActor, session: DbSession, idem: IdempotencyKey):
    """Buyer funds milestones. The money is captured by the payment provider, then held until acceptance."""
    return await idem.run(session, actor, lambda: service.fund(session, actor, account_id, body))


@router.put("/{account_id}/auto-funding", response_model=EscrowOut)
async def set_auto_funding(account_id: uuid.UUID, body: AutoFundingIn, actor: CurrentActor, session: DbSession):
    """Buyer: fund each new retainer cycle automatically from a saved payment method (null turns it off)."""
    return await service.set_auto_funding(session, actor, account_id, body.paymentMethodToken)


# Staff admin console: protected funds across the platform (outside the /v1/escrow prefix).
admin_router = APIRouter(prefix="/v1/admin/escrow", tags=["escrow"])


@admin_router.get("", response_model=Page[AdminEscrowRowOut])
async def admin_escrow(actor: CurrentActor, session: DbSession, status_: str | None = Query(default=None, alias="status", max_length=30),
                       currency: str | None = Query(default=None, min_length=3, max_length=3),
                       cursor: str | None = None, limit: int | None = Query(default=None, ge=1, le=100)):
    """Financial Operations / Platform Admin: every milestone allocation and its state. Reads are audited."""
    return await service.admin_escrow(session, actor, status_, currency, cursor, limit)


@admin_router.get("/summary", response_model=AdminEscrowSummaryOut)
async def admin_escrow_summary(actor: CurrentActor, session: DbSession):
    return await service.admin_escrow_summary(session, actor)
