"""Payments domain (Step 8): charges for escrow funding, professional payout accounts, payouts and buyer invoices
(BUILD_SPEC s.payments, Payments & Escrow doc phases 7-8).

Tokens only: no raw card or bank data. Provider webhooks live in ``webhooks.py`` and daily reconciliation in
``reconciliation.py``; chargebacks reverse escrow funding through PAYMENT_CHARGED_BACK.
"""

from __future__ import annotations

import hashlib
import json
import uuid
import asyncio
from datetime import date, timedelta

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from zoikorum.domains.admin import facade as admin_facade
from zoikorum.domains.buyer import facade as buyer_facade
from zoikorum.domains.contract import facade as contract_facade
from zoikorum.domains.escrow import facade as escrow_facade
from zoikorum.domains.marketplace import facade as marketplace_facade
from zoikorum.domains.payments.models import INVOICE_NUMBER_SEQ, Invoice, PaymentIntent, Payout, PayoutAccount, Refund
from zoikorum.domains.payments.providers import get_provider
from zoikorum.domains.payments.tax import included_tax
from zoikorum.domains.payments.schemas import (
    ChargeOut, EarningsOut, InvoiceOut, PayoutAccountIn, PayoutAccountOut, PayoutClientOut, PayoutDestinationOut,
    PayoutEngagementOut, PayoutOut, PayoutStatementOut, PayoutStepOut, PayoutTransactionOut, RefundOut,
)
from zoikorum.domains.professional import facade as professional_facade
from zoikorum.domains.proposal import facade as proposal_facade
from zoikorum.domains.trust import facade as trust_facade
from zoikorum.config import get_settings
from zoikorum.shared import clock, pdf
from zoikorum.shared.auth import Actor
from zoikorum.shared.capabilities import Cap
from zoikorum.shared.errors import DomainError, Forbidden, NotFound, PolicyBlocked, ServiceUnavailable, ValidationFailed
from zoikorum.shared.event_catalog import E
from zoikorum.shared.events import record_audit, record_event
from zoikorum.shared.http import page_of, paginate
from zoikorum.shared.money import MoneyDTO
from zoikorum.shared.relay import schedule_timer


def _m(minor: int, ccy: str) -> MoneyDTO:
    return MoneyDTO(amountMinor=minor, currency=ccy)


# ---- Charges (escrow funding) ------------------------------------------------------------------

async def charge_for_funding(session: AsyncSession, payload: dict) -> None:
    """Consumer of ESCROW_FUNDING_REQUESTED. Idempotent per funding."""
    funding_id = uuid.UUID(str(payload["fundingId"]))
    if await session.scalar(select(PaymentIntent.id).where(PaymentIntent.funding_id == funding_id)):
        return
    if not await escrow_facade.funding_open(session, funding_id):
        return  # cancelled or already failed while this was waiting: never charge it
    provider = get_provider()
    pi = PaymentIntent(funding_id=funding_id, escrow_account_id=uuid.UUID(str(payload["escrowAccountId"])),
                       contract_id=uuid.UUID(str(payload["contractId"])), organization_id=uuid.UUID(str(payload["organizationId"])),
                       amount_minor=int(payload["amountMinor"]), currency=payload["currency"], provider=provider.name)
    session.add(pi)
    await session.flush()
    base = {"paymentIntentId": pi.id, "escrowAccountId": pi.escrow_account_id, "fundingId": funding_id,
            "amountMinor": pi.amount_minor, "currency": pi.currency}
    record_event(session, E.PAYMENT_INTENT_CREATED, aggregate_type="PaymentIntent", aggregate_id=pi.id, tenant_id=pi.organization_id, payload=base)
    try:
        result = await asyncio.to_thread(provider.charge, payload["paymentMethodToken"], pi.amount_minor, pi.currency,
                                         idempotency_key=str(funding_id))
    except ServiceUnavailable:
        raise  # provider down: retried; if it stays down, the funding check timer reverts the milestones
    except DomainError as exc:  # the provider refused the request (amount, card, configuration): a failed payment
        pi.status, pi.failure_code, pi.failure_message = "FAILED", exc.code, str(exc.detail or exc.title)[:300]
        record_event(session, E.PAYMENT_FAILED, aggregate_type="PaymentIntent", aggregate_id=pi.id, tenant_id=pi.organization_id,
                     payload={**base, "failureCode": exc.code, "failureMessage": pi.failure_message})
        return
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

PAYOUT_RESUME_TIMER = "payments.payout_resume"


