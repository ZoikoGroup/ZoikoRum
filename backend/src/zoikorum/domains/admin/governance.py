"""Internal governance and ethics for staff (Ethics charter, Governance playbook, Regulator assurance).

* Conflict-of-interest register: a staff member declares a conflict with a person, professional or organisation, or
  recuses themselves from one case. Enforcement and dispute decisions check it (``declared_conflict``) and refuse a
  decider with a matching active entry. Entries are withdrawn, never deleted.
* Level 4 referrals to law enforcement or a regulator: agency, their reference, date and Legal's sign-off. Only Legal
  records or reads them; the case itself shows nothing about a referral.
* Third-party fraud alerts: a signed intake (the platform webhook secret, ``Webhook-Signature: t=<unix>,v1=<hmac>``)
  records the alert and opens an advisory Level 0 review. It never restricts anyone by itself.
"""

from __future__ import annotations

import hmac
import json
import uuid

from fastapi import APIRouter, Header, Request
from sqlalchemy import or_, select

from zoikorum.config import get_settings
from zoikorum.domains.admin.models import ConflictDeclaration, EnforcementCase, EnforcementReferral, FraudAlert
from zoikorum.domains.admin.schemas import ConflictIn, FraudAlertIn, PostReviewIn, ReferralIn
from zoikorum.domains.admin.service import case_get, case_out, open_referral_case, staff
from zoikorum.domains.buyer import facade as buyer_facade
from zoikorum.domains.identity import facade as identity_facade
from zoikorum.domains.professional import facade as professional_facade
from zoikorum.shared import clock
from zoikorum.shared.auth import CurrentActor
from zoikorum.shared.capabilities import ALL_CAPABILITIES, Cap
from zoikorum.shared.crypto import hmac_sha256_hex
from zoikorum.shared.db import DbSession
from zoikorum.shared.errors import Conflict, Forbidden, NotFound, ValidationFailed
from zoikorum.shared.events import record_audit

router = APIRouter(tags=["admin"])


# ---- Conflicts of interest and recusals ----------------------------------------------------------------------------

async def declared_conflict(session, identity_id: uuid.UUID, subjects: list[tuple[str, uuid.UUID]],
                            case: tuple[str, str] | None = None) -> bool:
    """True when this staff member has an active declaration on any of ``subjects`` or recused from ``case``."""
    match = [(ConflictDeclaration.kind == "DECLARATION") & (ConflictDeclaration.subject_type == t) & (ConflictDeclaration.subject_id == i)
             for t, i in subjects if i]
    if case:
        match.append((ConflictDeclaration.kind == "RECUSAL") & (ConflictDeclaration.case_kind == case[0]) & (ConflictDeclaration.case_id == case[1]))
    if not match:
        return False
    return await session.scalar(select(ConflictDeclaration.id).where(
        ConflictDeclaration.identity_id == identity_id, ConflictDeclaration.status == "ACTIVE", or_(*match)).limit(1)) is not None


def _conflict_out(d: ConflictDeclaration, names: dict) -> dict:
    who = names.get(d.identity_id)
    return {"id": d.id, "identityId": d.identity_id, "staffName": who.display_name if who else None, "kind": d.kind,
            "subjectType": d.subject_type, "subjectId": d.subject_id, "caseKind": d.case_kind, "caseId": d.case_id,
            "reason": d.reason, "status": d.status, "createdAt": d.created_at, "withdrawnAt": d.withdrawn_at}


def _require_staff(actor) -> None:
    actor.require_capability(*ALL_CAPABILITIES)  # any staff member, with MFA


@router.post("/v1/admin/conflicts", status_code=201)
async def declare_conflict(body: ConflictIn, actor: CurrentActor, session: DbSession) -> dict:
    """Any staff member: declare a conflict of interest with a subject, or recuse yourself from a case. From then on you
    are refused as its mediator, approver or reviewer."""
    _require_staff(actor)
    if body.kind == "DECLARATION":
        lookup = {"IDENTITY": identity_facade.get_identity, "PROFESSIONAL": professional_facade.get_professional,
                  "ORGANIZATION": buyer_facade.get_organization}
        if not await lookup[body.subjectType](session, body.subjectId):
            raise NotFound("Subject not found")
    d = ConflictDeclaration(identity_id=actor.identity_id, kind=body.kind, reason=body.reason.strip(), status="ACTIVE",
                            subject_type=body.subjectType if body.kind == "DECLARATION" else None,
                            subject_id=body.subjectId if body.kind == "DECLARATION" else None,
                            case_kind=body.caseKind if body.kind == "RECUSAL" else None,
                            case_id=body.caseId.strip() if body.kind == "RECUSAL" and body.caseId else None)
    session.add(d)
    await session.flush()
    record_audit(session, "admin.conflict." + body.kind.lower(), object_type="ConflictDeclaration", object_id=d.id,
                 details={"subjectType": d.subject_type, "subjectId": str(d.subject_id) if d.subject_id else None,
                          "caseKind": d.case_kind, "caseId": d.case_id})
    return _conflict_out(d, await identity_facade.get_identities(session, [d.identity_id]))


