"""Step 5 - search & discovery: projection from events, filters, ranking with explanations, safety."""

from __future__ import annotations

import base64
import hashlib
from sqlalchemy import text

from zoikorum.domains.search import facade

PHOTO = {"contentType": "image/png", "dataBase64": base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"0" * 64).decode()}


def pdf(name: str, body: bytes = b"scan") -> dict:
    """A small but real PDF evidence upload: bytes, type and the matching fingerprint."""
    data = b"%PDF-1.4\n" + body
    return {"name": name, "sha256": hashlib.sha256(data).hexdigest(), "size": len(data), "contentType": "application/pdf",
            "dataBase64": base64.b64encode(data).decode()}
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
    await client.post(f"/v1/verification/cases/{case['id']}/evidence", headers=u.h, json={"evidenceType": "ID_DOCUMENT", "items": [pdf("doc.pdf")]})
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
    assert why[0] == "“cfo” matches their name or headline" and "Trust light: Red (not verified yet)" in why
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
    # Licensed in Germany but not serving it: an engagement could not be agreed there, so it is not a match.
    await publish(client, make_user, drain, "lea", headline="Auditor", primary="transfer-pricing", served=("FR",), licensed=("DE",))
    assert await names(client, jurisdiction="DE") == []
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
    assert r["items"][0]["tier"] == "B" and "Trust light: Amber (identity verified)" in r["items"][0]["whyThisResult"]
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


async def test_company_policy_limits_results_and_says_so(client, make_user, drain):
    """An organisation's policy (here: Tier B and a verified identity) narrows search for its members, and the results say
    which rules applied and how many professionals they left out."""
    verified, verified_pro = await publish(client, make_user, drain, "quokka-verified", headline="Quokkaledger close lead", primary="transfer-pricing")
    await verify_identity(client, make_user, drain, verified, verified_pro)
    await publish(client, make_user, drain, "quokka-new", headline="Quokkaledger close helper", primary="transfer-pricing")

    owner = await make_user("policy-buyer")
    await drain()
    await owner.refresh()
    org = (await client.get("/v1/organizations/mine", headers=owner.h)).json()[0]
    before = (await client.get(URL, headers=owner.h, params={"q": "Quokkaledger"})).json()
    assert before["total"] == 2 and before["policy"] is None  # no policy yet: nothing hidden, nothing to explain

    profile = (await client.post("/v1/policy/profiles", headers=owner.h,
                                 json={"orgId": org["id"], "name": "Enterprise standard", "template": "ENTERPRISE_STANDARD"})).json()
    await owner.step_up()
    assert (await client.post(f"/v1/policy/profiles/{profile['id']}/activate", headers=owner.h)).status_code == 200
    after = (await client.get(URL, headers=owner.h, params={"q": "Quokkaledger"})).json()
    assert [i["displayName"] for i in after["items"]] == ["Quokka-Verified"]
    assert after["policy"]["hidden"] == 1 and after["policy"]["minTier"] in ("A", "B")
    assert "identity" in after["policy"]["requiredDimensions"] and after["policy"]["organizationName"]

    anonymous = (await client.get(URL, params={"q": "Quokkaledger"})).json()
    assert anonymous["total"] == 2 and anonymous["policy"] is None  # the public directory is not filtered by any one company
    outsider = await make_user("policy-outsider-search")
    r = await client.get(URL, headers=outsider.h, params={"q": "Quokkaledger", "organizationId": org["id"]})
    assert r.status_code == 403  # another organisation's policy view needs membership


def test_track_record_scoring():
    """Contract success (15), reviews (10), response (5): new professionals score 0, never a penalty; one 5-star review
    does not outrank many 4.8-star ones."""
    from types import SimpleNamespace

    from zoikorum.domains.search.service import track_record

    def doc(**kw):
        base = dict(completed_engagements=0, milestones_due=0, milestones_on_time=0, review_count=0, review_average=None,
                    response_median_hours=None)
        return SimpleNamespace(**{**base, **kw})

    new_score, new_why = track_record(doc())
    assert new_score == 0 and new_why == []
    one_five, _ = track_record(doc(review_count=1, review_average=5.0))
    many_good, why = track_record(doc(review_count=12, review_average=4.8))
    assert many_good > one_five and "4.8★ from 12 verified reviews" in why
    proven, why = track_record(doc(completed_engagements=12, milestones_due=20, milestones_on_time=19, response_median_hours=6))
    assert proven == 10 + 5 * 19 / 20 + 5
    assert "12 completed engagements, 95% of milestones on time" in why and "Usually replies within a day" in why