async def _send_payout(session: AsyncSession, p: Payout, account: PayoutAccount) -> None:
    if await admin_facade.is_paused(session, "PAYOUTS"):
        p.status = "QUEUED"  # staff paused payouts: try again in 10 minutes, never dropped
        when = clock.now() + timedelta(minutes=10)
        await schedule_timer(session, PAYOUT_RESUME_TIMER, f"{p.id}:{int(when.timestamp()) // 600}", when)
        return
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
    org_id = uuid.UUID(str(payload["organizationId"]))
    entity = contract.buyer_legal_entity if contract else None
    org = await buyer_facade.get_organization(session, org_id)
    tax = included_tax((entity or {}).get("country") or (org.country if org else None), gross, fee)
    lines = [{"description": f"M{m.sequence} {m.title}" if m else "Accepted work", "amountMinor": gross}]
    if tax:  # tax-inclusive: shown, never added (the total is what was paid)
        lines.append({"description": tax.description, "amountMinor": 0, "taxMinor": tax.amount_minor, "included": True,
                      "taxLabel": tax.label, "rateBps": tax.rate_bps, "basis": tax.basis})
    inv = Invoice(number=number, release_id=release_id, organization_id=org_id, contract_id=contract_id,
                  milestone_id=milestone_id, lines=lines, tax_minor=tax.amount_minor if tax else 0, total_minor=gross,
                  currency=ccy, issued_at=clock.now())
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
    """Needs a fresh two-step confirmation, an Amber trust light (identity verified) or better and clear restrictions (compliance checks)."""
    pro = await _my_professional(session, actor)
    trust = await trust_facade.get_trust(session, pro.id)
    if trust.tier == "C" or trust.dimensions.get("restrictions") != "CLEAR":
        raise PolicyBlocked("Payouts need an Amber trust light (identity verified) and clear restrictions screening", code="PAYOUT_COMPLIANCE_REQUIRED")
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


async def invoices(session: AsyncSession, actor: Actor, organization_id: uuid.UUID, cursor: str | None = None,
                   limit: int | None = None) -> dict:
    await _require_member(session, actor, organization_id)
    stmt, lim = paginate(select(Invoice).where(Invoice.organization_id == organization_id), Invoice, cursor, limit)
    return page_of((await session.scalars(stmt)).all(), lim, lambda i: InvoiceOut(
        id=i.id, number=i.number, contractId=i.contract_id, milestoneId=i.milestone_id, lines=i.lines,
        tax=_m(i.tax_minor, i.currency), total=_m(i.total_minor, i.currency), issuedAt=i.issued_at))


async def invoice_pdf(session: AsyncSession, actor: Actor, invoice_id: uuid.UUID) -> tuple[bytes, str]:
    """The invoice as a PDF for members of the buyer organisation. The footer carries the SHA-256 of the invoice's
    recorded content (number, lines, tax, total, date), so a copy can be checked. Audited."""
    inv = await session.get(Invoice, invoice_id)
    if inv is None:
        raise NotFound("Invoice not found")
    await _require_member(session, actor, inv.organization_id)
    org = await buyer_facade.get_organization(session, inv.organization_id)
    engagement = await contract_facade.get_contract(session, inv.contract_id)
    pro = await professional_facade.get_professional(session, engagement.professional_id) if engagement else None
    content = json.dumps({"number": inv.number, "lines": inv.lines, "taxMinor": inv.tax_minor, "totalMinor": inv.total_minor,
                          "currency": inv.currency, "issuedAt": inv.issued_at.isoformat()}, sort_keys=True, separators=(",", ":"))
    fingerprint = hashlib.sha256(content.encode()).hexdigest()
    items = [(str(line.get("description", "")),
              pdf.money(int(line.get("taxMinor" if line.get("included") else "amountMinor", 0)), inv.currency))
             for line in inv.lines]
    if inv.tax_minor and not any(line.get("included") for line in inv.lines):
        items.append(("Tax", pdf.money(inv.tax_minor, inv.currency)))
    doc = pdf.PdfDocument(
        title="Invoice", reference=inv.number, issued=inv.issued_at, fingerprint=fingerprint,
        subtitle=f"For engagement {engagement.reference}" if engagement else None,
        sections=[pdf.Section("Billed to", rows=_billed_to(org, engagement.buyer_legal_entity if engagement else None)
                              + [("Professional", pro.display_name if pro else "—")]),
                  pdf.Section("Items", table=items, total=("Total paid", pdf.money(inv.total_minor, inv.currency))),
                  pdf.Section(text="Funds were held in escrow and released for accepted work. Zoikorum provides the marketplace "
                                   "and payment protection; the services were provided by the professional named above.")])
    record_audit(session, "payments.invoice.pdf_downloaded", object_type="Invoice", object_id=inv.id,
                 tenant_id=inv.organization_id, evidence_hash=fingerprint)
    return pdf.render(doc), f"{inv.number}.pdf"


