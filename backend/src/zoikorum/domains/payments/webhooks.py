"""Provider webhooks (Engineering Handbook 15.1: "every provider webhook verified and idempotent"; BUILD_SPEC s.payments).

``POST /v1/payments/webhooks/{provider}``:
1. the signature must verify (HMAC-SHA256 with the shared secret, timestamped against replay), otherwise 401;
2. each provider event id is stored once; a repeat is acknowledged and ignored;
3. the event updates the matching charge, payout or refund, and emits the same domain events as the synchronous path.

Event body (provider-neutral; a real provider's adapter maps its own payload to this):
    {"id": "evt_...", "type": "<type>", "data": {"ref": "<provider reference>", "amountMinor": 123, "reason": "...", "message": "..."}}
Types: charge.succeeded · charge.failed · charge.dispute.created (chargeback) · payout.paid · payout.failed ·
refund.succeeded · refund.failed. Unknown types are stored and acknowledged so the provider stops retrying.
"""

from __future__ import annotations

import json

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from zoikorum.domains.payments.models import PaymentIntent, Payout, Refund, WebhookEvent
from zoikorum.domains.payments.providers import get_provider
from zoikorum.shared import clock
from zoikorum.shared.errors import NotFound, Unauthenticated, ValidationFailed
from zoikorum.shared.event_catalog import E
from zoikorum.shared.events import record_audit, record_event


async def handle(session: AsyncSession, provider_name: str, signature: str | None, body: bytes) -> dict:
    provider = get_provider()
    if provider_name != provider.name:
        raise NotFound("Unknown payment provider")
    if not signature or not provider.verify_webhook(signature, body):
        raise Unauthenticated("Webhook signature is missing, invalid or too old", code="INVALID_SIGNATURE")
    try:
        event = json.loads(body)
        event_id, event_type, data = str(event["id"]), str(event["type"]), dict(event.get("data") or {})
    except (ValueError, KeyError, TypeError) as exc:
        raise ValidationFailed("Webhook body is not a valid event", code="INVALID_WEBHOOK") from exc

    stored = await session.scalar(pg_insert(WebhookEvent).values(provider=provider.name, event_id=event_id, event_type=event_type,
                                                                 payload=event, outcome="")
                                  .on_conflict_do_nothing(constraint="uq_webhook_provider_event").returning(WebhookEvent.id))
    if stored is None:
        return {"received": True, "duplicate": True}
    outcome = await _apply(session, event_type, data)
    row = await session.get(WebhookEvent, stored)
    row.outcome = outcome[:200]
    return {"received": True, "duplicate": False, "outcome": outcome}


async def _apply(session: AsyncSession, event_type: str, data: dict) -> str:
    ref = data.get("ref")
    if event_type.startswith("charge."):
        pi = await session.scalar(select(PaymentIntent).where(PaymentIntent.provider_ref == ref).with_for_update()) if ref else None
        if pi is None:
            return "unknown charge reference"
        if event_type == "charge.dispute.created":
            return await chargeback(session, pi, int(data.get("amountMinor") or pi.amount_minor), str(data.get("reason") or "Card issuer dispute"))
        if event_type in ("charge.succeeded", "charge.failed"):
            return _charge_result(session, pi, event_type == "charge.succeeded", str(data.get("message") or "The payment failed"))
    if event_type.startswith("payout."):
        p = await session.scalar(select(Payout).where(Payout.provider_ref == ref).with_for_update()) if ref else None
        if p is None:
            return "unknown payout reference"
        return _payout_result(session, p, event_type == "payout.paid", str(data.get("message") or "The bank returned the transfer"))
    if event_type.startswith("refund."):
        r = await session.scalar(select(Refund).where(Refund.provider_ref == ref).with_for_update()) if ref else None
        if r is None:
            return "unknown refund reference"
        if event_type == "refund.succeeded" and r.status != "SETTLED":
            r.status, r.settled_at = "SETTLED", clock.now()
            record_event(session, E.REFUND_SETTLED, aggregate_type="Refund", aggregate_id=r.id, tenant_id=r.organization_id,
                         payload={"refundId": r.id, "organizationId": r.organization_id, "amountMinor": r.amount_minor, "currency": r.currency})
            return "refund settled"
        if event_type == "refund.failed":
            r.status = "FAILED"
            return "refund failed"
        return "refund already settled"
    return "ignored"


