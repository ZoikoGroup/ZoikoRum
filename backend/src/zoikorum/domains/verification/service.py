"""Verification domain: cases, evidence, provider checks, human review, expiry.

Verified status requires a positive provider result or an approved human review (Trust & Safety
Charter). Reviewers are COMPLIANCE_OFFICERs with a fresh MFA step-up, and never review their own case.
"""

from __future__ import annotations

import base64
import hashlib
import uuid
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from zoikorum.config import get_settings
from zoikorum.domains.firm import facade as firm_facade
from zoikorum.domains.professional import facade as professional_facade
from zoikorum.domains.verification.models import Appeal, EvidenceItem, VerificationCase
from zoikorum.domains.verification.providers import get_provider
from zoikorum.domains.verification.schemas import (
    AppealDecisionIn, AppealIn, AppealOut, AppealQueueItemOut, CaseIn, CaseOut, DecisionIn, EvidenceIn, EvidenceOut, QueueItemOut,
    RevokeIn,
)
from zoikorum.shared import clock
from zoikorum.shared.auth import Actor, FirmRole, PlatformRole
from zoikorum.shared.errors import Conflict, Forbidden, NotFound, ValidationFailed
from zoikorum.shared.event_catalog import E
from zoikorum.shared.events import record_audit, record_event
from zoikorum.shared.http import page_of, paginate
from zoikorum.shared.relay import cancel_timer, schedule_timer
from zoikorum.shared.state_machine import StateMachine
from zoikorum.shared.storage import get_storage

CASE_STATES = StateMachine("VerificationCase", {
    "PENDING": {"IN_REVIEW", "NEEDS_INFO", "VERIFIED", "FAILED"},
    "IN_REVIEW": {"NEEDS_INFO", "VERIFIED", "FAILED"},
    "NEEDS_INFO": {"IN_REVIEW", "FAILED"},
    "VERIFIED": {"EXPIRED", "REVOKED"},
    "FAILED": {"VERIFIED"},  # only through an upheld appeal (decide_appeal)
    "EXPIRED": set(),
    "REVOKED": {"VERIFIED"},  # only through an upheld appeal (decide_appeal)
})
OPEN_STATES = ("PENDING", "IN_REVIEW", "NEEDS_INFO")
# Published service levels (Onboarding s.15): identity 24h, credential 48h median.
SLA = {"IDENTITY": timedelta(hours=24), "CREDENTIAL": timedelta(hours=48)}
DEFAULT_SLA = timedelta(hours=72)
REMINDER_DAYS = (30, 14, 7)
REVIEWERS = (PlatformRole.COMPLIANCE_OFFICER,)
VIEWERS = (PlatformRole.COMPLIANCE_OFFICER, PlatformRole.PLATFORM_ADMIN, PlatformRole.TS_ANALYST)
LABELS = {"IDENTITY": "Identity", "JURISDICTION": "Jurisdiction eligibility", "INSURANCE": "Professional indemnity insurance",
          "RESTRICTIONS": "Sanctions & restrictions screening", "BACKGROUND": "Background check",
          "FIRM_REGISTRATION": "Firm registration"}
TIMER_REMINDER = "verification.expiry_reminder"
TIMER_EXPIRY = "verification.expiry"


# ---- Helpers -----------------------------------------------------------------

def _payload(case: VerificationCase, **extra) -> dict:
    return {"caseId": case.id, "subjectType": case.subject_type, "subjectId": case.subject_id,
            "verificationType": case.verification_type, "label": case.label, "jurisdiction": case.jurisdiction,
            "credentialClaimId": case.credential_claim_id, "specialization": case.specialization, **extra}


def _evt(session: AsyncSession, event_type: str, case: VerificationCase, **extra) -> None:
    record_event(session, event_type, aggregate_type="VerificationCase", aggregate_id=case.id,
                 tenant_id=case.subject_id, payload=_payload(case, **extra))


async def _is_owner(session: AsyncSession, actor: Actor, subject_type: str, subject_id: uuid.UUID) -> bool:
    if subject_type == "PROFESSIONAL":
        pro = await professional_facade.get_professional(session, subject_id)
        return pro is not None and pro.identity_id == actor.identity_id
    if subject_type == "FIRM":
        return FirmRole.FIRM_ADMIN in await firm_facade.member_roles(session, subject_id, actor.identity_id)
    return False


