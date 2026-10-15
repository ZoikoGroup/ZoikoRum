"""User reports (Trust & Safety Charter: reporting pathway; Governance playbook: intake, confidentiality, protection
against retaliatory reports).

A report becomes (or joins) a Level 0 enforcement case for Trust & Safety to triage; it never restricts anyone by itself.
The reported person is never told who reported. A report from someone who is in an open dispute with the person they
report is marked "possible retaliation" for the handler. Limits: 5 reports a day per person, one open report per
subject per reporter.
"""

from __future__ import annotations

import uuid
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from zoikorum.domains.admin.models import EnforcementCase, UserReport
from zoikorum.domains.admin.schemas import ReportIn
from zoikorum.domains.admin.service import event
from zoikorum.domains.buyer import facade as buyer_facade
from zoikorum.domains.contract import facade as contract_facade
from zoikorum.domains.identity import facade as identity_facade
from zoikorum.domains.messaging import facade as messaging_facade
from zoikorum.domains.professional import facade as professional_facade
from zoikorum.domains.review import facade as review_facade
from zoikorum.shared import clock
from zoikorum.shared.auth import Actor, PlatformRole
from zoikorum.shared.errors import Conflict, NotFound, RateLimited, ValidationFailed
from zoikorum.shared.event_catalog import E
from zoikorum.shared.events import record_event

DAILY_LIMIT = 5
CATEGORY_LABEL = {"MISCONDUCT": "Professional misconduct", "FRAUD_OR_SCAM": "Fraud or scam",
                  "MISREPRESENTATION": "False credentials or misrepresentation", "HARASSMENT_OR_ABUSE": "Harassment or abuse",
                  "OFF_PLATFORM_PAYMENT": "Asked to pay outside Zoikorum", "UNSAFE_OR_ILLEGAL": "Unsafe or illegal",
                  "FAKE_REVIEW": "Fake or abusive review", "OTHER": "Other"}
SEE_CONFIDENTIAL = (PlatformRole.RISK_LEAD, PlatformRole.LEGAL)


async def _resolve(session: AsyncSession, actor: Actor, body: ReportIn) -> tuple[str, uuid.UUID, str]:
    """The account a case is about (case subject type and id) and context for the handler."""
    if body.subjectType == "PROFESSIONAL":
        pro = await professional_facade.get_professional(session, body.subjectId)
        if pro is None:
            raise NotFound("Profile not found")
        return "PROFESSIONAL", pro.id, f"Profile {pro.display_name}"
    if body.subjectType == "ORGANIZATION":
        org = await buyer_facade.get_organization(session, body.subjectId)
        if org is None:
            raise NotFound("Organisation not found")
        return "ORGANIZATION", org.id, f"Organisation {org.name}"
    if body.subjectType == "IDENTITY":
        if await identity_facade.get_identity(session, body.subjectId) is None:
            raise NotFound("Account not found")
        return "IDENTITY", body.subjectId, "Account"
    if body.subjectType == "REVIEW":
        found = await review_facade.review_author(session, body.subjectId)
        if found is None:
            raise NotFound("Review not found")
        return "IDENTITY", found[0], f"Review {body.subjectId}"
    found = await messaging_facade.message_for_report(session, actor, body.subjectId)
    if found is None:
        raise NotFound("Message not found")
    return "IDENTITY", found[0], f"Message: \"{found[1]}\""


async def _in_dispute_with(session: AsyncSession, reporter: uuid.UUID, case_type: str, case_subject: uuid.UUID) -> bool:
    my_orgs = await buyer_facade.list_identity_organizations(session, reporter)
    me_pro = await professional_facade.get_professional_by_identity(session, reporter)
    if case_type == "PROFESSIONAL":
        return await contract_facade.disputed_between(session, case_subject, my_orgs)
    their_orgs = [case_subject] if case_type == "ORGANIZATION" else \
        await buyer_facade.list_identity_organizations(session, case_subject)
    if me_pro is not None and await contract_facade.disputed_between(session, me_pro.id, their_orgs):
        return True
    their_pro = await professional_facade.get_professional_by_identity(session, case_subject) if case_type == "IDENTITY" else None
    return their_pro is not None and await contract_facade.disputed_between(session, their_pro.id, my_orgs)


