"""Step 4 - trust tiers: deterministic rules, and recomputation driven by verification and enforcement events."""

from __future__ import annotations

import uuid

from sqlalchemy import text

from zoikorum.domains.trust.rules import Check, Facts, evaluate
from zoikorum.shared.event_catalog import E
from zoikorum.shared.events import record_event

BIO = ("Former Big Four audit manager. I help growing companies set up month-end close, "
       "board reporting and cash forecasting that their investors can rely on.")


def facts(*checks, required=(), regulated=False, licensed=(), served=("US",), suspended=False) -> Facts:
    return Facts(checks=tuple(Check(*c) for c in checks), credential_required=frozenset(required), regulated=regulated,
                 licensed=frozenset(licensed), served=frozenset(served), engagement_suspended=suspended)


# ---- Rules (pure) -----------------------------------------------------------------

def test_new_profiles_are_tier_c_with_reasons():
    r = evaluate(facts())
    assert r.tier == "C" and r.score == 0
    assert r.dimensions == {"identity": "NONE", "credentials": "NOT_APPLICABLE", "jurisdiction": "UNKNOWN",
                            "restrictions": "UNKNOWN", "insurance": "NOT_REQUIRED"}
    assert "For Tier B: identity is not verified yet." in r.explanation


def test_verified_identity_gives_tier_b_and_full_checks_give_tier_a():
    b = evaluate(facts(("IDENTITY", "VERIFIED"), ("RESTRICTIONS", "VERIFIED")))
    assert b.tier == "B" and "For Tier A: no licensed jurisdiction has been verified yet." in b.explanation
    a = evaluate(facts(("IDENTITY", "VERIFIED"), ("RESTRICTIONS", "VERIFIED"), ("JURISDICTION", "VERIFIED", "US")))
    assert a.tier == "A" and a.score == 40


def test_regulated_work_needs_credentials_and_insurance_for_tier_a():
    base = [("IDENTITY", "VERIFIED"), ("RESTRICTIONS", "VERIFIED"), ("CREDENTIAL", "VERIFIED", "US-TX", "tax-compliance-and-filings")]
    r = evaluate(facts(*base, required={"tax-compliance-and-filings", "transfer-pricing"}, regulated=True, licensed={"US"}))
    assert r.tier == "B" and r.dimensions["credentials"] == "PARTIAL" and r.dimensions["insurance"] == "PENDING"
    assert r.dimensions["jurisdiction"] == "ELIGIBLE"  # the verified credential proves the US licence
    r = evaluate(facts(*base, ("INSURANCE", "VERIFIED"), required={"tax-compliance-and-filings"}, regulated=True, licensed={"US"}))
    assert r.tier == "A"


def test_adverse_facts_drop_to_tier_c():
    verified = [("IDENTITY", "VERIFIED"), ("JURISDICTION", "VERIFIED", "US")]
    assert evaluate(facts(*verified, ("RESTRICTIONS", "FAILED"))).tier == "C"
    assert evaluate(facts(*verified, ("RESTRICTIONS", "VERIFIED"), suspended=True)).tier == "C"
    assert evaluate(facts(("IDENTITY", "REVOKED"), ("RESTRICTIONS", "VERIFIED"))).tier == "C"


# ---- Event-driven recomputation ---------------------------------------------------

async def published_pro(client, make_user, drain):
    u = await make_user("pia", account_type="PROFESSIONAL")
    pro = (await client.post("/v1/professionals", headers=u.h, json={})).json()
    await client.post("/v1/auth/confirm-email", json={"token": u.confirm_token})
    await client.patch("/v1/professionals/me", headers=u.h, json={
        "headline": "Fractional CFO", "bio": BIO, "engagementTypes": ["FRACTIONAL"], "deliveryModes": ["REMOTE"],
        "pricingModels": ["CUSTOM"]})
    await client.put("/v1/professionals/me/specializations", headers=u.h, json={"primary": "fractional-cfo"})
    await client.put("/v1/professionals/me/jurisdictions", headers=u.h, json={"served": ["US"]})
    await client.post("/v1/professionals/me/publish", headers=u.h, json={"attestAccurate": True})
    await drain()
    return u, pro


async def verify(client, make_user, u, pro, vtype, **extra):
    case = (await client.post("/v1/verification/cases", headers=u.h, json={
        "verificationType": vtype, "subjectType": "PROFESSIONAL", "subjectId": pro["id"], **extra})).json()
    o = await make_user(f"officer-{vtype.lower()}", platform_roles=("COMPLIANCE_OFFICER",))
    await o.step_up()
    r = await client.post(f"/v1/verification/cases/{case['id']}/decision", headers=o.h, json={"decision": "VERIFIED", "reasonCode": "OK"})
    assert r.status_code == 200, r.text
    return case, o


