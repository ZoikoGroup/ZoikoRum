from __future__ import annotations
import hashlib
import re
import uuid
from collections import Counter, defaultdict
from statistics import median
from sqlalchemy import Integer, cast, select, delete, func, literal_column, text
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
# Product-funnel events sent by the web app (POST /v1/analytics/events) share the facts table but are not domain events:
# they are kept out of marketplace health and survive a rebuild, which replays only the audit ledger.
CLIENT_PREFIX = "zoikorum.client.funnel."
NOT_CLIENT = EventFact.event_type.not_like(CLIENT_PREFIX + "%")
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
        select(EventFact.event_type, func.count()).where(NOT_CLIENT).group_by(EventFact.event_type), since, until))).all())
    last_event_at = await session.scalar(in_window(select(func.max(EventFact.occurred_at)).where(NOT_CLIENT), since, until))

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
    await session.execute(delete(EventFact).where(NOT_CLIENT))  # funnel events from the web app are not in the ledger: kept
    count, after = 0, 0
    while batch := await audit.replay_events(session, after, 500):
        for seq, event in batch:
            await project(session, event)
            count += int(event.eventType in EVENTS)
            after = seq
    record_audit(session, "analytics.rebuilt", object_type="AnalyticsProjection", object_id="all", details={"events": count})
    return {"projectedEvents": count}


# ---- Product funnels (Onboarding & Category wireframes, Request flow): events the web app sends ---------------------

CLIENT_EVENTS = frozenset({
    "onboarding_step_viewed", "onboarding_step_completed", "profile_published",
    "request_step_viewed", "request_step_completed", "request_abandoned", "proposal_started", "proposal_submitted",
    "filter_applied", "specialization_selected", "compare_opened", "quick_view_opened", "enterprise_cta_clicked",
    "verification_detail_viewed", "service_card_opened",
})
# The only properties kept: short slugs (a step, a filter, a specialization, where on the page) and small numbers.
# Free text, emails, names and ids never match (no "@", no spaces, no uuid-like runs, at most 60 characters): dropped.
CLIENT_PROPS = {"step": str, "filter": str, "specialization": str, "source": str, "position": int}
SAFE_VALUE = re.compile(r"^[a-z0-9][a-z0-9_.:-]{0,59}$")
UUID_LIKE = re.compile(r"[0-9a-f]{8}-?[0-9a-f]{4}-?[0-9a-f]{4}")
SEARCH_MICRO = ("filter_applied", "specialization_selected", "quick_view_opened", "compare_opened", "service_card_opened",
                "verification_detail_viewed", "enterprise_cta_clicked")


def client_type(name: str) -> str:
    return f"{CLIENT_PREFIX}{name}.v1"


def client_name(event_type: str) -> str:
    return event_type[len(CLIENT_PREFIX):-len(".v1")]


def clean_props(props: dict) -> dict:
    out: dict = {}
    for key, value in props.items():
        kind = CLIENT_PROPS.get(key)
        if kind is None or isinstance(value, bool) or not isinstance(value, kind):
            continue
        if kind is int:
            if 0 <= value <= 100_000:
                out[key] = value
        else:
            text_value = value.strip().lower()
            if SAFE_VALUE.match(text_value) and not UUID_LIKE.search(text_value):
                out[key] = text_value
    return out


def session_key(session_id: str | None) -> str:
    """A one-way hash of the browser's random visit id: steps of one visit count together, nothing names a person."""
    return "client:" + (hashlib.sha256(session_id.encode()).hexdigest()[:32] if session_id else "unknown")


async def record_client_events(session, events, session_id: str | None, signed_in: bool) -> dict:
    """Stores allowlisted events at the server's time (the browser's clock is never trusted). Unknown names are skipped."""
    now, key, rows = clock.now(), session_key(session_id), []
    for e in events:
        if e.name not in CLIENT_EVENTS:
            continue
        rows.append({"id": uuid.uuid4(), "source_event_id": uuid.uuid4(), "event_type": client_type(e.name), "aggregate_id": key,
                     "organization_id": None, "professional_id": None, "occurred_at": now,
                     "payload": {**clean_props(e.props), "signedIn": signed_in}})
    if rows:
        await session.execute(insert(EventFact), rows)
    return {"accepted": len(rows), "ignored": len(events) - len(rows)}


def pct(part, whole):
    return round(100 * part / whole, 1) if whole else None


async def _visits(session, names, since, until) -> dict[str, set[str]]:
    rows = await session.execute(in_window(select(EventFact.event_type, EventFact.aggregate_id).distinct()
                                           .where(EventFact.event_type.in_([client_type(n) for n in names])), since, until))
    out: dict[str, set[str]] = {n: set() for n in names}
    for kind, key in rows:
        out[client_name(kind)].add(key)
    return out