@router.get("/v1/admin/conflicts")
async def list_conflicts(actor: CurrentActor, session: DbSession, mine: bool = False, status: str | None = None) -> list[dict]:
    """My own declarations (any staff member), or the whole register (Legal, Risk Lead, Executive, Platform Admin)."""
    if mine:
        _require_staff(actor)
    else:
        await staff(session, actor, Cap.ETHICS_CONFLICTS_READ)
    stmt = select(ConflictDeclaration).order_by(ConflictDeclaration.created_at.desc()).limit(500)
    if mine:
        stmt = stmt.where(ConflictDeclaration.identity_id == actor.identity_id)
    if status:
        stmt = stmt.where(ConflictDeclaration.status == status)
    rows = (await session.scalars(stmt)).all()
    names = await identity_facade.get_identities(session, list({r.identity_id for r in rows}))
    return [_conflict_out(r, names) for r in rows]


@router.post("/v1/admin/conflicts/{declaration_id}/withdraw")
async def withdraw_conflict(declaration_id: uuid.UUID, actor: CurrentActor, session: DbSession) -> dict:
    """The person who declared it withdraws it (the conflict has ended). The entry stays in the register."""
    _require_staff(actor)
    d = await session.get(ConflictDeclaration, declaration_id, with_for_update=True)
    if d is None or d.identity_id != actor.identity_id:
        raise NotFound("Declaration not found")
    if d.status != "ACTIVE":
        raise Conflict("This declaration was already withdrawn", code="ALREADY_WITHDRAWN")
    d.status, d.withdrawn_at = "WITHDRAWN", clock.now()
    record_audit(session, "admin.conflict.withdrawn", object_type="ConflictDeclaration", object_id=d.id, details={})
    return _conflict_out(d, await identity_facade.get_identities(session, [d.identity_id]))


# ---- Level 4 referrals (Legal only) ------------------------------------------------------------------------------------

def _referral_out(r: EnforcementReferral) -> dict:
    return {"id": r.id, "caseId": r.case_id, "agency": r.agency, "agencyReference": r.agency_reference, "referredOn": r.referred_on,
            "legalSignOffBy": r.legal_signoff_by, "legalSignOff": r.legal_signoff_note, "createdAt": r.created_at}


@router.get("/v1/admin/enforcement-cases/{case_id}/referrals")
async def list_referrals(case_id: uuid.UUID, actor: CurrentActor, session: DbSession) -> list[dict]:
    await staff(session, actor, Cap.SAFETY_REFERRAL)
    await case_get(session, case_id)
    record_audit(session, "admin.referral.read", object_type="EnforcementCase", object_id=case_id, details={})
    rows = (await session.scalars(select(EnforcementReferral).where(EnforcementReferral.case_id == case_id)
                                  .order_by(EnforcementReferral.created_at))).all()
    return [_referral_out(r) for r in rows]


@router.post("/v1/admin/enforcement-cases/{case_id}/referrals", status_code=201)
async def record_referral(case_id: uuid.UUID, body: ReferralIn, actor: CurrentActor, session: DbSession) -> dict:
    """Legal: record a Level 4 case's referral to law enforcement or a regulator, with the sign-off (step-up)."""
    from zoikorum.domains.admin.service import is_subject, no_conflict

    await staff(session, actor, Cap.SAFETY_REFERRAL)
    actor.require_step_up()
    c = await case_get(session, case_id, True)
    if c.level != 4:
        raise Conflict("Referrals to law enforcement or a regulator are recorded on Level 4 cases", code="LEVEL_4_REQUIRED")
    if await is_subject(session, actor, c):
        raise Forbidden("You cannot act on your own case")
    await no_conflict(session, actor, c)
    if body.referredOn > clock.now().date():
        raise ValidationFailed("The referral date cannot be in the future", code="INVALID_DATE")
    r = EnforcementReferral(case_id=c.id, agency=body.agency.strip(), agency_reference=body.agencyReference.strip(),
                            referred_on=body.referredOn, legal_signoff_by=actor.identity_id, legal_signoff_note=body.legalSignOff.strip())
    session.add(r)
    await session.flush()
    record_audit(session, "admin.referral.recorded", object_type="EnforcementCase", object_id=c.id,
                 details={"referralId": str(r.id), "agency": r.agency, "referredOn": r.referred_on.isoformat()})
    return _referral_out(r)


