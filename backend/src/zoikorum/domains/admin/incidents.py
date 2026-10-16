"""Incident register (Regulator assurance s.11; RUNBOOKS.md "Write it down").

Any staff member opens an incident; its owner moves it on. Severity SEV1/SEV2 incidents need a root cause, every
remediation task done and a written post-incident review before they close. Every change is audited and timestamped;
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
from zoikorum.shared.auth import PlatformRole
from zoikorum.shared.errors import Conflict, NotFound, ValidationFailed
from zoikorum.shared.events import record_audit

LEADS = (PlatformRole.PLATFORM_ADMIN, PlatformRole.RISK_LEAD, PlatformRole.LEGAL, PlatformRole.EXECUTIVE)
NEXT = {"OPEN": "CONTAINED", "CONTAINED": "RESOLVED", "RESOLVED": "CLOSED"}


class IncidentIn(BaseModel):
    title: str = Field(min_length=5, max_length=200)
    kind: Literal["SECURITY", "DATA", "PAYMENTS", "OUTAGE", "SAFETY", "OTHER"]
    severity: Literal["SEV1", "SEV2", "SEV3", "SEV4"]
    summary: str = Field(min_length=10, max_length=4000)


class IncidentUpdateIn(BaseModel):
    note: str | None = Field(default=None, max_length=2000)  # adds to the timeline
    advanceTo: Literal["CONTAINED", "RESOLVED", "CLOSED"] | None = None
    severity: Literal["SEV1", "SEV2", "SEV3", "SEV4"] | None = None
    rootCause: str | None = Field(default=None, max_length=4000)
    addRemediation: list[str] = Field(default_factory=list, max_length=20)
    completeRemediation: list[int] = Field(default_factory=list, max_length=20)
    notified: list[dict] = Field(default_factory=list, max_length=10)  # [{party, note}] e.g. regulator, customers
    review: str | None = Field(default=None, max_length=8000)


async def _out(session, i: Incident) -> dict:
    owner = (await identity_facade.get_identities(session, [i.owner_id])).get(i.owner_id)
    return {"id": str(i.id), "reference": i.reference, "title": i.title, "kind": i.kind, "severity": i.severity,
            "status": i.status, "summary": i.summary, "detectedAt": i.detected_at, "containedAt": i.contained_at,
            "resolvedAt": i.resolved_at, "closedAt": i.closed_at, "owner": owner.display_name if owner else "—",
            "timeline": i.timeline, "notifications": i.notifications, "rootCause": i.root_cause,
            "remediation": i.remediation, "review": i.review, "createdAt": i.created_at, "updatedAt": i.updated_at}


async def open_incident(session, actor, body: IncidentIn) -> dict:
    await staff(session, actor, *PlatformRole.ALL)
    now = clock.now()
    i = Incident(reference="ZK-INC-" + uuid.uuid4().hex[:6].upper(), title=body.title.strip(), kind=body.kind,
                 severity=body.severity, status="OPEN", summary=body.summary.strip(), detected_at=now, owner_id=actor.identity_id,
                 timeline=[{"at": now.isoformat(), "by": str(actor.identity_id), "note": "Opened: " + body.summary.strip()[:500]}],
                 notifications=[], remediation=[])
    session.add(i)
    await session.flush()
    record_audit(session, "admin.incident.opened", object_type="Incident", object_id=i.id,
                 details={"reference": i.reference, "kind": i.kind, "severity": i.severity})
    return await _out(session, i)


async def list_incidents(session, actor, status: str | None) -> list[dict]:
    await staff(session, actor, *PlatformRole.ALL)
    stmt = select(Incident).order_by(Incident.detected_at.desc()).limit(200)
    if status:
        stmt = stmt.where(Incident.status == status)
    return [await _out(session, i) for i in (await session.scalars(stmt)).all()]


async def update_incident(session, actor, incident_id: uuid.UUID, body: IncidentUpdateIn) -> dict:
    await staff(session, actor, *PlatformRole.ALL)
    i = await session.get(Incident, incident_id, with_for_update=True)
    if i is None:
        raise NotFound("Incident not found")
    if i.status == "CLOSED":
        raise Conflict("This incident is closed", code="INCIDENT_CLOSED")
    lead = actor.has_platform_role(*LEADS)
    if i.owner_id != actor.identity_id and not lead and (body.advanceTo or body.severity or body.review):
        raise Conflict("Only the incident owner or an incident lead can change its state", code="NOT_INCIDENT_OWNER")
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
    if body.advanceTo:
        if NEXT.get(i.status) != body.advanceTo:
            raise Conflict(f"An incident moves {i.status.lower()} -> {NEXT.get(i.status, '?').lower()}", code="INVALID_STEP")
        if body.advanceTo == "CLOSED" and i.severity in ("SEV1", "SEV2"):
            missing = [m for m, ok in (("a root cause", i.root_cause), ("a post-incident review", i.review),
                                       ("every remediation task done", all(t["done"] for t in tasks))) if not ok]
            if missing:
                raise ValidationFailed("Before closing a SEV1/SEV2 incident, record " + ", ".join(missing), code="REVIEW_REQUIRED")
        i.status = body.advanceTo
        setattr(i, {"CONTAINED": "contained_at", "RESOLVED": "resolved_at", "CLOSED": "closed_at"}[body.advanceTo], now)
        entries.append({"at": now.isoformat(), "by": by, "note": f"Status: {body.advanceTo.lower()}"})
    i.timeline = entries
    record_audit(session, "admin.incident.updated", object_type="Incident", object_id=i.id,
                 details=body.model_dump(exclude_none=True, exclude_defaults=True))
    await session.flush()
    return await _out(session, i)
