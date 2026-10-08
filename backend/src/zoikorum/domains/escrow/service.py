"""Escrow domain (Step 8): accounts per contract, milestone funding, capture, and the release decision tree
(Payments & Escrow doc, BUILD_SPEC s.escrow, Engineering Handbook 15.2).

Rules: no HTTP endpoint releases money; release happens only when a milestone is accepted. Every movement writes a
balanced append-only double-entry group in the same transaction as the balance change, under a row lock on the
account. Dispute holds, refunds and amendments arrive with the dispute and change-order steps.
"""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from zoikorum.config import get_settings
from zoikorum.domains.buyer import facade as buyer_facade
from zoikorum.domains.escrow.models import Allocation, EscrowAccount, Funding, LedgerEntry, Release
from zoikorum.domains.escrow.schemas import AllocationOut, EscrowOut, FundingOut, FundIn, LedgerLineOut
from zoikorum.domains.professional import facade as professional_facade
from zoikorum.shared import clock
from zoikorum.shared.auth import Actor, OrgRole, PlatformRole
from zoikorum.shared.errors import Conflict, Forbidden, NotFound, PolicyBlocked
from zoikorum.shared.event_catalog import E
from zoikorum.shared.events import record_event
from zoikorum.shared.money import Money, MoneyDTO
from zoikorum.shared.state_machine import StateMachine

ALLOCATION_STATES = StateMachine("Allocation", {
    "UNFUNDED": {"FUNDING", "CANCELLED"},  # CANCELLED: e.g. a retainer cycle stopped before funding
    "FUNDING": {"HELD", "UNFUNDED"},
    "HELD": {"RELEASED", "PARTIALLY_RELEASED", "ON_HOLD", "RELEASE_PENDING_APPROVAL", "REFUNDED", "UNFUNDED"},  # UNFUNDED: chargeback
    "ON_HOLD": {"HELD", "RELEASED", "PARTIALLY_RELEASED", "REFUNDED", "UNFUNDED"},
    "RELEASE_PENDING_APPROVAL": {"RELEASED", "HELD"},
    "PARTIALLY_RELEASED": set(),
    "RELEASED": set(),
    "REFUNDED": set(),
    "CANCELLED": set(),
})
FUNDERS = (OrgRole.REQUESTER, OrgRole.APPROVER, OrgRole.BUDGET_OWNER)
VIEWERS = (PlatformRole.FINANCIAL_OPS, PlatformRole.PLATFORM_ADMIN)


def _m(minor: int, ccy: str) -> MoneyDTO:
    return MoneyDTO(amountMinor=minor, currency=ccy)


def _evt(session: AsyncSession, event_type: str, a: EscrowAccount, **payload) -> None:
    record_event(session, event_type, aggregate_type="EscrowAccount", aggregate_id=a.id, tenant_id=a.organization_id,
                 payload={"escrowAccountId": a.id, "contractId": a.contract_id, "organizationId": a.organization_id, **payload})


def _post(session: AsyncSession, a: EscrowAccount, ref_type: str, ref_id: uuid.UUID, lines: list[tuple[str, str, int, int, str]],
          milestone_id: uuid.UUID | None = None) -> None:
    """Write one balanced ledger group. lines = (entry_type, ledger_account, debit, credit, memo)."""
    debit, credit = sum(x[2] for x in lines), sum(x[3] for x in lines)
    if debit != credit or debit <= 0 or any(x[2] < 0 or x[3] < 0 for x in lines):
        raise ValueError(f"Unbalanced ledger group: debit {debit} != credit {credit}")  # never write money that does not add up
    group = uuid.uuid4()
    for entry_type, account, d, c, memo in lines:
        session.add(LedgerEntry(entry_group_id=group, account_id=a.id, entry_type=entry_type, ledger_account=account, debit_minor=d,
                                credit_minor=c, currency=a.currency, reference_type=ref_type, reference_id=ref_id,
                                milestone_id=milestone_id, memo=memo))


async def _account(session: AsyncSession, account_id: uuid.UUID, lock: bool = False) -> EscrowAccount:
    a = await session.get(EscrowAccount, account_id, with_for_update=lock)
    if a is None:
        raise NotFound("Escrow account not found")
    return a