async def _require_view(session: AsyncSession, actor: Actor, subject_type: str, subject_id: uuid.UUID) -> bool:
    """Returns True when the caller is the subject's owner; operators get read access (MFA enforced)."""
    if await _is_owner(session, actor, subject_type, subject_id):
        return True
    if actor.has_platform_role(*VIEWERS):
        actor.require_platform_role(*VIEWERS)
        return False
    raise NotFound("Verification case not found")


async def _case(session: AsyncSession, case_id: uuid.UUID, lock: bool = False) -> VerificationCase:
    case = await session.get(VerificationCase, case_id, with_for_update=lock)
    if case is None:
        raise NotFound("Verification case not found")
    return case


async def _evidence(session: AsyncSession, case_id: uuid.UUID) -> list[EvidenceOut]:
    rows = (await session.scalars(select(EvidenceItem).where(EvidenceItem.case_id == case_id).order_by(EvidenceItem.created_at))).all()
    return [EvidenceOut(id=e.id, evidenceType=e.evidence_type, fileName=e.file_name, sha256=e.sha256, sizeBytes=e.size_bytes,
                        contentType=e.content_type, hasFile=bool(e.storage_key), uploadedAt=e.created_at) for e in rows]


def _appeal_out(a: Appeal) -> AppealOut:
    return AppealOut(id=a.id, caseId=a.case_id, status=a.status, statement=a.statement, filedAt=a.created_at,
                     decidedAt=a.decided_at, decisionNote=a.decision_note)


def _appeal_deadline(case: VerificationCase) -> datetime | None:
    if case.status not in ("FAILED", "REVOKED") or case.decided_at is None:
        return None
    return case.decided_at + timedelta(days=get_settings().verification_appeal_days)


async def _out(session: AsyncSession, case: VerificationCase, is_mine: bool) -> CaseOut:
    appeal = await session.scalar(select(Appeal).where(Appeal.case_id == case.id))
    deadline = _appeal_deadline(case) if is_mine and appeal is None else None
    return CaseOut(
        id=case.id, subjectType=case.subject_type, subjectId=case.subject_id, verificationType=case.verification_type,
        status=case.status, label=case.label, jurisdiction=case.jurisdiction, credentialClaimId=case.credential_claim_id,
        specialization=case.specialization, estimatedCompletion=case.estimated_completion, verifiedAt=case.verified_at,
        expiresAt=case.expires_at, reasonCode=case.reason_code, publicReason=case.public_reason, isMine=is_mine,
        evidence=await _evidence(session, case.id), createdAt=case.created_at, version=case.version,
        appeal=_appeal_out(appeal) if appeal else None,
        appealDeadline=deadline if deadline and deadline > clock.now() else None,
    )


def _clean_details(details: dict) -> dict:
    if len(details) > 20 or any(not isinstance(v, (str, int, bool, type(None))) or len(str(v)) > 200 for v in details.values()):
        raise ValidationFailed("Details must be up to 20 short text values", code="INVALID_DETAILS")
    return details


# ---- Opening cases -------------------------------------------------------------

async def _open(session: AsyncSession, *, subject_type: str, subject_id: uuid.UUID, owner_identity_id: uuid.UUID,
                verification_type: str, label: str, jurisdiction: str | None = None, details: dict | None = None,
                credential_claim_id: uuid.UUID | None = None, specialization: str | None = None) -> VerificationCase:
    now = clock.now()
    case = VerificationCase(
        subject_type=subject_type, subject_id=subject_id, owner_identity_id=owner_identity_id,
        verification_type=verification_type, label=label, jurisdiction=jurisdiction, details=details or {},
        credential_claim_id=credential_claim_id, specialization=specialization, status="PENDING",
        estimated_completion=now + SLA.get(verification_type, DEFAULT_SLA),
    )
    session.add(case)
    await session.flush()
    _evt(session, E.VERIFICATION_STARTED, case)
    case.provider_result = await get_provider().check(verification_type, case.details)
    if case.provider_result == "PASS":
        await _verify(session, case, reviewer_id=None, expires_at=None)
    elif case.provider_result == "FAIL":
        # A negative provider result is never final on its own: a person reviews it (Architecture 10.4).
        CASE_STATES.assert_can(case.status, "IN_REVIEW")
        case.status = "IN_REVIEW"
    await session.flush()
    return case


