from __future__ import annotations

import uuid

from fastapi import APIRouter, Query, Response

from zoikorum.domains.escrow import service
from zoikorum.domains.escrow.schemas import (
    AdminEscrowRowOut, AdminEscrowSummaryOut, AutoFundingIn, BulkFundIn, EscrowOut, FundIn, LedgerLineOut, ProtectionIn,
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


@router.get("/releases/{release_id}/receipt")
async def release_receipt(release_id: uuid.UUID, actor: CurrentActor, session: DbSession) -> Response:
    """The receipt for one release as a PDF (both parties; gross, platform fee, net). Audited."""
    data, name = await service.release_receipt_pdf(session, actor, release_id)
    return Response(data, media_type="application/pdf", headers={
        "Content-Disposition": f'attachment; filename="{name}"', "Cache-Control": "no-store"})


@router.get("/by-contract/{contract_id}", response_model=EscrowOut)
async def by_contract(contract_id: uuid.UUID, actor: CurrentActor, session: DbSession):
    return await service.get_by_contract(session, actor, contract_id)


@router.get("/{account_id}", response_model=EscrowOut)
async def get_account(account_id: uuid.UUID, actor: CurrentActor, session: DbSession):
    return await service.get_account(session, actor, account_id)


@router.get("/{account_id}/ledger", response_model=Page[LedgerLineOut])
async def ledger(account_id: uuid.UUID, actor: CurrentActor, session: DbSession, cursor: str | None = None,
                 limit: int | None = Query(default=None, ge=1, le=100)):
    """Ledger lines, oldest first, one page at a time (follow nextCursor; 100 per page by default)."""
    return await service.ledger(session, actor, account_id, cursor, limit)


@router.put("/{account_id}/protection", response_model=EscrowOut)
async def set_protection(account_id: uuid.UUID, body: ProtectionIn, actor: CurrentActor, session: DbSession):
    """Buyer, after both signatures and before the first funding: release model, release approver, dispute-hold confirmation."""
    return await service.set_protection(session, actor, account_id, body)


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


# ---- Ledger snapshots (escrow/snapshots.py): Financial Operations, read-only ---------------------------------------------

@admin_router.get("/{account_id}/ledger-snapshot")
async def admin_ledger_snapshot(account_id: uuid.UUID, actor: CurrentActor, session: DbSession) -> dict:
    """The latest ledger snapshot of this escrow with its integrity checks, and the balances now (snapshot plus later lines)."""
    from zoikorum.domains.escrow import snapshots
    return await snapshots.latest_for(session, actor, account_id)


@admin_router.post("/{account_id}/ledger-snapshot")
async def admin_take_ledger_snapshot(account_id: uuid.UUID, actor: CurrentActor, session: DbSession) -> dict:
    """Take a snapshot now and check the ledger (never changes the ledger or the account)."""
    from zoikorum.domains.escrow import snapshots
    return await snapshots.check_now(session, actor, account_id)