async def _allocations(session: AsyncSession, account_id: uuid.UUID, lock: bool = False) -> list[Allocation]:
    stmt = select(Allocation).where(Allocation.account_id == account_id).order_by(Allocation.sequence)
    return list((await session.scalars(stmt.with_for_update() if lock else stmt)).all())


async def _viewer(session: AsyncSession, actor: Actor, a: EscrowAccount) -> str:
    if await buyer_facade.get_member_roles(session, a.organization_id, actor.identity_id):
        return "BUYER"
    pro = await professional_facade.get_professional(session, a.professional_id)
    if pro is not None and pro.identity_id == actor.identity_id:
        return "PROFESSIONAL"
    if actor.has_platform_role(*VIEWERS):
        actor.require_platform_role(*VIEWERS)  # read-only: operators can never move money
        return "OPERATOR"
    raise NotFound("Escrow account not found")


def _status(a: EscrowAccount, allocs: list[Allocation]) -> str:
    if any(x.state == "ON_HOLD" for x in allocs):
        return "DISPUTED"
    if allocs and any(x.state == "RELEASED" for x in allocs) and all(x.state in ("RELEASED", "CANCELLED") for x in allocs):
        return "FULLY_RELEASED"
    settled = ("RELEASED", "PARTIALLY_RELEASED", "REFUNDED", "UNFUNDED", "CANCELLED")  # UNFUNDED also covers chargebacks
    if allocs and a.refunded_minor > 0 and all(x.state in settled for x in allocs):
        return "REFUNDED" if a.released_minor == 0 else "CLOSED"
    if a.released_minor > 0:
        return "PARTIALLY_RELEASED"
    if a.funded_minor > 0:
        return "FUNDED"
    return "UNFUNDED"


async def _out(session: AsyncSession, actor: Actor, a: EscrowAccount, viewer: str) -> EscrowOut:
    allocs = await _allocations(session, a.id)
    fundings = (await session.scalars(select(Funding).where(Funding.account_id == a.id).order_by(Funding.created_at.desc()))).all()
    can_fund = viewer == "BUYER" and any(x.state == "UNFUNDED" for x in allocs) and bool(
        (await buyer_facade.get_member_roles(session, a.organization_id, actor.identity_id)).intersection(FUNDERS))
    ccy = a.currency
    unfunded = sum(x.amount_minor for x in allocs if x.state == "UNFUNDED")
    return EscrowOut(
        id=a.id, contractId=a.contract_id, status=a.status, currency=ccy, total=_m(a.total_minor, ccy), funded=_m(a.funded_minor, ccy),
        held=_m(a.held_minor, ccy), released=_m(a.released_minor, ccy), fees=_m(a.fees_minor, ccy), refunded=_m(a.refunded_minor, ccy),
        unfunded=_m(unfunded, ccy), feeBps=get_settings().platform_fee_bps,
        allocations=[AllocationOut(milestoneId=x.milestone_id, sequence=x.sequence, title=x.title, amount=_m(x.amount_minor, ccy), state=x.state,
                                   released=_m(x.released_minor, ccy), fee=_m(x.fee_minor, ccy), fundedAt=x.funded_at, releasedAt=x.released_at)
                     for x in allocs],
        fundings=[FundingOut(id=f.id, amount=_m(f.amount_minor, f.currency), milestoneIds=[uuid.UUID(str(i)) for i in f.milestone_ids],
                             status=f.status, failureMessage=f.failure_message, createdAt=f.created_at, capturedAt=f.captured_at)
                  for f in fundings],
        viewerRole=viewer, canFund=can_fund,
    )


# ---- Opening -------------------------------------------------------------------------------

async def open_account(session: AsyncSession, payload: dict) -> None:
    """Consumer of CONTRACT_ACTIVATED. Idempotent per contract."""
    contract_id = uuid.UUID(str(payload["contractId"]))
    if await session.scalar(select(EscrowAccount.id).where(EscrowAccount.contract_id == contract_id)):
        return
    a = EscrowAccount(contract_id=contract_id, organization_id=uuid.UUID(str(payload["organizationId"])),
                      professional_id=uuid.UUID(str(payload["professionalId"])), currency=payload["currency"],
                      total_minor=int(payload["totalMinor"]), status="UNFUNDED")
    session.add(a)
    await session.flush()
    session.add_all([Allocation(account_id=a.id, milestone_id=uuid.UUID(str(m["milestoneId"])), sequence=m["sequence"], title=m["title"],
                                amount_minor=int(m["amountMinor"]), state="UNFUNDED") for m in payload.get("milestones", [])])
    _evt(session, E.ESCROW_OPENED, a, professionalId=a.professional_id, currency=a.currency, totalMinor=a.total_minor)


