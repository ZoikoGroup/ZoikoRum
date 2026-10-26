"""Policy builder checks and the policy dashboard (Enterprise policy profiles: conflict checks, review-and-activate,
dashboard and KPIs)."""

from __future__ import annotations

import uuid
from collections import Counter
from datetime import timedelta
from statistics import median

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from zoikorum.domains.buyer import facade as buyer
from zoikorum.domains.policy.facade import Attr, PolicyAction
from zoikorum.domains.policy.models import ApprovalRequest, ExceptionRequest, PolicyEvaluation, PolicyProfile
from zoikorum.shared import clock

from zoikorum.domains.policy.schemas import FIELDS as KNOWN_FIELDS  # noqa: E402  (saving a rule already refuses others)
KNOWN_PREFIXES = ("contract.", "milestone.", "funding.", "proposal.", "policy.", "costCenter.")


def _fields(condition: dict) -> list[str]:
    if "all" in condition or "any" in condition:
        return [f for child in condition.get("all", condition.get("any", [])) for f in _fields(child)]
    return [condition.get("field", "")]


def checks(settings: dict, rules: list[dict], roles_held: set[str] | None = None) -> list[dict]:
    """Problems an administrator should see before activating. ERROR blocks activation; WARNING and INFO do not."""
    out: list[dict] = []

    def add(severity: str, code: str, message: str, rule: str | None = None):
        out.append({"severity": severity, "code": code, "message": message, "rule": rule})

    if settings.get("allowedJurisdictions") == []:
        add("ERROR", "NO_JURISDICTION_ALLOWED", "No jurisdiction is allowed, so no professional could ever be engaged.")
    if settings.get("allowedCurrencies") == []:
        add("ERROR", "NO_CURRENCY_ALLOWED", "No currency is allowed, so no engagement could be priced.")
    if settings.get("escrowRequired") is False:
        add("WARNING", "ESCROW_ALWAYS_ON", "Escrow is always used on Zoikorum; turning it off here has no effect.")
    accept, auto = settings.get("acceptanceWindowDays"), settings.get("autoAcceptAfterDays")
    if accept and auto and auto < accept:
        add("WARNING", "AUTO_ACCEPT_BEFORE_REVIEW",
            f"Work is accepted automatically after {auto} days, before the {accept}-day review window ends.")
    if settings.get("minTrustTier") == "C":
        add("WARNING", "TIER_C_ALLOWED", "Red (not verified yet) is allowed, but the platform never lets Red professionals be engaged.")
    if settings.get("minTrustTier") == "A" and "credentials" not in settings.get("requiredDimensions", []):
        add("INFO", "TIER_A_IMPLIES_CREDENTIALS", "Green (fully verified) already means credentials are validated; listing them too changes nothing.")
    mediation, legal = settings.get("disputeMediationAboveMinor"), settings.get("disputeLegalReviewAboveMinor")
    if mediation is not None and legal is not None and legal > mediation:
        add("INFO", "LEGAL_REVIEW_ABOVE_MEDIATION",
            "Legal review starts above the mediation threshold, so it only applies to settlements a mediator already handles.")

    seen: dict[tuple, str] = {}
    for r in rules:
        unknown = [f for f in _fields(r.get("condition", {})) if f not in KNOWN_FIELDS and not f.startswith(KNOWN_PREFIXES)]
        if unknown:
            add("ERROR", "UNKNOWN_FIELD", f"Rule {r['id']} uses {', '.join(unknown)}, which is never set, so it never applies.", r["id"])
        for action in r.get("appliesTo", []):
            key = (action, repr(sorted(r.get("condition", {}).items(), key=str)))
            if key in seen and seen[key] != r["id"]:
                add("WARNING", "OVERLAPPING_RULES", f"Rules {seen[key]} and {r['id']} have the same condition for {action}; "
                    "the stricter decision wins and the other never shows.", r["id"])
            seen.setdefault(key, r["id"])
        if r.get("decision") == "BLOCK" and r.get("condition", {}).get("op") == "GT" and r.get("condition", {}).get("value") == 0:
            add("WARNING", "BLOCKS_EVERYTHING", f"Rule {r['id']} blocks every {', '.join(r.get('appliesTo', []))} with an amount.", r["id"])
        if roles_held is not None and r.get("decision") == "REQUIRE_APPROVAL":
            for step in (r.get("approval") or {}).get("steps", []):
                if step.get("role") not in roles_held:
                    add("ERROR", "NO_APPROVER", f"Rule {r['id']} needs a {step.get('role', '').replace('_', ' ').title()}, "
                        "but nobody in the organisation has that role; approvals would wait until they time out.", r["id"])
    return out


