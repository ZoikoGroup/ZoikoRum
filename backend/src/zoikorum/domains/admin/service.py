"""Admin / operations: platform overview for staff. Evidence-based enforcement includes independent approvals, expiry and appeals."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from zoikorum.domains.identity import facade as identity_facade
from zoikorum.domains.professional import facade as professional_facade
from zoikorum.domains.verification import facade as verification_facade
from zoikorum.shared.auth import Actor, PlatformRole

import uuid
from datetime import timedelta
from sqlalchemy import select
from zoikorum.domains.admin.models import EnforcementCase
from zoikorum.domains.buyer import facade as buyer_facade
from zoikorum.shared import clock
from zoikorum.shared.errors import Conflict, Forbidden, NotFound, ValidationFailed
from zoikorum.shared.events import record_event, record_audit
from zoikorum.shared.event_catalog import E
from zoikorum.shared.relay import schedule_timer, cancel_timer

EXPIRY_TIMER = "admin.restriction_expiry"
ACTION_LEVEL = {"WARNING": 1, "VISIBILITY_REDUCTION": 2, "ENGAGEMENT_SUSPENSION": 3,
                "CREDENTIAL_ENFORCEMENT": 3, "VERIFICATION_RESET": 3, "SUSPEND_ACCOUNT": 4, "OFFBOARD": 4}


async def is_subject(session, actor, case):
    if case.subject_type == "IDENTITY":
        return case.subject_id == actor.identity_id
    if case.subject_type == "PROFESSIONAL":
        pro = await professional_facade.get_professional(session, case.subject_id)
        return pro is not None and pro.identity_id == actor.identity_id
    return "ORG_ADMIN" in await buyer_facade.get_member_roles(session, case.subject_id, actor.identity_id)


async def staff(session, actor, *roles):
    actor.require_platform_role(*roles)
    live = await identity_facade.live_platform_roles(session, actor.identity_id)
    if not set(roles).intersection(live):
        raise Forbidden("Your staff authority has changed")


def case_out(c):
    return {"id": str(c.id), "subjectType": c.subject_type, "subjectId": str(c.subject_id), "signalSource": c.signal_source,
            "summary": c.summary, "evidenceRefs": c.evidence_refs, "level": c.level, "reasonCode": c.reason_code,
            "status": c.status, "action": c.action, "notice": c.notice, "approvals": c.approvals,
            "expiresAt": c.expires_at, "appliedAt": c.applied_at, "appeal": c.appeal, "createdAt": c.created_at}


async def case_get(session, case_id, lock=False):
    c = await session.get(EnforcementCase, case_id, with_for_update=lock)
    if not c:
        raise NotFound("Enforcement case not found")
    return c


def event(session, kind, c, **extra):
    record_event(session, kind, aggregate_type="EnforcementCase", aggregate_id=c.id,
                 payload={"caseId": c.id, "subjectType": c.subject_type, "subjectId": c.subject_id,
                          "level": c.level, "action": c.action, "reasonCode": c.reason_code, "notice": c.notice,
                          "expiresAt": c.expires_at,
                          "organizationId": c.subject_id if c.subject_type == "ORGANIZATION" else None, **extra})


async def open_case(session, actor, body):
    await staff(session, actor, PlatformRole.TS_ANALYST)
    lookup = {"IDENTITY": identity_facade.get_identity, "PROFESSIONAL": professional_facade.get_professional,
              "ORGANIZATION": buyer_facade.get_organization}
    if not await lookup[body.subjectType](session, body.subjectId):
        raise NotFound("Subject not found")
    c = EnforcementCase(subject_type=body.subjectType, subject_id=body.subjectId, signal_source=body.signalSource,
                        summary=body.summary.strip(), evidence_refs=body.evidenceRefs, opened_by=actor.identity_id)
    session.add(c); await session.flush()
    event(session, E.ENFORCEMENT_CASE_OPENED, c)
    return case_out(c)


async def assess(session, actor, case_id, body):
    await staff(session, actor, PlatformRole.RISK_LEAD)
    c = await case_get(session, case_id, True)
    if c.status not in ("TRIAGE", "ASSESSED"):
        raise Conflict("An issued or proposed action cannot be reassessed")
    if await is_subject(session, actor, c):
        raise Forbidden("You cannot assess your own case")
    c.level, c.reason_code, c.status = body.level, body.reasonCode, "ASSESSED"
    record_audit(session, "admin.case.assessed", object_type="EnforcementCase", object_id=c.id,
                 details={"level": c.level, "reasonCode": c.reason_code})
    return case_out(c)


async def propose_action(session, actor, case_id, body):
    await staff(session, actor, PlatformRole.TS_ANALYST, PlatformRole.RISK_LEAD)
    actor.require_step_up()
    c = await case_get(session, case_id, True)
    if c.status != "ASSESSED" or ACTION_LEVEL[body.action] != c.level:
        raise Conflict("The action must match the assessed enforcement level")
    if await is_subject(session, actor, c):
        raise Forbidden("You cannot propose an action on your own case")
    if body.action in ("SUSPEND_ACCOUNT", "OFFBOARD") and c.subject_type != "IDENTITY":
        raise ValidationFailed("Account suspension and offboarding require an identity subject")
    if body.action in ("VISIBILITY_REDUCTION", "CREDENTIAL_ENFORCEMENT", "VERIFICATION_RESET") and c.subject_type != "PROFESSIONAL":
        raise ValidationFailed("This action requires a professional subject")
    if c.level == 2 and body.durationDays is None:
        raise ValidationFailed("Temporary restrictions require a duration")
    c.action, c.notice, c.duration_days = body.action, body.notice.model_dump(), body.durationDays
    c.proposed_by, c.status, c.approvals = actor.identity_id, "AWAITING_APPROVAL", []
    record_audit(session, "admin.action.proposed", object_type="EnforcementCase", object_id=c.id,
                 details={"action": c.action, "notice": c.notice, "durationDays": c.duration_days})
    return case_out(c)


async def approve_action(session, actor, case_id):
    c = await case_get(session, case_id, True)
    roles = (PlatformRole.EXECUTIVE, PlatformRole.LEGAL) if c.level == 4 else (PlatformRole.RISK_LEAD, PlatformRole.LEGAL)
    await staff(session, actor, *roles); actor.require_step_up()
    if c.status != "AWAITING_APPROVAL":
        raise Conflict("There is no action awaiting approval")
    if c.proposed_by == actor.identity_id or await is_subject(session, actor, c):
        raise Forbidden("An independent operator must approve the action", code="FOUR_EYES")
    if any(v["identityId"] == str(actor.identity_id) for v in c.approvals):
        raise Conflict("You already approved this action")
    live_roles = await identity_facade.live_platform_roles(session, actor.identity_id)
    role = next((r for r in roles if r in live_roles and r not in {v["role"] for v in c.approvals}), None)
    if role is None:
        raise Forbidden("The remaining approval needs a different role")
    c.approvals = [*c.approvals, {"identityId": str(actor.identity_id), "role": role, "at": clock.now().isoformat()}]
    if c.level == 4 and {v["role"] for v in c.approvals} != {PlatformRole.EXECUTIVE, PlatformRole.LEGAL}:
        return case_out(c)
    # Previously cast approval must still have live authority when the action is applied.
    for vote in c.approvals:
        if vote["role"] not in await identity_facade.live_platform_roles(session, uuid.UUID(vote["identityId"])):
            raise Conflict("An earlier approver no longer has the required authority")
    c.status, c.applied_at = "ACTIVE", clock.now()
    if c.duration_days:
        c.expires_at = clock.now() + timedelta(days=c.duration_days)
        await schedule_timer(session, EXPIRY_TIMER, str(c.id), c.expires_at)
    event(session, E.ENFORCEMENT_ACTION_APPLIED, c)
    return case_out(c)


async def reverse_case(session, actor, case_id, reason):
    await staff(session, actor, PlatformRole.RISK_LEAD, PlatformRole.LEGAL)
    actor.require_step_up()
    c = await case_get(session, case_id, True)
    if await is_subject(session, actor, c):
        raise Forbidden("You cannot reverse your own restriction")
    await reverse(session, c, actor.identity_id, reason)
    return case_out(c)


async def reverse(session, c, actor_id, reason):
    if c.status != "ACTIVE":
        raise Conflict("Only an active action can be reversed")
    c.status, c.reversed_by = "REVERSED", actor_id
    await cancel_timer(session, EXPIRY_TIMER, str(c.id))
    notice = {
        "whatHappened": "The restriction recorded in this safety case has ended.",
        "whyItHappened": reason,
        "whatChanged": "The action in this case is no longer active. Other active restrictions remain in effect.",
        "whatYouCanDo": "Sign in again if your session was revoked, and review any remaining notices.",
        "whatHappensNext": "Your access continues to follow your current permissions and other active restrictions.",
        "howToGetHelp": f"Contact support and quote safety case {c.id}.",
    }
    # Preserve the original action notice; the reversal has its own immutable event.
    event(session, E.ENFORCEMENT_ACTION_REVERSED, c, reversalReason=reason, notice=notice)


async def file_appeal(session, actor, case_id, reason):
    c = await case_get(session, case_id, True)
    if not await is_subject(session, actor, c):
        raise NotFound("Enforcement case not found")
    if c.level < 2 or c.status != "ACTIVE" or c.appeal:
        raise Conflict("This action cannot receive another appeal")
    c.appeal = {"reason": reason, "filedBy": str(actor.identity_id), "filedAt": clock.now().isoformat(), "status": "PENDING"}
    event(session, E.ENFORCEMENT_APPEAL_FILED, c)
    return case_out(c)


async def decide_appeal(session, actor, case_id, body):
    await staff(session, actor, PlatformRole.LEGAL); actor.require_step_up()
    c = await case_get(session, case_id, True)
    involved = {str(c.opened_by), str(c.proposed_by), *(v["identityId"] for v in c.approvals)}
    if str(actor.identity_id) in involved or await is_subject(session, actor, c):
        raise Forbidden("An independent reviewer must decide the appeal", code="FOUR_EYES")
    if not c.appeal or c.appeal["status"] != "PENDING":
        raise Conflict("No appeal is awaiting review")
    c.appeal = {**c.appeal, "status": "UPHELD" if body.upheld else "REJECTED", "decisionReason": body.reason,
                "reviewedBy": str(actor.identity_id), "decidedAt": clock.now().isoformat()}
    event(session, E.ENFORCEMENT_APPEAL_DECIDED, c, upheld=body.upheld)
    if body.upheld and c.status == "ACTIVE":
        await reverse(session, c, actor.identity_id, body.reason)
    return case_out(c)


async def triage_signal(session, event_envelope):
    p = event_envelope.payload
    subject_type = p.get("subjectType") or ("PROFESSIONAL" if p.get("professionalId") else "IDENTITY")
    raw_id = p.get("subjectId") or p.get("professionalId") or p.get("identityId") or p.get("senderIdentityId")
    if not raw_id:
        return
    if await session.scalar(select(EnforcementCase.id).where(EnforcementCase.source_event_id == event_envelope.eventId)):
        return
    c = EnforcementCase(subject_type=subject_type, subject_id=uuid.UUID(str(raw_id)), source_event_id=event_envelope.eventId,
                        signal_source=event_envelope.eventType, summary="Advisory risk signal: " + str(p.get("reasonCode") or p.get("reasonCodes") or "Review evidence"),
                        evidence_refs=[str(event_envelope.eventId)], level=0)
    session.add(c); await session.flush(); event(session, E.ENFORCEMENT_CASE_OPENED, c)


async def overview(session: AsyncSession, actor: Actor) -> dict:
    """Read-only platform counts for any staff member (MFA enforced by require_platform_role)."""
    actor.require_platform_role(*PlatformRole.ALL)
    accounts = await identity_facade.count_accounts(session)
    profiles = await professional_facade.count_profiles(session)
    checks = await verification_facade.open_case_counts(session)
    return {
        "accounts": {"total": accounts["total"], "buyers": accounts.get("BUYER", 0),
                     "professionals": accounts.get("PROFESSIONAL", 0), "firmAdmins": accounts.get("FIRM_ADMIN", 0),
                     "enterprise": accounts.get("ENTERPRISE_ADMIN", 0) + accounts.get("ENTERPRISE_MEMBER", 0)},
        "professionalProfiles": profiles,
        "verification": checks,
    }
