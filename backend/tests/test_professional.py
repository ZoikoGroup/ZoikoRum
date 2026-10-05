"""Step 3 - professional onboarding: profile, specializations, jurisdictions, credentials,
offerings, publishing and the public profile."""

from __future__ import annotations

import uuid
from urllib.parse import parse_qs, urlparse

from sqlalchemy import text

from zoikorum.domains.professional import facade

BIO = ("Former Big Four audit manager. I help growing companies set up month-end close, "
       "board reporting and cash forecasting that their investors can rely on.")


async def new_pro(client, make_user, name="pia", **kw):
    u = await make_user(name, account_type="PROFESSIONAL", **kw)
    r = await client.post("/v1/professionals", headers=u.h, json={})
    assert r.status_code == 201, r.text
    return u, r.json()


async def ready_to_publish(client, u):
    """Fill every required onboarding item."""
    await client.post("/v1/auth/confirm-email", json={"token": u.confirm_token})
    r = await client.patch("/v1/professionals/me", headers=u.h, json={
        "headline": "Fractional CFO", "bio": BIO, "engagementTypes": ["FRACTIONAL", "PROJECT"],
        "deliveryModes": ["REMOTE"], "pricingModels": ["RETAINER", "CUSTOM"]})
    assert r.status_code == 200, r.text
    r = await client.put("/v1/professionals/me/specializations", headers=u.h,
                         json={"primary": "fractional-cfo", "secondary": ["fp-and-a-and-financial-planning"]})
    assert r.status_code == 200, r.text
    r = await client.put("/v1/professionals/me/jurisdictions", headers=u.h, json={"served": ["US"], "licensed": ["US"]})
    assert r.status_code == 200, r.text


async def outbox(sf, event_type: str) -> list[dict]:
    async with sf() as s:
        rows = await s.execute(text("SELECT envelope FROM platform.outbox WHERE event_type = :t ORDER BY seq"), {"t": event_type})
        return [r[0]["payload"] for r in rows]


async def test_register_links_professional_to_the_account(client, make_user, drain, sf):
    u, pro = await new_pro(client, make_user)
    assert pro["status"] == "DRAFT" and pro["displayName"] == "Pia" and pro["country"] == "US"
    assert (await client.post("/v1/professionals", headers=u.h, json={})).status_code == 409

    (registered,) = await outbox(sf, "zoikorum.professional.professional.registered.v1")
    assert registered["professionalId"] == pro["id"] and registered["identityId"] == str(u.id)
    await drain()
    await u.refresh()
    async with sf() as s:
        summary = await facade.get_professional_by_identity(s, u.id)
    assert str(summary.id) == pro["id"] and summary.status == "DRAFT"


async def test_buyers_need_the_professional_role(client, make_user):
    buyer = await make_user("bea")
    r = await client.post("/v1/professionals", headers=buyer.h, json={})
    assert r.status_code == 403 and r.json()["code"] == "ROLE_REQUIRED"
    assert (await client.get("/v1/professionals/me", headers=buyer.h)).status_code == 404


async def test_profile_edits_use_optimistic_concurrency_and_copy_rules(client, make_user):
    u, pro = await new_pro(client, make_user)
    r = await client.patch("/v1/professionals/me", headers={**u.h, "If-Match": str(pro["version"])},
                           json={"headline": "Fractional CFO", "languages": ["English", "Spanish", "English"]})
    assert r.status_code == 200 and r.json()["languages"] == ["English", "Spanish"]
    assert r.json()["version"] == pro["version"] + 1
    stale = await client.patch("/v1/professionals/me", headers={**u.h, "If-Match": str(pro["version"])}, json={"city": "Austin"})
    assert stale.status_code == 409 and stale.json()["code"] == "VERSION_CONFLICT"

    r = await client.patch("/v1/professionals/me", headers=u.h, json={"bio": "The best CFO in Texas."})
    assert r.status_code == 422 and r.json()["code"] == "COPY_RULES"
    r = await client.patch("/v1/professionals/me", headers=u.h, json={"bio": "I build top-line revenue models."})
    assert r.status_code == 200

    r = await client.patch("/v1/professionals/me", headers=u.h, json={"indicativeRate": {"amountMinor": 15000, "currency": "USD"}})
    assert r.status_code == 422 and r.json()["code"] == "RATE_UNIT_REQUIRED"
    r = await client.patch("/v1/professionals/me", headers=u.h,
                           json={"indicativeRate": {"amountMinor": 15000, "currency": "USD"}, "rateUnit": "HOUR"})
    assert r.json()["indicativeRate"] == {"amountMinor": 15000, "currency": "USD"} and r.json()["rateUnit"] == "HOUR"


