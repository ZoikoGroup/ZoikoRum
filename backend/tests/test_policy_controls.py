"""Enterprise policy controls: payment rules (escrow stays mandatory), configurable exception roles, regional contract
variants, the procurement setup flag, live engagement indicators, the policy part of the evidence pack, and firm-level
offerings with the regulated-offering invariant."""

from __future__ import annotations

import uuid
from datetime import timedelta

from sqlalchemy import text

from test_automatic_disputes import policy_contract
from test_proposal import P, R, buyer_org, proposal_body, request_body, tier_b
from zoikorum.domains.policy import service
from zoikorum.domains.policy.facade import Attr, Decision, PolicyAction, PolicyContext
from zoikorum.shared import clock, context

PROFILES = "/v1/policy/profiles"


async def active_profile(client, buyer, org, settings, rules=()):
    await buyer.step_up()
    r = await client.post(PROFILES, headers=buyer.idem(), json={"orgId": org["id"], "name": "Controls", "settings": settings,
                                                                "rules": list(rules)})
    assert r.status_code == 201, r.text
    assert (await client.post(f"{PROFILES}/{r.json()['id']}/activate", headers=buyer.idem())).status_code == 200
    return r.json()


async def test_escrow_stays_mandatory_and_payment_rules_validate(client, make_user, drain):
    buyer, org = await buyer_org(client, make_user, drain, "pay-rules")
    await buyer.step_up()
    r = await client.post(PROFILES, headers=buyer.idem(), json={"orgId": org["id"], "name": "No escrow",
                                                                "settings": {"escrowRequired": False}})
    assert r.status_code == 422
    r = await client.post(PROFILES, headers=buyer.idem(), json={"orgId": org["id"], "name": "Overlap", "settings": {"contractVariants": [
        {"id": "a", "name": "A", "jurisdictions": ["GB"], "governingLaw": "England"},
        {"id": "b", "name": "B", "jurisdictions": ["gb"], "governingLaw": "Scotland"}]}})
    assert r.status_code == 422
    r = await client.post(PROFILES, headers=buyer.idem(), json={"orgId": org["id"], "name": "Rules", "settings": {
        "milestoneMaxSharePercent": 60, "milestoneAcceptanceCriteriaRequired": True, "retainerAutoFundAllowed": False,
        "retainerCycleApproval": True, "retainerCycleApprovalRole": "BUDGET_OWNER", "exceptionApproverRoles": ["LEGAL_REVIEWER"]}})
    assert r.status_code == 201, r.text
    assert r.json()["draftVersion"]["settings"]["escrowRequired"] is True


async def test_milestone_share_blocks_submission(client, make_user, drain):
    pro_user, pro = await tier_b(client, make_user, drain, "share-pro")
    buyer, org = await buyer_org(client, make_user, drain, "share-buyer")
    await active_profile(client, buyer, org, {"milestoneMaxSharePercent": 50})
    req = (await client.post(R, headers=buyer.idem(), json=request_body(org, pro))).json()[0]
    await drain()
    p = (await client.post(f"{R}/{req['id']}/proposals", headers=pro_user.h, json=proposal_body())).json()  # 1.0M of 1.5M
    r = await client.post(f"{P}/{p['id']}/submit", headers=pro_user.idem())
    assert r.status_code == 403 and r.json()["code"] == "POLICY_BLOCKED_MILESTONE_SHARE", r.text
    assert "50%" in r.json()["detail"]


