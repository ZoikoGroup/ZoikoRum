"""Policy builder checks, templates, the policy dashboard, live policy state on an engagement, emergency exceptions,
business-unit merge and the cost-centre quarterly budget."""

from __future__ import annotations

from datetime import timedelta

from test_automatic_disputes import policy_contract
from test_proposal import P, R, buyer_org, proposal_body, request_body, tier_b
from zoikorum.shared import clock

PROFILES = "/v1/policy/profiles"


async def test_checks_block_activation_and_templates_are_filled(client, make_user, drain, sf):
    from sqlalchemy import text

    buyer, org = await buyer_org(client, make_user, drain, "pol-buyer")
    await buyer.step_up()
    async with sf() as s, s.begin():  # nobody holds the Legal Reviewer role
        await s.execute(text("UPDATE buyer.members SET roles = array_remove(roles, 'LEGAL_REVIEWER') WHERE organization_id = :o"), {"o": org["id"]})
    rule = {"id": "legal", "appliesTo": ["PROPOSAL_ACCEPT"], "condition": {"field": "engagement.valueMinor", "op": "GT", "value": 1},
            "decision": "REQUIRE_APPROVAL", "reasonCode": "LEGAL", "message": "Legal approves engagements.",
            "approval": {"mode": "SINGLE", "steps": [{"role": "LEGAL_REVIEWER", "count": 1}]}}
    twin = {**rule, "id": "legal-2", "decision": "REQUIRE_EXCEPTION"}
    twin.pop("approval")
    p = (await client.post(PROFILES, headers=buyer.idem(), json={"orgId": org["id"], "name": "Legal policy", "settings": {"allowedCurrencies": ["USD"]},
                                                                 "rules": [rule, twin]})).json()
    checks = (await client.get(f"{PROFILES}/{p['id']}/checks", headers=buyer.h)).json()
    assert {c["code"] for c in checks["checks"]} >= {"NO_APPROVER", "OVERLAPPING_RULES"}
    assert checks["appliesTo"] == ["The whole organisation"]
    r = await client.post(f"{PROFILES}/{p['id']}/activate", headers=buyer.idem())
    assert r.status_code == 409 and r.json()["code"] == "POLICY_CHECKS_FAILED"

    for template, rule in (("CROSS_BORDER", "cross-border-legal-review"), ("GROWTH_ADVISORY", "growth-large-engagement")):
        t = (await client.post(PROFILES, headers=buyer.idem(), json={"orgId": org["id"], "name": f"{template} policy", "template": template})).json()
        version = t["draftVersion"] or t["activeVersion"]
        assert [x["id"] for x in version["rules"]] == [rule]


async def test_dashboard_and_live_policy_state(client, make_user, drain):
    from test_contract import signed_contract

    pro_user, pro, buyer, c = await policy_contract(client, make_user, drain, {"minTrustTier": "B"})
    dash = (await client.get("/v1/policy/dashboard", headers=buyer.h, params={"orgId": c["organizationId"]})).json()
    assert dash["activeProfiles"] == 1 and dash["evaluations"] > 0 and dash["decisions"].get("ALLOW", 0) > 0
    assert (await client.get("/v1/policy/dashboard", headers=pro_user.h, params={"orgId": c["organizationId"]})).status_code == 404

    p2, _, b2, c2 = await signed_contract(client, make_user, drain)
    state = (await client.get(f"/v1/contracts/{c2['id']}/policy-state", headers=b2.h)).json()
    assert [(a["action"], a["decision"]) for a in state["actions"]] == [("ESCROW_FUND", "ALLOW")]
    assert (await client.get(f"/v1/contracts/{c2['id']}/policy-state", headers=p2.h)).status_code == 403


async def test_emergency_exceptions_are_short_and_explained(client, make_user, drain):
    import uuid

    buyer, org = await buyer_org(client, make_user, drain, "emerg-buyer")
    body = {"orgId": org["id"], "subjectType": "Proposal", "subjectId": str(uuid.uuid4()), "action": "PROPOSAL_ACCEPT",
            "justification": "Regulator filing due tomorrow morning.", "emergency": True}
    long = (clock.now() + timedelta(days=5)).isoformat()
    assert (await client.post("/v1/policy/exceptions", headers=buyer.h, json={**body, "expiresAt": long})).json()["code"] == "EMERGENCY_TOO_LONG"
    soon = (clock.now() + timedelta(hours=24)).isoformat()
    assert (await client.post("/v1/policy/exceptions", headers=buyer.h, json={**body, "expiresAt": soon})).json()["code"] == "EMERGENCY_REASON_REQUIRED"


async def test_merging_business_units_moves_cost_centres_and_policies(client, make_user, drain):
    buyer, org = await buyer_org(client, make_user, drain, "merge-buyer")
    await buyer.step_up()
    O = f"/v1/organizations/{org['id']}"
    emea = (await client.post(f"{O}/business-units", headers=buyer.h, json={"name": "EMEA"})).json()
    uk = (await client.post(f"{O}/business-units", headers=buyer.h, json={"name": "UK", "parentId": emea["id"]})).json()
    europe = (await client.post(f"{O}/business-units", headers=buyer.h, json={"name": "Europe"})).json()
    cc = (await client.post(f"{O}/cost-centers", headers=buyer.h, json={"name": "EMEA Finance", "code": "EMEA-FIN", "businessUnitId": emea["id"]})).json()
    p = (await client.post(PROFILES, headers=buyer.idem(), json={"orgId": org["id"], "name": "EMEA policy", "settings": {},
                                                                 "businessUnitIds": [emea["id"]]})).json()
    units = (await client.post(f"{O}/business-units/{emea['id']}/merge", headers=buyer.h, json={"targetId": europe["id"]})).json()
    assert {u["name"] for u in units} == {"UK", "Europe"} and next(u for u in units if u["name"] == "UK")["parentId"] == europe["id"]
    centres = (await client.get(f"{O}/cost-centers", headers=buyer.h)).json()
    assert next(x for x in centres if x["id"] == cc["id"])["businessUnitId"] == europe["id"]
    await drain()
    assert (await client.get(f"{PROFILES}/{p['id']}", headers=buyer.h)).json()["businessUnitIds"] == [europe["id"]]
    assert uk["id"] in {u["id"] for u in units}


async def test_cost_centre_quarterly_budget_needs_an_exception(client, make_user, drain):
    pro_user, pro = await tier_b(client, make_user, drain, "budget-pro")
    buyer, org = await buyer_org(client, make_user, drain, "budget-buyer")
    await buyer.step_up()
    cc = (await client.post(f"/v1/organizations/{org['id']}/cost-centers", headers=buyer.h, json={
        "name": "Tax", "code": "TAX", "quarterlyBudget": {"amountMinor": 1_000_000, "currency": "USD"}})).json()
    req = (await client.post(R, headers=buyer.idem(), json=request_body(org, pro, costCenterId=cc["id"]))).json()[0]
    await drain()
    p = (await client.post(f"{R}/{req['id']}/proposals", headers=pro_user.h, json=proposal_body(total=1_500_000))).json()
    await client.post(f"{P}/{p['id']}/submit", headers=pro_user.idem())
    r = await client.post(f"{P}/{p['id']}/accept", headers=buyer.idem())
    assert r.status_code in (403, 409) and r.json()["code"] == "EXCEPTION_REQUIRED", r.text
    assert "budget" in r.json()["detail"].lower()
