from __future__ import annotations
import uuid
from collections import Counter, defaultdict
from sqlalchemy import select, delete, text
from sqlalchemy.dialects.postgresql import insert
from zoikorum.domains.analytics.models import EventFact
from zoikorum.domains.audit import facade as audit
from zoikorum.shared.event_catalog import E, ALL_EVENTS, domain_of
from zoikorum.shared.events import record_audit
from zoikorum.shared import clock

EVENTS = {e for e in ALL_EVENTS if domain_of(e) in {"proposal", "contract", "escrow", "search", "trust", "verification", "policy", "dispute", "payments", "marketplace"}}
PROJECTION_LOCK = 7310992


def as_uuid(value):
    try:
        return uuid.UUID(str(value)) if value else None
    except ValueError:
        return None


async def project(session, event):
    if event.eventType not in EVENTS:
        return
    await session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": PROJECTION_LOCK})
    p = event.payload
    safe = {k: v for k, v in p.items() if k.endswith(("Id", "Ids", "Minor")) or k in {
        "currency", "status", "tier", "toTier", "score", "onTime", "auto", "resultsCount", "resultCount", "count", "reference", "expiresAt", "milestoneOutcome", "subjectType", "decisionPath", "dueDate", "title", "sequence", "party", "verificationType"}}
    await session.execute(insert(EventFact).values(id=uuid.uuid4(), source_event_id=event.eventId,
        event_type=event.eventType, organization_id=as_uuid(p.get("organizationId")), professional_id=as_uuid(p.get("professionalId") or (p.get("subjectId") if p.get("subjectType") == "PROFESSIONAL" else None)),
        aggregate_id=str(event.aggregateId), payload=safe, occurred_at=event.occurredAt).on_conflict_do_nothing(index_elements=["source_event_id"]))


async def facts(session, *, org_id=None, professional_id=None, identity_id=None, since=None, until=None):
    stmt = select(EventFact).order_by(EventFact.occurred_at, EventFact.seq)
    if org_id:
        stmt = stmt.where(EventFact.organization_id == org_id)
    if professional_id:
        stmt = stmt.where(EventFact.professional_id == professional_id)
    if identity_id:
        stmt = stmt.where(EventFact.payload["identityId"].astext == str(identity_id))
    if since:
        stmt = stmt.where(EventFact.occurred_at >= since)
    if until:
        stmt = stmt.where(EventFact.occurred_at < until)
    return list((await session.scalars(stmt)).all())