async def test_acceptance_criteria_and_retainer_rules(monkeypatch):
    ctx = PolicyContext(uuid.uuid4(), PolicyAction.PROPOSAL_ACCEPT, "Proposal", uuid.uuid4(), uuid.uuid4(), {})

    async def plan(_session, _ctx):
        return {"milestones": [{"title": "One", "amountMinor": 100, "deliverableKeys": ["a"]},
                               {"title": "Two", "amountMinor": 100, "deliverableKeys": ["b"]}],
                "deliverables": [{"key": "a", "acceptanceCriteria": "Signed off"}, {"key": "b", "acceptanceCriteria": "  "}]}
    monkeypatch.setattr(service, "milestone_plan", plan)
    found, _ = await service.payment_rules(None, ctx, {"milestoneAcceptanceCriteriaRequired": True})
    assert [(d, c) for d, c, *_ in found] == [(Decision.BLOCK, "POLICY_BLOCKED_ACCEPTANCE_CRITERIA")] and "M2" in found[0][2]
    assert (await service.payment_rules(None, ctx, {"milestoneMaxSharePercent": 50}))[0] == []

    fund = PolicyContext(uuid.uuid4(), PolicyAction.ESCROW_FUND, "EscrowAccount", uuid.uuid4(), uuid.uuid4(),
                         {Attr.ENGAGEMENT_TYPE: "RETAINER"})
    by_hand, _ = await service.payment_rules(None, fund, {"retainerAutoFundAllowed": False})
    assert by_hand == []  # a person funding a cycle is fine
    with context.use_context(context.ExecutionContext(correlation_id="t", actor_id="consumer:escrow.auto_fund_retainer_cycle")):
        automatic, _ = await service.payment_rules(None, fund, {"retainerAutoFundAllowed": False})
    assert [c for _, c, *_ in automatic] == ["POLICY_BLOCKED_RETAINER_AUTO_FUNDING"]
    cycle, workflows = await service.payment_rules(None, fund, {"retainerCycleApproval": True, "retainerCycleApprovalRole": "BUDGET_OWNER"})
    assert [(d, c) for d, c, *_ in cycle] == [(Decision.REQUIRE_APPROVAL, "RETAINER_CYCLE_APPROVAL")]
    assert workflows[0]["steps"] == [{"role": "BUDGET_OWNER", "count": 1, "id": "retainer-cycle:0"}]
    project = PolicyContext(uuid.uuid4(), PolicyAction.ESCROW_FUND, "EscrowAccount", uuid.uuid4(), uuid.uuid4(),
                            {Attr.ENGAGEMENT_TYPE: "PROJECT"})
    assert (await service.payment_rules(None, project, {"retainerCycleApproval": True})) == ([], [])


async def test_retainer_cycle_approval_creates_a_request(client, make_user, drain, sf):
    owner = await make_user("retainer-owner")
    await drain()
    await owner.refresh()
    org = (await client.get("/v1/organizations/mine", headers=owner.h)).json()[0]
    await active_profile(client, owner, org, {"retainerCycleApproval": True})
    ctx = PolicyContext(uuid.UUID(org["id"]), PolicyAction.ESCROW_FUND, "EscrowAccount", uuid.uuid4(), owner.id,
                        {Attr.PRO_TIER: "B", Attr.PRO_DIMENSIONS: {"identity": "VERIFIED"}, Attr.AMOUNT_MINOR: 100,
                         Attr.ENGAGEMENT_CURRENCY: "USD", Attr.ENGAGEMENT_TYPE: "RETAINER"})
    async with sf() as session, session.begin():
        decision = await service.evaluate(session, ctx)
    assert decision.decision == Decision.REQUIRE_APPROVAL and decision.approval_request_id
    approvals = (await client.get("/v1/policy/approvals", headers=owner.h, params={"orgId": org["id"]})).json()["items"]
    assert approvals[0]["workflows"][0]["steps"][0]["role"] == "APPROVER"


