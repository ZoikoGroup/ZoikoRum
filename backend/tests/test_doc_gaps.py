"""Doc-audit gap fixes for Steps 0-9: jurisdiction conflicts, request scope builder, saved searches, profile history,
expired credentials stay visible."""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import text

from test_contract import signed_contract
from test_proposal import P, R, buyer_org, proposal_body, request_body, tier_b
from test_search import publish
from zoikorum.shared import clock


async def test_jurisdiction_conflict_is_flagged_and_blocks_agreement(client, make_user, drain):
    pro_user, pro = await tier_b(client, make_user, drain, "ann")  # serves US only
    buyer = await make_user("gus", country="GB")
    await drain()
    await buyer.refresh()
    org = (await client.get("/v1/organizations/mine", headers=buyer.h)).json()[0]
    req = (await client.post(R, headers=buyer.idem(), json=request_body(org, pro))).json()[0]
    assert req["jurisdictionConflict"] is True  # surfaced early, before any agreement
    p = (await client.post(f"{R}/{req['id']}/proposals", headers=pro_user.h, json=proposal_body())).json()
    await client.post(f"{P}/{p['id']}/submit", headers=pro_user.idem())
    r = await client.post(f"{P}/{p['id']}/accept", headers=buyer.idem())
    assert r.status_code == 403 and r.json()["code"] == "JURISDICTION_CONFLICT"


async def test_request_scope_builder_fields_and_nda(client, make_user, drain):
    pro_user, pro = await tier_b(client, make_user, drain, "ann")
    buyer, org = await buyer_org(client, make_user, drain)
    body = request_body(org, pro, ndaRequired=True, deliverables=["Master file", " Local file ", "Master file"],
                        dependencies=["BUYER_DATA"], pricingPreferences=["FIXED", "OPEN"], paymentCadence="MILESTONE")
    req = (await client.post(R, headers=buyer.idem(), json=body)).json()[0]
    assert req["deliverables"] == ["Master file", "Local file"] and req["paymentCadence"] == "MILESTONE" and not req["jurisdictionConflict"]
    seen = (await client.get(f"{R}/{req['id']}", headers=pro_user.h)).json()
    assert seen["deliverables"] == [] and seen["pricingPreferences"] == ["FIXED", "OPEN"]  # scope hidden until the NDA
    seen = (await client.post(f"{R}/{req['id']}/accept-nda", headers=pro_user.h)).json()
    assert seen["deliverables"] == ["Master file", "Local file"] and seen["dependencies"] == ["BUYER_DATA"]
    bad = await client.post(R, headers=buyer.idem(), json=request_body(org, pro, deliverables=["x"]))
    assert bad.status_code == 422


async def test_saved_searches_and_new_matches(client, make_user, drain):
    buyer, _ = await buyer_org(client, make_user, drain)
    r = await client.post("/v1/saved/searches", headers=buyer.h, json={"name": "Tax help", "params": {"q": "tax", "tier": "A,B", "junk": "x"}})
    assert r.status_code == 201 and r.json()["params"] == {"q": "tax", "tier": "A,B"}
    saved = r.json()
    assert (await client.post("/v1/saved/searches", headers=buyer.h, json={"name": "Empty", "params": {}})).json()["code"] == "EMPTY_SEARCH"
    assert (await client.post("/v1/saved/searches", headers=buyer.h, json={"name": "Tax help", "params": {"q": "vat"}})).json()["code"] == "SEARCH_EXISTS"

    before = (clock.now() - timedelta(minutes=1)).isoformat()
    await publish(client, make_user, drain, "ann", headline="Tax adviser", primary="transfer-pricing")
    newer = (await client.get("/v1/search/professionals", params={"publishedAfter": before})).json()
    assert newer["total"] == 1  # published after the last look
    later = (await client.get("/v1/search/professionals", params={"publishedAfter": (clock.now() + timedelta(minutes=1)).isoformat()})).json()
    assert later["total"] == 0
    viewed = (await client.post(f"/v1/saved/searches/{saved['id']}/viewed", headers=buyer.h)).json()
    assert viewed["lastViewedAt"] > saved["lastViewedAt"]
    stranger = await make_user("sam")
    assert (await client.delete(f"/v1/saved/searches/{saved['id']}", headers=stranger.h)).status_code == 404
    assert (await client.delete(f"/v1/saved/searches/{saved['id']}", headers=buyer.h)).status_code == 204
    assert (await client.get("/v1/saved/searches", headers=buyer.h)).json() == []


async def test_profile_history_and_expired_credentials_stay_visible(client, make_user, drain, sf):
    pro_user, pro, buyer, c = await signed_contract(client, make_user, drain)
    prof = (await client.get(f"/v1/professionals/{pro['id']}")).json()
    assert prof["history"]["completedEngagements"] == 0 and prof["history"]["newToPlatform"] is True
    assert prof["history"]["medianResponseHours"] is not None  # the proposal answered the request

    await client.post("/v1/professionals/me/credentials", headers=pro_user.h, json={
        "credentialType": "LICENSE", "name": "CPA", "issuingBody": "State Board", "registrationNumber": "123", "jurisdiction": "US"})
    async with sf() as s, s.begin():
        await s.execute(text("UPDATE professional.credential_claims SET status = 'EXPIRED' WHERE professional_id = :p"), {"p": pro["id"]})
    creds = (await client.get(f"/v1/professionals/{pro['id']}")).json()["credentials"]
    assert [(x["name"], x["displayLabel"]) for x in creds] == [("CPA", "Expired")]