async def start_case(session: AsyncSession, actor: Actor, body: CaseIn) -> CaseOut:
    if not await _is_owner(session, actor, body.subjectType, body.subjectId):
        raise Forbidden("You can only request verification for your own profile or a firm you administer")
    if (body.verificationType == "FIRM_REGISTRATION") != (body.subjectType == "FIRM"):
        raise ValidationFailed("Firm registration checks apply to firms only; firms cannot request personal checks",
                               code="WRONG_SUBJECT_TYPE")
    jurisdiction = body.jurisdiction.upper() if body.jurisdiction else None
    if body.verificationType == "JURISDICTION" and not jurisdiction:
        raise ValidationFailed("Say which jurisdiction to check", code="JURISDICTION_REQUIRED")
    stmt = select(VerificationCase.id).where(
        VerificationCase.subject_type == body.subjectType, VerificationCase.subject_id == body.subjectId,
        VerificationCase.verification_type == body.verificationType,
        VerificationCase.status.in_((*OPEN_STATES, "VERIFIED")))
    if jurisdiction:
        stmt = stmt.where(VerificationCase.jurisdiction == jurisdiction)
    if await session.scalar(stmt.limit(1)):
        raise Conflict("This check is already in progress or verified", code="CASE_EXISTS")
    label = LABELS[body.verificationType] + (f" ({jurisdiction})" if jurisdiction else "")
    case = await _open(session, subject_type=body.subjectType, subject_id=body.subjectId, owner_identity_id=actor.identity_id,
                       verification_type=body.verificationType, label=label, jurisdiction=jurisdiction,
                       details=_clean_details(body.details))
    return await _out(session, case, True)


async def open_credential_case(session: AsyncSession, p: dict) -> None:
    """Consumer of CREDENTIAL_SUBMITTED. Idempotent per credential claim."""
    claim_id = uuid.UUID(str(p["credentialClaimId"]))
    if await session.scalar(select(VerificationCase.id).where(VerificationCase.credential_claim_id == claim_id)):
        return
    pro = await professional_facade.get_professional(session, uuid.UUID(str(p["professionalId"])))
    if pro is None:
        return
    jurisdiction = p.get("jurisdiction")
    details = {k: p.get(k) for k in ("credentialName", "issuingBody", "registrationNumber", "issuedOn", "expiresOn")}
    await _open(session, subject_type="PROFESSIONAL", subject_id=pro.id, owner_identity_id=pro.identity_id,
                verification_type="CREDENTIAL", label=p["credentialName"] + (f" ({jurisdiction})" if jurisdiction else ""),
                jurisdiction=jurisdiction, details=details, credential_claim_id=claim_id, specialization=p.get("specialization"))


async def open_restrictions_screening(session: AsyncSession, p: dict) -> None:
    """Consumer of PROFESSIONAL_REGISTERED: sanctions/restrictions screening. Idempotent per professional."""
    pro_id = uuid.UUID(str(p["professionalId"]))
    if await session.scalar(select(VerificationCase.id).where(
            VerificationCase.subject_type == "PROFESSIONAL", VerificationCase.subject_id == pro_id,
            VerificationCase.verification_type == "RESTRICTIONS")):
        return
    pro = await professional_facade.get_professional(session, pro_id)
    if pro is None:
        return
    await _open(session, subject_type="PROFESSIONAL", subject_id=pro.id, owner_identity_id=pro.identity_id,
                verification_type="RESTRICTIONS", label=LABELS["RESTRICTIONS"],
                details={"name": pro.display_name, "country": pro.country})


# ---- Evidence --------------------------------------------------------------------

# File signatures: the declared type must match the document's own bytes.
_MAGIC = {"application/pdf": b"%PDF-", "image/jpeg": b"\xff\xd8\xff", "image/png": b"\x89PNG\r\n\x1a\n"}