async def test_exception_roles_are_configurable(client, make_user, drain, sf):
    from zoikorum.domains.buyer import facade as buyer_facade

    owner = await make_user("exc-owner")
    await drain()
    await owner.refresh()
    org = (await client.get("/v1/organizations/mine", headers=owner.h)).json()[0]
    rule = {"id": "big-release", "appliesTo": ["ESCROW_RELEASE"], "condition": {"field": "action.amountMinor", "op": "GT", "value": 0},
            "decision": "REQUIRE_EXCEPTION", "reasonCode": "BIG_RELEASE", "message": "Releases need an exception."}
    await active_profile(client, owner, org, {"exceptionRequestRoles": ["REQUESTER"], "exceptionApproverRoles": ["LEGAL_REVIEWER"]}, [rule])
    subject = uuid.uuid4()
    ctx = PolicyContext(uuid.UUID(org["id"]), PolicyAction.ESCROW_RELEASE, "Milestone", subject, owner.id,
                        {Attr.PRO_TIER: "B", Attr.PRO_DIMENSIONS: {"identity": "VERIFIED"}, Attr.AMOUNT_MINOR: 100,
                         Attr.ENGAGEMENT_CURRENCY: "USD"})
    async with sf() as session, session.begin():
        assert (await service.evaluate(session, ctx)).decision == Decision.REQUIRE_EXCEPTION
        await session.execute(text("UPDATE buyer.members SET roles = array_remove(roles, 'REQUESTER') WHERE identity_id = :i"), {"i": owner.id})
    body = {"orgId": org["id"], "subjectType": "Milestone", "subjectId": str(subject), "action": "ESCROW_RELEASE",
            "justification": "Quarter-end release agreed with finance.", "expiresAt": (clock.now() + timedelta(days=5)).isoformat()}
    r = await client.post("/v1/policy/exceptions", headers=owner.h, json=body)
    assert r.status_code == 403 and r.json()["code"] == "EXCEPTION_REQUEST_ROLE_REQUIRED"
    async with sf() as s, s.begin():
        await s.execute(text("UPDATE buyer.members SET roles = array_append(roles, 'REQUESTER') WHERE identity_id = :i"), {"i": owner.id})
    exc = await client.post("/v1/policy/exceptions", headers=owner.h, json=body)
    assert exc.status_code == 201, exc.text

    decider = await make_user("exc-decider")
    async with sf() as s, s.begin():
        await buyer_facade.ensure_member(s, uuid.UUID(org["id"]), decider.id, decider.email, "Decider", ["EXCEPTION_AUTHORITY"])
    await decider.step_up()
    url = f"/v1/policy/exceptions/{exc.json()['id']}/decide"
    r = await client.post(url, headers=decider.idem(), json={"decision": "GRANT", "reason": "Agreed"})
    assert r.status_code == 403 and "Legal Reviewer" in r.json()["detail"]
    async with sf() as s, s.begin():
        await buyer_facade.ensure_member(s, uuid.UUID(org["id"]), decider.id, decider.email, "Decider", ["LEGAL_REVIEWER"])
    r = await client.post(url, headers=decider.idem(), json={"decision": "GRANT", "reason": "Agreed"})
    assert r.status_code == 200 and r.json()["status"] == "GRANTED", r.text
    async with sf() as session, session.begin():
        assert (await service.evaluate(session, ctx)).decision == Decision.ALLOW  # the configured decider's grant counts


async def test_regional_contract_variant_is_chosen_at_generation(client, make_user, drain):
    pro_user, pro, buyer, c = await policy_contract(client, make_user, drain, {
        "governingLaw": "Base law", "contractVariants": [
            {"id": "home", "name": "Home market", "jurisdictions": ["US"], "governingLaw": "State of New York",
             "clauseTexts": {"CONFIDENTIALITY": "New York confidentiality wording."}},
            {"id": "uk", "name": "United Kingdom", "jurisdictions": ["GB"], "governingLaw": "England and Wales"}]})
    contract = (await client.get(f"/v1/contracts/{c['id']}", headers=buyer.h)).json()
    assert contract["terms"]["governingLaw"] == "State of New York"
    assert contract["terms"]["contractVariant"]["id"] == "home"
    assert contract["terms"]["clauseTexts"]["CONFIDENTIALITY"] == "New York confidentiality wording."


async def test_setup_flag_for_the_first_engagement(client, make_user, drain):
    buyer = await make_user("setup-admin", account_type="ENTERPRISE", organization="Acme Procurement")
    await drain()
    await buyer.refresh()
    org = (await client.get("/v1/organizations/mine", headers=buyer.h)).json()[0]
    s = (await client.get("/v1/policy/setup", headers=buyer.h, params={"orgId": org["id"]})).json()
    assert s["needsPolicySetup"] is (org["orgType"] != "INDIVIDUAL") and s["firstEngagement"] is True
    assert [x["key"] for x in s["steps"]] == ["ORGANISATION", "POLICY", "APPROVERS", "BUDGETS"]
    await active_profile(client, buyer, org, {})
    s = (await client.get("/v1/policy/setup", headers=buyer.h, params={"orgId": org["id"]})).json()
    assert s["needsPolicySetup"] is False and next(x for x in s["steps"] if x["key"] == "POLICY")["done"] is True
    stranger = await make_user("setup-stranger")
    assert (await client.get("/v1/policy/setup", headers=stranger.h, params={"orgId": org["id"]})).status_code == 404