async def test_specializations_come_from_the_taxonomy(client, make_user):
    u, _ = await new_pro(client, make_user)
    url = "/v1/professionals/me/specializations"
    r = await client.put(url, headers=u.h, json={"primary": "fractional-cfo", "secondary": ["astrology"]})
    assert r.status_code == 422 and r.json()["code"] == "UNKNOWN_SPECIALIZATION"
    r = await client.put(url, headers=u.h, json={"primary": "fractional-cfo", "secondary": ["fractional-cfo"]})
    assert r.status_code == 422 and r.json()["code"] == "DUPLICATE_SPECIALIZATION"
    six = ["internal-audit", "valuation-services", "transfer-pricing", "ifrs-reporting", "bookkeeping-and-accounting-services",
           "treasury-and-cash-management"]
    assert (await client.put(url, headers=u.h, json={"primary": "fractional-cfo", "secondary": six})).status_code == 422

    r = await client.put(url, headers=u.h, json={"primary": "fractional-cfo", "secondary": ["transfer-pricing"]})
    assert r.status_code == 200
    body = r.json()
    assert body["primaryCategory"] == "finance-and-accounting"
    assert [(s["slug"], s["primary"], s["requiresCredential"]) for s in body["specializations"]] == [
        ("fractional-cfo", True, False), ("transfer-pricing", False, True)]


async def test_serving_other_countries_needs_cross_border_acknowledgement(client, make_user, sf):
    u, _ = await new_pro(client, make_user)
    url = "/v1/professionals/me/jurisdictions"
    r = await client.put(url, headers=u.h, json={"served": ["us", "GB"]})
    assert r.status_code == 422 and r.json()["code"] == "CROSS_BORDER_ACK_REQUIRED"
    assert (await client.put(url, headers=u.h, json={"served": ["USA"]})).status_code == 422
    r = await client.put(url, headers=u.h, json={"served": ["us", "GB"], "licensed": ["US"], "crossBorderAcknowledged": True})
    assert r.status_code == 200 and r.json()["servedJurisdictions"] == ["GB", "US"] and r.json()["crossBorderAcknowledged"]
    (evt,) = await outbox(sf, "zoikorum.professional.professional.jurisdictions_updated.v1")
    assert evt["served"] == ["GB", "US"] and evt["licensed"] == ["US"]


async def test_publish_requires_readiness_and_attestation(client, make_user, sf):
    u, pro = await new_pro(client, make_user)
    r = await client.post("/v1/professionals/me/publish", headers=u.h, json={"attestAccurate": True})
    assert r.status_code == 422 and r.json()["code"] == "PROFILE_NOT_READY"
    assert "Confirm your email address" in r.json()["extra"]["missing"]

    await ready_to_publish(client, u)
    ready = (await client.get("/v1/professionals/me/readiness", headers=u.h)).json()
    assert ready["canPublish"] is True
    assert {i["key"] for i in ready["items"] if not i["done"]} == {"availability", "credentials", "offering"}

    assert (await client.post("/v1/professionals/me/publish", headers=u.h, json={"attestAccurate": False})).status_code == 422
    r = await client.post("/v1/professionals/me/publish", headers=u.h, json={"attestAccurate": True})
    assert r.status_code == 200 and r.json()["status"] == "PUBLISHED" and r.json()["publishedAt"]
    again = await client.post("/v1/professionals/me/publish", headers=u.h, json={"attestAccurate": True})
    assert again.status_code == 409 and again.json()["code"] == "INVALID_STATE_TRANSITION"
    assert len(await outbox(sf, "zoikorum.professional.professional.profile_published.v1")) == 1