async def test_proven_professionals_rank_above_newcomers(client, make_user, drain, sf):
    from test_contract import C, fund, signed_contract
    from test_proposal import tier_b

    pro_user, pro, buyer, c = await signed_contract(client, make_user, drain)
    newcomer_user, newcomer = await tier_b(client, make_user, drain, "newcomer-nell")
    await fund(sf, drain, c, [m["id"] for m in c["milestones"]])
    for m in c["milestones"]:
        await client.post(f"/v1/milestones/{m['id']}/submit", headers=pro_user.h, json={"note": "Delivered"})
        await client.post(f"/v1/milestones/{m['id']}/accept", headers=buyer.idem())
    await drain()
    assert (await client.get(f"{C}/{c['id']}", headers=buyer.h)).json()["status"] == "COMPLETED"
    review = await client.post(f"{C}/{c['id']}/review", headers=buyer.idem(), json={"rating": 5, "comment": "Delivered exactly as agreed."})
    assert review.status_code == 201, review.text
    await drain()

    items = (await client.get(URL, params={"q": "Tax adviser", "limit": 50})).json()["items"]
    order = [i["professionalId"] for i in items if i["professionalId"] in (pro["id"], newcomer["id"])]
    assert order == [pro["id"], newcomer["id"]]  # same headline and tier: the track record decides
    why = next(i for i in items if i["professionalId"] == pro["id"])["whyThisResult"]
    assert any("1 completed engagement" in w for w in why) and any("5.0★ from 1 verified review" in w for w in why)


async def test_advanced_filters_autocomplete_and_cache(client, make_user, drain):
    from zoikorum.domains.search import service as search_service

    local, _ = await publish(client, make_user, drain, "loc", headline="Bookkeeper", primary="management-accounting", served=("US",), offering_price=50_000)
    wide, wide_pro = await publish(client, make_user, drain, "wide", headline="Fractional CFO", primary="fractional-cfo",
                                   served=("US", "GB", "DE"), offering_price=900_000)
    await client.patch("/v1/professionals/me", headers=wide.h, json={"industries": ["Technology", "Healthcare"]})
    await drain()
    names = lambda r: {i["displayName"] for i in r.json()["items"]}  # noqa: E731

    tech = names(await client.get(URL, params={"industry": "Technology"}))
    assert any(n.startswith("Wide") for n in tech) and not any(n.startswith("Loc") for n in tech)
    cross = names(await client.get(URL, params={"crossBorder": "true"}))
    assert any(n.startswith("Wide") for n in cross) and not any(n.startswith("Loc") for n in cross)
    cheap = names(await client.get(URL, params={"budgetMaxMinor": 100_000, "budgetCurrency": "USD"}))
    assert any(n.startswith("Loc") for n in cheap) and not any(n.startswith("Wide") for n in cheap)
    assert (await client.patch("/v1/professionals/me", headers=wide.h, json={"industries": ["Space Mining"]})).status_code == 422

    s = (await client.get("/v1/search/suggest", params={"q": "fraction"})).json()
    assert any(x["slug"] == "fractional-cfo" for x in s["specializations"])
    assert any(p["headline"] == "Fractional CFO" for p in (await client.get("/v1/search/suggest", params={"q": "Fractional"})).json()["professionals"])
    assert (await client.get("/v1/search/suggest", params={"q": "f"})).json() == {"specializations": [], "professionals": []}

    # Signed-out results are cached, but any profile change shows at once.
    search_service._cache.clear()
    first = await client.get(URL, params={"industry": "Healthcare"})
    assert len(search_service._cache) == 1
    assert (await client.get(URL, params={"industry": "Healthcare"})).json() == first.json()  # served from the cache
    await client.patch("/v1/professionals/me", headers=local.h, json={"industries": ["Healthcare"]})
    await drain()
    assert (await client.get(URL, params={"industry": "Healthcare"})).json()["total"] == first.json()["total"] + 1


async def test_semantic_matching_finds_meaning_not_just_words(client, make_user, drain):
    await publish(client, make_user, drain, "books", headline="Small business accountant", primary="bookkeeping-and-accounting-services")
    await publish(client, make_user, drain, "vatty", headline="Indirect tax adviser", primary="vat-gst-sales-tax")
    found = (await client.get(URL, params={"q": "someone to do my books"})).json()
    first = found["items"][0]
    assert first["displayName"].startswith("Books") and first["whyThisResult"][0].startswith("Related to")
    vat = (await client.get(URL, params={"q": "GST registration"})).json()
    assert vat["items"] and vat["items"][0]["displayName"].startswith("Vatty")
