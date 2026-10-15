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
        add("WARNING", "TIER_C_ALLOWED", "Tier C (unverified) is allowed, but the platform never lets Tier C professionals be engaged.")
    if settings.get("minTrustTier") == "A" and "credentials" not in settings.get("requiredDimensions", []):
        add("INFO", "TIER_A_IMPLIES_CREDENTIALS", "Tier A already means credentials are validated; listing them too changes nothing.")
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