def summarize(rows, role="buyer"):
    requests, proposals, contracts, milestones, approvals = {}, {}, {}, {}, {}
    milestone_details, tier, signatures, checks = {}, None, defaultdict(set), {}
    protection, earnings, monthly = defaultdict(int), defaultdict(int), defaultdict(int)
    now = clock.now()
    for row in rows:
        p, kind = row.payload, row.event_type
        rid, pid, cid, mid = str(p.get("requestId", row.aggregate_id)), str(p.get("proposalId", row.aggregate_id)), str(p.get("contractId", row.aggregate_id)), str(p.get("milestoneId", row.aggregate_id))
        if kind == E.PROPOSAL_REQUESTED: requests[rid] = "NEW"
        if kind in (E.PROPOSAL_REQUEST_DECLINED, E.PROPOSAL_REQUEST_CANCELLED, E.PROPOSAL_SUBMITTED, E.PROPOSAL_REVISED): requests[rid] = "ANSWERED"
        if kind in (E.PROPOSAL_SUBMITTED, E.PROPOSAL_REVISED): proposals[pid] = "OPEN"
        if kind in (E.PROPOSAL_ACCEPTED, E.PROPOSAL_REJECTED, E.PROPOSAL_EXPIRED): proposals[pid] = "CLOSED"
        if kind == E.PROPOSAL_REVISION_REQUESTED: proposals[pid] = "REVISION"
        if kind in (E.CONTRACT_GENERATED, E.CONTRACT_AMENDED):
            contracts[cid], signatures[cid] = "SIGNING", set()
        if kind == E.CONTRACT_SIGNED: signatures[cid].add(p.get("party"))
        if kind == E.CONTRACT_ACTIVATED: contracts[cid] = "ACTIVE"
        if kind in (E.CONTRACT_COMPLETED, E.CONTRACT_TERMINATED): contracts[cid] = "CLOSED"
        if kind == E.MILESTONE_SUBMITTED: milestones[mid] = "REVIEW"
        if kind == E.MILESTONE_CREATED: milestone_details[mid] = {"id": mid, "contractId": cid, "title": p.get("title"), "dueDate": p.get("dueDate")}
        verification_states = {E.VERIFICATION_STARTED: "OPEN", E.VERIFICATION_EVIDENCE_SUBMITTED: "OPEN", E.VERIFICATION_NEEDS_INFO: "NEEDS_INFO",
            E.VERIFICATION_COMPLETED: "VERIFIED", E.VERIFICATION_FAILED: "FAILED", E.VERIFICATION_EXPIRED: "EXPIRED", E.VERIFICATION_REVOKED: "REVOKED"}
        if kind in verification_states: checks[str(p.get("caseId", row.aggregate_id))] = verification_states[kind]
        if kind in (E.TRUST_TIER_CHANGED, E.TRUST_SCORE_RECOMPUTED): tier = p.get("tier", p.get("toTier"))
        if kind in (E.MILESTONE_ACCEPTED, E.MILESTONE_REVISION_REQUESTED): milestones[mid] = "ACCEPTED" if kind == E.MILESTONE_ACCEPTED else "REVISION"
        if kind == E.APPROVAL_REQUIRED: approvals[row.aggregate_id] = "PENDING"
        if kind in (E.APPROVAL_GRANTED, E.APPROVAL_DENIED, E.APPROVAL_EXPIRED): approvals[row.aggregate_id] = "CLOSED"
        currency = p.get("currency")
        if currency:
            if kind == E.ESCROW_FUNDED: protection[currency] += p.get("amountMinor", 0)
            if kind == E.ESCROW_RELEASED:
                protection[currency] -= p.get("grossMinor", 0)
                earnings[currency] += p.get("netMinor", 0)
                if row.occurred_at.year == now.year and row.occurred_at.month == now.month: monthly[currency] += p.get("netMinor", 0)
            if kind in (E.ESCROW_REFUNDED, E.ESCROW_FUNDING_REVERSED): protection[currency] -= p.get("amountMinor", 0)
    return {"activeEngagements": sum(v == "ACTIVE" for v in contracts.values()), "openProposals": sum(v == "OPEN" for v in proposals.values()),
            "newRequests": sum(v == "NEW" for v in requests.values()),
            "pendingActions": (sum(v == "SIGNING" and "BUYER" not in signatures[cid] for cid, v in contracts.items()) + sum(v == "OPEN" for v in proposals.values()) + sum(v == "REVIEW" for v in milestones.values()) + sum(v == "PENDING" for v in approvals.values())) if role == "buyer" else
                (sum(v == "NEW" for v in requests.values()) + sum(v == "REVISION" for v in proposals.values()) + sum(v == "REVISION" for v in milestones.values()) + sum(v == "SIGNING" and "BUYER" in signatures[cid] and "PROFESSIONAL" not in signatures[cid] for cid, v in contracts.items()) + sum(v == "NEEDS_INFO" for v in checks.values())),
            "fundsInProtectionMinor": dict(protection), "lifetimeEarningsMinor": dict(earnings), "earningsThisMonthMinor": dict(monthly),
            "pendingReleaseMinor": dict(protection), "trustTier": tier,
            "verificationStatus": dict(Counter(checks.values())),
            "upcomingMilestones": sorted([detail for mid, detail in milestone_details.items() if milestones.get(mid) != "ACCEPTED" and detail["dueDate"] and contracts.get(detail["contractId"]) != "CLOSED"], key=lambda item: item["dueDate"]),
            "lastEventAt": max((r.occurred_at for r in rows), default=None)}


def report(rows):
    kinds = {E.ESCROW_FUNDED, E.ESCROW_RELEASED, E.ESCROW_REFUNDED, E.ESCROW_FUNDING_REVERSED}
    return [{"eventId": str(r.source_event_id), "date": r.occurred_at.isoformat(), "eventType": r.event_type,
             "contractId": r.payload.get("contractId"), "currency": r.payload.get("currency"),
             "grossMinor": r.payload.get("grossMinor", r.payload.get("amountMinor", 0)), "feeMinor": r.payload.get("feeMinor", 0),
             "netMinor": r.payload.get("netMinor", 0)} for r in rows if r.event_type in kinds]


async def rebuild(session, actor):
    await session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": PROJECTION_LOCK})
    await session.execute(delete(EventFact))
    count, after = 0, 0
    while batch := await audit.replay_events(session, after, 500):
        for seq, event in batch:
            await project(session, event)
            count += int(event.eventType in EVENTS)
            after = seq
    record_audit(session, "analytics.rebuilt", object_type="AnalyticsProjection", object_id="all", details={"events": count})
    return {"projectedEvents": count}
