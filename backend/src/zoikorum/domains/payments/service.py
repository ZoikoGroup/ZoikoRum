"""Payments domain (Step 8): charges for escrow funding, professional payout accounts, payouts and buyer invoices
(BUILD_SPEC s.payments, Payments & Escrow doc phases 7-8).

Tokens only: no raw card or bank data. Provider webhooks live in ``webhooks.py`` and daily reconciliation in
``reconciliation.py``; chargebacks reverse escrow funding through PAYMENT_CHARGED_BACK.
"""

from __future__ import annotations

import uuid
import asyncio

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from zoikorum.domains.buyer import facade as buyer_facade
from zoikorum.domains.contract import facade as contract_facade
from zoikorum.domains.payments.models import INVOICE_NUMBER_SEQ, Invoice, PaymentIntent, Payout, PayoutAccount, Refund
from zoikorum.domains.payments.providers import get_provider
from zoikorum.domains.payments.schemas import ChargeOut, EarningsOut, InvoiceOut, PayoutAccountIn, PayoutAccountOut, PayoutOut, RefundOut
from zoikorum.domains.professional import facade as professional_facade
from zoikorum.domains.trust import facade as trust_facade
from zoikorum.config import get_settings
from zoikorum.shared import clock
from zoikorum.shared.auth import Actor
from zoikorum.shared.errors import Forbidden, NotFound, PolicyBlocked, ValidationFailed
from zoikorum.shared.event_catalog import E
from zoikorum.shared.events import record_audit, record_event
from zoikorum.shared.money import MoneyDTO


def _m(minor: int, ccy: str) -> MoneyDTO:
    return MoneyDTO(amountMinor=minor, currency=ccy)


# ---- Charges (escrow funding) ------------------------------------------------------------------

async def charge_for_funding(session: AsyncSession, payload: dict) -> None:
    """Consumer of ESCROW_FUNDING_REQUESTED. Idempotent per funding."""
    funding_id = uuid.UUID(str(payload["fundingId"]))
    if await session.scalar(select(PaymentIntent.id).where(PaymentIntent.funding_id == funding_id)):
        return
    provider = get_provider()
    pi = PaymentIntent(funding_id=funding_id, escrow_account_id=uuid.UUID(str(payload["escrowAccountId"])),
                       contract_id=uuid.UUID(str(payload["contractId"])), organization_id=uuid.UUID(str(payload["organizationId"])),
                       amount_minor=int(payload["amountMinor"]), currency=payload["currency"], provider=provider.name)
    session.add(pi)
    await session.flush()
    base = {"paymentIntentId": pi.id, "escrowAccountId": pi.escrow_account_id, "fundingId": funding_id,
            "amountMinor": pi.amount_minor, "currency": pi.currency}
    record_event(session, E.PAYMENT_INTENT_CREATED, aggregate_type="PaymentIntent", aggregate_id=pi.id, tenant_id=pi.organization_id, payload=base)
    result = await asyncio.to_thread(provider.charge, payload["paymentMethodToken"], pi.amount_minor, pi.currency,
                                     idempotency_key=str(funding_id))
    pi.method_label = result.method_label
    pi.provider_ref = result.provider_ref
    if result.ok and result.pending:
        pi.status = "CREATED"
    elif result.ok:
        pi.status, pi.provider_ref, pi.captured_at = "CAPTURED", result.provider_ref, clock.now()
        record_event(session, E.PAYMENT_CAPTURED, aggregate_type="PaymentIntent", aggregate_id=pi.id, tenant_id=pi.organization_id,
                     payload={**base, "providerRef": result.provider_ref})
    else:
        pi.status, pi.failure_code, pi.failure_message = "FAILED", result.failure_code, result.failure_message
        record_event(session, E.PAYMENT_FAILED, aggregate_type="PaymentIntent", aggregate_id=pi.id, tenant_id=pi.organization_id,
                     payload={**base, "failureCode": result.failure_code, "failureMessage": result.failure_message})


# ---- Release: invoice for the buyer, payout for the professional --------------------------------