def _checked_file(f) -> bytes:
    """Decodes an uploaded document and checks size, type and fingerprint before it is stored."""
    try:
        data = base64.b64decode(f.dataBase64, validate=True)
    except ValueError as exc:
        raise ValidationFailed(f"{f.name} could not be read. Please upload it again.", code="INVALID_FILE") from exc
    if len(data) != f.size or len(data) > MAX_EVIDENCE_BYTES:
        raise ValidationFailed(f"{f.name} must be a complete file under 10 MB", code="INVALID_FILE")
    if not data.startswith(_MAGIC[f.contentType]):
        raise ValidationFailed(f"{f.name} is not a PDF, JPG or PNG file", code="INVALID_FILE_TYPE")
    if hashlib.sha256(data).hexdigest() != f.sha256:
        raise ValidationFailed(f"{f.name} changed during upload. Please upload it again.", code="FINGERPRINT_MISMATCH")
    return data


MAX_EVIDENCE_BYTES = 10 * 1024 * 1024


async def add_evidence(session: AsyncSession, actor: Actor, case_id: uuid.UUID, body: EvidenceIn) -> CaseOut:
    case = await _case(session, case_id, lock=True)
    if not await _is_owner(session, actor, case.subject_type, case.subject_id):
        raise NotFound("Verification case not found")
    appeal_open = case.status in ("FAILED", "REVOKED") and await session.scalar(
        select(Appeal.id).where(Appeal.case_id == case.id, Appeal.status == "OPEN"))
    if case.status not in OPEN_STATES and not appeal_open:
        raise Conflict("Evidence can only be added while the check is open", code="CASE_CLOSED")
    stored = [(f, _checked_file(f)) for f in body.items]  # validate every file before storing any
    for f, data in stored:
        key = f"verification/{case.id}/{f.sha256}"
        get_storage().put(key, data)
        session.add(EvidenceItem(case_id=case.id, evidence_type=body.evidenceType, file_name=f.name, sha256=f.sha256,
                                 size_bytes=len(data), storage_key=key, content_type=f.contentType, uploaded_by=actor.identity_id))
    if case.status in ("PENDING", "NEEDS_INFO"):
        CASE_STATES.assert_can(case.status, "IN_REVIEW")
        case.status = "IN_REVIEW"
    if body.evidenceType == "ID_DOCUMENT":
        await _check_duplicate_documents(session, case, [f.sha256 for f in body.items])
    _evt(session, E.VERIFICATION_EVIDENCE_SUBMITTED, case, evidenceType=body.evidenceType,
         files=[{"name": f.name, "sha256": f.sha256, "size": f.size} for f in body.items])
    await session.flush()
    return await _out(session, case, True)


async def _check_duplicate_documents(session: AsyncSession, case: VerificationCase, hashes: list[str]) -> None:
    """The same identity document already submitted from another account suggests a duplicate account (Onboarding s.20)."""
    others = (await session.scalars(select(VerificationCase.owner_identity_id).join(EvidenceItem, EvidenceItem.case_id == VerificationCase.id)
                                    .where(EvidenceItem.sha256.in_(hashes), EvidenceItem.evidence_type == "ID_DOCUMENT",
                                           VerificationCase.owner_identity_id != case.owner_identity_id).distinct())).all()
    for other in others:
        record_event(session, E.VERIFICATION_DUPLICATE_DOCUMENT, aggregate_type="VerificationCase", aggregate_id=case.id,
                     payload={"identityId": case.owner_identity_id, "otherIdentityId": other})


# ---- Decisions -------------------------------------------------------------------

def _default_expiry(case: VerificationCase) -> datetime | None:
    raw = (case.details or {}).get("expiresOn")
    if not raw:
        return None
    return datetime.combine(date.fromisoformat(raw), time(23, 59, 59), tzinfo=timezone.utc)


async def _verify(session: AsyncSession, case: VerificationCase, *, reviewer_id: uuid.UUID | None, expires_at: datetime | None) -> None:
    CASE_STATES.assert_can(case.status, "VERIFIED")
    now = clock.now()
    case.status, case.verified_at, case.decided_at, case.reviewer_id = "VERIFIED", now, now, reviewer_id
    case.expires_at = expires_at or _default_expiry(case)
    case.reason_code = case.public_reason = None
    if case.expires_at:
        for days in REMINDER_DAYS:
            fire = case.expires_at - timedelta(days=days)
            if fire > now:
                await schedule_timer(session, TIMER_REMINDER, f"{case.id}:{days}", fire, {"caseId": str(case.id), "days": days})
        await schedule_timer(session, TIMER_EXPIRY, str(case.id), case.expires_at, {"caseId": str(case.id)})
    _evt(session, E.VERIFICATION_COMPLETED, case, expiresAt=case.expires_at, decidedBy=reviewer_id or "PROVIDER")


