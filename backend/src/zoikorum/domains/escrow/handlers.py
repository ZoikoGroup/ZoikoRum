"""Escrow opens with an active contract, holds captured payments, releases on acceptance, freezes and settles disputes."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from zoikorum.domains.escrow import service
from zoikorum.shared.event_catalog import E
from zoikorum.shared.events import EventEnvelope, subscribe
from zoikorum.shared.relay import on_timer


@on_timer(service.TIMER_FUNDING_CHECK)
async def on_funding_check(session: AsyncSession, key: str, payload: dict) -> None:
    await service.funding_check(session, payload)


@subscribe(E.CONTRACT_ACTIVATED, consumer="escrow.open_account")
async def on_contract_activated(session: AsyncSession, event: EventEnvelope) -> None:
    await service.open_account(session, event.payload)


@subscribe(E.CONTRACT_AMENDED, consumer="escrow.apply_contract_amendment")
async def on_contract_amended(session: AsyncSession, event: EventEnvelope) -> None:
    await service.contract_amended(session, event.payload)


@subscribe(E.PAYMENT_CAPTURED, consumer="escrow.hold_captured_funds")
async def on_payment_captured(session: AsyncSession, event: EventEnvelope) -> None:
    await service.payment_captured(session, event.payload)


@subscribe(E.PAYMENT_FAILED, consumer="escrow.funding_failed")
async def on_payment_failed(session: AsyncSession, event: EventEnvelope) -> None:
    await service.payment_failed(session, event.payload)


@subscribe(E.MILESTONE_CANCELLED, consumer="escrow.cancel_allocation")
async def on_milestone_cancelled(session: AsyncSession, event: EventEnvelope) -> None:
    await service.milestone_cancelled(session, event.payload)
    await service.release_accepted_siblings(session, event.payload["contractId"])


# "Release only when every milestone is accepted": the last milestone can also close by a dispute decision or by
# cancelling the remaining cycles, not only by acceptance. Whatever closes it, the accepted ones are then paid.
@subscribe(E.CONTRACT_COMPLETED, consumer="escrow.release_on_completion")
async def on_contract_completed(session: AsyncSession, event: EventEnvelope) -> None:
    await service.release_accepted_siblings(session, event.payload["contractId"])


@subscribe(E.APPROVAL_DENIED, consumer="escrow.release_denied")
@subscribe(E.APPROVAL_EXPIRED, consumer="escrow.release_denied")
async def on_release_not_approved(session: AsyncSession, event: EventEnvelope) -> None:
    if event.payload.get("action") == "ESCROW_RELEASE" and event.payload.get("subjectType") == "Milestone":
        await service.release_not_approved(session, event.payload, event.eventType)


@subscribe(E.PAYMENT_CHARGED_BACK, consumer="escrow.chargeback")
async def on_payment_charged_back(session: AsyncSession, event: EventEnvelope) -> None:
    await service.payment_charged_back(session, event.payload)


@subscribe(E.MILESTONE_ACCEPTED, consumer="escrow.release_decision")
async def on_milestone_accepted(session: AsyncSession, event: EventEnvelope) -> None:
    await service.milestone_accepted(session, event.payload)
    await service.release_accepted_siblings(session, event.payload["contractId"])


@on_timer(service.RELEASE_RESUME_TIMER)
async def resume_paused_release(session: AsyncSession, key: str, payload: dict) -> None:
    """A release that waited while staff had paused releases (admin switch RELEASES)."""
    await service.milestone_accepted(session, {"milestoneId": key.split(":")[0]})


@subscribe(E.APPROVAL_GRANTED, consumer="escrow.resume_approved_release")
@subscribe(E.EXCEPTION_GRANTED, consumer="escrow.resume_excepted_release")
async def on_policy_authorized(session: AsyncSession, event: EventEnvelope) -> None:
    if event.payload.get("action") == "ESCROW_RELEASE" and event.payload.get("subjectType") == "Milestone":
        await service.milestone_accepted(session, {"milestoneId": event.payload["subjectId"]})


@subscribe(E.DISPUTE_INITIATED, consumer="escrow.dispute_hold")
async def on_dispute_initiated(session: AsyncSession, event: EventEnvelope) -> None:
    await service.dispute_initiated(session, event.payload)


@subscribe(E.DISPUTE_RESOLVED, consumer="escrow.execute_dispute_decision")
async def on_dispute_resolved(session: AsyncSession, event: EventEnvelope) -> None:
    await service.dispute_resolved(session, event.payload)
    await service.release_accepted_siblings(session, event.payload["contractId"])


@subscribe(E.CONTRACT_TERMINATED, consumer="escrow.refund_on_termination")
async def on_contract_terminated(session: AsyncSession, event: EventEnvelope) -> None:
    await service.contract_terminated(session, event.payload)


@subscribe(E.MILESTONE_FUNDING_REMINDER, consumer="escrow.auto_fund_retainer_cycle")
async def on_funding_reminder(session: AsyncSession, event: EventEnvelope) -> None:
    await service.auto_fund_cycle(session, event.payload)