async def _send_payout(session: AsyncSession, p: Payout, account: PayoutAccount) -> None:
    payload = {"payoutId": p.id, "professionalId": p.professional_id, "releaseId": p.release_id, "amountMinor": p.amount_minor,
               "currency": p.currency}
    p.status = "INITIATED"
    p.expected_at = clock.add_business_days(clock.now(), get_settings().payout_settlement_business_days)
    record_event(session, E.PAYOUT_INITIATED, aggregate_type="Payout", aggregate_id=p.id, tenant_id=p.professional_id, payload=payload)
    provider = get_provider()
    try:
        if provider.name == "stripe" and p.transfer_ref:
            p.provider_attempt += 1
            result = await asyncio.to_thread(provider.bank_payout, account.provider_account_ref, p.amount_minor, p.currency,
                                             idempotency_key=f"{p.release_id}:{p.provider_attempt}")
        else:
            result = await asyncio.to_thread(provider.payout, account.provider_account_ref, p.amount_minor, p.currency,
                                             idempotency_key=str(p.release_id))
            if provider.name == "stripe" and result.ok:
                p.transfer_ref = result.provider_ref
    except ValidationFailed:
        from zoikorum.domains.payments.providers import PayoutResult
        result = PayoutResult(False, failure_message="The payment partner rejected the payout. Review your connected account before retrying.")
    if result.provider_ref:
        p.provider_ref = result.provider_ref
    if result.ok and result.pending:
        p.status = "INITIATED"
    elif result.ok:
        # The fake provider confirms at once; a real one confirms later through the payout.paid webhook.
        p.status, p.provider_ref, p.settled_at = "SETTLED", result.provider_ref, clock.now()
        record_event(session, E.PAYOUT_SETTLED, aggregate_type="Payout", aggregate_id=p.id, tenant_id=p.professional_id, payload=payload)
    else:
        p.status, p.failure_message = "FAILED", result.failure_message
        record_event(session, E.PAYOUT_FAILED, aggregate_type="Payout", aggregate_id=p.id, tenant_id=p.professional_id,
                     payload={**payload, "failureMessage": result.failure_message})


async def on_released(session: AsyncSession, payload: dict) -> None:
    """Consumer of ESCROW_RELEASED. Idempotent per release."""
    release_id = uuid.UUID(str(payload["releaseId"]))
    if await session.scalar(select(Payout.id).where(Payout.release_id == release_id)):
        return
    ccy, gross, fee, net = payload["currency"], int(payload["grossMinor"]), int(payload["feeMinor"]), int(payload["netMinor"])
    contract_id = uuid.UUID(str(payload["contractId"]))
    milestone_id = uuid.UUID(str(payload["milestoneId"])) if payload.get("milestoneId") else None
    m = await contract_facade.get_milestone(session, milestone_id) if milestone_id else None
    contract = await contract_facade.get_contract(session, contract_id)

    number = f"ZK-INV-{await session.scalar(INVOICE_NUMBER_SEQ.next_value().select()):06d}"
    # Tax via the TaxCalculator seam: 0 until tax rules per jurisdiction are configured.
    inv = Invoice(number=number, release_id=release_id, organization_id=uuid.UUID(str(payload["organizationId"])), contract_id=contract_id,
                  milestone_id=milestone_id, lines=[{"description": f"M{m.sequence} {m.title}" if m else "Accepted work", "amountMinor": gross}],
                  tax_minor=0, total_minor=gross, currency=ccy, issued_at=clock.now())
    session.add(inv)
    await session.flush()
    record_event(session, E.INVOICE_ISSUED, aggregate_type="Invoice", aggregate_id=inv.id, tenant_id=inv.organization_id,
                 payload={"invoiceId": inv.id, "invoiceNumber": number, "organizationId": inv.organization_id, "contractId": contract_id,
                          "milestoneId": milestone_id, "totalMinor": gross, "currency": ccy})

    professional_id = uuid.UUID(str(payload["professionalId"]))
    p = Payout(release_id=release_id, professional_id=professional_id, contract_id=contract.id if contract else contract_id,
               milestone_id=milestone_id, gross_minor=gross, fee_minor=fee, amount_minor=net, currency=ccy, status="QUEUED")
    session.add(p)
    await session.flush()
    account = await session.scalar(select(PayoutAccount).where(PayoutAccount.professional_id == professional_id, PayoutAccount.status == "ACTIVE"))
    if account is not None:
        await _send_payout(session, p, account)  # otherwise QUEUED until the professional adds a payout account


# ---- Professional: payout account and earnings -------------------------------------------------------

def delay_reason(p: Payout) -> str | None:
    """Plain-language reason a payout has not arrived (Professional Dashboard s.12: "Delayed (with reason)")."""
    if p.status == "QUEUED":
        return "Waiting for your payout account. Add one under Payout details to receive this payment."
    if p.status == "FAILED":
        return f"{p.failure_message or 'The transfer failed'}. Update your payout account and we will retry."
    if p.status == "INITIATED" and p.expected_at is not None and p.expected_at < clock.now():
        return "Taking longer than usual at the bank. We are checking with the payment provider."
    return None