async def test_indicators_evidence_pack_and_activity(client, make_user, drain, sf):
    pro_user, pro, buyer, c = await policy_contract(client, make_user, drain, {"minTrustTier": "B"})
    org_id = c["organizationId"]
    url = "/v1/policy/engagement-indicators"
    item = (await client.get(url, headers=buyer.h, params={"orgId": org_id, "contractIds": [c["id"], str(uuid.uuid4())]})).json()["items"]
    assert len(item) == 1 and item[0]["riskLevel"] == "MEDIUM" and item[0]["exception"]["flag"] is False
    assert item[0]["approvals"] == {"total": 0, "pending": 0, "granted": 0, "denied": 0, "expired": 0, "current": None}

    # A release approval about one of the engagement's milestones.
    rule = {"id": "release", "appliesTo": ["ESCROW_RELEASE"], "condition": {"field": "action.amountMinor", "op": "GT", "value": 0},
            "decision": "REQUIRE_APPROVAL", "reasonCode": "RELEASE", "message": "An approver signs off releases.",
            "approval": {"mode": "SINGLE", "steps": [{"role": "APPROVER", "count": 1}]}}
    await active_profile(client, buyer, {"id": org_id}, {}, [rule])
    mid = uuid.UUID(c["milestones"][0]["id"])
    ctx = PolicyContext(uuid.UUID(org_id), PolicyAction.ESCROW_RELEASE, "Milestone", mid, buyer.id,
                        {Attr.PRO_TIER: "B", Attr.PRO_DIMENSIONS: {"identity": "VERIFIED"}, Attr.AMOUNT_MINOR: 100,
                         Attr.ENGAGEMENT_CURRENCY: "USD"})
    async with sf() as session, session.begin():
        assert (await service.evaluate(session, ctx)).decision == Decision.REQUIRE_APPROVAL
    await drain()
    ind = (await client.get(url, headers=buyer.h, params={"orgId": org_id, "contractIds": c["id"]})).json()["items"][0]
    assert ind["riskLevel"] == "MEDIUM" and ind["approvals"]["pending"] == 1 and "Waiting for approval" in ind["riskReasons"]
    current = ind["approvals"]["current"]
    assert (current["action"], current["stepsDone"], current["stepsRequired"], current["nextRole"]) == ("ESCROW_RELEASE", 0, 1, "APPROVER")
    assert (await client.get(url, headers=pro_user.h, params={"orgId": org_id, "contractIds": c["id"]})).status_code == 404

    pack = (await client.get(f"/v1/contracts/{c['id']}/evidence-pack", headers=buyer.h, params={"format": "json"})).json()["record"]
    assert len(pack["approvalLog"]) == 1 and pack["approvalLog"][0]["status"] == "PENDING"
    assert pack["exceptionHistory"] == []
    assert {e["action"] for e in pack["eligibility"]} >= {"PROPOSAL_ACCEPT"} and pack["eligibility"][0]["professionalTier"] == "B"
    assert any("approval" in a["what"].lower() for a in pack["activity"])
    theirs = (await client.get(f"/v1/contracts/{c['id']}/evidence-pack", headers=pro_user.h, params={"format": "json"})).json()["record"]
    assert "approvalLog" not in theirs and "exceptionHistory" not in theirs and theirs["eligibility"]
    csv = await client.get(f"/v1/contracts/{c['id']}/evidence-pack", headers=buyer.h, params={"format": "csv"})
    assert csv.status_code == 200 and csv.headers["content-type"].startswith("text/csv")
    lines = csv.text.splitlines()
    assert lines[0] == "section,date,item,detail,reference" and any(x.startswith("Approval log,") for x in lines)
    assert any(x.startswith("Eligibility evidence,") for x in lines)
    pdf = await client.get(f"/v1/contracts/{c['id']}/evidence-pack", headers=buyer.h)
    assert pdf.status_code == 200 and pdf.content[:4] == b"%PDF"


# ---- Firm-level offerings -----------------------------------------------------------------------------------------

async def firm_with_member(client, make_user, drain, name):
    from test_firms import firm_admin, token_of
    from test_search import publish

    member, _ = await publish(client, make_user, drain, name, headline="Tax adviser", primary="transfer-pricing")
    admin, firm = await firm_admin(make_user, drain, client)
    inv = (await client.post(f"/v1/firms/{firm['id']}/invitations", headers=admin.h, json={"email": member.email, "roles": ["FIRM_MEMBER"]})).json()
    assert (await client.post("/v1/firms/invitations/accept", headers=member.h, json={"token": token_of(inv)})).status_code == 200
    await drain()
    await member.refresh()
    pros = (await client.get(f"/v1/firms/{firm['id']}/overview", headers=admin.h)).json()["professionals"]
    return admin, firm, member, pros[0]["professionalId"]