async def test_public_profile_visibility(client, make_user):
    u, pro = await new_pro(client, make_user)
    url = f"/v1/professionals/{pro['id']}"
    assert (await client.get(url)).status_code == 404  # draft: invisible to the public
    preview = await client.get(url, headers=u.h)
    assert preview.status_code == 200 and preview.json()["isOwnProfile"] is True

    await ready_to_publish(client, u)
    await client.patch("/v1/professionals/me", headers=u.h, json={"legalName": "Pia Q. Private"})
    await client.post("/v1/professionals/me/publish", headers=u.h, json={"attestAccurate": True})
    public = await client.get(url)
    assert public.status_code == 200
    assert public.json()["primaryCategoryName"] == "Finance & Accounting" and public.json()["isOwnProfile"] is False
    assert "Pia Q. Private" not in public.text and "legalName" not in public.json()

    assert (await client.post("/v1/professionals/me/unpublish", headers=u.h)).json()["status"] == "UNPUBLISHED"
    assert (await client.get(url)).status_code == 404
    stranger = await make_user("sam")
    assert (await client.get(url, headers=stranger.h)).status_code == 404


async def test_credentials_are_self_reported_until_verified(client, make_user, sf):
    u, pro = await new_pro(client, make_user)
    url = "/v1/professionals/me/credentials"
    r = await client.post(url, headers=u.h, json={
        "credentialType": "LICENSE", "name": "Certified Public Accountant", "issuingBody": "Texas State Board",
        "registrationNumber": "TX-12345", "jurisdiction": "us", "expiresOn": "2030-12-31", "specialization": "transfer-pricing"})
    assert r.status_code == 201, r.text
    claim = r.json()
    assert claim["status"] == "PENDING" and claim["displayLabel"] == "Self-reported" and claim["jurisdiction"] == "US"

    (evt,) = await outbox(sf, "zoikorum.professional.credential.submitted.v1")
    assert evt["credentialClaimId"] == claim["id"] and evt["registrationNumber"] == "TX-12345"
    assert evt["expiresOn"] == "2030-12-31" and evt["specialization"] == "transfer-pricing"

    expired = await client.post(url, headers=u.h, json={"credentialType": "CERTIFICATION", "name": "CMA",
                                                        "issuingBody": "IMA", "expiresOn": "2020-01-01"})
    assert expired.status_code == 422 and expired.json()["code"] == "CREDENTIAL_EXPIRED"

    public = (await client.get(f"/v1/professionals/{pro['id']}", headers=u.h)).json()
    assert public["credentials"] == [{"name": "Certified Public Accountant", "issuingBody": "Texas State Board",
                                      "jurisdiction": "US", "status": "SELF_REPORTED", "displayLabel": "Self-reported"}]
    assert "TX-12345" not in str(public)

    assert (await client.delete(f"{url}/{claim['id']}", headers=u.h)).status_code == 204
    assert (await client.get(url, headers=u.h)).json() == []
    assert (await client.get(f"/v1/professionals/{pro['id']}", headers=u.h)).json()["credentials"] == []
    assert (await client.delete(f"{url}/{claim['id']}", headers=u.h)).status_code == 404


async def test_offering_lifecycle(client, make_user, sf):
    u, pro = await new_pro(client, make_user)
    url = "/v1/professionals/me/offerings"
    offer = {"title": "Fractional CFO retainer", "specialization": "fractional-cfo", "engagementTypes": ["RETAINER"],
             "pricingModel": "RETAINER"}
    r = await client.post(url, headers=u.h, json=offer)
    assert r.status_code == 422 and r.json()["code"] == "SPECIALIZATION_NOT_ON_PROFILE"
    await client.put("/v1/professionals/me/specializations", headers=u.h, json={"primary": "fractional-cfo"})
    r = await client.post(url, headers=u.h, json=offer)
    assert r.status_code == 201 and r.json()["status"] == "DRAFT" and r.json()["specializationName"] == "Fractional CFO"
    o = r.json()

    assert (await client.post(f"{url}/{o['id']}/pause", headers=u.h)).status_code == 409  # DRAFT -> PAUSED
    r = await client.post(f"{url}/{o['id']}/activate", headers=u.h)
    assert r.status_code == 422 and r.json()["code"] == "OFFERING_INCOMPLETE"

    r = await client.patch(f"{url}/{o['id']}", headers={**u.h, "If-Match": str(o["version"])},
                           json={"deliverables": ["13-week cash flow forecast", "Board pack"],
                                 "startingPrice": {"amountMinor": 500000, "currency": "USD"}})
    assert r.status_code == 200 and r.json()["version"] == o["version"] + 1
    assert (await client.post(f"{url}/{o['id']}/activate", headers=u.h)).json()["status"] == "ACTIVE"
    # A live offering must stay contract-ready.
    r = await client.patch(f"{url}/{o['id']}", headers=u.h, json={"clearStartingPrice": True})
    assert r.status_code == 422

    public = (await client.get(f"/v1/professionals/{pro['id']}", headers=u.h)).json()
    assert [x["title"] for x in public["offerings"]] == ["Fractional CFO retainer"]
    assert (await client.post(f"{url}/{o['id']}/pause", headers=u.h)).json()["status"] == "PAUSED"
    assert (await client.get(f"/v1/professionals/{pro['id']}", headers=u.h)).json()["offerings"] == []
    assert len((await client.get(url, headers=u.h)).json()) == 1  # paused != deleted

    async with sf() as s:
        pro_id = uuid.UUID(pro["id"])
        assert await facade.list_offerings(s, pro_id) == []
        assert len(await facade.list_offerings(s, pro_id, active_only=False)) == 1
    statuses = [e["status"] for e in await outbox(sf, "zoikorum.professional.offering.status_changed.v1")]
    assert statuses == ["ACTIVE", "PAUSED"]


