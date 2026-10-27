"""Enterprise readiness (Professional profile: Enterprise Ready designation and Enterprise Signals).

A professional applies once the automatic requirements are met (Green trust light, two-step sign-in, insurance checked) and they
attest to basic security practice. A compliance officer approves or declines; nothing is granted automatically. The
designation shows only while the requirements still hold, so a lapsed check removes it without anyone acting.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from zoikorum.domains.identity import facade as identity_facade
from zoikorum.domains.professional.models import Professional
from zoikorum.domains.professional.service import _mine
from zoikorum.domains.trust import facade as trust_facade
from zoikorum.shared import clock
from zoikorum.shared.auth import Actor
from zoikorum.shared.capabilities import Cap
from zoikorum.shared.errors import Conflict, NotFound, ValidationFailed
from zoikorum.shared.event_catalog import E
from zoikorum.shared.events import record_audit, record_event

ATTESTATION_VERSION = "2026-10"
ATTESTATION = {
    "deviceEncryption": "Devices I use for client work have full-disk encryption and a screen lock.",
    "accountProtection": "My email and file storage accounts use two-step sign-in.",
    "confidentialStorage": "Client files are kept only in the engagement or in encrypted storage I control, never on shared accounts.",
    "breachNotice": "I will tell the client and Zoikorum within 72 hours of any suspected loss or exposure of client data.",
    "returnOrDelete": "When an engagement ends I return or delete client data as the contract says.",
    "noSubcontracting": "I will not pass client work or data to anyone else without the client's written agreement.",
}


async def _requirements(session: AsyncSession, pro: Professional) -> list[dict]:
    trust = await trust_facade.get_trust(session, pro.id)
    insurance = trust.dimensions.get("insurance")
    return [
        {"key": "tierA", "label": "Green trust light (identity, credentials, right to practise and screening verified)", "met": trust.tier == "A"},
        {"key": "twoStep", "label": "Two-step sign-in on your account (authenticator app or passkey)",
         "met": await identity_facade.two_step_enabled(session, pro.identity_id)},
        {"key": "insurance", "label": "Professional indemnity insurance verified", "met": insurance in ("VERIFIED", "NOT_REQUIRED")},
        {"key": "published", "label": "Profile published", "met": pro.status == "PUBLISHED"},
    ]


async def is_ready(session: AsyncSession, pro: Professional) -> bool:
    """Designated, and every requirement still holds."""
    return pro.enterprise_status == "READY" and all(r["met"] for r in await _requirements(session, pro))


def _out(pro: Professional, requirements: list[dict], ready: bool) -> dict:
    return {"status": "READY" if ready else ("LAPSED" if pro.enterprise_status == "READY" else pro.enterprise_status),
            "requirements": requirements, "attestationVersion": ATTESTATION_VERSION,
            "attestationItems": [{"key": k, "text": v} for k, v in ATTESTATION.items()],
            "attestation": pro.enterprise_attestation, "appliedAt": pro.enterprise_applied_at, "decidedAt": pro.enterprise_decided_at,
            "decisionReason": pro.enterprise_decision_reason}


async def mine(session: AsyncSession, actor: Actor) -> dict:
    pro = await _mine(session, actor)
    requirements = await _requirements(session, pro)
    return _out(pro, requirements, pro.enterprise_status == "READY" and all(r["met"] for r in requirements))


async def apply(session: AsyncSession, actor: Actor, attestation: dict[str, bool]) -> dict:
    pro = await _mine(session, actor, lock=True)
    if pro.enterprise_status in ("PENDING", "READY"):
        raise Conflict("You have already applied" if pro.enterprise_status == "PENDING" else "You are already Enterprise Ready",
                       code="ALREADY_APPLIED")
    requirements = await _requirements(session, pro)
    missing = [r["label"] for r in requirements if not r["met"]]
    if missing:
        raise Conflict("Complete these first: " + "; ".join(missing), code="ENTERPRISE_REQUIREMENTS_NOT_MET", extra={"missing": missing})
    if set(ATTESTATION) - {k for k, v in attestation.items() if v is True}:
        raise ValidationFailed("Confirm every security statement", code="ATTESTATION_INCOMPLETE")
    actor.require_step_up()
    now = clock.now()
    pro.enterprise_status, pro.enterprise_applied_at, pro.enterprise_decided_at, pro.enterprise_decision_reason = "PENDING", now, None, None
    pro.enterprise_attestation = {"version": ATTESTATION_VERSION, "items": sorted(ATTESTATION), "attestedAt": now.isoformat()}
    record_event(session, E.ENTERPRISE_READINESS_REQUESTED, aggregate_type="Professional", aggregate_id=pro.id,
                 payload={"professionalId": pro.id, "audience": "STAFF"})
    record_audit(session, "professional.enterprise.applied", object_type="Professional", object_id=pro.id,
                 details={"attestationVersion": ATTESTATION_VERSION})
    await session.flush()
    return _out(pro, requirements, False)


async def queue(session: AsyncSession, actor: Actor) -> list[dict]:
    actor.require_capability(Cap.ENTERPRISE_READ)
    rows = (await session.scalars(select(Professional).where(Professional.enterprise_status == "PENDING")
                                  .order_by(Professional.enterprise_applied_at))).all()
    out = []
    for p in rows:
        requirements = await _requirements(session, p)
        out.append({"professionalId": p.id, "name": p.display_name, "headline": p.headline, "appliedAt": p.enterprise_applied_at,
                    "requirements": requirements, "attestation": p.enterprise_attestation})
    return out


async def decide(session: AsyncSession, actor: Actor, professional_id: uuid.UUID, approve: bool, reason: str) -> dict:
    """Compliance approves or declines. Approval needs every requirement to hold at the moment of the decision."""
    actor.require_capability(Cap.ENTERPRISE_DECIDE)
    actor.require_step_up()
    pro = await session.get(Professional, professional_id, with_for_update=True)
    if pro is None:
        raise NotFound("Professional not found")
    if pro.enterprise_status != "PENDING":
        raise Conflict("There is no pending application", code="NOT_PENDING")
    if pro.identity_id == actor.identity_id:
        raise Conflict("You cannot decide your own application", code="CONFLICT_OF_INTEREST")
    requirements = await _requirements(session, pro)
    if approve and not all(r["met"] for r in requirements):
        raise Conflict("A requirement no longer holds; decline with the reason instead", code="ENTERPRISE_REQUIREMENTS_NOT_MET")
    pro.enterprise_status = "READY" if approve else "REJECTED"
    pro.enterprise_decided_at, pro.enterprise_decision_reason = clock.now(), reason.strip()[:500]
    record_event(session, E.ENTERPRISE_READINESS_DECIDED, aggregate_type="Professional", aggregate_id=pro.id,
                 payload={"professionalId": pro.id, "identityId": pro.identity_id, "audience": "PROFESSIONAL", "approved": approve,
                          "message": ("You are Enterprise Ready: it now shows on your profile and in search."
                                      if approve else f"Your Enterprise Ready application was declined: {reason.strip()[:300]}")})
    record_event(session, E.PROFILE_UPDATED, aggregate_type="Professional", aggregate_id=pro.id,
                 payload={"professionalId": pro.id, "changes": ["enterpriseReady"]})
    record_audit(session, "professional.enterprise." + ("approved" if approve else "declined"), object_type="Professional",
                 object_id=pro.id, details={"reason": reason.strip()[:500]})
    await session.flush()
    return _out(pro, requirements, approve)


async def signals(session: AsyncSession, pro: Professional) -> dict:
    """What an enterprise buyer looks for, shown on the public profile."""
    requirements = await _requirements(session, pro)
    ready = pro.enterprise_status == "READY" and all(r["met"] for r in requirements)
    met = {r["key"] for r in requirements if r["met"]}
    items = [label for key, label in (("tierA", "Fully verified (Green)"), ("twoStep", "Two-step sign-in"),
                                      ("insurance", "Indemnity insurance checked")) if key in met]
    if pro.regulated_data_attested_at:
        items.append("Handles regulated data (attested)")
    if ready and pro.enterprise_attestation:
        items.append(f"Security practice attested {pro.enterprise_attestation.get('attestedAt', '')[:10]}")
    return {"enterpriseReady": ready, "signals": items}
