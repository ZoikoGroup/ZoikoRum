from __future__ import annotations

import uuid

from fastapi import APIRouter, Header, Request, Response

from zoikorum.domains.payments import reconciliation, service, webhooks
from zoikorum.domains.payments.schemas import (
    ChargeOut, EarningsOut, InvoiceOut, PayoutAccountIn, PayoutAccountOut, ReconcileIn, ReconciliationOut, RefundOut,
)
from zoikorum.shared.auth import CurrentActor
from zoikorum.shared.db import DbSession

router = APIRouter(tags=["payments"])


@router.put("/v1/payout-accounts/me", response_model=PayoutAccountOut)
async def set_payout_account(body: PayoutAccountIn, actor: CurrentActor, session: DbSession):
    """Professional: where payouts go. Needs a fresh two-step confirmation and Trust Tier B."""
    return await service.set_payout_account(session, actor, body)


@router.get("/v1/payments/earnings/me", response_model=EarningsOut)
async def earnings(actor: CurrentActor, session: DbSession):
    return await service.earnings(session, actor)


@router.get("/v1/payments/invoices", response_model=list[InvoiceOut])
async def invoices(organizationId: uuid.UUID, actor: CurrentActor, session: DbSession):
    return await service.invoices(session, actor, organizationId)


@router.get("/v1/payments/invoices/{invoice_id}/pdf")
async def invoice_pdf(invoice_id: uuid.UUID, actor: CurrentActor, session: DbSession) -> Response:
    """The invoice as a PDF (members of the buyer organisation). Audited."""
    data, name = await service.invoice_pdf(session, actor, invoice_id)
    return Response(data, media_type="application/pdf", headers={
        "Content-Disposition": f'attachment; filename="{name}"', "Cache-Control": "no-store"})


@router.get("/v1/payments/charges", response_model=list[ChargeOut])
async def charges(organizationId: uuid.UUID, actor: CurrentActor, session: DbSession):
    return await service.charges(session, actor, organizationId)


@router.get("/v1/payments/refunds", response_model=list[RefundOut])
async def refunds(organizationId: uuid.UUID, actor: CurrentActor, session: DbSession):
    return await service.refunds(session, actor, organizationId)


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


@router.get("/v1/payments/reconciliations", response_model=list[ReconciliationOut])
async def reconciliations(actor: CurrentActor, session: DbSession):
    """Financial Ops: daily reconciliation results, newest first."""
    return await reconciliation.list_batches(session, actor)


@router.post("/v1/payments/reconciliations", response_model=ReconciliationOut)
async def run_reconciliation(body: ReconcileIn, actor: CurrentActor, session: DbSession):
    """Financial Ops: (re-)run reconciliation for one day."""
    return await reconciliation.run(session, actor, body.day)
