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
from zoikorum.config import get_settings
from zoikorum.shared import clock
from zoikorum.shared.uploads import store_uploads
from zoikorum.shared.errors import Conflict, Forbidden, NotFound, ValidationFailed
from zoikorum.shared.events import record_event, record_audit
from zoikorum.shared.event_catalog import E
from zoikorum.shared.relay import schedule_timer, cancel_timer

EXPIRY_TIMER = "admin.restriction_expiry"
ACTION_LEVEL = {"WARNING": 1, "VISIBILITY_REDUCTION": 2, "DISPUTE_ACCESS_RESTRICTION": 2, "ENGAGEMENT_SUSPENSION": 3,
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


def triage_due(c):
    return c.created_at + timedelta(hours=get_settings().enforcement_triage_hours)


def appeal_deadline(c):
    return c.applied_at + timedelta(days=get_settings().enforcement_appeal_days) if c.applied_at else None


def case_out(c):
    open_ = c.status in ("TRIAGE", "ASSESSED")
    deadline = appeal_deadline(c)
    return {"id": str(c.id), "subjectType": c.subject_type, "subjectId": str(c.subject_id), "signalSource": c.signal_source,
            "summary": c.summary, "evidenceRefs": c.evidence_refs, "level": c.level, "reasonCode": c.reason_code,
            "status": c.status, "action": c.action, "notice": c.notice, "approvals": c.approvals,
            "expiresAt": c.expires_at, "appliedAt": c.applied_at, "appeal": c.appeal, "createdAt": c.created_at,
            "triageDueAt": triage_due(c) if open_ else None, "overdue": open_ and triage_due(c) < clock.now(),
            "appealDeadline": deadline, "canAppeal": c.level >= 2 and c.status == "ACTIVE" and not c.appeal
            and deadline is not None and clock.now() <= deadline,
            "remediation": c.remediation or []}


async def case_get(session, case_id, lock=False):
    c = await session.get(EnforcementCase, case_id, with_for_update=lock)
    if not c:
        raise NotFound("Enforcement case not found")
    return c


def event(session, kind, c, **extra):
    # Every enforcement record names its evidence and the playbook version it was decided under (Governance s.10).
    policy = get_settings().enforcement_policy_version
    record_event(session, kind, aggregate_type="EnforcementCase", aggregate_id=c.id,
                 payload={"caseId": c.id, "subjectType": c.subject_type, "subjectId": c.subject_id,
                          "level": c.level, "action": c.action, "reasonCode": c.reason_code, "notice": c.notice,
                          "expiresAt": c.expires_at, "evidenceRefs": c.evidence_refs, "policyVersion": policy,
                          "organizationId": c.subject_id if c.subject_type == "ORGANIZATION" else None, **extra},
                 policy_version=policy)


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


async def close_case(session, actor, case_id, reason):
    """Reviewed and no action is needed (Level 0: no breach, or an education message is enough). Recorded with the
    reason; reporters are told it was reviewed. A case with a proposed or applied action is reversed instead."""
    await staff(session, actor, PlatformRole.TS_ANALYST, PlatformRole.RISK_LEAD)
    c = await case_get(session, case_id, True)
    if c.status not in ("TRIAGE", "ASSESSED"):
        raise Conflict("Only a case without a proposed or applied action can be closed this way", code="CASE_NOT_OPEN")
    if await is_subject(session, actor, c):
        raise Forbidden("You cannot close your own case")
    c.status = "CLOSED_NO_ACTION"
    record_audit(session, "admin.case.closed", object_type="EnforcementCase", object_id=c.id, details={"reason": reason.strip()})
    record_event(session, E.ENFORCEMENT_CASE_CLOSED, aggregate_type="EnforcementCase", aggregate_id=c.id,
                 payload={"caseId": c.id, "level": c.level, "reason": reason.strip()})
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
    if not c.evidence_refs:
        raise ValidationFailed("Record the evidence this action rests on before proposing it", code="EVIDENCE_REQUIRED")
    c.action, c.notice, c.duration_days = body.action, body.notice.model_dump(), body.durationDays
    c.remediation = [{"task": t.strip(), "done": False} for t in body.remediation if t.strip()]
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
    if c.level >= 3 and c.proposed_by == actor.identity_id:
        raise Forbidden("Another senior reviewer must reverse a restriction you proposed", code="FOUR_EYES")
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


async def file_appeal(session, actor, case_id, reason, evidence=None):
    c = await case_get(session, case_id, True)
    if not await is_subject(session, actor, c):
        raise NotFound("Enforcement case not found")
    if c.level < 2 or c.status != "ACTIVE" or c.appeal:
        raise Conflict("This action cannot receive another appeal")
    if clock.now() > appeal_deadline(c):
        raise Conflict(f"The {get_settings().enforcement_appeal_days}-day appeal window has closed", code="APPEAL_WINDOW_CLOSED")
    files = store_uploads(f"admin/appeals/{c.id}", evidence or [])
    c.appeal = {"reason": reason, "filedBy": str(actor.identity_id), "filedAt": clock.now().isoformat(), "status": "PENDING",
                "evidence": files}
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



# ---- Remediation, executive override, queue ------------------------------------------------------------------------

async def remediation_done(session, actor, case_id, index: int, note: str):
    """The person marks a remediation task done; staff confirm it."""
    c = await case_get(session, case_id, True)
    if not await is_subject(session, actor, c):
        raise NotFound("Enforcement case not found")
    tasks = list(c.remediation or [])
    if not 0 <= index < len(tasks):
        raise NotFound("Task not found")
    tasks[index] = {**tasks[index], "done": True, "doneAt": clock.now().isoformat(), "note": note.strip()}
    c.remediation = tasks
    record_audit(session, "admin.remediation.done", object_type="EnforcementCase", object_id=c.id, details={"task": index})
    return case_out(c)


async def remediation_confirm(session, actor, case_id, index: int):
    """Staff confirm a completed task. When all are confirmed, the restriction may end early (reverse with a reason)."""
    await staff(session, actor, PlatformRole.TS_ANALYST, PlatformRole.RISK_LEAD)
    c = await case_get(session, case_id, True)
    if await is_subject(session, actor, c):
        raise Forbidden("You cannot confirm your own remediation")
    tasks = list(c.remediation or [])
    if not 0 <= index < len(tasks) or not tasks[index].get("done"):
        raise Conflict("The task is not marked done yet", code="TASK_NOT_DONE")
    tasks[index] = {**tasks[index], "confirmedBy": str(actor.identity_id), "confirmedAt": clock.now().isoformat()}
    c.remediation = tasks
    record_audit(session, "admin.remediation.confirmed", object_type="EnforcementCase", object_id=c.id, details={"task": index})
    if all(t.get("confirmedBy") for t in tasks):
        event(session, E.ENFORCEMENT_REMEDIATION_COMPLETED, c)
    return case_out(c)


async def executive_override(session, actor, case_id, reason: str):
    """Final authority (Governance playbook): an Executive ends an active action. Justified, step-up, audited, and never
    by someone involved in the case."""
    await staff(session, actor, PlatformRole.EXECUTIVE)
    actor.require_step_up()
    c = await case_get(session, case_id, True)
    involved = {str(c.opened_by), str(c.proposed_by), *(v["identityId"] for v in c.approvals)}
    if str(actor.identity_id) in involved or await is_subject(session, actor, c):
        raise Forbidden("An executive not involved in the case must make an override", code="FOUR_EYES")
    record_audit(session, "admin.executive_override", object_type="EnforcementCase", object_id=c.id,
                 details={"reason": reason, "previousStatus": c.status})
    await reverse(session, c, actor.identity_id, "Executive override: " + reason)
    return case_out(c)


async def queue(session, actor, status: str | None, level: int | None, overdue: bool, source: str | None,
                limit: int, offset: int):
    """Staff queue: filters, and cases past their triage target first."""
    from sqlalchemy import case as sql_case

    await staff(session, actor, *PlatformRole.ALL)
    stmt = select(EnforcementCase)
    if status:
        stmt = stmt.where(EnforcementCase.status == status)
    if level is not None:
        stmt = stmt.where(EnforcementCase.level == level)
    if source:
        stmt = stmt.where(EnforcementCase.signal_source == source)
    due = clock.now() - timedelta(hours=get_settings().enforcement_triage_hours)
    is_overdue = EnforcementCase.status.in_(("TRIAGE", "ASSESSED")) & (EnforcementCase.created_at < due)
    if overdue:
        stmt = stmt.where(is_overdue)
    stmt = stmt.order_by(sql_case((is_overdue, 0), else_=1), EnforcementCase.created_at.desc()).limit(limit).offset(offset)
    return [case_out(c) for c in (await session.scalars(stmt)).all()]


# ---- Staff admin console: platform configuration (read-only) --------------------------------------------------------

# An explicit allowlist: only business rules and switch positions are shown, never a secret, key, token, password,
# connection string or address that may carry credentials. A setting added to config.py stays hidden until listed here.
CONFIG_GROUPS: tuple[tuple[str, tuple[tuple[str, str], ...]], ...] = (
    ("Fees and payments", (
        ("platform_fee_bps", "Platform fee in basis points (1000 = 10%), fixed on each contract when it activates"),
        ("payout_settlement_business_days", "Business days a payout is expected to take to reach the professional's bank"),
        ("fx_margin_bps", "Safety margin (basis points) added when a spend limit in another currency is converted"),
        ("fx_rates", "Units of each currency per 1 USD, set by Finance, for spend limits in another currency"),
        ("tax_rules", "Invoice tax by the buyer's country (label, rate, basis)"),
        ("payment_provider", "Payment provider in use"),
        ("payment_operating_countries", "Countries where funds may be taken and paid out"),
        ("payment_flow_approved", "The configured funds flow has partner and business approval"),
        ("funding_reminder_days", "Days before an unfunded milestone or retainer cycle is due that the buyer is reminded"),
    )),
    ("Contracts and delivery", (
        ("signature_deadline_days", "Days both parties have to sign before an unsigned contract escalates"),
        ("request_response_hours", "Hours a professional has to answer a request (reminded a day before)"),
        ("max_professionals_per_request", "Professionals one requirement can be sent to at once"),
        ("acceptance_window_days", "Days a buyer has to review a submitted milestone"),
        ("release_block_escalation_days", "Days between reminders when an approver has refused or let a release expire"),
        ("termination_response_days", "Days a request to end an engagement by agreement stays open"),
    )),
    ("Disputes", (
        ("dispute_evidence_days", "Days each side has to add evidence"),
        ("dispute_direct_resolution_business_days", "Business days for the parties to settle directly before mediation"),
        ("dispute_challenge_window_days", "Days after acceptance in which accepted work may still be disputed (payment held)"),
        ("dispute_retention_years", "Minimum years closed dispute records are kept"),
    )),
    ("Trust, verification and enforcement", (
        ("verification_provider", "Identity verification provider in use"),
        ("verification_second_look_pct", "Share (%) of automatically approved checks a compliance officer looks at again"),
        ("verification_appeal_days", "Days to appeal a failed or revoked verification"),
        ("enforcement_triage_hours", "Target hours for a new safety case to be looked at"),
        ("enforcement_appeal_days", "Days to appeal an enforcement action"),
        ("enforcement_policy_version", "Trust & Safety playbook recorded with every enforcement decision"),
        ("trust_completion_half_life_days", "Half-life (days) of a completed engagement's weight in trust scoring"),
        ("trust_completion_full_credit", "Completed engagements that earn full delivery credit"),
    )),
    ("Privacy and retention", (
        ("erasure_cooling_off_days", "Days an account deletion can still be cancelled"),
        ("data_export_days", "Days a personal data export can be downloaded"),
        ("idempotency_retention_days", "Days replayed-request records are kept"),
        ("event_retention_days", "Days handled events are kept"),
    )),
    ("Operations", (
        ("ai_provider", "AI assistance provider"),
        ("ai_model", "AI model used for assistance"),
        ("ai_disabled_prompts", "Built-in AI prompts switched off (their features use non-AI rules)"),
        ("email_provider", "Email delivery"),
        ("storage_provider", "File storage"),
        ("malware_scanner", "Upload malware scanning"),
        ("event_bus", "Event bus"),
        ("rate_limit_enabled", "Request rate limits are on"),
        ("provider_breaker_failures", "Consecutive provider errors before calls to it pause"),
        ("provider_breaker_reset_seconds", "Seconds a paused provider waits before a trial call"),
        ("log_level", "Log level"),
        ("tracing_sample_ratio", "Share of new traces kept"),
    )),
)


def _config_value(value) -> str:
    import json

    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (list, dict)):
        return json.dumps(value, sort_keys=True)
    return "" if value is None else str(value)


def admin_config(actor: Actor) -> dict:
    """Platform Admin: the environment, the release and the business rules in force. Changing them is a deployment
    (environment variables), never done here."""
    actor.require_platform_role(PlatformRole.PLATFORM_ADMIN)
    s = get_settings()
    return {"environment": s.env, "version": s.release or None,
            "groups": [{"domain": domain, "settings": [{"key": f"ZK_{name.upper()}", "value": _config_value(getattr(s, name)),
                                                        "description": description} for name, description in settings]}
                       for domain, settings in CONFIG_GROUPS]}