async def roles_held(session: AsyncSession, org_id: uuid.UUID) -> set[str]:
    return set().union(*[set(m) for m in (await buyer.member_roles_by_identity(session, org_id)).values()] or [set()])


async def dashboard(session: AsyncSession, org_id: uuid.UUID, days: int = 30) -> dict:
    """Usage, exceptions, approval speed and spend held back by policy, for the organisation's administrators."""
    since = clock.now() - timedelta(days=days)
    evaluations = (await session.scalars(select(PolicyEvaluation).where(
        PolicyEvaluation.organization_id == org_id, PolicyEvaluation.dry_run.is_(False), PolicyEvaluation.created_at >= since))).all()
    decisions = Counter(e.decision for e in evaluations)
    by_action = Counter(e.action for e in evaluations)
    blocked_spend: dict[str, int] = {}
    for e in evaluations:
        if e.decision == "BLOCK" and e.action in (PolicyAction.PROPOSAL_ACCEPT, PolicyAction.ESCROW_FUND, PolicyAction.CHANGE_ORDER_APPROVE):
            ccy = e.attributes.get(Attr.ENGAGEMENT_CURRENCY)
            if ccy:
                blocked_spend[ccy] = blocked_spend.get(ccy, 0) + int(e.attributes.get(Attr.AMOUNT_MINOR) or 0)
    reasons = Counter(r.get("code") for e in evaluations if e.decision != "ALLOW" for r in e.reasons)
    approvals = (await session.scalars(select(ApprovalRequest).where(
        ApprovalRequest.organization_id == org_id, ApprovalRequest.created_at >= since))).all()
    decided = [(a.updated_at - a.created_at).total_seconds() / 3600 for a in approvals if a.status in ("GRANTED", "DENIED")]
    exceptions = (await session.scalars(select(ExceptionRequest).where(
        ExceptionRequest.organization_id == org_id, ExceptionRequest.created_at >= since))).all()
    profiles = (await session.scalars(select(PolicyProfile).where(PolicyProfile.organization_id == org_id))).all()
    governed = len(evaluations)
    return {
        "organizationId": org_id, "days": days,
        "activeProfiles": sum(1 for p in profiles if p.active_version_id), "draftProfiles": sum(1 for p in profiles if p.draft_version_id),
        "evaluations": governed, "decisions": dict(decisions), "byAction": dict(by_action),
        "interventionRate": round(100 * (governed - decisions.get("ALLOW", 0)) / governed, 1) if governed else None,
        "approvals": {"requested": len(approvals), "pending": sum(1 for a in approvals if a.status == "PENDING"),
                      "granted": sum(1 for a in approvals if a.status == "GRANTED"), "denied": sum(1 for a in approvals if a.status == "DENIED"),
                      "expired": sum(1 for a in approvals if a.status == "EXPIRED"),
                      "medianHoursToDecide": round(median(decided), 1) if decided else None},
        "exceptions": {"requested": len(exceptions), "granted": sum(1 for x in exceptions if x.status == "GRANTED"),
                       "denied": sum(1 for x in exceptions if x.status == "DENIED"),
                       "emergency": sum(1 for x in exceptions if (x.justification or "").startswith("[EMERGENCY]")),
                       "rate": round(100 * len(exceptions) / governed, 1) if governed else None},
        "spendHeldBack": [{"currency": c, "amountMinor": v} for c, v in sorted(blocked_spend.items())],
        "topReasons": [{"code": c, "count": n} for c, n in reasons.most_common(5)],
    }


# ---- Approval bottlenecks and the per-profile breakdown (Enterprise policy profiles: dashboard and KPIs) ---------------

def _hours(delta) -> float:
    return delta.total_seconds() / 3600