_PAYOUT_STATUS = {"QUEUED": "Waiting for a payout account", "INITIATED": "Sent to your bank",
                  "SETTLED": "Paid to your bank", "FAILED": "Failed"}


async def payout_statement_pdf(session: AsyncSession, actor: Actor, payout_id: uuid.UUID) -> tuple[bytes, str]:
    """The professional's statement for one payout: what the client paid, the platform fee, what was paid to the bank,
    when, and the transfer reference. Only the professional it was paid to can download it. The footer carries the
    SHA-256 of the recorded payout, so a copy can be checked. Audited."""
    pro = await _my_professional(session, actor)
    p = await session.get(Payout, payout_id)
    if p is None or p.professional_id != pro.id:
        raise NotFound("Payout not found")
    engagement = await contract_facade.get_contract(session, p.contract_id)
    milestone = await contract_facade.get_milestone(session, p.milestone_id) if p.milestone_id else None
    org = await buyer_facade.get_organization(session, engagement.organization_id) if engagement else None
    invoice = await session.scalar(select(Invoice).where(Invoice.release_id == p.release_id))
    account = await session.scalar(select(PayoutAccount).where(PayoutAccount.professional_id == pro.id))
    reference = f"ZK-PAY-{str(p.id)[:8].upper()}"
    content = json.dumps({"payoutId": str(p.id), "releaseId": str(p.release_id), "grossMinor": p.gross_minor,
                          "feeMinor": p.fee_minor, "netMinor": p.amount_minor, "currency": p.currency, "status": p.status,
                          "transferRef": p.transfer_ref or p.provider_ref,
                          "settledAt": p.settled_at.isoformat() if p.settled_at else None},
                         sort_keys=True, separators=(",", ":"))
    fingerprint = hashlib.sha256(content.encode()).hexdigest()
    fee_pct = f"{p.fee_minor * 100 / p.gross_minor:g}%" if p.gross_minor else ""
    when = lambda d: d.strftime("%d %b %Y") if d else "—"  # noqa: E731
    paid_to = [("Professional", (await professional_facade.legal_name(session, pro.id)) or pro.display_name)]
    if account:
        paid_to += [("Account holder", account.holder_name), ("Bank account", f"•••• {account.last4} ({account.country}, {account.currency})")]
    work = [("Engagement", engagement.reference if engagement else "—"),
            ("Milestone", milestone.title if milestone else "Whole engagement"),
            ("Client", (engagement.buyer_legal_entity or {}).get("legalName") if engagement and engagement.buyer_legal_entity
             else (org.name if org else "—"))]
    if invoice:
        work.append(("Client invoice", invoice.number))
    payment = [("Status", _PAYOUT_STATUS.get(p.status, p.status)), ("Started", when(p.created_at)),
               ("Paid", when(p.settled_at)) if p.settled_at else ("Expected in your bank", when(p.expected_at)),
               ("Transfer reference", p.transfer_ref or p.provider_ref or "—")]
    if p.status == "FAILED" and p.failure_message:
        payment.append(("Reason", p.failure_message))
    doc = pdf.PdfDocument(
        title="Payout statement", reference=reference, issued=p.settled_at or p.created_at, fingerprint=fingerprint,
        subtitle=f"For engagement {engagement.reference}" if engagement else None,
        sections=[pdf.Section("Paid to", rows=paid_to),
                  pdf.Section("Work", rows=work),
                  pdf.Section("Amounts", table=[("Released from escrow for accepted work", pdf.money(p.gross_minor, p.currency)),
                                                (f"Zoikorum platform fee {fee_pct}".strip(), "- " + pdf.money(p.fee_minor, p.currency))],
                              total=("Paid to you", pdf.money(p.amount_minor, p.currency))),
                  pdf.Section("Payment", rows=payment),
                  pdf.Section(text="The client paid into escrow. When the work was accepted, the money was released: the platform "
                                   "fee went to Zoikorum and the rest was sent to the bank account above. Use the transfer "
                                   "reference to find this payment on your bank statement.")])
    record_audit(session, "payments.payout.statement_downloaded", object_type="Payout", object_id=p.id,
                 evidence_hash=fingerprint)
    return pdf.render(doc), f"{reference}.pdf"