async def test_firm_offering_published_and_regulated_invariant(client, make_user, drain, sf, monkeypatch):
    from test_verification import outbox
    from zoikorum.domains.firm import facade as firm_facade
    from zoikorum.domains.firm import service as firm_service

    admin, firm, member, pid = await firm_with_member(client, make_user, drain, "off-member")
    base = f"/v1/firms/{firm['id']}/offerings"
    body = {"title": "Transfer pricing documentation", "summary": "Master and local files.", "specialization": "transfer-pricing",
            "engagementTypes": ["PROJECT"], "pricingModel": "FIXED", "startingPriceMinor": 500_000, "currency": "USD"}
    outsider = await client.post(base, headers=admin.h, json={**body, "deliveredBy": [str(uuid.uuid4())]})
    assert outsider.status_code == 422 and outsider.json()["code"] == "NOT_A_FIRM_MEMBER"
    assert (await client.post(base, headers=member.h, json={**body, "deliveredBy": [pid]})).status_code == 403

    plain = (await client.post(base, headers=admin.h, json={**body, "deliveredBy": [pid]})).json()
    assert plain["status"] == "DRAFT" and plain["regulated"] is False and plain["deliveredBy"][0]["professionalId"] == pid
    published = await client.post(f"{base}/{plain['id']}/publish", headers=admin.h)
    assert published.status_code == 200 and published.json()["status"] == "PUBLISHED", published.text
    assert [e["offeringId"] for e in await outbox(sf, "zoikorum.firm.offering.published.v1")] == [plain["id"]]
    public = (await client.get(f"/v1/firms/{firm['id']}/public")).json()
    assert [o["id"] for o in public["offerings"]] == [plain["id"]]

    regulated = (await client.post(base, headers=admin.h, json={**body, "title": "Regulatory returns",
                                                                 "specialization": "regulatory-reporting", "deliveredBy": [pid]})).json()
    assert regulated["regulated"] is True and regulated["deliveredBy"][0]["licensed"] is False
    blocked = await client.post(f"{base}/{regulated['id']}/publish", headers=admin.h)
    assert blocked.status_code == 403 and blocked.json()["code"] == "REGULATED_OFFERING_NEEDS_LICENSED_MEMBER"
    assert "licensed" in blocked.json()["detail"] and "verified" in blocked.json()["detail"]

    # With a verified firm, a verified representative and a licensed member, the regulated offering publishes.
    async with sf() as s, s.begin():
        await s.execute(text("UPDATE firm.firms SET status = 'VERIFIED' WHERE id = :f"), {"f": firm["id"]})
    real_get_firm = firm_facade.get_firm

    async def with_rep(session, firm_id):
        summary = await real_get_firm(session, firm_id)
        return summary.__class__(**{**summary.__dict__, "has_verified_representative": True})
    monkeypatch.setattr(firm_facade, "get_firm", with_rep)
    monkeypatch.setattr(firm_service, "licensed_member", lambda pro, trust, spec: True)
    ok = await client.post(f"{base}/{regulated['id']}/publish", headers=admin.h)
    assert ok.status_code == 200 and ok.json()["status"] == "PUBLISHED", ok.text

    # The member leaves: nobody delivers the published offerings any more, so they are taken down.
    assert (await client.delete(f"/v1/firms/{firm['id']}/members/{member.id}", headers=admin.h)).status_code == 204
    after = {o["id"]: o for o in (await client.get(base, headers=admin.h)).json()}
    assert after[regulated["id"]]["status"] == "UNPUBLISHED" and "automatically" in after[regulated["id"]]["unpublishedReason"]
    assert after[plain["id"]]["status"] == "UNPUBLISHED"
    assert len(await outbox(sf, "zoikorum.firm.offering.unpublished.v1")) == 2


def test_licensed_member_rule():
    from types import SimpleNamespace as NS

    from zoikorum.domains.firm.service import licensed_member

    pro = NS(status="PUBLISHED", licensed_jurisdictions=("GB",), specializations=("regulatory-reporting",))
    good = NS(tier="A", dimensions={"identity": "VERIFIED", "credentials": "VALIDATED"})
    assert licensed_member(pro, good, "regulatory-reporting")
    assert not licensed_member(pro, NS(tier="B", dimensions=good.dimensions), "regulatory-reporting")
    assert not licensed_member(pro, NS(tier="A", dimensions={"identity": "VERIFIED", "credentials": "PENDING"}), "regulatory-reporting")
    assert not licensed_member(NS(**{**pro.__dict__, "licensed_jurisdictions": ()}), good, "regulatory-reporting")
    assert not licensed_member(pro, good, "audit")