async def submit(session: AsyncSession, actor: Actor, body: ReportIn) -> dict:
    case_type, case_subject, context = await _resolve(session, actor, body)
    me_pro = await professional_facade.get_professional_by_identity(session, actor.identity_id)
    if case_subject == actor.identity_id or (me_pro is not None and case_type == "PROFESSIONAL" and case_subject == me_pro.id):
        raise ValidationFailed("You cannot report yourself", code="SELF_REPORT")
    since = clock.now() - timedelta(days=1)
    today = await session.scalar(select(func.count()).select_from(UserReport).where(
        UserReport.reporter_identity_id == actor.identity_id, UserReport.created_at >= since))
    if today >= DAILY_LIMIT:
        raise RateLimited("You have sent several reports today. Our team is reviewing them; you can send more tomorrow.")
    if await session.scalar(select(UserReport.id).where(
            UserReport.reporter_identity_id == actor.identity_id, UserReport.subject_type == body.subjectType,
            UserReport.subject_id == body.subjectId, UserReport.status == "RECEIVED")):
        raise Conflict("You have already reported this. Our team will look at it; you will be told when it is reviewed.",
                       code="REPORT_EXISTS")
    retaliation = await _in_dispute_with(session, actor.identity_id, case_type, case_subject)
    # Reports about the same account join its open triage case instead of opening many.
    case = await session.scalar(select(EnforcementCase).where(
        EnforcementCase.subject_type == case_type, EnforcementCase.subject_id == case_subject,
        EnforcementCase.signal_source == "USER_REPORT", EnforcementCase.status.in_(("TRIAGE", "ASSESSED")))
        .with_for_update())
    summary = f"User report: {CATEGORY_LABEL[body.category]}. {context}."
    if case is None:
        case = EnforcementCase(subject_type=case_type, subject_id=case_subject, signal_source="USER_REPORT",
                               summary=summary[:2000], evidence_refs=[], level=0)
        session.add(case)
        await session.flush()
        event(session, E.ENFORCEMENT_CASE_OPENED, case)
    report = UserReport(reporter_identity_id=actor.identity_id, subject_type=body.subjectType, subject_id=body.subjectId,
                        category=body.category, description=body.description.strip(), confidential=body.confidential,
                        possible_retaliation=retaliation, case_id=case.id, status="RECEIVED")
    session.add(report)
    await session.flush()
    case.evidence_refs = [*case.evidence_refs, f"report:{report.id}"]
    # identityId is the reporter (they get "Report received"); the reported account is not a recipient.
    record_event(session, E.USER_REPORT_SUBMITTED, aggregate_type="UserReport", aggregate_id=report.id,
                 payload={"reportId": report.id, "identityId": actor.identity_id, "caseId": case.id,
                          "category": body.category, "possibleRetaliation": retaliation})
    return report_out(report)


def report_out(r: UserReport) -> dict:
    return {"id": str(r.id), "subjectType": r.subject_type, "subjectId": str(r.subject_id), "category": r.category,
            "categoryLabel": CATEGORY_LABEL[r.category], "description": r.description, "confidential": r.confidential,
            "status": r.status, "outcome": r.outcome, "createdAt": r.created_at, "updatedAt": r.updated_at}


async def mine(session: AsyncSession, actor: Actor) -> list[dict]:
    rows = (await session.scalars(select(UserReport).where(UserReport.reporter_identity_id == actor.identity_id)
                                  .order_by(UserReport.created_at.desc()).limit(100))).all()
    return [report_out(r) for r in rows]


async def for_case(session: AsyncSession, actor: Actor, case_id: uuid.UUID) -> list[dict]:
    """Staff view of the reports behind a case. Confidential reporters are named only to Risk Lead and Legal."""
    rows = (await session.scalars(select(UserReport).where(UserReport.case_id == case_id).order_by(UserReport.created_at))).all()
    sees_all = actor.has_platform_role(*SEE_CONFIDENTIAL)
    people = await identity_facade.get_identities(session, [r.reporter_identity_id for r in rows])
    out = []
    for r in rows:
        item = report_out(r) | {"possibleRetaliation": r.possible_retaliation}
        who = people.get(r.reporter_identity_id)
        item["reporter"] = (who.display_name if who else "Unknown") if (sees_all or not r.confidential) else "Confidential reporter"
        out.append(item)
    return out


async def close_for_case(session: AsyncSession, case_id: uuid.UUID, outcome: str) -> None:
    """When the case is decided: each open report is closed and its reporter told the outcome, without details."""
    for r in (await session.scalars(select(UserReport).where(UserReport.case_id == case_id, UserReport.status == "RECEIVED")
                                    .with_for_update())).all():
        r.status, r.outcome = "CLOSED", outcome
        record_event(session, E.USER_REPORT_CLOSED, aggregate_type="UserReport", aggregate_id=r.id,
                     payload={"reportId": r.id, "identityId": r.reporter_identity_id, "outcome": outcome})
