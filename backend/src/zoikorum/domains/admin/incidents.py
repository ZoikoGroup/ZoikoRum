"""Incident register (Regulator assurance s.11; RUNBOOKS.md "Write it down").

Any staff member opens an incident; its owner (the incident commander) moves it on:
UNACKNOWLEDGED -> INVESTIGATING -> MITIGATING -> MONITORING -> RECOVERED -> CLOSED.
Mitigation is not verified recovery: RECOVERED needs a recovery verification note from a staff member who is neither
the incident owner nor the person who set MITIGATING. Severity SEV1/SEV2 incidents need a root cause, every
remediation task done and a written post-incident review (with the user experience impact and the policy updates
proposed) before they close. Every change is audited and timestamped;
nothing is deleted.
"""

from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel, Field
from sqlalchemy import select

from zoikorum.domains.admin.models import Incident
from zoikorum.domains.admin.service import staff
from zoikorum.domains.identity import facade as identity_facade
from zoikorum.shared import clock
from zoikorum.shared.capabilities import Cap
from zoikorum.shared.errors import Conflict, NotFound, ValidationFailed
from zoikorum.shared.events import record_audit

STAGES = ("UNACKNOWLEDGED", "INVESTIGATING", "MITIGATING", "MONITORING", "RECOVERED", "CLOSED")
NEXT = dict(zip(STAGES, STAGES[1:]))
STAMP = {"INVESTIGATING": "acknowledged_at", "MITIGATING": "contained_at", "MONITORING": "monitoring_at",
         "RECOVERED": "resolved_at", "CLOSED": "closed_at"}


class IncidentIn(BaseModel):
    title: str = Field(min_length=5, max_length=200)
    # CREDENTIAL_FAILURE: a verification or credential check failed at scale (wrong passes or fails);
    # SYSTEM_INTEGRITY: records, ledgers or audit trails may be wrong or tampered with.
    kind: Literal["SECURITY", "DATA", "PAYMENTS", "OUTAGE", "SAFETY", "CREDENTIAL_FAILURE", "SYSTEM_INTEGRITY", "OTHER"]
    severity: Literal["SEV1", "SEV2", "SEV3", "SEV4"]
    summary: str = Field(min_length=10, max_length=4000)


class IncidentUpdateIn(BaseModel):
    note: str | None = Field(default=None, max_length=2000)  # adds to the timeline
    advanceTo: Literal["INVESTIGATING", "MITIGATING", "MONITORING", "RECOVERED", "CLOSED"] | None = None
    recoveryNote: str | None = Field(default=None, max_length=2000)  # required to reach RECOVERED: how recovery was verified
    severity: Literal["SEV1", "SEV2", "SEV3", "SEV4"] | None = None
    rootCause: str | None = Field(default=None, max_length=4000)
    addRemediation: list[str] = Field(default_factory=list, max_length=20)
    completeRemediation: list[int] = Field(default_factory=list, max_length=20)
    notified: list[dict] = Field(default_factory=list, max_length=10)  # [{party, note}] e.g. regulator, customers
    review: str | None = Field(default=None, max_length=8000)
    uxImpact: str | None = Field(default=None, max_length=4000)  # post-incident review: how people were affected
    policyUpdates: str | None = Field(default=None, max_length=4000)  # post-incident review: policy changes proposed


async def _out(session, i: Incident) -> dict:
    people = await identity_facade.get_identities(session, [p for p in (i.owner_id, i.mitigated_by, i.recovery_verified_by) if p])

    def name(pid):
        return people[pid].display_name if pid in people else None
    return {"id": str(i.id), "reference": i.reference, "title": i.title, "kind": i.kind, "severity": i.severity,
            "status": i.status, "summary": i.summary, "detectedAt": i.detected_at, "acknowledgedAt": i.acknowledged_at,
            "mitigatingAt": i.contained_at, "monitoringAt": i.monitoring_at, "recoveredAt": i.resolved_at,
            "containedAt": i.contained_at, "resolvedAt": i.resolved_at, "closedAt": i.closed_at,
            "owner": name(i.owner_id) or "—", "ownerId": str(i.owner_id),
            "mitigatedBy": name(i.mitigated_by), "mitigatedById": str(i.mitigated_by) if i.mitigated_by else None,
            "recoveryNote": i.recovery_note, "recoveryVerifiedBy": name(i.recovery_verified_by),
            "timeline": i.timeline, "notifications": i.notifications, "rootCause": i.root_cause,
            "remediation": i.remediation, "review": i.review, "uxImpact": i.ux_impact, "policyUpdates": i.policy_updates,
            "createdAt": i.created_at, "updatedAt": i.updated_at}