def _fail(session: AsyncSession, case: VerificationCase, *, reviewer_id: uuid.UUID | None, reason_code: str, public_reason: str) -> None:
    CASE_STATES.assert_can(case.status, "FAILED")
    case.status, case.decided_at, case.reviewer_id = "FAILED", clock.now(), reviewer_id
    case.reason_code, case.public_reason = reason_code, public_reason
    _evt(session, E.VERIFICATION_FAILED, case, reasonCode=reason_code, publicReason=public_reason)


async def decide(session: AsyncSession, actor: Actor, case_id: uuid.UUID, body: DecisionIn) -> CaseOut:
    """Human review. Needs COMPLIANCE_OFFICER + fresh step-up; nobody reviews their own case."""
    actor.require_platform_role(*REVIEWERS)
    actor.require_step_up()
    case = await _case(session, case_id, lock=True)
    if case.owner_identity_id == actor.identity_id or (
            case.subject_type == "FIRM" and await firm_facade.member_roles(session, case.subject_id, actor.identity_id)):
        raise Forbidden("You cannot review your own verification or your own firm's", code="SELF_REVIEW")
    if body.decision != "VERIFIED" and not body.publicReason:
        raise ValidationFailed("Explain the outcome to the professional in plain language", code="PUBLIC_REASON_REQUIRED")
    if body.decision == "VERIFIED":
        if body.expiresAt and body.expiresAt <= clock.now():
            raise ValidationFailed("The expiry date must be in the future", code="INVALID_EXPIRY")
        # Evidence-based verification (Trust charter s.6): screening is checked against lists, everything else needs a document.
        if case.verification_type != "RESTRICTIONS" and not await session.scalar(
                select(func.count()).select_from(EvidenceItem).where(EvidenceItem.case_id == case.id)):
            raise ValidationFailed("Ask for supporting documents before verifying: none have been submitted",
                                   code="EVIDENCE_REQUIRED")
        await _verify(session, case, reviewer_id=actor.identity_id, expires_at=body.expiresAt)
    elif body.decision == "FAILED":
        _fail(session, case, reviewer_id=actor.identity_id, reason_code=body.reasonCode, public_reason=body.publicReason)
    else:
        CASE_STATES.assert_can(case.status, "NEEDS_INFO")
        case.status, case.reason_code, case.public_reason = "NEEDS_INFO", body.reasonCode, body.publicReason
        _evt(session, E.VERIFICATION_NEEDS_INFO, case, reasonCode=body.reasonCode, publicReason=body.publicReason)
    await session.flush()
    return await _out(session, case, False)


async def _cancel_expiry_timers(session: AsyncSession, case: VerificationCase) -> None:
    await cancel_timer(session, TIMER_EXPIRY, str(case.id))
    for days in REMINDER_DAYS:
        await cancel_timer(session, TIMER_REMINDER, f"{case.id}:{days}")


async def revoke(session: AsyncSession, actor: Actor, case_id: uuid.UUID, body: RevokeIn) -> CaseOut:
    actor.require_platform_role(*REVIEWERS)
    actor.require_step_up()
    case = await _case(session, case_id, lock=True)
    CASE_STATES.assert_can(case.status, "REVOKED")
    case.status, case.reason_code, case.public_reason, case.reviewer_id = "REVOKED", body.reasonCode, body.publicReason, actor.identity_id
    case.decided_at = clock.now()
    await _cancel_expiry_timers(session, case)
    _evt(session, E.VERIFICATION_REVOKED, case, reasonCode=body.reasonCode, publicReason=body.publicReason)
    await session.flush()
    return await _out(session, case, False)


# ---- Expiry (durable timers) -------------------------------------------------------

def _still_verified(case: VerificationCase | None) -> bool:
    # Revocation cancels the timers; this guard also covers timers that fire late or twice.
    return case is not None and case.status == "VERIFIED" and case.expires_at is not None


async def remind_expiring(session: AsyncSession, payload: dict) -> None:
    case = await session.get(VerificationCase, uuid.UUID(payload["caseId"]))
    if not _still_verified(case):
        return
    # The reminder kind (30/14/7) is the promise; the timer may fire a little late.
    days_left = int(payload.get("days") or max(0, (case.expires_at - clock.now()).days))
    _evt(session, E.VERIFICATION_EXPIRING, case, expiresAt=case.expires_at, daysLeft=days_left)