# ---- Reads --------------------------------------------------------------------------------------

async def get_account(session: AsyncSession, actor: Actor, account_id: uuid.UUID) -> EscrowOut:
    a = await _account(session, account_id)
    return await _out(session, actor, a, await _viewer(session, actor, a))


async def get_by_contract(session: AsyncSession, actor: Actor, contract_id: uuid.UUID) -> EscrowOut:
    a = await session.scalar(select(EscrowAccount).where(EscrowAccount.contract_id == contract_id))
    if a is None:
        raise NotFound("No escrow account yet: it opens when both parties have signed the contract")
    return await _out(session, actor, a, await _viewer(session, actor, a))


async def ledger(session: AsyncSession, actor: Actor, account_id: uuid.UUID) -> list[LedgerLineOut]:
    a = await _account(session, account_id)
    await _viewer(session, actor, a)
    rows = (await session.scalars(select(LedgerEntry).where(LedgerEntry.account_id == a.id)
                                  .order_by(LedgerEntry.created_at, LedgerEntry.entry_group_id, LedgerEntry.debit_minor.desc()).limit(500))).all()
    return [LedgerLineOut(id=r.id, entryGroupId=r.entry_group_id, entryType=r.entry_type, ledgerAccount=r.ledger_account,
                          debit=_m(r.debit_minor, r.currency), credit=_m(r.credit_minor, r.currency), referenceType=r.reference_type,
                          referenceId=r.reference_id, milestoneId=r.milestone_id, memo=r.memo, createdAt=r.created_at) for r in rows]


# ---- Funding ------------------------------------------------------------------------------------

async def fund(session: AsyncSession, actor: Actor, account_id: uuid.UUID, body: FundIn) -> EscrowOut:
    a = await _account(session, account_id, lock=True)
    if await _viewer(session, actor, a) != "BUYER":
        raise Forbidden("Only the buyer funds escrow")
    roles = await buyer_facade.get_member_roles(session, a.organization_id, actor.identity_id)
    if not roles.intersection(FUNDERS):
        raise Forbidden("Funding needs the Requester, Approver or Budget Owner role", code="ROLE_REQUIRED")
    allocs = await _allocations(session, a.id, lock=True)
    wanted = [x for x in allocs if x.state == "UNFUNDED"] if body.all else [x for x in allocs if x.milestone_id in set(body.milestoneIds)]
    if not body.all and len(wanted) != len(set(body.milestoneIds)):
        raise NotFound("Milestone not found on this contract")
    if not wanted:
        raise Conflict("Every milestone is already funded", code="NOTHING_TO_FUND")
    busy = [x for x in wanted if x.state != "UNFUNDED"]
    if busy:
        raise Conflict(f"M{busy[0].sequence} is already funded or being funded", code="ALREADY_FUNDED")
    amount = sum(x.amount_minor for x in wanted)
    if a.funded_minor + amount > a.total_minor:
        raise Conflict("That would fund more than the contract total", code="OVER_FUNDING")
    limit = await buyer_facade.get_member_spend_limit(session, a.organization_id, actor.identity_id)
    if limit is not None and limit.currency == a.currency and amount > limit.minor:
        raise PolicyBlocked("This funding is above your spend limit; ask a colleague with a higher limit", code="SPEND_LIMIT_EXCEEDED")

    f = Funding(account_id=a.id, organization_id=a.organization_id, requested_by=actor.identity_id,
                milestone_ids=[str(x.milestone_id) for x in wanted], amount_minor=amount, currency=a.currency, status="REQUESTED")
    session.add(f)
    await session.flush()
    for x in wanted:
        ALLOCATION_STATES.assert_can(x.state, "FUNDING")
        x.state, x.funding_id = "FUNDING", f.id
    _evt(session, E.ESCROW_FUNDING_REQUESTED, a, fundingId=f.id, amountMinor=amount, currency=a.currency,
         milestoneIds=[x.milestone_id for x in wanted], paymentMethodToken=body.paymentMethodToken)
    await session.flush()
    return await _out(session, actor, a, "BUYER")


