from __future__ import annotations

import uuid

from fastapi import APIRouter

from zoikorum.domains.payments import service
from zoikorum.domains.payments.schemas import ChargeOut, EarningsOut, InvoiceOut, PayoutAccountIn, PayoutAccountOut
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


@router.get("/v1/payments/charges", response_model=list[ChargeOut])
async def charges(organizationId: uuid.UUID, actor: CurrentActor, session: DbSession):
    return await service.charges(session, actor, organizationId)