# ---- Third-party fraud alerts --------------------------------------------------------------------------------------------

def _signed(signature: str | None, body: bytes) -> bool:
    s = get_settings()
    try:
        parts = dict(p.split("=", 1) for p in (signature or "").split(","))
        t = int(parts["t"])
    except (KeyError, ValueError):
        return False
    if abs(clock.now().timestamp() - t) > s.webhook_tolerance_seconds:
        return False
    return hmac.compare_digest(hmac_sha256_hex(s.webhook_secret, f"{t}.".encode() + body), parts.get("v1", ""))


@router.post("/v1/integrations/fraud-alerts", status_code=202)
async def fraud_alert(request: Request, session: DbSession, webhook_signature: str | None = Header(default=None)) -> dict:
    """A fraud-detection partner reports a risk on a person, professional or organisation. Signed with the platform
    webhook secret (``Webhook-Signature: t=<unix seconds>,v1=<HMAC-SHA256 of "<t>.<body>">``). Advisory: it opens a
    Level 0 review for Trust & Safety; nothing is restricted automatically. Repeating an alert id is harmless."""
    raw = await request.body()
    if not _signed(webhook_signature, raw):
        raise Forbidden("Invalid or expired signature", code="INVALID_SIGNATURE")
    try:
        body = FraudAlertIn.model_validate(json.loads(raw or b"{}"))
    except ValueError as exc:
        raise ValidationFailed("The alert is not valid", code="INVALID_ALERT") from exc
    existing = await session.scalar(select(FraudAlert).where(FraudAlert.provider == body.provider, FraudAlert.external_id == body.alertId))
    if existing:
        return {"alertId": existing.id, "caseId": existing.case_id, "duplicate": True}
    lookup = {"IDENTITY": identity_facade.get_identity, "PROFESSIONAL": professional_facade.get_professional,
              "ORGANIZATION": buyer_facade.get_organization}
    if not await lookup[body.subjectType](session, body.subjectId):
        raise NotFound("Subject not found")
    alert = FraudAlert(provider=body.provider, external_id=body.alertId, subject_type=body.subjectType, subject_id=body.subjectId,
                       reason_code=body.reasonCode, score=body.score, details=body.details)
    session.add(alert)
    await session.flush()
    alert.case_id = await open_referral_case(
        session, body.subjectType, body.subjectId, f"THIRD_PARTY_FRAUD:{body.provider}"[:100],
        f"Advisory risk signal from {body.provider}: {body.reasonCode}" + (f" (score {body.score})" if body.score is not None else ""),
        [f"fraud-alert:{alert.id}"])
    record_audit(session, "admin.fraud_alert.received", object_type="FraudAlert", object_id=alert.id,
                 details={"provider": body.provider, "reasonCode": body.reasonCode, "score": body.score})
    return {"alertId": alert.id, "caseId": alert.case_id, "duplicate": False}


@router.get("/v1/admin/fraud-alerts")
async def list_fraud_alerts(actor: CurrentActor, session: DbSession, limit: int = 50) -> list[dict]:
    """Trust & Safety: third-party fraud alerts received, newest first, with the review case each one opened."""
    await staff(session, actor, Cap.SAFETY_RISK_READ)
    rows = (await session.scalars(select(FraudAlert).order_by(FraudAlert.created_at.desc()).limit(max(1, min(limit, 200))))).all()
    cases = {c.id: c for c in (await session.scalars(select(EnforcementCase).where(
        EnforcementCase.id.in_([r.case_id for r in rows if r.case_id])))).all()} if rows else {}
    return [{"id": r.id, "provider": r.provider, "alertId": r.external_id, "subjectType": r.subject_type, "subjectId": r.subject_id,
             "reasonCode": r.reason_code, "score": r.score, "receivedAt": r.created_at, "caseId": r.case_id,
             "caseStatus": cases[r.case_id].status if r.case_id in cases else None} for r in rows]


# ---- Post-review and conclusion of Level 3+ cases ------------------------------------------------------------------------

@router.post("/v1/admin/enforcement-cases/{case_id}/post-review")
async def post_review(case_id: uuid.UUID, body: PostReviewIn, actor: CurrentActor, session: DbSession) -> dict:
    """Level 3+ (Risk Lead or Legal): root cause, user experience impact and policy updates proposed."""
    from zoikorum.domains.admin import service
    return await service.post_review(session, actor, case_id, body)


@router.post("/v1/admin/enforcement-cases/{case_id}/conclude")
async def conclude(case_id: uuid.UUID, actor: CurrentActor, session: DbSession) -> dict:
    """Level 3+: close a case whose action has ended, once its post-review is recorded."""
    from zoikorum.domains.admin import service
    return await service.conclude_case(session, actor, case_id)


__all__ = ["router", "declared_conflict", "case_out"]
