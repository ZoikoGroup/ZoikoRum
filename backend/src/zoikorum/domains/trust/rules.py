"""Deterministic, explainable trust rules (Trust & Safety Charter, Onboarding doc).

Pure functions: no I/O, so every tier decision can be unit-tested and explained.
Tier C: default (Discovery only).
Tier B: identity VERIFIED, restrictions screening CLEAR (baseline eligibility), no engagement suspension.
Tier A: Tier B + credentials VALIDATED for every credential-required specialization + jurisdiction
        ELIGIBLE + insurance VERIFIED when a specialization requires it.
"""

from __future__ import annotations

from dataclasses import dataclass

OPEN = ("PENDING", "IN_REVIEW", "NEEDS_INFO")
TIER_LABEL = {"A": "Fully Verified Professional", "B": "Verified Identity", "C": "Unverified (Discovery Only)"}


@dataclass(frozen=True)
class Check:
    verification_type: str
    status: str
    jurisdiction: str | None = None
    specialization: str | None = None


@dataclass(frozen=True)
class Facts:
    checks: tuple[Check, ...]
    credential_required: frozenset[str]  # specialization slugs that require a credential
    insurance_required: bool  # a specialization requires professional indemnity insurance
    licensed: frozenset[str]
    served: frozenset[str]
    engagement_suspended: bool = False


@dataclass(frozen=True)
class Evaluation:
    tier: str
    score: int
    dimensions: dict[str, str]
    explanation: tuple[str, ...]


def _of(facts: Facts, vtype: str) -> list[Check]:
    return [c for c in facts.checks if c.verification_type == vtype]


def dimensions(f: Facts) -> dict[str, str]:
    identity = _of(f, "IDENTITY")
    identity_dim = ("VERIFIED" if any(c.status == "VERIFIED" for c in identity)
                    else "PENDING" if any(c.status in OPEN for c in identity) else "NONE")

    restrictions = _of(f, "RESTRICTIONS")
    restrictions_dim = ("FLAGGED" if any(c.status == "FAILED" for c in restrictions)
                        else "CLEAR" if any(c.status == "VERIFIED" for c in restrictions) else "UNKNOWN")

    creds = _of(f, "CREDENTIAL")
    validated = {c.specialization for c in creds if c.status == "VERIFIED" and c.specialization}
    if not f.credential_required:
        cred_dim = "NOT_APPLICABLE"
    elif f.credential_required <= validated:
        cred_dim = "VALIDATED"
    elif f.credential_required & validated:
        cred_dim = "PARTIAL"
    elif any(c.status in OPEN for c in creds):
        cred_dim = "PENDING"
    else:
        cred_dim = "NONE"

    # A jurisdiction is eligible when a jurisdiction or credential check verified it for a country the
    # professional is licensed in (or, with no licences claimed, serves).
    relevant = f.licensed or f.served

    def country(c: Check) -> str:
        return (c.jurisdiction or "")[:2].upper()  # "US-CA" -> "US"

    juris = [c for c in f.checks if c.verification_type in ("JURISDICTION", "CREDENTIAL") and c.jurisdiction]
    if any(c.status == "VERIFIED" and country(c) in relevant for c in juris):
        juris_dim = "ELIGIBLE"
    elif any(c.verification_type == "JURISDICTION" and c.status == "FAILED" and country(c) in relevant for c in juris):
        juris_dim = "RESTRICTED"
    else:
        juris_dim = "UNKNOWN"

    insurance = _of(f, "INSURANCE")
    if any(c.status == "VERIFIED" for c in insurance):
        ins_dim = "VERIFIED"
    elif f.insurance_required or any(c.status in OPEN for c in insurance):
        ins_dim = "PENDING"
    else:
        ins_dim = "NOT_REQUIRED"

    return {"identity": identity_dim, "credentials": cred_dim, "jurisdiction": juris_dim,
            "restrictions": restrictions_dim, "insurance": ins_dim}


def evaluate(f: Facts) -> Evaluation:
    d = dimensions(f)
    why: list[str] = []

    tier_b_gaps = []
    if d["identity"] != "VERIFIED":
        tier_b_gaps.append("Identity is not verified yet" if d["identity"] == "NONE" else "Identity verification is in progress")
    if d["restrictions"] == "FLAGGED":
        tier_b_gaps.append("Sanctions and restrictions screening did not clear")
    elif d["restrictions"] != "CLEAR":
        tier_b_gaps.append("Sanctions and restrictions screening has not cleared yet")
    if f.engagement_suspended:
        tier_b_gaps.append("Engagements are suspended by a Trust & Safety action")

    tier_a_gaps = list(tier_b_gaps)
    if d["credentials"] not in ("VALIDATED", "NOT_APPLICABLE"):
        tier_a_gaps.append("Credentials required by your specializations are not all verified")
    if d["jurisdiction"] != "ELIGIBLE":
        tier_a_gaps.append("No licensed jurisdiction has been verified yet")
    if d["insurance"] not in ("VERIFIED", "NOT_REQUIRED"):
        tier_a_gaps.append("Professional indemnity insurance is required for your specialization and is not verified")

    if not tier_a_gaps:
        tier = "A"
        why.append("Identity, credentials, jurisdiction, screening and insurance requirements are all verified.")
    elif not tier_b_gaps:
        tier = "B"
        why.append("Identity is verified and restrictions screening is clear.")
        why.extend(f"For Tier A: {g[0].lower()}{g[1:]}." for g in tier_a_gaps)
    else:
        tier = "C"
        why.append("Profiles start in Tier C (Discovery Only) until identity is verified.")
        why.extend(f"For Tier B: {g[0].lower()}{g[1:]}." for g in tier_b_gaps)

    score, score_why = _score(d)
    return Evaluation(tier=tier, score=score, dimensions=d, explanation=tuple(why + score_why))


def _score(d: dict[str, str]) -> tuple[int, list[str]]:
    """0-100. Verification depth 40 now; engagement history (60) builds as contracts complete."""
    identity_ok = d["identity"] == "VERIFIED"
    parts = [
        (15 if identity_ok else 0),
        (5 if d["restrictions"] == "CLEAR" else 0),
        # "Not applicable" credits only count once identity is verified, so an unverified profile scores nothing.
        (10 if d["credentials"] == "VALIDATED" or (identity_ok and d["credentials"] == "NOT_APPLICABLE")
         else 5 if d["credentials"] == "PARTIAL" else 0),
        (5 if d["jurisdiction"] == "ELIGIBLE" else 0),
        (5 if d["insurance"] == "VERIFIED" or (identity_ok and d["insurance"] == "NOT_REQUIRED") else 0),
    ]
    depth = sum(parts)
    return depth, [
        f"Verification depth: {depth} of 40 points.",
        "Engagement history (completed contracts, on-time delivery, dispute outcomes, responsiveness: 60 points) "
        "builds as you complete engagements on Zoikorum.",
    ]