def step_rows(requests, votes_by_request: dict) -> list[dict]:
    """How long each approval step waited for its approvers: from when the step could be acted on (the request, or for a
    sequential route the previous step) to the vote that completed it. Steps still waiting count as pending, with the
    age of the oldest; steps never completed because the request expired count as expired."""
    now, agg = clock.now(), {}
    for r in requests:
        votes = sorted(votes_by_request.get(r.id, []), key=lambda v: v.created_at)
        for workflow in r.workflows or []:
            ready = r.created_at
            for i, step in enumerate(workflow.get("steps", [])):
                row = agg.setdefault((i + 1, step.get("role", "")), {"waits": [], "pending": 0, "oldest": 0.0, "expired": 0})
                start = ready if workflow.get("mode") == "SEQUENTIAL" else r.created_at
                needed = step.get("count", 1)
                grants = [v for v in votes if v.step_id == step.get("id") and v.decision == "GRANT"]
                done = grants[needed - 1].created_at if len(grants) >= needed else None
                if done:
                    row["waits"].append(_hours(done - start))
                elif r.status == "PENDING":
                    row["pending"] += 1
                    row["oldest"] = max(row["oldest"], _hours(now - start))
                elif r.status == "EXPIRED":
                    row["expired"] += 1
                if workflow.get("mode") == "SEQUENTIAL":
                    if done is None:
                        break
                    ready = done
    return [{"step": pos, "role": role, "completed": len(a["waits"]),
             "medianHoursWait": round(median(a["waits"]), 1) if a["waits"] else None,
             "pending": a["pending"], "oldestPendingHours": round(a["oldest"], 1) if a["pending"] else None, "expired": a["expired"]}
            for (pos, role), a in sorted(agg.items())]


def bottleneck(rows: list[dict]) -> dict | None:
    """The step that holds approvals up most: the longest median wait, or failing that the oldest pending one."""
    timed = [r for r in rows if r["medianHoursWait"] is not None or r["oldestPendingHours"] is not None]
    if not timed:
        return None
    worst = max(timed, key=lambda r: (r["medianHoursWait"] or 0, r["oldestPendingHours"] or 0))
    return {"step": worst["step"], "role": worst["role"], "medianHoursWait": worst["medianHoursWait"], "pending": worst["pending"]}


async def _votes(session: AsyncSession, requests) -> dict:
    from zoikorum.domains.policy.models import ApprovalVote

    out: dict = {}
    if requests:
        for v in (await session.scalars(select(ApprovalVote).where(ApprovalVote.request_id.in_([r.id for r in requests])))).all():
            out.setdefault(v.request_id, []).append(v)
    return out


async def step_waits(session: AsyncSession, since, until, org_id: uuid.UUID | None = None) -> dict:
    """Approval waits per step for requests raised in the period (all organisations unless one is given)."""
    q = select(ApprovalRequest).where(ApprovalRequest.created_at >= since, ApprovalRequest.created_at < until)
    if org_id:
        q = q.where(ApprovalRequest.organization_id == org_id)
    requests = (await session.scalars(q)).all()
    rows = step_rows(requests, await _votes(session, requests))
    return {"requests": len(requests), "pendingNow": sum(1 for r in requests if r.status == "PENDING"), "steps": rows,
            "bottleneck": bottleneck(rows)}


def _money(totals: dict[str, int]) -> list[dict]:
    return [{"currency": c, "amountMinor": v} for c, v in sorted(totals.items())]