_STATEMENT_STATUS = {"QUEUED": "Processing", "INITIATED": "In transit", "SETTLED": "Paid", "FAILED": "Failed"}
_PROVIDER_NAMES = {"stripe": "Stripe", "fake": "Test payment partner"}


def _initiated_at(p: Payout):
    """When the transfer started. Recorded only through the expected date: a payout sent as soon as it was created has
    expected_at = created_at + settlement days; one that waited (no account, payouts paused) has no start time stored."""
    if p.status == "QUEUED" or p.expected_at is None:
        return None
    if clock.add_business_days(p.created_at, get_settings().payout_settlement_business_days) == p.expected_at:
        return p.created_at
    return None


def _statement_steps(p: Payout, funded_at, accepted_at, initiated_at) -> list[PayoutStepOut]:
    sent = p.status in ("INITIATED", "SETTLED")
    expected = f"Expected by {p.expected_at:%d %b %Y}" if p.expected_at and p.status == "INITIATED" else None
    return [PayoutStepOut(key="FUNDED", label="Client funded escrow", state="DONE" if funded_at else "UPCOMING", at=funded_at),
            PayoutStepOut(key="ACCEPTED", label="Work accepted", state="DONE", at=accepted_at),
            PayoutStepOut(key="INITIATED", label="Payout initiated", state="DONE" if p.status != "QUEUED" else "CURRENT",
                          at=initiated_at, note=delay_reason(p) if p.status == "QUEUED" else None),
            PayoutStepOut(key="IN_TRANSIT", label="In transit",
                          state="FAILED" if p.status == "FAILED" else "DONE" if p.status == "SETTLED" else
                          "CURRENT" if sent else "UPCOMING", at=initiated_at if sent else None,
                          note=(p.failure_message or "The transfer failed") if p.status == "FAILED" else expected),
            PayoutStepOut(key="COMPLETED", label="Completed", state="DONE" if p.status == "SETTLED" else "UPCOMING",
                          at=p.settled_at)]


def _day(v) -> date | None:
    return date.fromisoformat(v) if isinstance(v, str) else v.date() if v else None


