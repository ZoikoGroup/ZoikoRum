from __future__ import annotations
import uuid
from collections import Counter, defaultdict
from sqlalchemy import select, delete, func, literal_column, text
from sqlalchemy.dialects.postgresql import insert
from zoikorum.domains.analytics.models import EventFact
from zoikorum.domains.audit import facade as audit
from zoikorum.domains.contract import facade as contract_facade
from zoikorum.shared.event_catalog import E, ALL_EVENTS, domain_of
from zoikorum.shared.events import record_audit
from zoikorum.shared import clock

EVENTS = {e for e in ALL_EVENTS if domain_of(e) in {"proposal", "contract", "escrow", "search", "trust", "verification", "policy", "dispute", "payments", "marketplace"}} | {E.PROFILE_VIEWED}
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
    professional_id = as_uuid(p.get("professionalId") or (p.get("subjectId") if p.get("subjectType") == "PROFESSIONAL" else None))
    if professional_id is None and domain_of(event.eventType) == "escrow" and p.get("contractId"):
        # Funding, refund and reversal events name only the contract: without this the professional's summary would count
        # releases but never the funding behind them. Looked up here so a rebuild from the audit ledger is right too.
        contract = await contract_facade.get_contract(session, as_uuid(p["contractId"]))
        professional_id = contract.professional_id if contract else None
    await session.execute(insert(EventFact).values(id=uuid.uuid4(), source_event_id=event.eventId,
        event_type=event.eventType, organization_id=as_uuid(p.get("organizationId")), professional_id=professional_id,
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
        if kind in (E.PROPOSAL_ACCEPTED, E.PROPOSAL_REJECTED, E.PROPOSAL_EXPIRED, E.PROPOSAL_WITHDRAWN): proposals[pid] = "CLOSED"
        if kind == E.PROPOSAL_ACCEPTANCE_PENDING_APPROVAL: proposals[pid] = "APPROVAL"  # chosen; the approvers act next
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


DAILY_METRICS = {
    E.SEARCH_PERFORMED: "searches", E.SEARCH_ZERO_RESULT: "zeroResultSearches", E.PROPOSAL_SUBMITTED: "proposalsSubmitted",
    E.CONTRACT_GENERATED: "contractsGenerated", E.CONTRACT_ACTIVATED: "activations", E.ESCROW_RELEASED: "releases",
    E.DISPUTE_INITIATED: "disputesOpened", E.DISPUTE_RESOLVED: "disputesResolved",
}
UTC_DAY = literal_column("(analytics.event_facts.occurred_at AT TIME ZONE 'UTC')::date")


def in_window(stmt, since, until):
    if since:
        stmt = stmt.where(EventFact.occurred_at >= since)
    if until:
        stmt = stmt.where(EventFact.occurred_at < until)
    return stmt


async def marketplace_health(session, since=None, until=None):
    """Aggregated in Postgres so the cost follows the window, not the size of the event history."""
    counts = dict((await session.execute(in_window(
        select(EventFact.event_type, func.count()).group_by(EventFact.event_type), since, until))).all())
    last_event_at = await session.scalar(in_window(select(func.max(EventFact.occurred_at)), since, until))

    daily: dict = {}
    rows = await session.execute(in_window(
        select(UTC_DAY, EventFact.event_type, func.count()).where(EventFact.event_type.in_(DAILY_METRICS))
        .group_by(UTC_DAY, EventFact.event_type), since, until))
    for day, kind, n in rows:
        daily.setdefault(day, {"date": day.isoformat(), **{metric: 0 for metric in DAILY_METRICS.values()}})[DAILY_METRICS[kind]] = n

    released = in_window(select(EventFact.occurred_at.label("released_at"), EventFact.payload["milestoneId"].astext.label("milestone_id"))
                         .where(EventFact.event_type == E.ESCROW_RELEASED), since, until).subquery()
    funded = (select(EventFact.occurred_at.label("funded_at"), func.jsonb_array_elements_text(EventFact.payload["milestoneIds"]).label("milestone_id"))
              .where(EventFact.event_type == E.ESCROW_FUNDED).subquery())
    last_funding = (select(func.max(funded.c.funded_at)).where(funded.c.milestone_id == released.c.milestone_id,
                                                                funded.c.funded_at <= released.c.released_at).scalar_subquery())
    latency = func.extract("epoch", released.c.released_at - last_funding)
    median_release = await session.scalar(select(func.percentile_cont(0.5).within_group(latency)).where(last_funding.isnot(None)))

    tier = func.coalesce(EventFact.payload["tier"].astext, EventFact.payload["toTier"].astext).label("tier")
    latest = (select(EventFact.professional_id, tier)
              .where(EventFact.event_type.in_((E.TRUST_TIER_CHANGED, E.TRUST_SCORE_RECOMPUTED)), EventFact.professional_id.isnot(None))
              .order_by(EventFact.professional_id, EventFact.occurred_at.desc(), EventFact.seq.desc())
              .distinct(EventFact.professional_id).subquery())
    tiers = dict((await session.execute(select(latest.c.tier, func.count()).where(latest.c.tier.isnot(None)).group_by(latest.c.tier))).all())

    return {"window": {"from": since, "to": until},
            "eventCounts": counts, "searches": counts.get(E.SEARCH_PERFORMED, 0), "zeroResultSearches": counts.get(E.SEARCH_ZERO_RESULT, 0),
            "activations": counts.get(E.CONTRACT_ACTIVATED, 0),
            "disputesOpened": counts.get(E.DISPUTE_INITIATED, 0), "disputesResolved": counts.get(E.DISPUTE_RESOLVED, 0),
            "proposalContractConversionBps": round(10000 * counts.get(E.CONTRACT_GENERATED, 0) / counts[E.PROPOSAL_SUBMITTED]) if counts.get(E.PROPOSAL_SUBMITTED) else None,
            "medianReleaseLatencySeconds": float(median_release) if median_release is not None else None,
            "trustTierDistribution": tiers, "daily": [daily[day] for day in sorted(daily)], "lastEventAt": last_event_at}


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