async def open_incident(session, actor, body: IncidentIn) -> dict:
    await staff(session, actor, Cap.INCIDENTS_OPERATE)
    now = clock.now()
    i = Incident(reference="ZK-INC-" + uuid.uuid4().hex[:6].upper(), title=body.title.strip(), kind=body.kind,
                 severity=body.severity, status="UNACKNOWLEDGED", summary=body.summary.strip(), detected_at=now,
                 owner_id=actor.identity_id,
                 timeline=[{"at": now.isoformat(), "by": str(actor.identity_id), "note": "Opened: " + body.summary.strip()[:500]}],
                 notifications=[], remediation=[])
    session.add(i)
    await session.flush()
    record_audit(session, "admin.incident.opened", object_type="Incident", object_id=i.id,
                 details={"reference": i.reference, "kind": i.kind, "severity": i.severity})
    return await _out(session, i)


async def list_incidents(session, actor, status: str | None) -> list[dict]:
    await staff(session, actor, Cap.INCIDENTS_READ)
    stmt = select(Incident).order_by(Incident.detected_at.desc()).limit(200)
    if status:
        stmt = stmt.where(Incident.status == status)
    return [await _out(session, i) for i in (await session.scalars(stmt)).all()]


async def update_incident(session, actor, incident_id: uuid.UUID, body: IncidentUpdateIn) -> dict:
    await staff(session, actor, Cap.INCIDENTS_OPERATE)
    i = await session.get(Incident, incident_id, with_for_update=True)
    if i is None:
        raise NotFound("Incident not found")
    if i.status == "CLOSED":
        raise Conflict("This incident is closed", code="INCIDENT_CLOSED")
    lead = actor.has_capability(Cap.INCIDENTS_LEAD)
    owner = i.owner_id == actor.identity_id
    # Recovery is verified independently: any staff member other than the owner and the mitigator may record it.
    verifying = body.advanceTo == "RECOVERED"
    if not owner and not lead and ((body.advanceTo and not verifying) or body.severity or body.review or body.uxImpact or body.policyUpdates):
        raise Conflict("Only the incident owner or an incident lead can change its state", code="NOT_INCIDENT_OWNER")
    if body.advanceTo and NEXT.get(i.status) != body.advanceTo:
        raise Conflict(f"An incident moves {i.status.lower()} -> {NEXT.get(i.status, '?').lower()}", code="INVALID_STEP")
    if verifying:
        if owner or i.mitigated_by == actor.identity_id:
            raise Conflict("Recovery must be verified by someone other than the incident owner and the person who set "
                           "mitigating", code="INDEPENDENT_VERIFICATION_REQUIRED")
        if not (body.recoveryNote or "").strip() or len(body.recoveryNote.strip()) < 10:
            raise ValidationFailed("Record how recovery was verified (at least 10 characters)", code="RECOVERY_NOTE_REQUIRED")
    now, by = clock.now(), str(actor.identity_id)
    entries = list(i.timeline)
    if body.note:
        entries.append({"at": now.isoformat(), "by": by, "note": body.note.strip()})
    if body.severity and body.severity != i.severity:
        entries.append({"at": now.isoformat(), "by": by, "note": f"Severity {i.severity} -> {body.severity}"})
        i.severity = body.severity
    if body.rootCause:
        i.root_cause = body.rootCause.strip()
    tasks = list(i.remediation)
    tasks += [{"task": t.strip(), "done": False} for t in body.addRemediation if t.strip()]
    for index in body.completeRemediation:
        if 0 <= index < len(tasks):
            tasks[index] = {**tasks[index], "done": True, "doneAt": now.isoformat(), "by": by}
    i.remediation = tasks
    if body.notified:
        i.notifications = [*i.notifications, *[{"party": str(n.get("party", ""))[:100], "note": str(n.get("note", ""))[:500],
                                               "at": now.isoformat(), "by": by} for n in body.notified]]
    if body.review:
        i.review = body.review.strip()
    if body.uxImpact:
        i.ux_impact = body.uxImpact.strip()
    if body.policyUpdates:
        i.policy_updates = body.policyUpdates.strip()
    if body.advanceTo:
        if body.advanceTo == "CLOSED" and i.severity in ("SEV1", "SEV2"):
            missing = [m for m, ok in (("a root cause", i.root_cause), ("a post-incident review", i.review),
                                       ("the user experience impact", i.ux_impact), ("the policy updates proposed", i.policy_updates),
                                       ("every remediation task done", all(t["done"] for t in tasks))) if not ok]
            if missing:
                raise ValidationFailed("Before closing a SEV1/SEV2 incident, record " + ", ".join(missing), code="REVIEW_REQUIRED")
        if body.advanceTo == "MITIGATING":
            i.mitigated_by = actor.identity_id
        if verifying:
            i.recovery_note, i.recovery_verified_by = body.recoveryNote.strip(), actor.identity_id
            entries.append({"at": now.isoformat(), "by": by, "note": "Recovery verified: " + i.recovery_note[:500]})
        i.status = body.advanceTo
        setattr(i, STAMP[body.advanceTo], now)
        entries.append({"at": now.isoformat(), "by": by, "note": f"Status: {body.advanceTo.lower()}"})
    i.timeline = entries
    record_audit(session, "admin.incident.updated", object_type="Incident", object_id=i.id,
                 details=body.model_dump(exclude_none=True, exclude_defaults=True))
    await session.flush()
    return await _out(session, i)
