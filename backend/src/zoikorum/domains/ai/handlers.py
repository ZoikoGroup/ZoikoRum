import uuid
from datetime import timedelta
from sqlalchemy import select, func
from zoikorum.domains.ai.models import RiskObservation
from zoikorum.shared.events import subscribe, record_event
from zoikorum.shared.event_catalog import E
from zoikorum.shared import clock


async def observe(session, event):
    p = event.payload
    raw = p.get("identityId") or p.get("senderIdentityId") or p.get("initiatedBy")
    if not raw:
        return
    iid = uuid.UUID(str(raw))
    if await session.scalar(select(RiskObservation.id).where(RiskObservation.source_event_id == event.eventId)):
        return
    kind = "LOGIN_FAILURE" if event.eventType == E.AUTHENTICATION_FAILED else "DISPUTE" if event.eventType == E.DISPUTE_INITIATED else "MESSAGE_FLAG"
    session.add(RiskObservation(source_event_id=event.eventId, identity_id=iid, kind=kind, created_at=event.occurredAt))
    await session.flush()
    count = await session.scalar(select(func.count()).select_from(RiskObservation).where(RiskObservation.identity_id == iid,
        RiskObservation.kind == kind, RiskObservation.created_at >= clock.now() - timedelta(minutes=10)))
    # Advisory triage defaults, not automatic sanctions or trust-tier penalties.
    threshold = 5 if kind == "LOGIN_FAILURE" else 3 if kind == "DISPUTE" else 1
    if count == threshold:
        record_event(session, E.RISK_FLAG_RAISED, aggregate_type="Identity", aggregate_id=iid,
            payload={"identityId": iid, "subjectType": "IDENTITY", "subjectId": iid, "reasonCode": kind,
                     "sourceEventId": event.eventId, "advisoryOnly": True})


for event_type in (E.AUTHENTICATION_FAILED, E.DISPUTE_INITIATED, E.MESSAGE_FLAGGED):
    subscribe(event_type, consumer="ai.advisory_risk")(observe)