async def test_other_professionals_cannot_touch_my_offerings(client, make_user):
    u, _ = await new_pro(client, make_user)
    await client.put("/v1/professionals/me/specializations", headers=u.h, json={"primary": "fractional-cfo"})
    o = (await client.post("/v1/professionals/me/offerings", headers=u.h, json={
        "title": "CFO advisory", "specialization": "fractional-cfo", "engagementTypes": ["ADVISORY"],
        "pricingModel": "CUSTOM"})).json()
    other, _ = await new_pro(client, make_user, "oli")
    assert (await client.get(f"/v1/professionals/me/offerings/{o['id']}", headers=other.h)).status_code == 404
    assert (await client.post(f"/v1/professionals/me/offerings/{o['id']}/activate", headers=other.h)).status_code == 404


async def test_availability_and_capacity(client, make_user, sf):
    u, pro = await new_pro(client, make_user)
    r = await client.put("/v1/professionals/me/availability", headers=u.h,
                         json={"availability": "TWO_WEEKS", "maxConcurrentEngagements": 3})
    assert r.status_code == 200 and r.json()["availability"] == "TWO_WEEKS"
    r = await client.put("/v1/professionals/me/availability", headers=u.h,
                         json={"availability": "TWO_WEEKS", "maxConcurrentEngagements": 3, "temporarilyUnavailable": True})
    assert r.json()["temporarilyUnavailable"] is True
    assert (await client.get(f"/v1/professionals/{pro['id']}", headers=u.h)).json()["availability"] == "AT_CAPACITY"
    events = await outbox(sf, "zoikorum.professional.professional.availability_updated.v1")
    assert [e["availability"] for e in events] == ["TWO_WEEKS", "AT_CAPACITY"]
    async with sf() as s:
        assert (await facade.get_professional(s, uuid.UUID(pro["id"]))).availability == "AT_CAPACITY"


async def test_firm_members_can_practise_under_their_firm(client, make_user, drain):
    admin = await make_user("fay", account_type="FIRM", organization="Fay Advisory LLP")
    await drain()
    await admin.step_up()
    firm = (await client.get("/v1/firms/mine", headers=admin.h)).json()[0]
    member = await make_user("max")
    inv = (await client.post(f"/v1/firms/{firm['id']}/invitations", headers=admin.h,
                             json={"email": member.email, "roles": ["FIRM_MEMBER"]})).json()
    token = parse_qs(urlparse(inv["devInviteUrl"]).query)["token"][0]
    await client.post("/v1/firms/invitations/accept", headers=member.h, json={"token": token})
    await drain()
    await member.refresh()

    r = await client.post("/v1/professionals", headers=member.h, json={"firmId": firm["id"]})
    assert r.status_code == 201 and r.json()["firmId"] == firm["id"]

    outsider = await make_user("oz", account_type="PROFESSIONAL")
    r = await client.post("/v1/professionals", headers=outsider.h, json={"firmId": firm["id"]})
    assert r.status_code == 403 and r.json()["code"] == "NOT_FIRM_MEMBER"