async def payment_captured(session: AsyncSession, payload: dict) -> None:
    """Consumer of PAYMENT_CAPTURED: hold the money in escrow and start the funded milestones. Idempotent per funding."""
    f = await session.get(Funding, uuid.UUID(str(payload["fundingId"])), with_for_update=True)
    if f is None or f.status != "REQUESTED":
        return
    a = await _account(session, f.account_id, lock=True)
    if int(payload["amountMinor"]) != f.amount_minor or payload["currency"] != f.currency:
        raise ValueError(f"Captured amount does not match funding {f.id}")
    ids = {uuid.UUID(str(i)) for i in f.milestone_ids}
    allocs = [x for x in await _allocations(session, a.id, lock=True) if x.milestone_id in ids]
    now = clock.now()
    _post(session, a, "FUNDING", f.id, [
        ("BUYER_FUNDING", "BUYER_CLEARING", f.amount_minor, 0, "Payment captured from buyer"),
        ("ESCROW_HOLD", "ESCROW_HELD", 0, f.amount_minor, "Held in escrow until acceptance"),
    ])
    for x in allocs:
        ALLOCATION_STATES.assert_can(x.state, "HELD")
        x.state, x.funded_at = "HELD", now
    f.status, f.captured_at = "CAPTURED", now
    a.funded_minor += f.amount_minor
    a.held_minor += f.amount_minor
    a.status = _status(a, await _allocations(session, a.id))
    _evt(session, E.ESCROW_FUNDED, a, fundingId=f.id, milestoneIds=[x.milestone_id for x in allocs], amountMinor=f.amount_minor,
         currency=f.currency)


async def payment_failed(session: AsyncSession, payload: dict) -> None:
    """Consumer of PAYMENT_FAILED: the milestones go back to unfunded; nothing is held."""
    f = await session.get(Funding, uuid.UUID(str(payload["fundingId"])), with_for_update=True)
    if f is None or f.status != "REQUESTED":
        return
    await _account(session, f.account_id, lock=True)
    for x in await _allocations(session, f.account_id, lock=True):
        if x.funding_id == f.id and x.state == "FUNDING":
            x.state, x.funding_id = "UNFUNDED", None
    f.status, f.failure_message = "FAILED", (payload.get("failureMessage") or "Payment was declined")[:300]


# ---- Release decision tree (Handbook 15.2) ---------------------------------------------------------

async def milestone_accepted(session: AsyncSession, payload: dict) -> None:
    """Consumer of MILESTONE_ACCEPTED. Releases the milestone's escrow to the professional, minus the platform fee."""
    milestone_id = uuid.UUID(str(payload["milestoneId"]))
    x = await session.scalar(select(Allocation).where(Allocation.milestone_id == milestone_id))
    if x is None:
        return
    a = await _account(session, x.account_id, lock=True)
    x = await session.get(Allocation, x.id, with_for_update=True)

    def evaluated(decision: str, reason: str) -> None:
        _evt(session, E.ESCROW_RELEASE_EVALUATED, a, milestoneId=milestone_id, decision=decision, reason=reason)

    if x.state == "RELEASED" or await session.scalar(select(Release.id).where(Release.milestone_id == milestone_id)):
        return  # already released: idempotent no-op
    if x.state == "ON_HOLD":
        evaluated("BLOCKED", "DISPUTE_HOLD")  # while held, no release path may run
        return
    if x.state != "HELD":
        evaluated("BLOCKED", f"NOT_FUNDED:{x.state}")
        return

    bps = get_settings().platform_fee_bps
    # An agreed partial acceptance releases only that part; the rest goes back to the buyer.
    gross = min(int(payload["releaseMinor"]), x.amount_minor) if payload.get("releaseMinor") is not None else x.amount_minor
    refund = x.amount_minor - gross
    fee = Money(gross, a.currency).percentage_bps(bps).minor
    net = gross - fee
    r = Release(account_id=a.id, milestone_id=milestone_id, gross_minor=gross, fee_minor=fee, net_minor=net, currency=a.currency, fee_bps=bps)
    session.add(r)
    await session.flush()
    lines = [("ESCROW_RELEASE", "ESCROW_HELD", gross, 0, f"M{x.sequence} accepted: released from escrow"),
             ("ESCROW_RELEASE", "PRO_PAYABLE", 0, net, f"M{x.sequence}: payable to professional")]
    if fee:
        lines.append(("PLATFORM_FEE", "PLATFORM_REVENUE", 0, fee, f"M{x.sequence}: platform fee {bps / 100:.2f}%"))
    if refund:
        lines += [("REFUND", "ESCROW_HELD", refund, 0, f"M{x.sequence}: not released (partial acceptance)"),
                  ("REFUND", "BUYER_REFUND_PAYABLE", 0, refund, f"M{x.sequence}: refund payable to buyer")]
    _post(session, a, "RELEASE", r.id, lines, milestone_id)
    new_state = "PARTIALLY_RELEASED" if refund else "RELEASED"
    ALLOCATION_STATES.assert_can(x.state, new_state)
    x.state, x.released_minor, x.fee_minor, x.refunded_minor, x.released_at = new_state, net, fee, refund, clock.now()
    a.held_minor -= gross + refund
    a.released_minor += net
    a.fees_minor += fee
    a.refunded_minor += refund
    a.status = _status(a, await _allocations(session, a.id))
    evaluated("RELEASE", "PARTIAL_ACCEPTANCE" if refund else "ACCEPTED")
    _evt(session, E.ESCROW_RELEASED, a, milestoneId=milestone_id, professionalId=a.professional_id, grossMinor=gross, feeMinor=fee,
         netMinor=net, currency=a.currency, releaseId=r.id)
    if refund:
        _evt(session, E.ESCROW_REFUNDED, a, milestoneId=milestone_id, amountMinor=refund, currency=a.currency, refundId=uuid.uuid4(),
             fundingIds=[x.funding_id] if x.funding_id else [])


