"""Escrow domain (Step 8): accounts per contract, milestone funding, capture, and the release decision tree
(Payments & Escrow doc, BUILD_SPEC s.escrow, Engineering Handbook 15.2).

Rules: no HTTP endpoint releases money; release happens only when a milestone is accepted. Every movement writes a
balanced append-only double-entry group in the same transaction as the balance change, under a row lock on the
account. Dispute holds and refunds arrive with the dispute step; contract amendments update only unfunded allocations.
"""

from __future__ import annotations

import uuid
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from zoikorum.config import get_settings
from zoikorum.domains.admin import facade as admin_facade
from zoikorum.domains.buyer import facade as buyer_facade
from zoikorum.domains.contract import facade as contract_facade
from zoikorum.domains.policy import facade as policy_facade
from zoikorum.domains.escrow.models import Allocation, EscrowAccount, Funding, LedgerEntry, Release
from zoikorum.domains.escrow.schemas import AllocationOut, BulkFundIn, EscrowOut, FundingOut, FundIn, LedgerLineOut
from zoikorum.domains.professional import facade as professional_facade
from zoikorum.shared import clock, fx
from zoikorum.shared.auth import Actor, OrgRole, PlatformRole
from zoikorum.shared.errors import ValidationFailed, Conflict, DomainError, Forbidden, NotFound, PolicyBlocked
from zoikorum.shared.event_catalog import E
from zoikorum.shared.events import record_audit, record_event
from zoikorum.shared.money import Money, MoneyDTO
from zoikorum.shared.relay import schedule_timer
from zoikorum.shared.state_machine import StateMachine

ALLOCATION_STATES = StateMachine("Allocation", {
    "UNFUNDED": {"FUNDING", "CANCELLED"},  # CANCELLED: e.g. a retainer cycle stopped before funding
    "FUNDING": {"HELD", "UNFUNDED"},
    "HELD": {"RELEASED", "PARTIALLY_RELEASED", "ON_HOLD", "RELEASE_PENDING_APPROVAL", "REFUNDED", "UNFUNDED"},  # UNFUNDED: chargeback
    "ON_HOLD": {"HELD", "RELEASED", "PARTIALLY_RELEASED", "REFUNDED", "UNFUNDED"},
    "RELEASE_PENDING_APPROVAL": {"RELEASED", "HELD", "ON_HOLD", "REFUNDED", "UNFUNDED"},
    "PARTIALLY_RELEASED": set(),
    "RELEASED": set(),
    "REFUNDED": set(),
    "CANCELLED": set(),
})
FUNDERS = (OrgRole.REQUESTER, OrgRole.APPROVER, OrgRole.BUDGET_OWNER)
TIMER_FUNDING_CHECK = "escrow.funding_check"
FUNDING_CHECK_AFTER = timedelta(hours=1)  # longer than every consumer retry together (about 42 minutes)
VIEWERS = (PlatformRole.FINANCIAL_OPS, PlatformRole.PLATFORM_ADMIN)


def _m(minor: int, ccy: str) -> MoneyDTO:
    return MoneyDTO(amountMinor=minor, currency=ccy)


def _fee_bps(a: EscrowAccount) -> int:
    """The fee agreed when this engagement started (accounts opened before it was recorded use today's)."""
    return a.fee_bps if a.fee_bps is not None else get_settings().platform_fee_bps


FUNDABLE_CONTRACT = "ACTIVE"
CLOSED_CONTRACT = ("TERMINATED", "COMPLETED")


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
    if allocs and a.refunded_minor > 0 and all(x.state in settled for x in allocs) and any(
            x.state in ("REFUNDED", "PARTIALLY_RELEASED") for x in allocs):
        return "REFUNDED" if a.released_minor == 0 else "CLOSED"
    if a.released_minor > 0:
        return "PARTIALLY_RELEASED"
    if a.funded_minor > 0:
        return "FUNDED"
    return "UNFUNDED"


