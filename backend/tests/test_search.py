"""Step 5 - search & discovery: projection from events, filters, ranking with explanations, safety."""

from __future__ import annotations

import base64
from sqlalchemy import text

from zoikorum.domains.search import facade

PHOTO = {"contentType": "image/png", "dataBase64": base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"0" * 64).decode()}
BIO = (
"I help growing companies with month-end close, board reporting, cash forecasting and investor-ready "
       "financial models, working closely with founders and their teams.")
URL = "/v1/search/professionals"


async def publish(client, make_user, drain, name, *, headline, primary, secondary=(), served=("US",), licensed=(),
                  availability=None, offering_price=None):
    u = await make_user(name, account_type="PROFESSIONAL")
    pro = (await client.post("/v1/professionals", headers=u.h, json={})).json()
    await client.post("/v1/auth/confirm-email", json={"token": u.confirm_token})
    await client.put("/v1/professionals/me/photo", headers=u.h, json=PHOTO)
    await client.patch("/v1/professionals/me", headers=u.h, json={
        "headline": headline, "bio": BIO, "engagementTypes": ["PROJECT"], "deliveryModes": ["REMOTE"],
        "pricingModels": ["FIXED"], "yearsExperienceBand": "6-10", "legalName": f"{name.title()} Example"})
    await client.put("/v1/professionals/me/specializations", headers=u.h, json={"primary": primary, "secondary": list(secondary)})
    await client.put("/v1/professionals/me/jurisdictions", headers=u.h,
                     json={"served": list(served), "licensed": list(licensed), "crossBorderAcknowledged": True})
    if availability:
        await client.put("/v1/professionals/me/availability", headers=u.h, json={"availability": availability})
    if offering_price is not None:
        o = (await client.post("/v1/professionals/me/offerings", headers=u.h, json={
            "title": f"{headline} package", "specialization": primary, "deliverables": ["Report"],
            "engagementTypes": ["PROJECT"], "pricingModel": "FIXED",
            "startingPrice": {"amountMinor": offering_price, "currency": "USD"}})).json()
        await client.post(f"/v1/professionals/me/offerings/{o['id']}/activate", headers=u.h)
    r = await client.post("/v1/professionals/me/publish", headers=u.h, json={"attestAccurate": True})
    assert r.status_code == 200, r.text
    await drain()
    return u, pro


async def verify_identity(client, make_user, drain, u, pro):
    case = (await client.post("/v1/verification/cases", headers=u.h, json={
        "verificationType": "IDENTITY", "subjectType": "PROFESSIONAL", "subjectId": pro["id"]})).json()
    await client.post(f"/v1/verification/cases/{case['id']}/evidence", headers=u.h, json={"evidenceType": "ID_DOCUMENT", "items": [{"name": "doc.pdf", "sha256": "d" * 64, "size": 1000}]})
    o = await make_user(f"officer-{pro['id'][:6]}", platform_roles=("COMPLIANCE_OFFICER",))
    await o.step_up()
    await client.post(f"/v1/verification/cases/{case['id']}/decision", headers=o.h, json={"decision": "VERIFIED", "reasonCode": "OK"})
    await drain()


async def names(client, **params) -> list[str]:
    r = await client.get(URL, params=params)
    assert r.status_code == 200, r.text
    return [i["displayName"] for i in r.json()["items"]]


async def test_only_published_profiles_are_discoverable(client, make_user, drain):
    u, pro = await publish(client, make_user, drain, "pia", headline="Fractional CFO", primary="fractional-cfo")
    draft = await make_user("dan", account_type="PROFESSIONAL")
    await client.post("/v1/professionals", headers=draft.h, json={})
    await drain()
    assert await names(client) == ["Pia"]

    await client.post("/v1/professionals/me/unpublish", headers=u.h)
    await drain()  # the projection follows the PROFILE_UNPUBLISHED event
    assert await names(client) == []


async def test_full_text_relevance_and_explanations(client, make_user, drain):
    await publish(client, make_user, drain, "pia", headline="Fractional CFO for SaaS", primary="fractional-cfo")
    await publish(client, make_user, drain, "tom", headline="Tax adviser", primary="transfer-pricing")
    r = (await client.get(URL, params={"q": "cfo"})).json()
    assert r["total"] == 1 and r["items"][0]["displayName"] == "Pia"
    why = r["items"][0]["whyThisResult"]
    assert why[0] == "“cfo” matches their name or headline" and "Tier C: Unverified (Discovery Only)" in why
    # Specialization names are indexed too (weight B).
    assert await names(client, q="transfer pricing") == ["Tom"]


