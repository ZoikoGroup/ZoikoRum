"""Regulated work and the checks around it: Tier A before regulated work, background checks only with consent,
beneficial ownership for firms, and the "can handle regulated data" attestation."""

from __future__ import annotations

from test_proposal import P, R, buyer_org, proposal_body, request_body, tier_b


async def test_regulated_work_needs_tier_a(client, make_user, drain):
    pro_user, pro = await tier_b(client, make_user, drain, "reg-pro")
    buyer, org = await buyer_org(client, make_user, drain, "reg-buyer")
    req = (await client.post(R, headers=buyer.idem(), json=request_body(org, pro, specialization="regulatory-reporting"))).json()[0]
    await drain()
    p = (await client.post(f"{R}/{req['id']}/proposals", headers=pro_user.h, json=proposal_body())).json()
    r = await client.post(f"{P}/{p['id']}/submit", headers=pro_user.idem())
    assert r.status_code == 403 and r.json()["code"] == "POLICY_BLOCKED_MINIMUM_TRUST_TIER" and "regulated" in r.json()["detail"]
    await drain()
    titles = [n["title"] for n in (await client.get("/v1/notifications", headers=pro_user.h)).json()["items"]]
    assert "Verify to work with this buyer" in titles  # the professional is told what to verify


async def test_background_check_needs_consent_and_firm_declares_owners(client, make_user, drain):
    pro_user, pro = await tier_b(client, make_user, drain, "bg-pro")
    body = {"verificationType": "BACKGROUND", "subjectType": "PROFESSIONAL", "subjectId": pro["id"]}
    assert (await client.post("/v1/verification/cases", headers=pro_user.h, json=body)).json()["code"] == "CONSENT_REQUIRED"
    r = await client.post("/v1/verification/cases", headers=pro_user.h, json={**body, "consent": True})
    assert r.status_code == 201, r.text

    admin = await make_user("owner-admin", account_type="FIRM", organization="Owner Advisory LLP")
    await drain()
    firm = (await client.get("/v1/firms/mine", headers=admin.h)).json()[0]
    own = {"verificationType": "BENEFICIAL_OWNERSHIP", "subjectType": "FIRM", "subjectId": firm["id"]}
    assert (await client.post("/v1/verification/cases", headers=admin.h, json=own)).json()["code"] == "OWNERS_REQUIRED"
    over = [{"name": "A One", "country": "GB", "percent": 60}, {"name": "B Two", "country": "GB", "percent": 50}]
    assert (await client.post("/v1/verification/cases", headers=admin.h, json={**own, "owners": over})).json()["code"] == "OWNERSHIP_OVER_100"
    small = [{"name": "A One", "country": "GB", "percent": 10}]
    assert (await client.post("/v1/verification/cases", headers=admin.h, json={**own, "owners": small})).json()["code"] == "NO_BENEFICIAL_OWNER"
    ok = await client.post("/v1/verification/cases", headers=admin.h, json={**own, "owners": [{"name": "A One", "country": "GB", "percent": 75}]})
    assert ok.status_code == 201, ok.text
    assert (await client.post("/v1/verification/cases", headers=pro_user.h, json={
        "verificationType": "BENEFICIAL_OWNERSHIP", "subjectType": "PROFESSIONAL", "subjectId": pro["id"]})).json()["code"] == "WRONG_SUBJECT_TYPE"


async def test_regulated_data_attestation_shows_on_the_profile(client, make_user, drain):
    pro_user, pro = await tier_b(client, make_user, drain, "data-pro")
    me = (await client.get("/v1/professionals/me", headers=pro_user.h)).json()
    assert me["handlesRegulatedData"] is False
    r = await client.patch("/v1/professionals/me", headers=pro_user.h, json={"handlesRegulatedData": True})
    assert r.status_code == 200 and r.json()["handlesRegulatedData"] is True
    assert (await client.get(f"/v1/professionals/{pro['id']}")).json()["handlesRegulatedData"] is True