async def by_profile(session: AsyncSession, org_id: uuid.UUID, days: int = 30) -> dict:
    """Per policy profile: what it governed (evaluations, engagements accepted under it and their value per currency),
    how often it intervened, exceptions asked for, approvals and the step that holds approvals up. Money is per currency."""
    from zoikorum.domains.policy.models import PolicyVersion

    since = clock.now() - timedelta(days=days)
    profiles = (await session.scalars(select(PolicyProfile).where(PolicyProfile.organization_id == org_id)
                                      .order_by(PolicyProfile.name, PolicyProfile.id))).all()
    ids = [p.id for p in profiles]
    versions: dict = {}
    numbers: dict = {}
    if ids:
        for vid, pid, number in (await session.execute(select(PolicyVersion.id, PolicyVersion.profile_id, PolicyVersion.number)
                                                       .where(PolicyVersion.profile_id.in_(ids)))).all():
            versions[vid], numbers[vid] = pid, number
    evaluations = (await session.scalars(select(PolicyEvaluation).where(
        PolicyEvaluation.organization_id == org_id, PolicyEvaluation.dry_run.is_(False), PolicyEvaluation.created_at >= since)
        .order_by(PolicyEvaluation.created_at))).all()
    approvals = (await session.scalars(select(ApprovalRequest).where(
        ApprovalRequest.organization_id == org_id, ApprovalRequest.created_at >= since))).all()
    votes = await _votes(session, approvals)
    exceptions = (await session.scalars(select(ExceptionRequest).where(
        ExceptionRequest.organization_id == org_id, ExceptionRequest.created_at >= since))).all()

    out = []
    for p in profiles:
        evs = [e for e in evaluations if (e.policy_profile_id or versions.get(e.policy_version_id)) == p.id]
        decisions = Counter(e.decision for e in evs)
        accepted: dict = {}  # the latest decision on each proposal acceptance
        for e in evs:
            if e.action == PolicyAction.PROPOSAL_ACCEPT:
                accepted[e.subject_id] = e
        exposure: dict[str, int] = {}
        held: dict[str, int] = {}
        for e in accepted.values():
            ccy = e.attributes.get(Attr.ENGAGEMENT_CURRENCY)
            value = int(e.attributes.get(Attr.ENGAGEMENT_VALUE_MINOR) or e.attributes.get(Attr.AMOUNT_MINOR) or 0)
            if ccy:
                bucket = held if e.decision == "BLOCK" else exposure
                bucket[ccy] = bucket.get(ccy, 0) + value
        mine = [a for a in approvals if versions.get(a.policy_version_id) == p.id]
        steps = step_rows(mine, votes)
        xs = [x for x in exceptions if versions.get(x.policy_version_id) == p.id]
        out.append({
            "profileId": p.id, "name": p.name, "riskLevel": p.risk_level,
            "status": "ACTIVE" if p.active_version_id else ("DRAFT" if p.draft_version_id else "INACTIVE"),
            "activeVersion": numbers.get(p.active_version_id), "evaluations": len(evs), "decisions": dict(decisions),
            "interventionRatePct": round(100 * (len(evs) - decisions.get("ALLOW", 0)) / len(evs), 1) if evs else None,
            "engagements": sum(1 for e in accepted.values() if e.decision != "BLOCK"),
            "spendExposure": _money(exposure), "spendHeldBack": _money(held),
            "exceptions": {"requested": len(xs), "granted": sum(1 for x in xs if x.status == "GRANTED"),
                           "denied": sum(1 for x in xs if x.status == "DENIED"), "pending": sum(1 for x in xs if x.status == "PENDING")},
            "approvals": {"requested": len(mine), "pending": sum(1 for a in mine if a.status == "PENDING"),
                          "granted": sum(1 for a in mine if a.status == "GRANTED"), "denied": sum(1 for a in mine if a.status == "DENIED"),
                          "expired": sum(1 for a in mine if a.status == "EXPIRED")},
            "approvalSteps": steps, "bottleneck": bottleneck(steps),
        })
    return {"organizationId": org_id, "days": days, "profiles": out}


CSV_FIELDS = ["profile", "status", "riskLevel", "activeVersion", "evaluations", "interventionRatePct", "engagements",
              "spendExposureMinor", "spendHeldBackMinor", "approvalsRequested", "approvalsPending", "exceptionsRequested",
              "exceptionsGranted", "bottleneckStep", "bottleneckRole", "bottleneckMedianHours"]


def csv_rows(report: dict) -> list[dict]:
    """One row per profile. Money stays per currency ("USD:150000; EUR:2000", minor units), never added together."""
    def money(items):
        return "; ".join(f"{m['currency']}:{m['amountMinor']}" for m in items)
    return [{"profile": p["name"], "status": p["status"], "riskLevel": p["riskLevel"], "activeVersion": p["activeVersion"],
             "evaluations": p["evaluations"], "interventionRatePct": p["interventionRatePct"], "engagements": p["engagements"],
             "spendExposureMinor": money(p["spendExposure"]), "spendHeldBackMinor": money(p["spendHeldBack"]),
             "approvalsRequested": p["approvals"]["requested"], "approvalsPending": p["approvals"]["pending"],
             "exceptionsRequested": p["exceptions"]["requested"], "exceptionsGranted": p["exceptions"]["granted"],
             "bottleneckStep": (p["bottleneck"] or {}).get("step"), "bottleneckRole": (p["bottleneck"] or {}).get("role"),
             "bottleneckMedianHours": (p["bottleneck"] or {}).get("medianHoursWait")} for p in report["profiles"]]
