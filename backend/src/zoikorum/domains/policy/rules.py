"""Deterministic rule conditions and document-defined profile templates."""
from __future__ import annotations

import operator

from zoikorum.domains.policy.facade import PolicyAction

DIMENSION_OK = {
    "identity": {"VERIFIED"},
    "credentials": {"VALIDATED", "NOT_APPLICABLE"},
    "jurisdiction": {"ELIGIBLE"},
    "restrictions": {"CLEAR"},
    "insurance": {"VERIFIED", "NOT_REQUIRED"},
}


def matches(condition: dict, attributes: dict) -> bool:
    if "all" in condition:
        return all(matches(child, attributes) for child in condition["all"])
    if "any" in condition:
        return any(matches(child, attributes) for child in condition["any"])
    field, op = condition["field"], condition["op"]
    found, actual = field in attributes, attributes.get(field)
    expected = condition.get("value")
    if op == "EXISTS":
        return (found and actual is not None) == bool(expected if "value" in condition else True)
    if not found or actual is None:
        return False
    try:
        if op == "IN":
            return actual in expected
        if op == "NOT_IN":
            return actual not in expected
        if op == "CONTAINS":
            return expected in actual
        if op in {"GT", "GTE", "LT", "LTE"}:
            if isinstance(actual, bool) or isinstance(expected, bool):
                return False
            if not isinstance(actual, (int, float)) or not isinstance(expected, (int, float)):
                return False
        return {"EQ": operator.eq, "NEQ": operator.ne, "GT": operator.gt,
                "GTE": operator.ge, "LT": operator.lt, "LTE": operator.le}[op](actual, expected)
    except (TypeError, KeyError):
        return False


def template(name: str | None) -> tuple[dict, list]:
    settings, rules = {}, []
    if name == "REGULATED":
        settings = {"minTrustTier": "A", "requiredDimensions": ["identity", "credentials", "jurisdiction", "restrictions"]}
        rules = [{
            "id": "regulated-release", "appliesTo": [PolicyAction.ESCROW_RELEASE],
            "condition": {"field": "action.amountMinor", "op": "GT", "value": 0},
            "decision": "REQUIRE_APPROVAL", "reasonCode": "REGULATED_RELEASE_APPROVAL",
            "message": "Regulated engagements require approval from finance and a budget owner before release.",
            "approval": {"mode": "PARALLEL", "steps": [{"role": "APPROVER", "count": 1}, {"role": "BUDGET_OWNER", "count": 1}],
                         "timeoutHours": 48, "escalationRole": "ORG_ADMIN"},
        }]
    elif name == "ENTERPRISE_STANDARD":
        rules = [{
            "id": "enterprise-release", "appliesTo": [PolicyAction.ESCROW_RELEASE],
            "condition": {"field": "action.amountMinor", "op": "GT", "value": 0},
            "decision": "REQUIRE_APPROVAL", "reasonCode": "ENTERPRISE_RELEASE_APPROVAL",
            "message": "An approver must authorize release after the buyer accepts the milestone.",
            "approval": {"mode": "SINGLE", "steps": [{"role": "APPROVER", "count": 1}],
                         "timeoutHours": 48, "escalationRole": "ORG_ADMIN"},
        }]
    elif name == "CROSS_BORDER":
        # Engaging across borders: eligibility and screening verified, and Legal reviews each cross-border agreement.
        settings = {"requiredDimensions": ["identity", "jurisdiction", "restrictions"], "minTrustTier": "B"}
        rules = [{
            "id": "cross-border-legal-review", "appliesTo": [PolicyAction.PROPOSAL_ACCEPT, PolicyAction.CONTRACT_SIGN],
            "condition": {"field": "engagement.crossBorder", "op": "EQ", "value": True},
            "decision": "REQUIRE_APPROVAL", "reasonCode": "CROSS_BORDER_LEGAL_REVIEW",
            "message": "A Legal Reviewer approves engagements with a professional in another country (tax, data transfer, local rules).",
            "approval": {"mode": "SINGLE", "steps": [{"role": "LEGAL_REVIEWER", "count": 1}],
                         "timeoutHours": 72, "escalationRole": "ORG_ADMIN"},
        }]
    elif name == "GROWTH_ADVISORY":
        # Lighter control for advisory work: verified identity, and an approver only above a set engagement value.
        settings = {"minTrustTier": "B", "requiredDimensions": ["identity"]}
        rules = [{
            "id": "growth-large-engagement", "appliesTo": [PolicyAction.PROPOSAL_ACCEPT],
            "condition": {"field": "engagement.valueMinor", "op": "GT", "value": 2_500_000},
            "decision": "REQUIRE_APPROVAL", "reasonCode": "GROWTH_LARGE_ENGAGEMENT",
            "message": "Engagements above 25,000 need an approver before they are accepted.",
            "approval": {"mode": "SINGLE", "steps": [{"role": "APPROVER", "count": 1}],
                         "timeoutHours": 48, "escalationRole": "ORG_ADMIN"},
        }]
    return settings, rules