async def test_filters(client, make_user, drain):
    await publish(client, make_user, drain, "pia", headline="Fractional CFO", primary="fractional-cfo",
                  secondary=["budgeting-and-forecasting"], served=("US", "GB"), availability="NOW")
    await publish(client, make_user, drain, "tom", headline="Tax adviser", primary="transfer-pricing", served=("IN",), licensed=("IN",))
    assert sorted(await names(client, spec="fractional-cfo,transfer-pricing")) == ["Pia", "Tom"]
    assert await names(client, spec="fractional-cfo,budgeting-and-forecasting", specMatch="all") == ["Pia"]
    assert await names(client, jurisdiction="gb") == ["Pia"]
    assert await names(client, jurisdiction="IN") == ["Tom"]
    assert await names(client, availability="NOW") == ["Pia"]
    assert await names(client, category="finance-and-accounting", tier="A") == []
    bad = await client.get(URL, params={"verified": "astrology"})
    assert bad.status_code == 422 and bad.json()["code"] == "INVALID_FILTER"


async def test_verified_professionals_rank_first_and_filter(client, make_user, drain):
    await publish(client, make_user, drain, "cara", headline="Fractional CFO", primary="fractional-cfo")
    u, pro = await publish(client, make_user, drain, "bea", headline="Fractional CFO", primary="fractional-cfo")
    await verify_identity(client, make_user, drain, u, pro)

    r = (await client.get(URL, params={"q": "fractional cfo"})).json()
    assert [i["displayName"] for i in r["items"]] == ["Bea", "Cara"]  # same relevance; Tier B outranks Tier C
    assert r["items"][0]["tier"] == "B" and "Tier B: Verified Identity" in r["items"][0]["whyThisResult"]
    assert r["items"][0]["dimensions"]["identity"] == "VERIFIED" and r["items"][0]["yearsExperienceBand"] == "6-10"
    assert {f["value"]: f["count"] for f in r["facets"]["tier"]} == {"B": 1, "C": 1}
    assert await names(client, verified="identity") == ["Bea"]


async def test_sorting_by_price_and_experience(client, make_user, drain):
    await publish(client, make_user, drain, "hi", headline="CFO", primary="fractional-cfo", offering_price=900000)
    await publish(client, make_user, drain, "lo", headline="CFO", primary="fractional-cfo", offering_price=150000)
    await publish(client, make_user, drain, "none", headline="CFO", primary="fractional-cfo")
    assert await names(client, sort="price_asc") == ["Lo", "Hi", "None"]  # no price goes last
    assert await names(client, sort="price_desc") == ["Hi", "Lo", "None"]
    r = (await client.get(URL, params={"sort": "price_asc"})).json()
    assert r["items"][0]["startingPrice"] == {"amountMinor": 150000, "currency": "USD"}


async def test_searches_are_recorded_and_zero_results_flagged(client, make_user, drain, sf):
    await publish(client, make_user, drain, "pia", headline="Fractional CFO", primary="fractional-cfo")
    await client.get(URL, params={"q": "cfo"})
    await client.get(URL, params={"q": "astrophysicist"})
    async with sf() as s:
        performed = (await s.execute(text("SELECT envelope FROM platform.outbox WHERE event_type = :t ORDER BY seq"),
                                     {"t": "zoikorum.search.query.performed.v1"})).all()
        zero = (await s.execute(text("SELECT envelope FROM platform.outbox WHERE event_type = :t"),
                                {"t": "zoikorum.search.query.zero_result.v1"})).all()
    assert [p[0]["payload"]["total"] for p in performed] == [1, 0]
    assert [z[0]["payload"]["query"] for z in zero] == ["astrophysicist"]


async def test_reindex_and_policy_impact_count(client, make_user, drain, sf):
    u, pro = await publish(client, make_user, drain, "bea", headline="Fractional CFO", primary="fractional-cfo")
    await verify_identity(client, make_user, drain, u, pro)
    await publish(client, make_user, drain, "cara", headline="Tax adviser", primary="transfer-pricing", served=("GB",))

    buyer = await make_user("buyer")
    assert (await client.post("/v1/admin/search/reindex", headers=buyer.h)).status_code == 403
    admin = await make_user("admin", platform_roles=("PLATFORM_ADMIN",))
    await admin.step_up()
    async with sf() as s, s.begin():
        await s.execute(text("DELETE FROM search.professional_documents"))
    assert await names(client) == []
    r = await client.post("/v1/admin/search/reindex", headers=admin.h)
    assert r.status_code == 200 and r.json()["reindexed"] == 2
    assert sorted(await names(client)) == ["Bea", "Cara"]

    async with sf() as s:
        assert await facade.count_eligible(s, {}) == 2
        assert await facade.count_eligible(s, {"minTier": "B"}) == 1
        assert await facade.count_eligible(s, {"requiredDimensions": ["identity"], "jurisdictions": ["US"]}) == 1
        assert await facade.count_eligible(s, {"jurisdictions": ["GB"], "categories": ["finance-and-accounting"]}) == 1