async def expire(session: AsyncSession, payload: dict) -> None:
    case = await session.get(VerificationCase, uuid.UUID(payload["caseId"]), with_for_update=True)
    if not _still_verified(case) or case.expires_at > clock.now():
        return
    case.status = "EXPIRED"
    _evt(session, E.VERIFICATION_EXPIRED, case)


# ---- Queries ---------------------------------------------------------------------

async def evidence_file(session: AsyncSession, actor: Actor, evidence_id: uuid.UUID) -> tuple[bytes, str, str]:
    """The document itself, for its owner and for reviewers. Every opening is recorded in the audit log."""
    item = await session.get(EvidenceItem, evidence_id)
    if item is None:
        raise NotFound("Document not found")
    case = await _case(session, item.case_id)
    await _require_view(session, actor, case.subject_type, case.subject_id)
    data = get_storage().get(item.storage_key) if item.storage_key else None
    if data is None:
        raise NotFound("This document was recorded before file uploads were stored. Ask for it to be uploaded again.",
                       code="FILE_NOT_STORED")
    record_audit(session, "verification.evidence.viewed", object_type="EvidenceItem", object_id=item.id,
                 tenant_id=case.subject_id, evidence_hash=item.sha256, details={"caseId": str(case.id)})
    return data, item.content_type or "application/octet-stream", item.file_name


async def get_case(session: AsyncSession, actor: Actor, case_id: uuid.UUID) -> CaseOut:
    case = await _case(session, case_id)
    return await _out(session, case, await _require_view(session, actor, case.subject_type, case.subject_id))


async def subject_cases(session: AsyncSession, actor: Actor, subject_type: str, subject_id: uuid.UUID) -> list[CaseOut]:
    mine = await _require_view(session, actor, subject_type, subject_id)
    rows = (await session.scalars(select(VerificationCase).where(
        VerificationCase.subject_type == subject_type, VerificationCase.subject_id == subject_id)
        .order_by(VerificationCase.created_at.desc()))).all()
    return [await _out(session, c, mine) for c in rows]


async def review_queue(session: AsyncSession, actor: Actor, cursor: str | None, limit: int | None, status: str | None) -> dict:
    actor.require_platform_role(*REVIEWERS)
    # Default: checks waiting for a decision. "VERIFIED": decided checks, so a mistaken verification can be revoked.
    states = (status,) if status in (*OPEN_STATES, "VERIFIED") else ("PENDING", "IN_REVIEW")
    stmt, lim = paginate(select(VerificationCase).where(VerificationCase.status.in_(states)), VerificationCase, cursor, limit)
    rows = (await session.scalars(stmt)).all()
    counts = dict((await session.execute(
        select(EvidenceItem.case_id, func.count()).where(EvidenceItem.case_id.in_([c.id for c in rows])).group_by(EvidenceItem.case_id)
    )).all())
    pros = await professional_facade.get_professionals(session, [c.subject_id for c in rows if c.subject_type == "PROFESSIONAL"])
    names = {k: v.display_name for k, v in pros.items()}
    for c in rows:
        if c.subject_type == "FIRM" and c.subject_id not in names:
            firm = await firm_facade.get_firm(session, c.subject_id)
            names[c.subject_id] = firm.legal_name if firm else None
    now = clock.now()
    return page_of(list(rows), lim, lambda c: QueueItemOut(
        id=c.id, subjectType=c.subject_type, subjectId=c.subject_id, subjectName=names.get(c.subject_id),
        verificationType=c.verification_type, status=c.status, label=c.label, jurisdiction=c.jurisdiction,
        providerResult=c.provider_result, evidenceCount=counts.get(c.id, 0), estimatedCompletion=c.estimated_completion,
        overdue=bool(c.estimated_completion and c.estimated_completion < now), createdAt=c.created_at))


# ---- Appeals (Governance playbook s.11: independent reviewer, evidence-based, time-bounded, one final decision) ----