async def payout_statement(session: AsyncSession, actor: Actor, payout_id: uuid.UUID) -> PayoutStatementOut:
    """One payout in full for the professional it was paid to (Financial Operations staff may read any; audited): the
    amounts, the engagement and milestone it pays for, the buyer organisation (name and country only, never a person's
    contact details), each step with its time, the related money movements and where it was paid (masked)."""
    if actor.has_capability(Cap.PAYMENTS_READ):
        actor.require_capability(Cap.PAYMENTS_READ)  # staff session with MFA
        p = await session.get(Payout, payout_id)
        if p is None:
            raise NotFound("Payout not found")
        record_audit(session, "payments.payout.statement_viewed", object_type="Payout", object_id=p.id, tenant_id=p.professional_id)
    else:
        pro = await _my_professional(session, actor)
        p = await session.get(Payout, payout_id)
        if p is None or p.professional_id != pro.id:
            raise NotFound("Payout not found")
    ccy = p.currency
    engagement = await contract_facade.get_contract(session, p.contract_id)
    facts = await contract_facade.engagement_facts(session, p.contract_id) or {}
    milestone = await contract_facade.get_milestone(session, p.milestone_id) if p.milestone_id else None
    org = await buyer_facade.get_organization(session, engagement.organization_id) if engagement else None
    entity = (engagement.buyer_legal_entity or {}) if engagement else {}
    trail = await escrow_facade.release_trail(session, p.release_id)
    invoice = await session.scalar(select(Invoice).where(Invoice.release_id == p.release_id))
    account = await session.scalar(select(PayoutAccount).where(PayoutAccount.professional_id == p.professional_id))
    specialization = None
    slug = await proposal_facade.request_specialization(session, engagement.request_id) if engagement else None
    if slug:
        info = (await marketplace_facade.get_specializations(session, [slug])).get(slug)
        specialization = info.name if info else None

    reference = f"ZK-PAY-{str(p.id)[:8].upper()}"
    fee_bps = trail.fee_bps if trail else (round(p.fee_minor * 10000 / p.gross_minor) if p.gross_minor else 0)
    accepted_at = (milestone.accepted_at if milestone else None) or (trail.released_at if trail else None) or facts.get("completedAt")
    initiated_at = _initiated_at(p)
    project = engagement.reference if engagement else None

    transactions: list[PayoutTransactionOut] = []
    if trail and trail.funded_at and trail.funded_minor is not None:  # same engagement, so the same currency
        transactions.append(PayoutTransactionOut(
            kind="ESCROW_FUNDED", at=trail.funded_at, reference=project, amount=_m(trail.funded_minor, ccy), status="Funded",
            description=f"Client funded escrow for M{milestone.sequence} {milestone.title}" if milestone else "Client funded escrow"))
    if invoice:
        transactions.append(PayoutTransactionOut(
            kind="MILESTONE_INVOICE", at=invoice.issued_at, reference=invoice.number, amount=_m(invoice.total_minor, invoice.currency),
            status="Issued", description="Invoice issued to the client for the accepted work"))
    if trail:
        transactions.append(PayoutTransactionOut(
            kind="ESCROW_RELEASE", at=trail.released_at, reference=project, amount=_m(trail.gross_minor, trail.currency),
            status="Released", description="Released from escrow for accepted work"))
    transactions.append(PayoutTransactionOut(
        kind="PAYOUT", at=p.created_at, reference=reference, amount=_m(p.amount_minor, ccy), status=_STATEMENT_STATUS[p.status],
        description=f"Payout to bank account \u2022\u2022\u2022\u2022 {account.last4}" if account else "Payout to your bank account"))
    transactions.sort(key=lambda t: t.at)

    return PayoutStatementOut(
        id=p.id, reference=reference, status=p.status, statusLabel=_STATEMENT_STATUS[p.status], createdAt=p.created_at,
        initiatedAt=initiated_at, expectedAt=p.expected_at, settledAt=p.settled_at, failureMessage=p.failure_message,
        delayReason=delay_reason(p),
        transferReference=(p.transfer_ref or p.provider_ref) if p.status in ("INITIATED", "SETTLED") else None,
        gross=_m(p.gross_minor, ccy), fee=_m(p.fee_minor, ccy), feeBps=fee_bps, net=_m(p.amount_minor, ccy),
        engagement=PayoutEngagementOut(
            contractId=p.contract_id, reference=project or "", title=facts.get("title") or "Engagement",
            milestoneId=p.milestone_id, milestoneTitle=milestone.title if milestone else None,
            milestoneSequence=milestone.sequence if milestone else None, specialization=specialization,
            engagementType=facts.get("engagementType") or "PROJECT", pricingModel=facts.get("pricingModel"),
            workStart=_day(facts.get("startDate") or facts.get("activatedAt")),
            workEnd=_day(facts.get("endDate") or facts.get("completedAt")),
            acceptedAt=accepted_at, clientInvoiceNumber=invoice.number if invoice else None),
        client=PayoutClientOut(name=entity.get("legalName") or (org.name if org else "Client"),
                               country=entity.get("country") or facts.get("buyerCountry") or (org.country if org else None)),
        steps=_statement_steps(p, trail.funded_at if trail else None, accepted_at, initiated_at),
        transactions=transactions,
        destination=PayoutDestinationOut(provider=_PROVIDER_NAMES.get(account.provider, account.provider.title()),
                                         label=f"Bank account \u2022\u2022\u2022\u2022 {account.last4}", last4=account.last4,
                                         currency=account.currency, country=account.country) if account else None)


async def charges(session: AsyncSession, actor: Actor, organization_id: uuid.UUID, cursor: str | None = None,
                  limit: int | None = None) -> dict:
    await _require_member(session, actor, organization_id)
    stmt, lim = paginate(select(PaymentIntent).where(PaymentIntent.organization_id == organization_id), PaymentIntent,
                         cursor, limit)
    return page_of((await session.scalars(stmt)).all(), lim, lambda p: ChargeOut(
        id=p.id, contractId=p.contract_id, amount=_m(p.amount_minor, p.currency), status=p.status, methodLabel=p.method_label,
        failureMessage=p.failure_message, createdAt=p.created_at, capturedAt=p.captured_at, chargedBackAt=p.charged_back_at))


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
    # The original charge, whatever happened since (a partial chargeback leaves part of it refundable).
    intent = await session.scalar(select(PaymentIntent).where(PaymentIntent.funding_id.in_(funding_ids),
                                                              PaymentIntent.status.in_(("CAPTURED", "CHARGED_BACK")))) \
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
    try:
        result = await asyncio.to_thread(get_provider().refund, intent.provider_ref if intent else None, r.amount_minor, r.currency,
                                         idempotency_key=str(escrow_refund_id))
    except ServiceUnavailable:
        raise  # provider down: the consumer retries
    except DomainError as exc:  # the provider refused it: recorded, announced, retried daily
        refund_failed(session, r, str(exc.detail))
        return
    r.provider_ref = result.provider_ref
    if result.ok and result.pending:
        r.status = "INITIATED"
    elif result.ok:
        r.status, r.provider_ref, r.settled_at = "SETTLED", result.provider_ref, clock.now()
        record_event(session, E.REFUND_SETTLED, aggregate_type="Refund", aggregate_id=r.id, tenant_id=r.organization_id, payload=base)
    else:
        refund_failed(session, r, getattr(result, "failure_message", None))