async def _out(session: AsyncSession, actor: Actor, a: EscrowAccount, viewer: str) -> EscrowOut:
    allocs = await _allocations(session, a.id)
    fundings = (await session.scalars(select(Funding).where(Funding.account_id == a.id).order_by(Funding.created_at.desc()))).all()
    contract = await contract_facade.get_contract(session, a.contract_id)
    waiting = {m.id for m in contract.milestones if m.status == "PENDING_FUNDING"} if contract else set()
    can_fund = viewer == "BUYER" and contract is not None and contract.status == FUNDABLE_CONTRACT and any(
        x.state == "UNFUNDED" and x.milestone_id in waiting for x in allocs) and bool(
        (await buyer_facade.get_member_roles(session, a.organization_id, actor.identity_id)).intersection(FUNDERS)) and not (
        await contract_facade.retainer_paused(session, a.contract_id))
    ccy = a.currency
    unfunded = sum(x.amount_minor for x in allocs if x.state == "UNFUNDED")
    releases = {r.milestone_id: r.id for r in (await session.scalars(select(Release).where(Release.account_id == a.id))).all()}
    return EscrowOut(
        autoFundingEnabledAt=a.auto_fund_enabled_at,
        id=a.id, contractId=a.contract_id, status=a.status, currency=ccy, total=_m(a.total_minor, ccy), funded=_m(a.funded_minor, ccy),
        held=_m(a.held_minor, ccy), released=_m(a.released_minor, ccy), fees=_m(a.fees_minor, ccy), refunded=_m(a.refunded_minor, ccy),
        unfunded=_m(unfunded, ccy), feeBps=_fee_bps(a),
        allocations=[AllocationOut(milestoneId=x.milestone_id, sequence=x.sequence, title=x.title, amount=_m(x.amount_minor, ccy), state=x.state,
                                   released=_m(x.released_minor, ccy), fee=_m(x.fee_minor, ccy), fundedAt=x.funded_at, releasedAt=x.released_at,
                                   releaseReference=f"ZK-REL-{releases[x.milestone_id].hex[:8].upper()}" if x.milestone_id in releases else None)
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
                      total_minor=int(payload["totalMinor"]), status="UNFUNDED", fee_bps=get_settings().platform_fee_bps)
    session.add(a)
    await session.flush()
    session.add_all([Allocation(account_id=a.id, milestone_id=uuid.UUID(str(m["milestoneId"])), sequence=m["sequence"], title=m["title"],
                                amount_minor=int(m["amountMinor"]), state="UNFUNDED") for m in payload.get("milestones", [])])
    _evt(session, E.ESCROW_OPENED, a, professionalId=a.professional_id, currency=a.currency, totalMinor=a.total_minor)


async def contract_amended(session: AsyncSession, payload: dict) -> None:
    """Apply signed contract amendments without rewriting any allocation with money or work in flight."""
    contract_id = uuid.UUID(str(payload["contractId"]))
    account = await session.scalar(
        select(EscrowAccount).where(EscrowAccount.contract_id == contract_id).with_for_update()
    )
    if account is None:
        raise NotFound("Escrow account not found for amended contract")
    allocations = await _allocations(session, account.id, lock=True)
    requested = {
        uuid.UUID(str(item["milestoneId"])): int(item["amountMinor"])
        for item in payload.get("milestones", [])
    }
    by_id = {item.milestone_id: item for item in allocations}
    if requested.keys() != by_id.keys():
        raise Conflict("Amended milestone schedule does not match the escrow allocations", code="AMENDMENT_ALLOCATION_MISMATCH")
    for milestone_id, amount in requested.items():
        allocation = by_id[milestone_id]
        if allocation.amount_minor == amount:
            continue
        if allocation.state != "UNFUNDED":
            raise Conflict("An amendment cannot change a funded or released escrow allocation",
                           code="AMENDED_ALLOCATION_HAS_FUNDS")
        allocation.amount_minor = amount
        allocation.title = str(next(
            item["title"] for item in payload["milestones"] if uuid.UUID(str(item["milestoneId"])) == milestone_id
        ))
    total = int(payload["totalMinor"])
    if sum(item.amount_minor for item in allocations) != total or total < account.funded_minor:
        raise Conflict("Amended escrow total does not reconcile with the allocations and funds already captured",
                       code="AMENDMENT_TOTAL_MISMATCH")
    account.total_minor = total


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
    await _fund_for(session, actor.identity_id, a, body)
    return await _out(session, actor, a, "BUYER")


async def _fund_for(session: AsyncSession, identity_id: uuid.UUID, a: EscrowAccount, body: FundIn) -> None:
    """Fund milestones on behalf of a member of the buyer organisation: their role, their spend limit and the
    organisation's policy are checked exactly as when they press Fund themselves (also used by retainer auto-funding)."""
    from zoikorum.domains.payments import facade as payments_facade
    payments_facade.require_available()
    await admin_facade.require_on(session, "FUNDING")
    roles = await buyer_facade.get_member_roles(session, a.organization_id, identity_id)
    if not roles.intersection(FUNDERS):
        raise Forbidden("Funding needs the Requester, Approver or Budget Owner role", code="ROLE_REQUIRED")
    contract = await contract_facade.get_contract(session, a.contract_id)
    if contract is not None and await contract_facade.retainer_paused(session, a.contract_id):
        raise Conflict("This retainer is paused. Resume it to fund the next cycle.", code="RETAINER_PAUSED")
    if contract is None or contract.status != FUNDABLE_CONTRACT:
        why = {"DISPUTED": "while a dispute is open", "PENDING_SIGNATURE": "until both parties sign the latest version",
               "COMPLETED": "because the engagement is complete", "TERMINATED": "because the engagement has ended"}
        raise Conflict(f"Funding is paused {why.get(contract.status if contract else '', 'right now')}.", code="CONTRACT_NOT_ACTIVE")
    waiting = {m.id for m in contract.milestones if m.status == "PENDING_FUNDING"}
    allocs = await _allocations(session, a.id, lock=True)
    if body.all:
        wanted = [x for x in allocs if x.state == "UNFUNDED" and x.milestone_id in waiting]
    else:
        wanted = [x for x in allocs if x.milestone_id in set(body.milestoneIds)]
    if not body.all and len(wanted) != len(set(body.milestoneIds)):
        raise NotFound("Milestone not found on this contract")
    if not wanted:
        raise Conflict("Every milestone is already funded", code="NOTHING_TO_FUND")
    busy = [x for x in wanted if x.state != "UNFUNDED"]
    if busy:
        raise Conflict(f"M{busy[0].sequence} is already funded or being funded", code="ALREADY_FUNDED")
    closed = [x for x in wanted if x.milestone_id not in waiting]
    if closed:
        raise Conflict(f"M{closed[0].sequence} is no longer waiting for funding", code="MILESTONE_NOT_FUNDABLE")
    amount = sum(x.amount_minor for x in wanted)
    if a.funded_minor + amount > a.total_minor:
        raise Conflict("That would fund more than the contract total", code="OVER_FUNDING")
    limit = await buyer_facade.get_member_spend_limit(session, a.organization_id, identity_id)
    if limit is not None:
        # Per engagement: what this person has already put in counts too, so a large contract cannot be funded in
        # small pieces. A limit in another currency is compared at Finance's rate with a safety margin (shared/fx).
        already = await session.scalar(select(func.coalesce(func.sum(Funding.amount_minor), 0)).where(
            Funding.account_id == a.id, Funding.requested_by == identity_id, Funding.status.in_(("REQUESTED", "CAPTURED")))) or 0
        if not fx.within_limit(already + amount, a.currency, limit.minor, limit.currency):
            raise PolicyBlocked("This funding is above your spend limit for this engagement; ask a colleague with a higher limit",
                                code="SPEND_LIMIT_EXCEEDED")

    await policy_facade.require_allowed(session, await policy_facade.commercial_context(session,
        org_id=a.organization_id, professional_id=a.professional_id, action=policy_facade.PolicyAction.ESCROW_FUND,
        subject_type="EscrowAccount", subject_id=a.id, actor_identity_id=identity_id,
        amount=amount, currency=a.currency, pinned_version_id=contract.policy_version_id,
        platform_default_pinned=contract.policy_version_id is None,
        extra={"contract.termsHash": contract.terms_hash, "contract.version": contract.contract_version,
            "funding.milestoneIds": sorted(str(x.milestone_id) for x in wanted)}))
    f = Funding(account_id=a.id, organization_id=a.organization_id, requested_by=identity_id,
                milestone_ids=[str(x.milestone_id) for x in wanted], amount_minor=amount, currency=a.currency, status="REQUESTED")
    session.add(f)
    await session.flush()
    for x in wanted:
        ALLOCATION_STATES.assert_can(x.state, "FUNDING")
        x.state, x.funding_id = "FUNDING", f.id
    _evt(session, E.ESCROW_FUNDING_REQUESTED, a, fundingId=f.id, amountMinor=amount, currency=a.currency,
         milestoneIds=[x.milestone_id for x in wanted], paymentMethodToken=body.paymentMethodToken)
    await schedule_timer(session, TIMER_FUNDING_CHECK, str(f.id), clock.now() + FUNDING_CHECK_AFTER, {"fundingId": str(f.id)})
    await session.flush()


async def payment_captured(session: AsyncSession, payload: dict) -> None:
    """Consumer of PAYMENT_CAPTURED: hold the money in escrow and start the funded milestones. Idempotent per funding."""
    f = await session.get(Funding, uuid.UUID(str(payload["fundingId"])), with_for_update=True)
    if f is None or f.status not in ("REQUESTED", "FAILED"):
        return
    a = await _account(session, f.account_id, lock=True)
    if int(payload["amountMinor"]) != f.amount_minor or payload["currency"] != f.currency:
        raise ValueError(f"Captured amount does not match funding {f.id}")
    if f.status == "FAILED":  # given up (e.g. the hourly check) but the buyer paid after all: hold it and give it back
        _post(session, a, "FUNDING", f.id, [
            ("BUYER_FUNDING", "BUYER_CLEARING", f.amount_minor, 0, "Payment captured after the funding was given up"),
            ("ESCROW_HOLD", "ESCROW_HELD", 0, f.amount_minor, "Held only until it is returned")])
        refund_id = uuid.uuid4()
        _post(session, a, "REFUND", refund_id, [
            ("REFUND", "ESCROW_HELD", f.amount_minor, 0, "Late payment returned to the buyer"),
            ("REFUND", "BUYER_REFUND_PAYABLE", 0, f.amount_minor, "Refund payable to buyer")])
        f.status, f.captured_at = "REFUNDED", clock.now()
        a.refunded_minor += f.amount_minor
        _evt(session, E.ESCROW_REFUNDED, a, milestoneId=None, amountMinor=f.amount_minor, currency=a.currency, refundId=refund_id,
             fundingIds=[f.id])
        return
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
    _evt(session, E.ESCROW_FUNDED, a, fundingId=f.id, milestoneIds=[x.milestone_id for x in allocs], amountMinor=f.amount_minor,
         currency=f.currency)
    # The payment can finish after the work closed (a cycle cancelled, or the engagement ended while checkout was open):
    # that money is not kept in escrow for nothing; it goes straight back to the buyer.
    contract = await contract_facade.get_contract(session, a.contract_id)
    status = {m.id: m.status for m in contract.milestones} if contract else {}
    for x in allocs:
        ended = contract is None or contract.status in CLOSED_CONTRACT
        if status.get(x.milestone_id) == "CANCELLED" or (ended and status.get(x.milestone_id) != "ACCEPTED"):
            _refund(session, a, x, "refunded: the work closed before the payment completed")
    a.status = _status(a, await _allocations(session, a.id))


async def funding_check(session: AsyncSession, payload: dict) -> None:
    """An hour after funding was requested: if the provider never even started the charge (it stayed unavailable through
    every retry), the milestones go back to unfunded so the buyer can try again, instead of showing "processing"
    forever. A charge that started (e.g. the buyer is still at checkout) is left to finish or fail on its own."""
    from zoikorum.domains.payments import facade as payments_facade

    f = await session.get(Funding, uuid.UUID(payload["fundingId"]), with_for_update=True)
    if f is None or f.status != "REQUESTED" or await payments_facade.payment_started(session, f.id):
        return
    await payment_failed(session, {"fundingId": f.id, "failureMessage": "The payment could not be started. Please try again."})


async def payment_failed(session: AsyncSession, payload: dict) -> None:
    """Consumer of PAYMENT_FAILED: the milestones go back to unfunded; nothing is held."""
    f = await session.get(Funding, uuid.UUID(str(payload["fundingId"])), with_for_update=True)
    if f is None or f.status != "REQUESTED":
        return
    a = await _account(session, f.account_id, lock=True)
    contract = await contract_facade.get_contract(session, a.contract_id)
    closed = {m.id for m in contract.milestones if m.status == "CANCELLED"} if contract else set()
    for x in await _allocations(session, f.account_id, lock=True):
        if x.funding_id == f.id and x.state == "FUNDING":
            x.state, x.funding_id = ("CANCELLED" if x.milestone_id in closed else "UNFUNDED"), None
    f.status, f.failure_message = "FAILED", (payload.get("failureMessage") or "Payment was declined")[:300]


# ---- Release decision tree (Handbook 15.2) ---------------------------------------------------------

def _accepted_gross(accepted_release_minor: int | None, funded_minor: int) -> int:
    """Use persisted acceptance terms, including when an approval resumes release."""
    if accepted_release_minor is None:
        return funded_minor
    if not 0 < accepted_release_minor <= funded_minor:
        raise Conflict("The accepted release amount does not match funded work", code="INVALID_ACCEPTED_RELEASE")
    return accepted_release_minor


RELEASE_RESUME_TIMER = "escrow.release_resume"
TIMER_RELEASE_AFTER_WINDOW = "escrow.release_after_window"


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
    if x.state not in ("HELD", "RELEASE_PENDING_APPROVAL"):
        evaluated("BLOCKED", f"NOT_FUNDED:{x.state}")
        return

    if await admin_facade.is_paused(session, "RELEASES"):
        evaluated("BLOCKED", "RELEASES_PAUSED")  # staff paused releases: try again in 10 minutes, never dropped
        when = clock.now() + timedelta(minutes=10)
        await schedule_timer(session, RELEASE_RESUME_TIMER, f"{milestone_id}:{int(when.timestamp()) // 600}", when)
        return
    contract = await contract_facade.get_contract(session, a.contract_id)
    milestone = next((m for m in contract.milestones if m.id == milestone_id), None)
    if milestone is None or milestone.status != "ACCEPTED":
        evaluated("BLOCKED", "MILESTONE_NOT_ACCEPTED")
        return
    # Challenge window (contract terms): accepted work stays held until it ends, so a defect found after acceptance can
    # still be disputed. The timer brings the release back here when the window is over.
    window = int((await contract_facade.policy_controls(session, a.contract_id)).get("challengeWindowDays") or 0)
    if window and milestone.accepted_at and clock.now() < (due := milestone.accepted_at + timedelta(days=window)):
        await schedule_timer(session, TIMER_RELEASE_AFTER_WINDOW, str(milestone_id), due, {"milestoneId": str(milestone_id)})
        evaluated("HELD", "CHALLENGE_WINDOW")
        return
    settings = await policy_facade.get_settings_for_org(session,
        a.organization_id if contract.policy_version_id else None, contract.policy_version_id)
    if not settings.partial_release_allowed and any(m.status not in ("ACCEPTED", "CANCELLED") for m in contract.milestones):
        evaluated("BLOCKED", "ALL_MILESTONES_MUST_BE_ACCEPTED")
        return
    decision = await policy_facade.evaluate(session, await policy_facade.commercial_context(session,
        org_id=a.organization_id, professional_id=a.professional_id, action=policy_facade.PolicyAction.ESCROW_RELEASE,
        subject_type="Milestone", subject_id=milestone_id,
        actor_identity_id=await contract_facade.milestone_acceptor(session, milestone_id),
        amount=x.amount_minor, currency=a.currency, pinned_version_id=contract.policy_version_id,
        platform_default_pinned=contract.policy_version_id is None,
        extra={"contract.termsHash": contract.terms_hash, "contract.version": contract.contract_version,
            "engagement.allMilestonesAccepted": all(m.status in ("ACCEPTED", "CANCELLED") for m in contract.milestones),
            "milestone.acceptedAt": next((m.accepted_at.isoformat() for m in contract.milestones if m.id == milestone_id and m.accepted_at), None)}))
    if not decision.allowed:
        if decision.decision == policy_facade.Decision.REQUIRE_APPROVAL and x.state == "HELD":
            ALLOCATION_STATES.assert_can(x.state, "RELEASE_PENDING_APPROVAL")
            x.state = "RELEASE_PENDING_APPROVAL"
        evaluated(decision.decision, decision.first_reason.code if decision.first_reason else "POLICY")
        return
    bps = _fee_bps(a)
    # An agreed partial acceptance releases only that part; the rest goes back to the buyer.
    gross = _accepted_gross(milestone.accepted_release_minor, x.amount_minor)
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


async def release_not_approved(session: AsyncSession, payload: dict, event_type: str) -> None:
    """The buyer organisation's approver denied (or let expire) the release of accepted work. The money stays held -
    it is neither paid nor refunded on one side's word - and both parties and Financial Ops are told, so the buyer can
    ask again or either party can take it to a mediator."""
    x = await session.scalar(select(Allocation).where(Allocation.milestone_id == uuid.UUID(str(payload["subjectId"]))))
    if x is None or x.state not in ("HELD", "RELEASE_PENDING_APPROVAL"):
        return
    a = await _account(session, x.account_id, lock=True)
    _evt(session, E.ESCROW_RELEASE_BLOCKED, a, milestoneId=x.milestone_id, amountMinor=x.amount_minor, currency=a.currency,
         reason="APPROVAL_DENIED" if event_type == E.APPROVAL_DENIED else "APPROVAL_EXPIRED", professionalId=a.professional_id)
    await _schedule_release_escalation(session, x.milestone_id, 1)


TIMER_RELEASE_ESCALATION = "escrow.release_escalation"
RELEASE_ESCALATION_ROUNDS = 3  # then it stays with the parties' dispute right and Financial Ops


async def _schedule_release_escalation(session: AsyncSession, milestone_id: uuid.UUID, round_: int) -> None:
    days = get_settings().release_block_escalation_days
    await schedule_timer(session, TIMER_RELEASE_ESCALATION, f"{milestone_id}:{round_}", clock.now() + timedelta(days=days),
                         {"milestoneId": str(milestone_id), "round": round_})


async def release_escalation(session: AsyncSession, payload: dict) -> None:
    """Timer: accepted work is still unpaid because its release was not approved. The organisation's approvers and admins
    and the professional are told again, and that either side can open a payment-release dispute. Never moves money."""
    milestone_id = uuid.UUID(str(payload["milestoneId"]))
    x = await session.scalar(select(Allocation).where(Allocation.milestone_id == milestone_id))
    if x is None or x.state not in ("HELD", "RELEASE_PENDING_APPROVAL"):
        return  # released, refunded, or a dispute already holds it
    if await session.scalar(select(Release.id).where(Release.milestone_id == milestone_id)):
        return
    a = await _account(session, x.account_id)
    round_ = int(payload.get("round", 1))
    _evt(session, E.ESCROW_RELEASE_ESCALATED, a, milestoneId=milestone_id, amountMinor=x.amount_minor, currency=a.currency,
         professionalId=a.professional_id, round=round_, daysWaiting=round_ * get_settings().release_block_escalation_days)
    if round_ < RELEASE_ESCALATION_ROUNDS:
        await _schedule_release_escalation(session, milestone_id, round_ + 1)



async def milestone_cancelled(session: AsyncSession, payload: dict) -> None:
    """Consumer of MILESTONE_CANCELLED: an unfunded allocation is closed; it no longer counts as money to fund."""
    x = await session.scalar(select(Allocation).where(Allocation.milestone_id == uuid.UUID(str(payload["milestoneId"]))).with_for_update())
    if x is None or x.state != "UNFUNDED":
        return
    a = await _account(session, x.account_id, lock=True)
    x.state = "CANCELLED"
    a.status = _status(a, await _allocations(session, a.id))


# ---- Chargebacks (Payments & Escrow s.18) ----------------------------------------------------------------

async def release_accepted_siblings(session, contract_id):
    contract = await contract_facade.get_contract(session, uuid.UUID(str(contract_id)))
    if not contract or any(m.status not in ("ACCEPTED", "CANCELLED") for m in contract.milestones):
        return
    controls = await contract_facade.policy_controls(session, contract.id)
    if controls.get("partialReleaseAllowed", True):
        return
    waiting = {x.milestone_id for x in (await session.scalars(select(Allocation).where(
        Allocation.milestone_id.in_([m.id for m in contract.milestones]),
        Allocation.state.in_(("HELD", "RELEASE_PENDING_APPROVAL"))))).all()}
    for milestone in contract.milestones:
        if milestone.status == "ACCEPTED" and milestone.id in waiting:
            await milestone_accepted(session, {"milestoneId": milestone.id})

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
    leftovers: list[tuple[Allocation, int]] = []
    for x in await _allocations(session, a.id, lock=True):
        if remaining <= 0 or x.funding_id != f.id or x.state not in ("HELD", "ON_HOLD", "RELEASE_PENDING_APPROVAL"):
            continue
        take = min(x.amount_minor, remaining)
        lines += [("CHARGEBACK", "ESCROW_HELD", take, 0, f"M{x.sequence}: reversed by the card issuer"),
                  ("CHARGEBACK", "CHARGEBACK_REVERSAL", 0, take, f"M{x.sequence}: returned to the buyer's card")]
        if take < x.amount_minor:  # partial chargeback: the rest of this milestone's money is refunded so it can be funded afresh
            rest = x.amount_minor - take
            lines += [("REFUND", "ESCROW_HELD", rest, 0, f"M{x.sequence}: rest refunded after a partial chargeback"),
                      ("REFUND", "BUYER_REFUND_PAYABLE", 0, rest, f"M{x.sequence}: refund payable to buyer")]
            leftovers.append((x, rest))
            a.refunded_minor += rest
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
    for x, rest in leftovers:
        _evt(session, E.ESCROW_REFUNDED, a, milestoneId=x.milestone_id, amountMinor=rest, currency=a.currency, refundId=uuid.uuid4(),
             fundingIds=[f.id])
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
        if x.milestone_id in ids and x.state in ("HELD", "RELEASE_PENDING_APPROVAL"):
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
    bps = _fee_bps(a)
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


def _refund(session: AsyncSession, a: EscrowAccount, x: Allocation, why: str, dispute_id=None) -> None:
    """Return one held allocation to the buyer (balanced ledger group + ESCROW_REFUNDED for payments)."""
    refund_id = uuid.uuid4()
    _post(session, a, "REFUND", refund_id, [
        ("REFUND", "ESCROW_HELD", x.amount_minor, 0, f"M{x.sequence}: {why}"),
        ("REFUND", "BUYER_REFUND_PAYABLE", 0, x.amount_minor, f"M{x.sequence}: refund payable to buyer")], x.milestone_id)
    ALLOCATION_STATES.assert_can(x.state, "REFUNDED")
    x.state, x.refunded_minor = "REFUNDED", x.amount_minor
    a.held_minor -= x.amount_minor
    a.refunded_minor += x.amount_minor
    _evt(session, E.ESCROW_REFUNDED, a, milestoneId=x.milestone_id, disputeId=dispute_id, amountMinor=x.amount_minor,
         currency=a.currency, refundId=refund_id, fundingIds=[x.funding_id] if x.funding_id else [])


async def contract_terminated(session: AsyncSession, payload: dict) -> None:
    """Consumer of CONTRACT_TERMINATED: work the buyer accepted is still paid; every other funded, unreleased milestone
    that a dispute is not freezing is refunded; allocations never funded are closed."""
    a = await _account_for_contract(session, payload["contractId"])
    if a is None:
        return
    contract = await contract_facade.get_contract(session, a.contract_id)
    accepted = {m.id for m in contract.milestones if m.status == "ACCEPTED"} if contract else set()
    for x in await _allocations(session, a.id, lock=True):
        if x.state in ("HELD", "RELEASE_PENDING_APPROVAL") and x.milestone_id in accepted:
            await milestone_accepted(session, {"milestoneId": x.milestone_id})  # accepted before the end: pay it
    allocs = await _allocations(session, a.id, lock=True)
    for x in allocs:
        if x.state == "HELD" and x.milestone_id not in accepted:
            _refund(session, a, x, "refunded on termination", payload.get("disputeId"))
        elif x.state == "UNFUNDED":
            x.state = "CANCELLED"
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



# ---- Enterprise payments overview and bulk funding (Payments & Escrow: enterprise dashboard) ---------------------------

async def organization_overview(session: AsyncSession, actor: Actor, org_id: uuid.UUID) -> dict:
    """For any member of the buyer organisation: money held per vendor, what is frozen in disputes, what still needs
    funding, and when held money is expected to be released (by milestone due date)."""
    if not await buyer_facade.get_member_roles(session, org_id, actor.identity_id):
        raise NotFound("Organization not found")
    accounts = (await session.scalars(select(EscrowAccount).where(EscrowAccount.organization_id == org_id))).all()
    allocs = (await session.scalars(select(Allocation).where(Allocation.account_id.in_([a.id for a in accounts])))).all() if accounts else []
    by_account: dict[uuid.UUID, list[Allocation]] = {}
    for x in allocs:
        by_account.setdefault(x.account_id, []).append(x)

    vendors: dict[tuple[uuid.UUID, str], dict] = {}
    totals: dict[str, dict] = {}
    timeline: list[dict] = []
    fundable: list[dict] = []
    for a in accounts:
        contract = await contract_facade.get_contract(session, a.contract_id)
        if contract is None:
            continue
        due = {m.id: m for m in contract.milestones}
        pro = await professional_facade.get_professional(session, a.professional_id)
        v = vendors.setdefault((a.professional_id, a.currency), {
            "professionalId": a.professional_id, "name": pro.display_name if pro else "Professional", "currency": a.currency,
            "engagements": 0, "heldMinor": 0, "frozenMinor": 0, "awaitingFundingMinor": 0, "releasedMinor": 0})
        t = totals.setdefault(a.currency, {"currency": a.currency, "heldMinor": 0, "frozenMinor": 0, "awaitingFundingMinor": 0, "releasedMinor": 0})
        v["engagements"] += 1
        for x in by_account.get(a.id, []):
            m = due.get(x.milestone_id)
            if x.state == "HELD":
                bucket = "heldMinor"
                timeline.append({"accountId": a.id, "contractId": a.contract_id, "reference": contract.reference, "vendor": v["name"],
                                 "milestone": f"M{x.sequence} {x.title}", "amountMinor": x.amount_minor, "currency": a.currency,
                                 "dueDate": m.due_date if m else None, "status": m.status if m else None})
            elif x.state == "ON_HOLD":
                bucket = "frozenMinor"
            elif x.state == "UNFUNDED" and contract.status == FUNDABLE_CONTRACT and m and m.status == "PENDING_FUNDING":
                bucket = "awaitingFundingMinor"
                fundable.append({"accountId": a.id, "contractId": a.contract_id, "reference": contract.reference, "vendor": v["name"],
                                 "milestoneId": x.milestone_id, "milestone": f"M{x.sequence} {x.title}", "amountMinor": x.amount_minor,
                                 "currency": a.currency, "dueDate": m.due_date})
            else:
                bucket = None
            if bucket:
                v[bucket] += x.amount_minor
                t[bucket] += x.amount_minor
            v["releasedMinor"] += x.released_minor
            t["releasedMinor"] += x.released_minor
    timeline.sort(key=lambda r: (r["dueDate"] is None, r["dueDate"] or clock.now().date()))
    fundable.sort(key=lambda r: (r["dueDate"] is None, r["dueDate"] or clock.now().date()))
    return {"organizationId": org_id, "totals": list(totals.values()),
            "vendors": sorted(vendors.values(), key=lambda v: -(v["heldMinor"] + v["frozenMinor"])),
            "releaseTimeline": timeline[:100], "awaitingFunding": fundable[:100]}


async def bulk_fund(session: AsyncSession, actor: Actor, body: BulkFundIn) -> dict:
    """Fund several engagements in one go. Each is a separate funding with every usual check; results say which
    worked and why any did not."""
    results = []
    for item in body.items:
        try:
            async with session.begin_nested():
                out = await fund(session, actor, item.accountId, FundIn(milestoneIds=item.milestoneIds, paymentMethodToken=body.paymentMethodToken))
            results.append({"accountId": item.accountId, "ok": True, "status": out.status})
        except DomainError as e:
            results.append({"accountId": item.accountId, "ok": False, "code": e.code, "detail": str(e.detail) if getattr(e, "detail", None) else e.code})
    return {"results": results, "funded": sum(1 for r in results if r["ok"]), "failed": sum(1 for r in results if not r["ok"])}



# ---- Retainer auto-funding (Payments & Escrow s.15: auto-fund cycles from a saved payment method) ----------------------

def _saved_method_ok(token: str) -> bool:
    """A method that can be charged again later: a saved card or bank mandate at the provider, not a one-off checkout."""
    from zoikorum.config import get_settings

    if token == "hosted_checkout":
        return False
    return get_settings().payment_provider != "stripe" or token.startswith("pm_")


async def set_auto_funding(session: AsyncSession, actor: Actor, account_id: uuid.UUID, token: str | None) -> EscrowOut:
    """Turn automatic funding of retainer cycles on (with a saved payment method) or off. Funding then runs under the
    authority of the person who turned it on: their role and spend limit are checked again for every cycle."""
    a = await _account(session, account_id, lock=True)
    if await _viewer(session, actor, a) != "BUYER":
        raise Forbidden("Only the buyer organisation sets up automatic funding")
    roles = await buyer_facade.get_member_roles(session, a.organization_id, actor.identity_id)
    if not roles.intersection(FUNDERS):
        raise Forbidden("Automatic funding needs the Requester, Approver or Budget Owner role", code="ROLE_REQUIRED")
    if not await contract_facade.is_retainer(session, a.contract_id):
        raise Conflict("Automatic funding is for retainers", code="NOT_A_RETAINER")
    actor.require_step_up()
    if token is not None:
        if not _saved_method_ok(token):
            raise ValidationFailed("Choose a saved payment method; a one-off checkout cannot be charged again", code="SAVED_METHOD_REQUIRED")
        a.auto_fund_token, a.auto_fund_identity_id, a.auto_fund_enabled_at = token, actor.identity_id, clock.now()
    else:
        a.auto_fund_token = a.auto_fund_identity_id = a.auto_fund_enabled_at = None
    _evt(session, E.ESCROW_AUTO_FUNDING_CHANGED, a, enabled=token is not None, by=actor.identity_id, audience="BUYER",
         message="Retainer cycles will now be funded automatically before they are due." if token else "Automatic funding is off.")
    record_audit(session, "escrow.auto_funding." + ("enabled" if token else "disabled"), object_type="EscrowAccount", object_id=a.id,
                 tenant_id=a.organization_id)
    await session.flush()
    return await _out(session, actor, a, "BUYER")


async def auto_fund_cycle(session: AsyncSession, payload: dict) -> None:
    """Consumer of MILESTONE_FUNDING_REMINDER: fund the upcoming cycle when automatic funding is on. Every usual check
    applies; if one fails, the buyer is told and the cycle waits to be funded by hand."""
    a = await session.scalar(select(EscrowAccount).where(EscrowAccount.contract_id == uuid.UUID(str(payload["contractId"])))
                             .with_for_update())
    if a is None or not a.auto_fund_token or not a.auto_fund_identity_id:
        return
    milestone_id = uuid.UUID(str(payload["milestoneId"]))
    alloc = await session.scalar(select(Allocation).where(Allocation.account_id == a.id, Allocation.milestone_id == milestone_id))
    if alloc is None or alloc.state != "UNFUNDED":
        return
    try:
        async with session.begin_nested():
            await _fund_for(session, a.auto_fund_identity_id, a,
                            FundIn(milestoneIds=[milestone_id], paymentMethodToken=a.auto_fund_token))
    except DomainError as e:
        _evt(session, E.ESCROW_AUTO_FUNDING_FAILED, a, milestoneId=milestone_id, code=e.code, audience="BUYER",
             message=f"M{alloc.sequence} {alloc.title} could not be funded automatically ({e.detail or e.code}). Fund it from the engagement.")