async def file_appeal(session: AsyncSession, actor: Actor, case_id: uuid.UUID, body: AppealIn) -> CaseOut:
    case = await _case(session, case_id, lock=True)
    if not await _is_owner(session, actor, case.subject_type, case.subject_id):
        raise NotFound("Verification case not found")
    if case.status not in ("FAILED", "REVOKED"):
        raise Conflict("Only a failed or revoked verification can be appealed", code="NOT_APPEALABLE")
    if await session.scalar(select(Appeal.id).where(Appeal.case_id == case.id)):
        raise Conflict("This decision has already been appealed; appeals are decided once", code="APPEAL_EXISTS")
    deadline = _appeal_deadline(case)
    if deadline is None or clock.now() > deadline:
        raise Conflict(f"The appeal window ({get_settings().verification_appeal_days} days) has closed. Start a new check instead.",
                       code="APPEAL_WINDOW_CLOSED")
    a = Appeal(case_id=case.id, filed_by=actor.identity_id, statement=body.statement.strip(), case_status_at_filing=case.status,
               original_reviewer_id=case.reviewer_id, status="OPEN")
    session.add(a)
    await session.flush()
    _evt(session, E.VERIFICATION_APPEAL_FILED, case, appealId=a.id)
    return await _out(session, case, True)


async def appeal_queue(session: AsyncSession, actor: Actor, status: str | None) -> list[AppealQueueItemOut]:
    actor.require_platform_role(*REVIEWERS)
    rows = (await session.execute(select(Appeal, VerificationCase).join(VerificationCase, VerificationCase.id == Appeal.case_id)
                                  .where(Appeal.status == (status or "OPEN")).order_by(Appeal.created_at).limit(200))).all()
    counts = dict((await session.execute(select(EvidenceItem.case_id, func.count())
                                         .where(EvidenceItem.case_id.in_([c.id for _, c in rows])).group_by(EvidenceItem.case_id))).all())
    pros = await professional_facade.get_professionals(session, [c.subject_id for _, c in rows if c.subject_type == "PROFESSIONAL"])
    return [AppealQueueItemOut(
        id=a.id, caseId=c.id, caseLabel=c.label, verificationType=c.verification_type, subjectType=c.subject_type, subjectId=c.subject_id,
        subjectName=pros[c.subject_id].display_name if c.subject_id in pros else None, caseStatus=c.status, originalReason=c.public_reason,
        statement=a.statement, status=a.status, evidenceCount=counts.get(c.id, 0),
        canDecide=a.original_reviewer_id != actor.identity_id and c.owner_identity_id != actor.identity_id, filedAt=a.created_at)
        for a, c in rows]


async def decide_appeal(session: AsyncSession, actor: Actor, appeal_id: uuid.UUID, body: AppealDecisionIn) -> AppealOut:
    actor.require_platform_role(*REVIEWERS)
    actor.require_step_up()
    a = await session.get(Appeal, appeal_id, with_for_update=True)
    if a is None:
        raise NotFound("Appeal not found")
    if a.status != "OPEN":
        raise Conflict("This appeal has already been decided", code="APPEAL_DECIDED")
    case = await _case(session, a.case_id, lock=True)
    if case.owner_identity_id == actor.identity_id or (
            case.subject_type == "FIRM" and await firm_facade.member_roles(session, case.subject_id, actor.identity_id)):
        raise Forbidden("You cannot review your own verification or your own firm's", code="SELF_REVIEW")
    if a.original_reviewer_id == actor.identity_id:
        raise Forbidden("An appeal must be decided by a reviewer who did not make the original decision", code="INDEPENDENT_REVIEWER_REQUIRED")
    now = clock.now()
    if body.outcome == "OVERTURNED":
        if case.verification_type != "RESTRICTIONS" and not await session.scalar(
                select(func.count()).select_from(EvidenceItem).where(EvidenceItem.case_id == case.id)):
            raise ValidationFailed("There are no documents to support overturning this decision", code="EVIDENCE_REQUIRED")
        if body.expiresAt and body.expiresAt <= now:
            raise ValidationFailed("The expiry date must be in the future", code="INVALID_EXPIRY")
        await _verify(session, case, reviewer_id=actor.identity_id, expires_at=body.expiresAt)
    a.status, a.decided_by, a.decided_at, a.decision_note = body.outcome, actor.identity_id, now, body.note.strip()
    _evt(session, E.VERIFICATION_APPEAL_DECIDED, case, appealId=a.id, outcome=body.outcome)
    await session.flush()
    return _appeal_out(a)