def _account_out(a: PayoutAccount) -> PayoutAccountOut:
    return PayoutAccountOut(holderName=a.holder_name, country=a.country, currency=a.currency, label=f"Bank account •••• {a.last4}",
                            status=a.status, createdAt=a.created_at)


async def _my_professional(session: AsyncSession, actor: Actor):
    pro = await professional_facade.get_professional_by_identity(session, actor.identity_id)
    if pro is None:
        raise NotFound("You have not created a professional profile yet", code="PROFILE_NOT_FOUND")
    return pro


async def set_payout_account(session: AsyncSession, actor: Actor, body: PayoutAccountIn) -> PayoutAccountOut:
    """Needs a fresh two-step confirmation, Trust Tier B or above and clear restrictions (compliance checks)."""
    pro = await _my_professional(session, actor)
    trust = await trust_facade.get_trust(session, pro.id)
    if trust.tier == "C" or trust.dimensions.get("restrictions") != "CLEAR":
        raise PolicyBlocked("Payouts need a verified identity (Trust Tier B) and clear restrictions screening", code="PAYOUT_COMPLIANCE_REQUIRED")
    actor.require_step_up()
    digits = body.accountNumber.replace(" ", "")
    ref = get_provider().create_payout_account(body.holderName, body.country, body.currency, digits)
    account = await session.scalar(select(PayoutAccount).where(PayoutAccount.professional_id == pro.id).with_for_update())
    if account is None:
        account = PayoutAccount(professional_id=pro.id, created_by=actor.identity_id, holder_name="", country="", currency="", last4="",
                                provider=get_provider().name, provider_account_ref="")
        session.add(account)
    account.holder_name, account.country, account.currency, account.last4 = body.holderName.strip(), body.country, body.currency, digits[-4:]
    account.provider_account_ref, account.status = ref, "ACTIVE"
    await session.flush()
    record_audit(session, "payments.payout_account.updated", object_type="PayoutAccount", object_id=account.id, tenant_id=pro.id,
                 details={"last4": account.last4, "country": account.country, "currency": account.currency})
    # Release anything that was waiting for an account, and retry failed transfers.
    waiting = (await session.scalars(select(Payout).where(Payout.professional_id == pro.id, Payout.status.in_(("QUEUED", "FAILED")))
                                     .with_for_update())).all()
    for p in waiting:
        await _send_payout(session, p, account)
    return _account_out(account)


async def earnings(session: AsyncSession, actor: Actor) -> EarningsOut:
    pro = await _my_professional(session, actor)
    account = await session.scalar(select(PayoutAccount).where(PayoutAccount.professional_id == pro.id))
    payouts = (await session.scalars(select(Payout).where(Payout.professional_id == pro.id).order_by(Payout.created_at.desc()).limit(200))).all()
    now = clock.now()
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    states = (("settled", ("SETTLED",)), ("pending", ("QUEUED", "INITIATED")), ("failed", ("FAILED",)))
    # Aggregate the entire history, independently of the latest-200 detail window.
    aggregates = (await session.execute(select(Payout.currency,
        *(func.sum(case((Payout.status.in_(statuses), Payout.amount_minor), else_=0)) for _, statuses in states),
        func.sum(Payout.fee_minor),
        func.sum(case(((Payout.status == "SETTLED") & (Payout.settled_at >= month_start) &
                       (Payout.settled_at <= now), Payout.amount_minor), else_=0))
    ).where(Payout.professional_id == pro.id).group_by(Payout.currency).order_by(Payout.currency))).all()
    grouped = {row[0]: {key: _m(int(amount or 0), row[0])
               for key, amount in zip(("settled", "pending", "failed", "fees"), row[1:5])} for row in aggregates}
    if not grouped:
        currency = account.currency if account else "USD"
        grouped[currency] = {key: _m(0, currency) for key in ("settled", "pending", "failed", "fees")}
    totals = next(iter(grouped.values())) if len(grouped) == 1 else {}
    monthly = [_m(int(row[5] or 0), row[0]) for row in aggregates]
    return EarningsOut(payoutAccount=_account_out(account) if account else None, totals=totals,
                       totalsByCurrency=grouped, monthlySettledByCurrency=monthly, payouts=[PayoutOut(
        id=p.id, contractId=p.contract_id, milestoneId=p.milestone_id, gross=_m(p.gross_minor, p.currency), fee=_m(p.fee_minor, p.currency),
        net=_m(p.amount_minor, p.currency), status=p.status, failureMessage=p.failure_message, expectedAt=p.expected_at,
        delayReason=delay_reason(p), settledAt=p.settled_at, createdAt=p.created_at)
        for p in payouts])


# ---- Buyer: invoices and charges -------------------------------------------------------------------

