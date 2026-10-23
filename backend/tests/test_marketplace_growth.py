"""Professional replies to reviews, sign-up referral codes, public procurement requests, on-site regions and the
search filters for credentials, enterprise history and currencies."""

from __future__ import annotations

from sqlalchemy import text

from test_search import publish, verify_identity

URL = "/v1/search/professionals"


async def _completed_with_review(client, make_user, drain, sf):
    from test_contract import C, fund, signed_contract

    pro_user, pro, buyer, c = await signed_contract(client, make_user, drain)
    await fund(sf, drain, c, [m["id"] for m in c["milestones"]])
    for m in c["milestones"]:
        await client.post(f"/v1/milestones/{m['id']}/submit", headers=pro_user.h, json={"note": "Delivered"})
        await client.post(f"/v1/milestones/{m['id']}/accept", headers=buyer.idem())
    await drain()
    review = await client.post(f"{C}/{c['id']}/review", headers=buyer.idem(), json={"rating": 4, "comment": "Clear work, a little late."})
    assert review.status_code == 201, review.text
    await drain()
    return pro_user, pro, buyer, c, review.json()


async def test_the_reviewed_professional_replies_once_and_edits_are_audited(client, make_user, drain, sf):
    pro_user, pro, buyer, c, review = await _completed_with_review(client, make_user, drain, sf)
    url = f"/v1/reviews/{review['id']}/reply"

    # Only the reviewed professional may answer.
    assert (await client.put(url, headers=buyer.h, json={"body": "Not mine to answer"})).status_code == 403
    stranger = await make_user("stranger-sam")
    assert (await client.put(url, headers=stranger.h, json={"body": "Hello"})).status_code == 403
    assert (await client.put("/v1/reviews/00000000-0000-0000-0000-000000000000/reply", headers=pro_user.h,
                             json={"body": "Hello"})).status_code == 404

    first = await client.put(url, headers=pro_user.h, json={"body": "  Thank you. The delay was agreed in week two.  "})
    assert first.status_code == 200, first.text
    assert first.json()["reply"]["body"] == "Thank you. The delay was agreed in week two." and not first.json()["reply"]["edited"]
    edited = await client.put(url, headers=pro_user.h, json={"body": "Thank you for the feedback."})
    assert edited.json()["reply"]["edited"] and edited.json()["reply"]["id"] == first.json()["reply"]["id"]  # still one reply

    public = (await client.get(f"/v1/professionals/{pro['id']}/reviews")).json()
    assert public["items"][0]["reply"]["body"] == "Thank you for the feedback."
    await drain()
    async with sf() as s:
        actions = (await s.execute(text("SELECT action FROM audit.audit_records WHERE action LIKE 'review.reply.%' ORDER BY seq"))).scalars().all()
        replies = await s.scalar(text("SELECT count(*) FROM review.review_replies"))
    assert actions == ["review.reply.created", "review.reply.edited"] and replies == 1


async def test_a_referral_code_is_stored_once_per_account(client, make_user):
    u = await make_user("ria")
    assert (await client.get("/v1/referrals/mine", headers=u.h)).json() is None
    assert (await client.post("/v1/referrals", headers=u.h, json={"code": "bad code!"})).status_code == 422
    r = await client.post("/v1/referrals", headers=u.h, json={"code": "friend-2026"})
    assert r.status_code == 201 and r.json()["code"] == "FRIEND-2026"
    assert (await client.post("/v1/referrals", headers=u.h, json={"code": "FRIEND-2026"})).status_code == 201  # retry is harmless
    other = await client.post("/v1/referrals", headers=u.h, json={"code": "OTHER-1"})
    assert other.status_code == 409 and other.json()["code"] == "REFERRAL_ALREADY_RECORDED"
    assert (await client.post("/v1/referrals", json={"code": "FRIEND-2026"})).status_code == 401


async def test_public_procurement_requests_create_a_lead_for_staff_only(client, make_user, drain):
    _, pro = await publish(client, make_user, drain, "pia", headline="Fractional CFO", primary="fractional-cfo")
    body = {"kind": "SECURITY_REVIEW", "professionalId": pro["id"], "name": "Ann Buyer", "organization": "Acme plc",
            "email": "ann@acme.example", "message": "Please send your security questionnaire answers."}
    r = await client.post("/v1/procurement-requests", json=body)
    assert r.status_code == 201, r.text
    out = r.json()
    assert out["reference"].startswith("ZK-PRC-") and out["email"] is None and out["name"] is None  # contact details stay with staff
    assert (await client.post("/v1/procurement-requests", json={**body, "email": "not-an-email"})).status_code == 422
    assert (await client.post("/v1/procurement-requests", json={**body, "professionalId": "00000000-0000-0000-0000-000000000000"})).status_code == 404

    nobody = await make_user("nora")
    assert (await client.get("/v1/admin/procurement-requests", headers=nobody.h)).status_code == 403
    agent = await make_user("sue", platform_roles=("SUPPORT_AGENT",))
    await agent.step_up()
    listed = await client.get("/v1/admin/procurement-requests", headers=agent.h)
    assert listed.status_code == 200, listed.text
    assert [(i["reference"], i["email"], i["kind"]) for i in listed.json()] == [(out["reference"], "ann@acme.example", "SECURITY_REVIEW")]