async def milestone_cancelled(session: AsyncSession, payload: dict) -> None:
    """Consumer of MILESTONE_CANCELLED: an unfunded allocation is closed; it no longer counts as money to fund."""
    x = await session.scalar(select(Allocation).where(Allocation.milestone_id == uuid.UUID(str(payload["milestoneId"]))).with_for_update())
    if x is None or x.state != "UNFUNDED":
        return
    a = await _account(session, x.account_id, lock=True)
    x.state = "CANCELLED"
    a.status = _status(a, await _allocations(session, a.id))


# ---- Chargebacks (Payments & Escrow s.18) ----------------------------------------------------------------

async def payment_charged_back(session: AsyncSession, payload: dict) -> None:
    """Consumer of PAYMENT_CHARGED_BACK. The card issuer took money back, so it can no longer be in escrow:
    - money still held for unreleased milestones leaves escrow and those milestones need funding again
      ("no work without funding"), even if a dispute had frozen them;
    - any part already released to the professional becomes a platform loss for Financial Ops to recover.
    Both are balanced ledger groups. Idempotent per payment intent."""
    intent_id = uuid.UUID(str(payload["paymentIntentId"]))
    if await session.scalar(select(LedgerEntry.id).where(LedgerEntry.reference_type == "CHARGEBACK", LedgerEntry.reference_id == intent_id)):
        return
    f = await session.get(Funding, uuid.UUID(str(payload["fundingId"])), with_for_update=True)
    if f is None:
        return
    a = await _account(session, f.account_id, lock=True)
    remaining = min(int(payload["amountMinor"]), f.amount_minor)
    lines: list[tuple[str, str, int, int, str]] = []
    reversed_ids = []
    for x in await _allocations(session, a.id, lock=True):
        if remaining <= 0 or x.funding_id != f.id or x.state not in ("HELD", "ON_HOLD"):
            continue
        take = min(x.amount_minor, remaining)
        lines += [("CHARGEBACK", "ESCROW_HELD", take, 0, f"M{x.sequence}: reversed by the card issuer"),
                  ("CHARGEBACK", "CHARGEBACK_REVERSAL", 0, take, f"M{x.sequence}: returned to the buyer's card")]
        if x.state == "ON_HOLD":
            a.on_hold_minor -= x.amount_minor
        ALLOCATION_STATES.assert_can(x.state, "UNFUNDED")
        x.state, x.funding_id, x.funded_at = "UNFUNDED", None, None
        a.held_minor -= x.amount_minor
        a.funded_minor -= x.amount_minor
        remaining -= take
        reversed_ids.append(x.milestone_id)
    loss = remaining  # whatever was already released: the platform owes it back to the provider
    if loss:
        lines += [("CHARGEBACK", "PLATFORM_CHARGEBACK_LOSS", loss, 0, "Chargeback on money already released"),
                  ("CHARGEBACK", "CHARGEBACK_REVERSAL", 0, loss, "Returned to the buyer's card")]
    if not lines:
        return
    _post(session, a, "CHARGEBACK", intent_id, lines)
    f.status = "REVERSED"
    a.status = _status(a, await _allocations(session, a.id))
    _evt(session, E.ESCROW_FUNDING_REVERSED, a, fundingId=f.id, milestoneIds=reversed_ids, amountMinor=int(payload["amountMinor"]),
         lossMinor=loss, currency=a.currency, reason=payload.get("reason") or "")