def _charge_result(session: AsyncSession, pi: PaymentIntent, ok: bool, message: str) -> str:
    """Asynchronous capture confirmation (providers that confirm later). Already-final charges are left alone."""
    if pi.status != "CREATED":
        return f"charge already {pi.status.lower()}"
    base = {"paymentIntentId": pi.id, "escrowAccountId": pi.escrow_account_id, "fundingId": pi.funding_id,
            "amountMinor": pi.amount_minor, "currency": pi.currency}
    if ok:
        pi.status, pi.captured_at = "CAPTURED", clock.now()
        record_event(session, E.PAYMENT_CAPTURED, aggregate_type="PaymentIntent", aggregate_id=pi.id, tenant_id=pi.organization_id,
                     payload={**base, "providerRef": pi.provider_ref})
        return "charge captured"
    pi.status, pi.failure_message = "FAILED", message[:300]
    record_event(session, E.PAYMENT_FAILED, aggregate_type="PaymentIntent", aggregate_id=pi.id, tenant_id=pi.organization_id,
                 payload={**base, "failureCode": "provider_failed", "failureMessage": pi.failure_message})
    return "charge failed"


def _payout_result(session: AsyncSession, p: Payout, ok: bool, message: str) -> str:
    payload = {"payoutId": p.id, "professionalId": p.professional_id, "releaseId": p.release_id, "amountMinor": p.amount_minor,
               "currency": p.currency}
    if ok:
        if p.status == "SETTLED":
            return "payout already settled"
        p.status, p.settled_at = "SETTLED", clock.now()
        record_event(session, E.PAYOUT_SETTLED, aggregate_type="Payout", aggregate_id=p.id, tenant_id=p.professional_id, payload=payload)
        return "payout settled"
    if p.status == "FAILED":
        return "payout already failed"
    # A bank can return a transfer even after it looked settled; the professional is asked to fix the account and it is retried.
    p.status, p.settled_at, p.failure_message = "FAILED", None, message[:300]
    record_event(session, E.PAYOUT_FAILED, aggregate_type="Payout", aggregate_id=p.id, tenant_id=p.professional_id,
                 payload={**payload, "failureMessage": p.failure_message})
    return "payout failed"


async def chargeback(session: AsyncSession, pi: PaymentIntent, amount_minor: int, reason: str) -> str:
    """The card issuer reversed a captured payment. Escrow takes the money out (PAYMENT_CHARGED_BACK)."""
    if pi.status == "CHARGED_BACK":
        return "already charged back"
    if pi.status != "CAPTURED":
        return f"charge is {pi.status.lower()}, nothing to reverse"
    amount = max(1, min(amount_minor, pi.amount_minor))
    pi.status, pi.charged_back_at, pi.chargeback_minor, pi.chargeback_reason = "CHARGED_BACK", clock.now(), amount, reason[:200]
    record_event(session, E.PAYMENT_CHARGED_BACK, aggregate_type="PaymentIntent", aggregate_id=pi.id, tenant_id=pi.organization_id,
                 payload={"paymentIntentId": pi.id, "fundingId": pi.funding_id, "escrowAccountId": pi.escrow_account_id,
                          "organizationId": pi.organization_id, "contractId": pi.contract_id, "amountMinor": amount,
                          "currency": pi.currency, "reason": pi.chargeback_reason})
    record_audit(session, "payments.chargeback.received", object_type="PaymentIntent", object_id=pi.id, tenant_id=pi.organization_id,
                 details={"amountMinor": amount, "currency": pi.currency, "reason": pi.chargeback_reason})
    return "chargeback recorded"