async def tier_changes(sf):
    async with sf() as s:
        rows = await s.execute(text("SELECT envelope FROM platform.outbox WHERE event_type = :t ORDER BY seq"),
                               {"t": "zoikorum.trust.profile.tier_changed.v1"})
        return [(r[0]["payload"]["fromTier"], r[0]["payload"]["toTier"]) for r in rows]


async def test_verification_moves_a_professional_from_c_to_b_to_a(client, make_user, drain, sf):
    u, pro = await published_pro(client, make_user, drain)
    trust_url = f"/v1/trust/professionals/{pro['id']}"
    t = (await client.get(trust_url)).json()  # public, no sign-in
    assert t["tier"] == "C" and t["tierLabel"] == "Unverified (Discovery Only)" and t["dimensions"]["restrictions"] == "CLEAR"

    await verify(client, make_user, u, pro, "IDENTITY")
    await drain()
    assert (await client.get(trust_url)).json()["tier"] == "B"

    await verify(client, make_user, u, pro, "JURISDICTION", jurisdiction="US")
    await drain()
    t = (await client.get(trust_url)).json()
    assert t["tier"] == "A" and t["tierLabel"] == "Fully Verified Professional" and t["score"] == 40
    assert await tier_changes(sf) == [("C", "B"), ("B", "A")]

    public = (await client.get(f"/v1/professionals/{pro['id']}")).json()
    assert public["trust"]["tier"] == "A" and public["trust"]["dimensions"]["identity"] == "VERIFIED"

    history = (await client.get(f"{trust_url}/history", headers=u.h)).json()
    assert [(h["fromTier"], h["toTier"]) for h in history["tierChanges"]] == [("B", "A"), ("C", "B")]
    stranger = await make_user("sam")
    assert (await client.get(f"{trust_url}/history", headers=stranger.h)).status_code == 404


async def test_revoked_identity_drops_the_tier_immediately(client, make_user, drain, sf):
    u, pro = await published_pro(client, make_user, drain)
    case, o = await verify(client, make_user, u, pro, "IDENTITY")
    await drain()
    await client.post(f"/v1/verification/cases/{case['id']}/revoke", headers=o.h,
                      json={"reasonCode": "FRAUD_SUSPECTED", "publicReason": "Your identity document could not be confirmed."})
    await drain()
    t = (await client.get(f"/v1/trust/professionals/{pro['id']}")).json()
    assert t["tier"] == "C" and t["dimensions"]["identity"] == "NONE"
    assert await tier_changes(sf) == [("C", "B"), ("B", "C")]


async def test_enforcement_suspends_and_risk_flags_never_change_the_tier(client, make_user, drain, sf):
    u, pro = await published_pro(client, make_user, drain)
    await verify(client, make_user, u, pro, "IDENTITY")
    await drain()
    pid = uuid.UUID(pro["id"])

    async def emit(event_type, **payload):
        async with sf() as s, s.begin():
            record_event(s, event_type, aggregate_type="Test", aggregate_id=uuid.uuid4(), payload=payload)
        await drain()

    await emit(E.RISK_FLAG_RAISED, flagId=str(uuid.uuid4()), subjectType="PROFESSIONAL", subjectId=pid,
               riskScore=80, reasonCodes=["RAPID_DISPUTES"], source="ai")
    assert (await client.get(f"/v1/trust/professionals/{pid}")).json()["tier"] == "B"
    assert (await client.get(f"/v1/trust/professionals/{pid}/history", headers=u.h)).json()["flags"] == ["RAPID_DISPUTES"]

    notice = {"whatHappened": "-", "why": "-", "whatChanged": "-", "whatYouCanDo": "-", "whatHappensNext": "-", "howToGetHelp": "-"}
    await emit(E.ENFORCEMENT_ACTION_APPLIED, caseId=str(uuid.uuid4()), subjectType="PROFESSIONAL", subjectId=pid,
               action="ENGAGEMENT_SUSPENSION", level=3, reasonCode="POLICY_BREACH", notice=notice, recipientIdentityIds=[])
    assert (await client.get(f"/v1/trust/professionals/{pid}")).json()["tier"] == "C"
    await emit(E.ENFORCEMENT_ACTION_REVERSED, caseId=str(uuid.uuid4()), subjectType="PROFESSIONAL", subjectId=pid,
               action="ENGAGEMENT_SUSPENSION", level=3, reasonCode="APPEAL_UPHELD", notice=notice, recipientIdentityIds=[])
    assert (await client.get(f"/v1/trust/professionals/{pid}")).json()["tier"] == "B"


async def test_unpublished_profiles_hide_their_trust(client, make_user, drain):
    u = await make_user("pia", account_type="PROFESSIONAL")
    pro = (await client.post("/v1/professionals", headers=u.h, json={})).json()
    await drain()
    assert (await client.get(f"/v1/trust/professionals/{pro['id']}")).status_code == 404
    assert (await client.get(f"/v1/trust/professionals/{pro['id']}", headers=u.h)).json()["tier"] == "C"