async def test_a_bot_filling_the_hidden_field_stores_nothing(client, sf):
    r = await client.post("/v1/procurement-requests", json={"name": "Bot", "organization": "Spam", "email": "bot@spam.example",
                                                            "website": "http://spam.example"})
    assert r.status_code == 201
    async with sf() as s:
        assert await s.scalar(text("SELECT count(*) FROM marketplace.procurement_requests")) == 0


async def test_onsite_regions_and_review_state_show_on_the_public_profile(client, make_user, drain, sf):
    u, pro = await publish(client, make_user, drain, "olu", headline="Fractional CFO", primary="fractional-cfo")
    me = (await client.get("/v1/professionals/me", headers=u.h)).json()
    r = await client.patch("/v1/professionals/me", headers={**u.h, "If-Match": str(me["version"])},
                           json={"deliveryModes": ["ONSITE"], "onsiteRegions": ["London", " London ", "Manchester", ""]})
    assert r.status_code == 200, r.text
    assert r.json()["onsiteRegions"] == ["London", "Manchester"]
    public = (await client.get(f"/v1/professionals/{pro['id']}")).json()
    assert public["onsiteRegions"] == ["London", "Manchester"] and public["profileStatus"] == "PUBLISHED" and public["underReview"] is False
    async with sf() as s, s.begin():
        await s.execute(text("UPDATE professional.professionals SET visibility_reduced = true WHERE id = :i"), {"i": pro["id"]})
    assert (await client.get(f"/v1/professionals/{pro['id']}")).json()["underReview"] is True


async def test_search_filters_for_credentials_currencies_and_enterprise_history(client, make_user, drain, sf):
    from zoikorum.domains.search import service as search_service

    a_user, a = await publish(client, make_user, drain, "ada", headline="Fractional CFO", primary="fractional-cfo", offering_price=50000)
    await publish(client, make_user, drain, "bob", headline="Fractional CFO", primary="fractional-cfo", offering_price=40000)
    # Ada prices a second service in euros: she now accepts more than one currency.
    o = (await client.post("/v1/professionals/me/offerings", headers=a_user.h, json={
        "title": "EU close support", "specialization": "fractional-cfo", "deliverables": ["Close pack"],
        "engagementTypes": ["PROJECT"], "pricingModel": "FIXED", "startingPrice": {"amountMinor": 30000, "currency": "EUR"}})).json()
    await client.post(f"/v1/professionals/me/offerings/{o['id']}/activate", headers=a_user.h)
    await drain()

    async def names(**params):
        r = await client.get(URL, params=params)
        assert r.status_code == 200, r.text
        return sorted(i["displayName"] for i in r.json()["items"]), r.json()

    found, body = await names(multiCurrency="true")
    assert found == ["Ada"] and body["items"][0]["currencies"] == ["EUR", "USD"]
    assert body["facets"]["multiCurrency"] == [{"value": "true", "label": "true", "count": 1}]

    # Verified credentials: any of several (multi-select). Names are written straight into the projection here.
    async with sf() as s, s.begin():
        await s.execute(text("UPDATE search.professional_documents SET verified_credentials = '{CPA}' WHERE display_name = 'Ada'"))
        await s.execute(text("UPDATE search.professional_documents SET verified_credentials = '{ACCA}' WHERE display_name = 'Bob'"))
    search_service._cache.clear()
    assert (await names(credentials="CPA"))[0] == ["Ada"]
    assert (await names(credentials="CPA,ACCA"))[0] == ["Ada", "Bob"]
    assert (await names(credentials="CFA"))[0] == []
    assert {f["value"] for f in (await names())[1]["facets"]["credential"]} == {"CPA", "ACCA"}

    assert (await names(priorEnterprise="true"))[0] == []
    async with sf() as s, s.begin():
        await s.execute(text("UPDATE search.professional_documents SET enterprise_engagements = 2 WHERE display_name = 'Bob'"))
    search_service._cache.clear()
    found, body = await names(priorEnterprise="true")
    assert found == ["Bob"] and body["items"][0]["enterpriseEngagements"] == 2


async def test_completed_work_for_an_enterprise_counts_as_prior_enterprise_engagement(client, make_user, drain, sf):
    import uuid

    from zoikorum.domains.search import service as search_service

    pro_user, pro, buyer, c, _ = await _completed_with_review(client, make_user, drain, sf)
    async with sf() as s, s.begin():
        await s.execute(text("UPDATE buyer.organizations SET org_type = 'ENTERPRISE' WHERE id = :o"), {"o": c["organizationId"]})
        await search_service.rebuild(s, uuid.UUID(pro["id"]))
    async with sf() as s:
        assert await s.scalar(text("SELECT enterprise_engagements FROM search.professional_documents WHERE professional_id = :p"),
                              {"p": pro["id"]}) == 1


async def test_verified_professionals_still_appear_with_new_filters_off(client, make_user, drain):
    u, pro = await publish(client, make_user, drain, "vic", headline="Fractional CFO", primary="fractional-cfo")
    await verify_identity(client, make_user, drain, u, pro)
    r = await client.get(URL, params={"priorEnterprise": "false", "multiCurrency": "false"})
    assert [i["displayName"] for i in r.json()["items"]] == ["Vic"]