def refund_failed(session: AsyncSession, r: Refund, message: str | None) -> None:
    r.status = "FAILED"
    r.failure_message = (message or "The payment provider could not return the money")[:300]
    record_event(session, E.REFUND_FAILED, aggregate_type="Refund", aggregate_id=r.id, tenant_id=r.organization_id,
                 payload={"refundId": r.id, "organizationId": r.organization_id, "contractId": r.contract_id,
                          "amountMinor": r.amount_minor, "currency": r.currency,
                          "failureMessage": (message or "The payment provider could not return the money")[:300]})


async def retry_failed_refunds(session: AsyncSession) -> int:
    """Daily: try failed refunds again. Each refund is tried on its own (one the provider still refuses never stops the
    others, or the reconciliation that runs after). The provider key changes per day: a failed refund is not replayed,
    while two tries on the same day can never refund twice."""
    retried = 0
    for r in (await session.scalars(select(Refund).where(Refund.status == "FAILED").with_for_update(skip_locked=True))).all():
        intent = await session.get(PaymentIntent, r.payment_intent_id) if r.payment_intent_id else None
        try:
            result = await asyncio.to_thread(get_provider().refund, intent.provider_ref if intent else None, r.amount_minor,
                                             r.currency, idempotency_key=f"{r.escrow_refund_id}:{clock.now().date().isoformat()}")
        except DomainError:
            continue  # still refused or provider down: stays FAILED for Financial Ops, tried again tomorrow
        if result.ok:
            r.provider_ref = result.provider_ref
            r.status = "INITIATED" if result.pending else "SETTLED"
            if not result.pending:
                r.settled_at = clock.now()
                record_event(session, E.REFUND_SETTLED, aggregate_type="Refund", aggregate_id=r.id, tenant_id=r.organization_id,
                             payload={"refundId": r.id, "organizationId": r.organization_id, "amountMinor": r.amount_minor,
                                      "currency": r.currency})
            retried += 1
    return retried


async def refunds(session: AsyncSession, actor: Actor, organization_id: uuid.UUID, cursor: str | None = None,
                  limit: int | None = None) -> dict:
    await _require_member(session, actor, organization_id)
    stmt, lim = paginate(select(Refund).where(Refund.organization_id == organization_id), Refund, cursor, limit)
    return page_of((await session.scalars(stmt)).all(), lim, lambda r: RefundOut(
        id=r.id, contractId=r.contract_id, milestoneId=r.milestone_id, disputeId=r.dispute_id,
        amount=_m(r.amount_minor, r.currency), status=r.status, failureMessage=r.failure_message, createdAt=r.created_at,
        settledAt=r.settled_at))


async def resume_payout(session: AsyncSession, payout_id: uuid.UUID) -> None:
    """Timer: a payout that waited while payouts were paused (admin switch PAYOUTS)."""
    p = await session.get(Payout, payout_id, with_for_update=True)
    if p is None or p.status != "QUEUED":
        return
    account = await session.scalar(select(PayoutAccount).where(PayoutAccount.professional_id == p.professional_id,
                                                               PayoutAccount.status == "ACTIVE"))
    if account is not None:
        await _send_payout(session, p, account)


def _billed_to(org, entity: dict | None) -> list[tuple[str, str]]:
    """The buyer's legal entity on the invoice (as on the contract), or the organisation when it has none."""
    if not entity:
        return [("Organisation", org.name if org else "—")]
    rows = [("Legal entity", entity["legalName"]), ("Organisation", org.name if org else "—")]
    for label, key in (("Registration no.", "registrationNumber"), ("Tax ID", "taxId"), ("Registered address", "registeredAddress")):
        if entity.get(key):
            rows.append((label, f"{entity[key]}, {entity['country']}" if key == "registeredAddress" else entity[key]))
    return rows
