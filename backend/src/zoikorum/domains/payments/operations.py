"""Financial Operations worklist (Payments & Escrow: failed payouts, failed refunds and chargeback losses need a person).

Automatic retries already run (payouts when the account is fixed, refunds daily). This is where staff see what is still
stuck, retry it now, or close it with a recorded outcome when it was settled another way (append-only, audited).
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from zoikorum.domains.buyer import facade as buyer_facade
from zoikorum.domains.contract import facade as contract_facade
from zoikorum.domains.escrow import facade as escrow_facade
from zoikorum.domains.payments import service
from zoikorum.domains.payments.models import OpsResolution, PaymentIntent, Payout, PayoutAccount, Refund
from zoikorum.domains.payments.providers import get_provider
from zoikorum.domains.payments.schemas import OpsItemOut, OpsResolveIn, OpsWorklistOut
from zoikorum.domains.professional import facade as professional_facade
from zoikorum.shared import clock
from zoikorum.shared.auth import Actor, PlatformRole
from zoikorum.shared.errors import Conflict, DomainError, NotFound
from zoikorum.shared.events import record_audit
from zoikorum.shared.money import MoneyDTO

STAFF = (PlatformRole.FINANCIAL_OPS, PlatformRole.PLATFORM_ADMIN)
WAITING_TOO_LONG = timedelta(days=14)  # a payout still waiting for the professional's account after this is chased


async def _names(session: AsyncSession, contract_id, organization_id=None, professional_id=None) -> tuple[str, str, str]:
    c = await contract_facade.get_contract(session, contract_id)
    org = await buyer_facade.get_organization(session, organization_id or (c.organization_id if c else None)) \
        if (organization_id or c) else None
    pro = await professional_facade.get_professional(session, professional_id or (c.professional_id if c else None)) \
        if (professional_id or c) else None
    return (c.reference if c else "—", org.name if org else "—", pro.display_name if pro else "—")


async def worklist(session: AsyncSession, actor: Actor, include_resolved: bool = False) -> OpsWorklistOut:
    actor.require_platform_role(*STAFF)
    resolved = {(r.item_kind, r.item_id): r for r in (await session.scalars(select(OpsResolution))).all()}
    items: list[OpsItemOut] = []

    async def add(kind, item_id, amount, currency, contract_id, problem, since, can_retry, org=None, pro=None):
        res = resolved.get((kind, item_id))
        if res is not None and not include_resolved:
            return
        engagement, org_name, pro_name = await _names(session, contract_id, org, pro)
        items.append(OpsItemOut(kind=kind, id=item_id, amount=MoneyDTO(amountMinor=amount, currency=currency),
                                engagement=engagement, contractId=contract_id, buyer=org_name, professional=pro_name,
                                problem=problem, since=since, canRetry=can_retry and res is None,
                                resolution=f"{res.outcome}: {res.note}" if res else None,
                                resolvedAt=res.created_at if res else None))

    payouts = (await session.scalars(select(Payout).where(
        (Payout.status == "FAILED") | ((Payout.status == "QUEUED") & (Payout.created_at < clock.now() - WAITING_TOO_LONG))))).all()
    for p in payouts:
        account = await session.scalar(select(PayoutAccount).where(PayoutAccount.professional_id == p.professional_id))
        problem = (p.failure_message or "The transfer failed") if p.status == "FAILED" else \
            "Still waiting for the professional to add a payout account"
        await add("PAYOUT", p.id, p.amount_minor, p.currency, p.contract_id, problem, p.updated_at,
                  p.status == "FAILED" and account is not None and account.status == "ACTIVE", pro=p.professional_id)
    for r in (await session.scalars(select(Refund).where(Refund.status == "FAILED"))).all():
        await add("REFUND", r.id, r.amount_minor, r.currency, r.contract_id,
                  r.failure_message or "The payment provider could not return the money", r.updated_at, True,
                  org=r.organization_id)
    for loss in await escrow_facade.chargeback_losses(session):
        await add("CHARGEBACK_LOSS", loss.reference_id, loss.amount_minor, loss.currency, loss.contract_id,
                  "Chargeback on money already paid out: the platform carried the loss", loss.booked_at, False,
                  org=loss.organization_id, pro=loss.professional_id)
    items.sort(key=lambda i: i.since)
    return OpsWorklistOut(items=items, open=sum(1 for i in items if i.resolution is None))


async def retry(session: AsyncSession, actor: Actor, kind: str, item_id: uuid.UUID) -> OpsWorklistOut:
    """Retry a failed payout or refund now instead of waiting for the automatic retry. Needs a fresh confirmation."""
    actor.require_platform_role(*STAFF)
    actor.require_step_up()
    if kind == "PAYOUT":
        p = await session.get(Payout, item_id, with_for_update=True)
        if p is None or p.status != "FAILED":
            raise NotFound("No failed payout with that id")
        account = await session.scalar(select(PayoutAccount).where(PayoutAccount.professional_id == p.professional_id,
                                                                   PayoutAccount.status == "ACTIVE"))
        if account is None:
            raise Conflict("The professional has no active payout account; ask them to update it", code="NO_PAYOUT_ACCOUNT")
        await service._send_payout(session, p, account)
    elif kind == "REFUND":
        r = await session.get(Refund, item_id, with_for_update=True)
        if r is None or r.status != "FAILED":
            raise NotFound("No failed refund with that id")
        intent = await session.get(PaymentIntent, r.payment_intent_id) if r.payment_intent_id else None
        try:
            result = await asyncio.to_thread(get_provider().refund, intent.provider_ref if intent else None, r.amount_minor,
                                             r.currency, idempotency_key=f"{r.escrow_refund_id}:ops:{clock.now().isoformat()}")
        except DomainError as exc:
            r.failure_message = str(exc.detail or exc.title)[:300]
        else:
            if result.ok:
                r.provider_ref, r.status = result.provider_ref, "INITIATED" if result.pending else "SETTLED"
                r.settled_at = None if result.pending else clock.now()
                r.failure_message = None
            else:
                r.failure_message = (getattr(result, "failure_message", None) or r.failure_message or "Refused again")[:300]
    else:
        raise Conflict("Only failed payouts and refunds can be retried", code="NOT_RETRYABLE")
    record_audit(session, "payments.ops.retried", object_type=kind.title(), object_id=item_id, details={"kind": kind})
    await session.flush()
    return await worklist(session, actor)


async def resolve(session: AsyncSession, actor: Actor, kind: str, item_id: uuid.UUID, body: OpsResolveIn) -> OpsWorklistOut:
    """Close an item by hand with what happened (e.g. refunded by bank transfer, loss written off). Append-only."""
    actor.require_platform_role(*STAFF)
    actor.require_step_up()
    if kind not in ("PAYOUT", "REFUND", "CHARGEBACK_LOSS"):
        raise NotFound("Unknown item")
    if await session.scalar(select(OpsResolution.id).where(OpsResolution.item_kind == kind, OpsResolution.item_id == item_id)):
        raise Conflict("This item was already resolved", code="ALREADY_RESOLVED")
    session.add(OpsResolution(item_kind=kind, item_id=item_id, outcome=body.outcome, note=body.note.strip(),
                              resolved_by=actor.identity_id))
    record_audit(session, "payments.ops.resolved", object_type=kind.title(), object_id=item_id,
                 details={"outcome": body.outcome, "note": body.note.strip()})
    await session.flush()
    return await worklist(session, actor)