# ---- Disputes and termination -------------------------------------------------------------------------

async def _account_for_contract(session: AsyncSession, contract_id) -> EscrowAccount | None:
    return await session.scalar(select(EscrowAccount).where(EscrowAccount.contract_id == uuid.UUID(str(contract_id))).with_for_update())


async def dispute_initiated(session: AsyncSession, payload: dict) -> None:
    """Consumer of DISPUTE_INITIATED: freeze the disputed milestones' funds. While held, no release path may run."""
    a = await _account_for_contract(session, payload["contractId"])
    if a is None:
        return
    ids = {uuid.UUID(str(i)) for i in payload.get("milestoneIds", [])}
    frozen = []
    for x in await _allocations(session, a.id, lock=True):
        if x.milestone_id in ids and x.state == "HELD":
            ALLOCATION_STATES.assert_can(x.state, "ON_HOLD")
            x.state = "ON_HOLD"
            frozen.append(x)
    if not frozen:
        return
    a.on_hold_minor += sum(x.amount_minor for x in frozen)
    a.status = _status(a, await _allocations(session, a.id))
    _evt(session, E.ESCROW_HOLD_APPLIED, a, disputeId=payload["disputeId"], milestoneIds=[x.milestone_id for x in frozen],
         amountMinor=sum(x.amount_minor for x in frozen))


def _decision_lines(x: Allocation, gross: int, fee: int, refund: int, bps: int) -> list[tuple[str, str, int, int, str]]:
    lines: list[tuple[str, str, int, int, str]] = []
    if gross:
        lines += [("ESCROW_RELEASE", "ESCROW_HELD", gross, 0, f"M{x.sequence}: released by dispute decision"),
                  ("ESCROW_RELEASE", "PRO_PAYABLE", 0, gross - fee, f"M{x.sequence}: payable to professional")]
        if fee:
            lines.append(("PLATFORM_FEE", "PLATFORM_REVENUE", 0, fee, f"M{x.sequence}: platform fee {bps / 100:.2f}%"))
    if refund:
        lines += [("REFUND", "ESCROW_HELD", refund, 0, f"M{x.sequence}: refunded by dispute decision"),
                  ("REFUND", "BUYER_REFUND_PAYABLE", 0, refund, f"M{x.sequence}: refund payable to buyer")]
    return lines


