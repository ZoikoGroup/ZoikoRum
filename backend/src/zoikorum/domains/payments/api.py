from __future__ import annotations

import uuid
from typing import Literal

from fastapi import APIRouter, Header, Query, Request, Response

from zoikorum.domains.admin import facade as admin_facade
from zoikorum.domains.admin.facade import ApprovalRequestOut
from zoikorum.domains.payments import operations, reconciliation, service, webhooks
from zoikorum.domains.payments.schemas import (
    BreakAdvanceIn, ChargeOut, EarningsOut, InvoiceOut, OpsResolveIn, OpsWorklistOut, PayoutAccountIn, PayoutAccountOut, PayoutStatementOut, ReconcileIn,
    ReconciliationBreakOut, ReconciliationOut, RefundOut,
)
from zoikorum.shared.auth import CurrentActor
from zoikorum.shared.db import DbSession
from zoikorum.shared.http import Page

router = APIRouter(tags=["payments"])


@router.put("/v1/payout-accounts/me", response_model=PayoutAccountOut)
async def set_payout_account(body: PayoutAccountIn, actor: CurrentActor, session: DbSession):
    """Professional: where payouts go. Needs a fresh two-step confirmation and an Amber trust light (identity verified)."""
    return await service.set_payout_account(session, actor, body)


@router.get("/v1/payments/earnings/me", response_model=EarningsOut)
async def earnings(actor: CurrentActor, session: DbSession):
    return await service.earnings(session, actor)


@router.get("/v1/payments/invoices", response_model=Page[InvoiceOut])
async def invoices(organizationId: uuid.UUID, actor: CurrentActor, session: DbSession, cursor: str | None = None, limit: int | None = Query(default=None, ge=1, le=100)):
    """Newest first, one page at a time (follow nextCursor)."""
    return await service.invoices(session, actor, organizationId, cursor, limit)


@router.get("/v1/payments/invoices/{invoice_id}/pdf")
async def invoice_pdf(invoice_id: uuid.UUID, actor: CurrentActor, session: DbSession) -> Response:
    """The invoice as a PDF (members of the buyer organisation). Audited."""
    data, name = await service.invoice_pdf(session, actor, invoice_id)
    return Response(data, media_type="application/pdf", headers={
        "Content-Disposition": f'attachment; filename="{name}"', "Cache-Control": "no-store"})


@router.get("/v1/payments/payouts/{payout_id}", response_model=PayoutStatementOut)
async def payout_statement(payout_id: uuid.UUID, actor: CurrentActor, session: DbSession):
    """Professional: the statement for one of your payouts (amounts, engagement, buyer organisation, steps, related
    transactions, masked destination). Financial Operations staff may read any payout (audited). 404 for anyone else."""
    return await service.payout_statement(session, actor, payout_id)


@router.get("/v1/payments/payouts/{payout_id}/pdf")
async def payout_statement_pdf(payout_id: uuid.UUID, actor: CurrentActor, session: DbSession) -> Response:
    """Professional: the statement for one of your payouts as a PDF (gross, platform fee, net, bank, transfer reference). Audited."""
    data, name = await service.payout_statement_pdf(session, actor, payout_id)
    return Response(data, media_type="application/pdf", headers={
        "Content-Disposition": f'attachment; filename="{name}"', "Cache-Control": "no-store"})


@router.get("/v1/payments/charges", response_model=Page[ChargeOut])
async def charges(organizationId: uuid.UUID, actor: CurrentActor, session: DbSession, cursor: str | None = None, limit: int | None = Query(default=None, ge=1, le=100)):
    """Newest first, one page at a time (follow nextCursor)."""
    return await service.charges(session, actor, organizationId, cursor, limit)


@router.get("/v1/payments/refunds", response_model=Page[RefundOut])
async def refunds(organizationId: uuid.UUID, actor: CurrentActor, session: DbSession, cursor: str | None = None, limit: int | None = Query(default=None, ge=1, le=100)):
    """Newest first, one page at a time (follow nextCursor)."""
    return await service.refunds(session, actor, organizationId, cursor, limit)


