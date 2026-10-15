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


# ---- Risk score (ai/risk.py): payment and behaviour signals, per person and per organisation --------------------------

RISK_SIGNALS = {
    E.AUTHENTICATION_FAILED: "LOGIN_FAILURE", E.DISPUTE_INITIATED: "DISPUTE", E.MESSAGE_FLAGGED: "MESSAGE_FLAG",
    E.PAYMENT_FAILED: "PAYMENT_FAILED", E.CHARGEBACK_RECEIVED: "CHARGEBACK", E.ESCROW_FUNDING_REVERSED: "FUNDING_REVERSED",
    E.DUPLICATE_ACCOUNT_SUSPECTED: "DUPLICATE_ACCOUNT", E.DISPUTE_PATTERN_FLAGGED: "DISPUTE_PATTERN",
}


async def score_signal(session, event):
    from zoikorum.domains.ai import risk

    kind = RISK_SIGNALS[event.eventType]
    p = event.payload
    person = p.get("identityId") or p.get("senderIdentityId") or p.get("initiatedBy") or (
        p.get("subjectId") if p.get("subjectType") == "IDENTITY" else None)
    org = p.get("organizationId") or (event.tenantId if event.eventType in (E.PAYMENT_FAILED, E.CHARGEBACK_RECEIVED) else None)
    if person:
        await risk.observe(session, uuid.uuid5(event.eventId, "identity"), "IDENTITY", uuid.UUID(str(person)), kind, event.occurredAt)
    if org and event.eventType in (E.PAYMENT_FAILED, E.CHARGEBACK_RECEIVED, E.ESCROW_FUNDING_REVERSED, E.DISPUTE_INITIATED):
        await risk.observe(session, uuid.uuid5(event.eventId, "organization"), "ORGANIZATION", uuid.UUID(str(org)), kind, event.occurredAt)


for event_type in RISK_SIGNALS:
    subscribe(event_type, consumer="ai.risk_score")(score_signal)