async def dispute_resolved(session: AsyncSession, payload: dict) -> None:
    """Consumer of DISPUTE_RESOLVED: execute the decision exactly (release part, refund part, or back to held)."""
    a = await _account_for_contract(session, payload["contractId"])
    if a is None:
        return
    allocs = {x.milestone_id: x for x in await _allocations(session, a.id, lock=True)}
    bps = get_settings().platform_fee_bps
    released = refunded = 0
    now = clock.now()
    for item in payload.get("allocations", []):
        x = allocs.get(uuid.UUID(str(item["milestoneId"])))
        if x is None or x.state != "ON_HOLD":
            continue  # already executed (idempotent) or never funded
        gross, refund = int(item["releaseMinor"]), int(item["refundMinor"])
        if gross + refund > x.amount_minor:
            raise ValueError(f"Decision moves more than is held for milestone {x.milestone_id}")
        a.on_hold_minor -= x.amount_minor
        if gross == 0 and refund == 0:  # rework / extension: unfreeze, the money stays held
            ALLOCATION_STATES.assert_can(x.state, "HELD")
            x.state = "HELD"
            _evt(session, E.ESCROW_HOLD_RELEASED, a, disputeId=payload["disputeId"], milestoneIds=[x.milestone_id], amountMinor=x.amount_minor)
            continue
        fee = Money(gross, a.currency).percentage_bps(bps).minor if gross else 0
        ref = uuid.uuid4()
        if gross:
            r = Release(account_id=a.id, milestone_id=x.milestone_id, gross_minor=gross, fee_minor=fee, net_minor=gross - fee,
                        currency=a.currency, fee_bps=bps)
            session.add(r)
            await session.flush()
            ref = r.id
        _post(session, a, "DISPUTE_DECISION", ref, _decision_lines(x, gross, fee, refund, bps), x.milestone_id)
        new_state = "RELEASED" if not refund else ("REFUNDED" if not gross else "PARTIALLY_RELEASED")
        ALLOCATION_STATES.assert_can(x.state, new_state)
        x.state, x.released_minor, x.fee_minor, x.refunded_minor, x.released_at = new_state, gross - fee, fee, refund, now
        a.held_minor -= gross + refund
        a.released_minor += gross - fee
        a.fees_minor += fee
        a.refunded_minor += refund
        released, refunded = released + gross, refunded + refund
        if gross:
            _evt(session, E.ESCROW_RELEASED, a, milestoneId=x.milestone_id, disputeId=payload["disputeId"], professionalId=a.professional_id,
                 grossMinor=gross, feeMinor=fee, netMinor=gross - fee, currency=a.currency, releaseId=ref)
        if refund:
            _evt(session, E.ESCROW_REFUNDED, a, milestoneId=x.milestone_id, disputeId=payload["disputeId"], amountMinor=refund,
                 currency=a.currency, refundId=uuid.uuid4(), fundingIds=[x.funding_id] if x.funding_id else [])
    a.status = _status(a, list(allocs.values()))
    _evt(session, E.ESCROW_RESOLUTION_EXECUTED, a, disputeId=payload["disputeId"], releasedMinor=released, refundedMinor=refunded,
         currency=a.currency)


async def contract_terminated(session: AsyncSession, payload: dict) -> None:
    """Consumer of CONTRACT_TERMINATED: refund every funded, unreleased milestone that a dispute is not freezing."""
    a = await _account_for_contract(session, payload["contractId"])
    if a is None:
        return
    allocs = await _allocations(session, a.id, lock=True)
    for x in allocs:
        if x.state != "HELD":
            continue
        refund_id = uuid.uuid4()
        _post(session, a, "REFUND", refund_id, [
            ("REFUND", "ESCROW_HELD", x.amount_minor, 0, f"M{x.sequence}: refunded on termination"),
            ("REFUND", "BUYER_REFUND_PAYABLE", 0, x.amount_minor, f"M{x.sequence}: refund payable to buyer")], x.milestone_id)
        ALLOCATION_STATES.assert_can(x.state, "REFUNDED")
        x.state, x.refunded_minor = "REFUNDED", x.amount_minor
        a.held_minor -= x.amount_minor
        a.refunded_minor += x.amount_minor
        _evt(session, E.ESCROW_REFUNDED, a, milestoneId=x.milestone_id, disputeId=payload.get("disputeId"), amountMinor=x.amount_minor,
             currency=a.currency, refundId=refund_id, fundingIds=[x.funding_id] if x.funding_id else [])
    a.status = _status(a, allocs)


async def movements(session: AsyncSession, since, until) -> dict[tuple[str, str], tuple[int, int]]:
    """(ledger account, currency) -> (debits, credits) for ledger groups written in [since, until)."""
    rows = (await session.execute(
        select(LedgerEntry.ledger_account, LedgerEntry.currency, func.sum(LedgerEntry.debit_minor), func.sum(LedgerEntry.credit_minor))
        .where(LedgerEntry.created_at >= since, LedgerEntry.created_at < until)
        .group_by(LedgerEntry.ledger_account, LedgerEntry.currency))).all()
    return {(acct, ccy): (int(d or 0), int(c or 0)) for acct, ccy, d, c in rows}


async def totals(session: AsyncSession, since, until) -> dict[str, int]:
    rows = (await session.execute(
        select(LedgerEntry.entry_type, LedgerEntry.currency, func.sum(LedgerEntry.debit_minor + LedgerEntry.credit_minor))
        .where(LedgerEntry.created_at >= since, LedgerEntry.created_at < until)
        .group_by(LedgerEntry.entry_type, LedgerEntry.currency))).all()
    return {f"{t}:{c}": int(v) for t, c, v in rows}
