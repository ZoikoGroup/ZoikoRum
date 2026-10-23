"""Contract reacts to accepted proposals (generate the agreement), escrow funding (start funded milestones) and disputes."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from zoikorum.domains.contract import service
from zoikorum.shared.event_catalog import E
from zoikorum.shared.events import EventEnvelope, subscribe
from zoikorum.shared.relay import on_timer
import uuid
from zoikorum.shared.errors import DomainError
from zoikorum.shared.events import record_audit


@subscribe(E.APPROVAL_GRANTED, consumer="contract.policy_continuation")
@subscribe(E.EXCEPTION_GRANTED, consumer="contract.policy_continuation")
async def continue_acceptance(session, event):
    p = event.payload
    if p.get("subjectType") != "Milestone" or p.get("action") != "MILESTONE_ACCEPT":
        return
    actor = await service.policy_facade.continuation_actor(session, p)
    try:
        async with session.begin_nested():
            mid = uuid.UUID(str(p["subjectId"]))
            if actor:
                await service.accept_milestone(session, actor, mid)
            elif not p.get("requesterIdentityId"):
                latest = await session.scalar(service.select(service.Submission.id).where(service.Submission.milestone_id == mid).order_by(service.Submission.created_at.desc()).limit(1))
                if latest:
                    await service.policy_auto_accept(session, {"milestoneId": str(mid), "submissionId": str(latest)})
    except DomainError as exc:
        record_audit(session, "contract.policy.continuation_skipped", object_type="Milestone", object_id=p["subjectId"], details={"reason": exc.code})


@subscribe(E.PROPOSAL_ACCEPTED, consumer="contract.generate")
async def on_proposal_accepted(session: AsyncSession, event: EventEnvelope) -> None:
    await service.generate_from_proposal(session, event.payload)


@subscribe(E.ESCROW_FUNDED, consumer="contract.start_funded_milestones")
async def on_escrow_funded(session: AsyncSession, event: EventEnvelope) -> None:
    await service.escrow_funded(session, event.payload)


@on_timer(service.TIMER_SIGNATURE)
async def on_signature_deadline(session: AsyncSession, key: str, payload: dict) -> None:
    await service.signature_deadline_passed(session, payload)


@on_timer(service.TIMER_SIGNATURE_EXPIRY)
async def on_signature_expiry(session: AsyncSession, key: str, payload: dict) -> None:
    await service.signature_expired(session, payload)


@on_timer(service.TIMER_FUNDING_REMINDER)
async def on_funding_reminder(session: AsyncSession, key: str, payload: dict) -> None:
    await service.funding_reminder(session, payload)


@on_timer(service.TIMER_REVIEW_REMINDER)
async def on_review_reminder(session: AsyncSession, key: str, payload: dict) -> None:
    await service.review_reminder(session, payload)


@on_timer(service.TIMER_REVIEW_DUE)
async def on_review_due(session: AsyncSession, key: str, payload: dict) -> None:
    await service.review_overdue(session, payload)


@on_timer(service.TIMER_AUTO_ACCEPT)
async def on_policy_auto_accept(session: AsyncSession, key: str, payload: dict) -> None:
    await service.policy_auto_accept(session, payload)


@subscribe(E.ESCROW_FUNDING_REVERSED, consumer="contract.funding_reversed")
async def on_funding_reversed(session: AsyncSession, event: EventEnvelope) -> None:
    await service.funding_reversed(session, event.payload)


@subscribe(E.ESCROW_FUNDING_EXPIRED, consumer="contract.funding_expired")
async def on_funding_expired(session: AsyncSession, event: EventEnvelope) -> None:
    await service.funding_expired(session, event.payload)


@subscribe(E.DISPUTE_INITIATED, consumer="contract.dispute_pause")
async def on_dispute_initiated(session: AsyncSession, event: EventEnvelope) -> None:
    await service.dispute_initiated(session, event.payload)


@subscribe(E.DISPUTE_RESOLVED, consumer="contract.dispute_outcome")
async def on_dispute_resolved(session: AsyncSession, event: EventEnvelope) -> None:
    await service.dispute_resolved(session, event.payload)


@on_timer(service.TIMER_TERMINATION_LAPSE)
async def on_termination_lapse(session: AsyncSession, key: str, payload: dict) -> None:
    await service.termination_lapsed(session, payload)


@subscribe(E.ENFORCEMENT_ACTION_APPLIED, consumer="contract.offboarding")
async def on_enforcement_applied(session: AsyncSession, event: EventEnvelope) -> None:
    p = event.payload
    if p.get("action") != "OFFBOARD" or p.get("subjectType") != "IDENTITY":
        return
    pro = await service.professional_facade.get_professional_by_identity(session, uuid.UUID(str(p["subjectId"])))
    if pro is not None:
        await service.professional_offboarded(session, pro.id)



@subscribe(E.ENFORCEMENT_ACTION_APPLIED, consumer="contract.tell_buyers_restricted")
async def on_professional_restricted(session: AsyncSession, event: EventEnvelope) -> None:
    await service.professional_restricted(session, event.payload)


@subscribe(E.ENFORCEMENT_ACTION_REVERSED, consumer="contract.tell_buyers_restored")
async def on_professional_restored(session: AsyncSession, event: EventEnvelope) -> None:
    await service.professional_restricted(session, event.payload, reversed_=True)


@subscribe(E.VERIFICATION_EXPIRED, consumer="contract.tell_buyers_check_expired")
async def on_check_expired(session: AsyncSession, event: EventEnvelope) -> None:
    await service.professional_check_lapsed(session, event.payload, expired=True)


@subscribe(E.VERIFICATION_REVOKED, consumer="contract.tell_buyers_check_revoked")
async def on_check_revoked(session: AsyncSession, event: EventEnvelope) -> None:
    await service.professional_check_lapsed(session, event.payload, expired=False)