@router.post("/v1/payments/webhooks/{provider}")
async def provider_webhook(provider: str, request: Request, session: DbSession,
                           webhook_signature: str | None = Header(default=None)):
    """Called by the payment provider, not by users. Signed (HMAC-SHA256, timestamped) and stored once per event id."""
    return await webhooks.handle(session, provider, webhook_signature or request.headers.get("stripe-signature"), await request.body())


@router.get("/v1/payments/configuration")
async def configuration(actor: CurrentActor):
    from zoikorum.domains.payments.integration import configuration
    return configuration()


@router.get("/v1/payments/fundings/{funding_id}/checkout")
async def checkout(funding_id: uuid.UUID, actor: CurrentActor, session: DbSession):
    from zoikorum.domains.payments.integration import checkout
    return await checkout(session, actor, funding_id)


@router.post("/v1/payout-accounts/me/onboarding")
async def onboarding(actor: CurrentActor, session: DbSession):
    from zoikorum.domains.payments.integration import onboarding
    return await onboarding(session, actor)


@router.get("/v1/payments/ops/worklist", response_model=OpsWorklistOut)
async def ops_worklist(actor: CurrentActor, session: DbSession, includeResolved: bool = False):
    """Financial Ops: failed payouts, failed refunds and chargeback losses that still need a person."""
    return await operations.worklist(session, actor, includeResolved)


@router.post("/v1/payments/ops/{kind}/{item_id}/retry", response_model=OpsWorklistOut)
async def ops_retry(kind: Literal["PAYOUT", "REFUND"], item_id: uuid.UUID, actor: CurrentActor, session: DbSession):
    return await operations.retry(session, actor, kind, item_id)


@router.post("/v1/payments/ops/{kind}/{item_id}/resolve", status_code=202, response_model=ApprovalRequestOut)
async def ops_resolve(kind: Literal["PAYOUT", "REFUND", "CHARGEBACK_LOSS"], item_id: uuid.UUID, body: OpsResolveIn,
                      actor: CurrentActor, session: DbSession):
    """Financial Ops: ask to close an item by hand with its outcome (written off, settled outside, recovered). 202: a
    maker-checker approval request (FINANCIAL_EXCEPTION_RESOLVE, status REQUESTED); the item is closed only when a
    second member of Financial Operations (or a Platform Admin) approves it. Retrying stays immediate."""
    payload = {"itemKind": kind, "itemId": str(item_id), "outcome": body.outcome, "note": body.note}
    return await admin_facade.request_approval(session, actor, "FINANCIAL_EXCEPTION_RESOLVE", payload,
                                               body.justification or body.note)


@router.get("/v1/payments/reconciliations", response_model=list[ReconciliationOut])
async def reconciliations(actor: CurrentActor, session: DbSession):
    """Financial Ops: daily reconciliation results, newest first."""
    return await reconciliation.list_batches(session, actor)


@router.post("/v1/payments/reconciliations", response_model=ReconciliationOut)
async def run_reconciliation(body: ReconcileIn, actor: CurrentActor, session: DbSession):
    """Financial Ops: (re-)run reconciliation for one day."""
    return await reconciliation.run(session, actor, body.day)


@router.get("/v1/payments/reconciliation-breaks", response_model=list[ReconciliationBreakOut])
async def reconciliation_breaks(actor: CurrentActor, session: DbSession,
                                status: Literal["OPEN", "EVIDENCE_GATHERING", "REVIEWED", "CLOSED"] | None = None):
    """Financial Ops: suspense items (unmatched differences) found by reconciliation runs, newest day first."""
    return await reconciliation.list_breaks(session, actor, status)


@router.post("/v1/payments/reconciliation-breaks/{break_id}/advance", response_model=ReconciliationBreakOut)
async def advance_reconciliation_break(break_id: uuid.UUID, body: BreakAdvanceIn, actor: CurrentActor, session: DbSession):
    """Financial Ops: move a break one step (OPEN -> EVIDENCE_GATHERING -> REVIEWED -> CLOSED). Closing needs a fresh
    step-up and a different person from the reviewer. Audited."""
    return await reconciliation.advance_break(session, actor, break_id, body)