async def _require_member(session: AsyncSession, actor: Actor, organization_id: uuid.UUID) -> None:
    if not await buyer_facade.get_member_roles(session, organization_id, actor.identity_id):
        raise Forbidden("You are not a member of this organisation")


async def invoices(session: AsyncSession, actor: Actor, organization_id: uuid.UUID) -> list[InvoiceOut]:
    await _require_member(session, actor, organization_id)
    rows = (await session.scalars(select(Invoice).where(Invoice.organization_id == organization_id).order_by(Invoice.created_at.desc()).limit(200))).all()
    return [InvoiceOut(id=i.id, number=i.number, contractId=i.contract_id, milestoneId=i.milestone_id, lines=i.lines, tax=_m(i.tax_minor, i.currency),
                       total=_m(i.total_minor, i.currency), issuedAt=i.issued_at) for i in rows]


async def charges(session: AsyncSession, actor: Actor, organization_id: uuid.UUID) -> list[ChargeOut]:
    await _require_member(session, actor, organization_id)
    rows = (await session.scalars(select(PaymentIntent).where(PaymentIntent.organization_id == organization_id)
                                  .order_by(PaymentIntent.created_at.desc()).limit(200))).all()
    return [ChargeOut(id=p.id, contractId=p.contract_id, amount=_m(p.amount_minor, p.currency), status=p.status, methodLabel=p.method_label,
                      failureMessage=p.failure_message, createdAt=p.created_at, capturedAt=p.captured_at,
                      chargedBackAt=p.charged_back_at) for p in rows]


async def has_valid_payout_account(session: AsyncSession, professional_id: uuid.UUID) -> bool:
    return bool(await session.scalar(select(PayoutAccount.id).where(PayoutAccount.professional_id == professional_id,
                                                                    PayoutAccount.status == "ACTIVE")))


# ---- Refunds ----------------------------------------------------------------------------------------------

async def on_refunded(session: AsyncSession, payload: dict) -> None:
    """Consumer of ESCROW_REFUNDED: return the money to the original payment method. Idempotent per escrow refund."""
    escrow_refund_id = uuid.UUID(str(payload["refundId"]))
    if await session.scalar(select(Refund.id).where(Refund.escrow_refund_id == escrow_refund_id)):
        return
    funding_ids = [uuid.UUID(str(f)) for f in payload.get("fundingIds") or []]
    intent = await session.scalar(select(PaymentIntent).where(PaymentIntent.funding_id.in_(funding_ids), PaymentIntent.status == "CAPTURED")) \
        if funding_ids else None
    r = Refund(escrow_refund_id=escrow_refund_id, payment_intent_id=intent.id if intent else None,
               organization_id=uuid.UUID(str(payload["organizationId"])), contract_id=uuid.UUID(str(payload["contractId"])),
               milestone_id=uuid.UUID(str(payload["milestoneId"])) if payload.get("milestoneId") else None,
               dispute_id=uuid.UUID(str(payload["disputeId"])) if payload.get("disputeId") else None,
               amount_minor=int(payload["amountMinor"]), currency=payload["currency"], status="INITIATED")
    session.add(r)
    await session.flush()
    base = {"refundId": r.id, "escrowRefundId": escrow_refund_id, "organizationId": r.organization_id, "amountMinor": r.amount_minor,
            "currency": r.currency}
    record_event(session, E.REFUND_INITIATED, aggregate_type="Refund", aggregate_id=r.id, tenant_id=r.organization_id, payload=base)
    result = await asyncio.to_thread(get_provider().refund, intent.provider_ref if intent else None, r.amount_minor, r.currency,
                                     idempotency_key=str(escrow_refund_id))
    r.provider_ref = result.provider_ref
    if result.ok and result.pending:
        r.status = "INITIATED"
    elif result.ok:
        r.status, r.provider_ref, r.settled_at = "SETTLED", result.provider_ref, clock.now()
        record_event(session, E.REFUND_SETTLED, aggregate_type="Refund", aggregate_id=r.id, tenant_id=r.organization_id, payload=base)
    else:
        r.status = "FAILED"


async def refunds(session: AsyncSession, actor: Actor, organization_id: uuid.UUID) -> list[RefundOut]:
    await _require_member(session, actor, organization_id)
    rows = (await session.scalars(select(Refund).where(Refund.organization_id == organization_id).order_by(Refund.created_at.desc()).limit(200))).all()
    return [RefundOut(id=r.id, contractId=r.contract_id, milestoneId=r.milestone_id, disputeId=r.dispute_id, amount=_m(r.amount_minor, r.currency),
                      status=r.status, createdAt=r.created_at, settledAt=r.settled_at) for r in rows]
