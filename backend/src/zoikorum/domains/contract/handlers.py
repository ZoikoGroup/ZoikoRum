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


@subscribe(E.DISPUTE_INITIATED, consumer="contract.dispute_pause")
async def on_dispute_initiated(session: AsyncSession, event: EventEnvelope) -> None:
    await service.dispute_initiated(session, event.payload)


@subscribe(E.DISPUTE_RESOLVED, consumer="contract.dispute_outcome")
async def on_dispute_resolved(session: AsyncSession, event: EventEnvelope) -> None:
    await service.dispute_resolved(session, event.payload)