async def _steps(session, viewed: str, completed: str, since, until) -> list[dict]:
    """Per step: visits that saw it, visits that completed it, and the share that left without completing it. Steps are in
    the order the web app numbers them (``position``), then by how many visits reached them."""
    step = EventFact.payload["step"].astext
    position = func.min(cast(EventFact.payload["position"].astext, Integer))
    rows = await session.execute(in_window(
        select(EventFact.event_type, step, func.count(func.distinct(EventFact.aggregate_id)), position)
        .where(EventFact.event_type.in_((client_type(viewed), client_type(completed))), step.isnot(None))
        .group_by(EventFact.event_type, step), since, until))
    steps: dict[str, dict] = {}
    for kind, name, n, pos in rows:
        s = steps.setdefault(name, {"step": name, "viewed": 0, "completed": 0, "position": None})
        s["viewed" if kind == client_type(viewed) else "completed"] = n
        if pos is not None:
            s["position"] = pos if s["position"] is None else min(s["position"], pos)
    for s in steps.values():
        s["dropOffPct"] = pct(max(s["viewed"] - s["completed"], 0), s["viewed"])
    return sorted(steps.values(), key=lambda s: (s["position"] if s["position"] is not None else 10**6, -s["viewed"], s["step"]))


async def onboarding_funnel(session, since, until, signup_to_publish_hours: list[float]) -> dict:
    """Professional onboarding: visits that started, per-step drop-off, visits that published, and (from profile records,
    not the browser) the median time from sign-up to a published profile."""
    visits = await _visits(session, ("onboarding_step_viewed", "profile_published"), since, until)
    started, published = visits["onboarding_step_viewed"], visits["profile_published"]
    return {"window": {"from": since, "to": until}, "visitsStarted": len(started), "visitsPublished": len(published & started),
            "completionRatePct": pct(len(published & started), len(started)),
            "steps": await _steps(session, "onboarding_step_viewed", "onboarding_step_completed", since, until),
            "profilesPublished": len(signup_to_publish_hours),
            "medianHoursSignupToPublish": round(median(signup_to_publish_hours), 1) if signup_to_publish_hours else None}


async def request_funnel(session, since, until) -> dict:
    """The buyer's request flow (per-step completion and where visits abandoned) and the professional's proposal flow."""
    visits = await _visits(session, ("request_step_viewed", "request_abandoned", "proposal_started", "proposal_submitted"), since, until)
    step = func.coalesce(EventFact.payload["step"].astext, "unknown")
    abandoned = dict((await session.execute(in_window(
        select(step, func.count(func.distinct(EventFact.aggregate_id)))
        .where(EventFact.event_type == client_type("request_abandoned")).group_by(step), since, until))).all())
    sent = await session.scalar(in_window(select(func.count()).where(EventFact.event_type == E.PROPOSAL_REQUESTED), since, until)) or 0
    viewed, left = visits["request_step_viewed"], visits["request_abandoned"]
    started, submitted = visits["proposal_started"], visits["proposal_submitted"]
    return {"window": {"from": since, "to": until}, "visitsStarted": len(viewed), "visitsAbandoned": len(left & viewed),
            "abandonmentRatePct": pct(len(left & viewed), len(viewed)),
            "steps": await _steps(session, "request_step_viewed", "request_step_completed", since, until),
            "abandonedByStep": [{"step": k, "visits": v} for k, v in sorted(abandoned.items(), key=lambda kv: (-kv[1], kv[0]))],
            "requestsSent": sent,
            "proposals": {"started": len(started), "submitted": len(submitted & started),
                          "completionRatePct": pct(len(submitted & started), len(started))}}


async def search_micro_conversions(session, since, until) -> dict:
    """What people do after searching: filters, specializations, quick views, comparisons, opened services, verification
    details and the enterprise call to action, per 100 searches (searches come from the search domain's own events)."""
    searches = await session.scalar(in_window(select(func.count()).where(EventFact.event_type == E.SEARCH_PERFORMED), since, until)) or 0
    counts = {client_name(kind): (n, v) for kind, n, v in (await session.execute(in_window(
        select(EventFact.event_type, func.count(), func.count(func.distinct(EventFact.aggregate_id)))
        .where(EventFact.event_type.in_([client_type(n) for n in SEARCH_MICRO])).group_by(EventFact.event_type), since, until))).all()}

    async def top(name: str, prop: str) -> list[dict]:
        value = EventFact.payload[prop].astext
        rows = await session.execute(in_window(select(value, func.count()).where(EventFact.event_type == client_type(name), value.isnot(None))
                                               .group_by(value).order_by(func.count().desc(), value).limit(10), since, until))
        return [{"value": v, "count": n} for v, n in rows]

    return {"window": {"from": since, "to": until}, "searches": searches,
            "actions": [{"event": name, "count": counts.get(name, (0, 0))[0], "visits": counts.get(name, (0, 0))[1],
                         "per100Searches": round(100 * counts.get(name, (0, 0))[0] / searches, 1) if searches else None}
                        for name in SEARCH_MICRO],
            "topFilters": await top("filter_applied", "filter"), "topSpecializations": await top("specialization_selected", "specialization")}
