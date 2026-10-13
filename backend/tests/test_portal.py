"""Customer portal backend: account settings, sessions, privacy requests, organisation profile and billing
contacts, notification preferences, collections and compare."""

from __future__ import annotations

import uuid

from sqlalchemy import text

from test_search import publish


async def test_account_settings_profile_is_encrypted_and_validated(client, make_user, sf):
    u = await make_user("bea")
    r = await client.patch("/v1/me", headers=u.h, json={"phone": "+12025550187", "language": "en-GB", "timeZone": "Europe/London"})
    assert r.status_code == 200 and r.json()["phone"] == "+12025550187" and r.json()["timeZone"] == "Europe/London"
    async with sf() as s:
        stored = await s.scalar(text("SELECT phone_enc FROM identity.identities WHERE id = :i"), {"i": u.id})
    assert stored and "2025550187" not in stored  # encrypted at rest
    assert (await client.patch("/v1/me", headers=u.h, json={"phone": "12345"})).status_code == 422
    r = await client.patch("/v1/me", headers=u.h, json={"timeZone": "Mars/Olympus"})
    assert r.status_code == 422 and r.json()["code"] == "INVALID_TIME_ZONE"
    assert (await client.patch("/v1/me", headers=u.h, json={"phone": ""})).json()["phone"] is None


async def test_sessions_can_be_listed_and_signed_out(client, make_user):
    u = await make_user("bea")
    login = (await client.post("/v1/auth/login", json={"email": u.email, "password": u.password})).json()
    other = login["tokens"]["refreshToken"]
    sessions = (await client.get("/v1/me/sessions", headers=u.h)).json()
    assert len(sessions) == 2 and sum(s["current"] for s in sessions) == 1
    target = next(s for s in sessions if not s["current"])
    assert (await client.delete(f"/v1/me/sessions/{target['id']}", headers=u.h)).status_code == 204
    assert (await client.post("/v1/auth/refresh", json={"refreshToken": other})).status_code == 401
    stranger = await make_user("sam")
    assert (await client.delete(f"/v1/me/sessions/{sessions[0]['id']}", headers=stranger.h)).status_code == 404


async def test_privacy_requests_are_logged_once(client, make_user):
    u = await make_user("bea")
    first = (await client.post("/v1/me/data-requests", headers=u.h, json={"requestType": "ACCESS"})).json()
    again = (await client.post("/v1/me/data-requests", headers=u.h, json={"requestType": "ACCESS"})).json()
    assert first["status"] == "RECEIVED" and again["id"] == first["id"]  # one open request per type
    refused = await client.post("/v1/me/data-requests", headers=u.h, json={"requestType": "ERASURE"})
    assert refused.json()["code"] == "STEP_UP_REQUIRED"  # deleting an account needs a fresh two-step check
    await u.step_up()
    await client.post("/v1/me/data-requests", headers=u.h, json={"requestType": "ERASURE"})
    assert {r["requestType"] for r in (await client.get("/v1/me/data-requests", headers=u.h)).json()} == {"ACCESS", "ERASURE"}


async def test_organisation_profile_and_billing_contacts(client, make_user, drain):
    admin = await make_user("dana", account_type="ENTERPRISE", organization="Acme Corp")
    await drain()
    await admin.refresh()
    org = next(o for o in (await client.get("/v1/organizations/mine", headers=admin.h)).json() if o["orgType"] != "INDIVIDUAL")
    r = await client.patch(f"/v1/organizations/{org['id']}", headers=admin.h,
                           json={"industry": "Professional Services", "timeZone": "America/New_York"})
    assert r.status_code == 200 and r.json()["industry"] == "Professional Services" and r.json()["timeZone"] == "America/New_York"

    members = (await client.get(f"/v1/organizations/{org['id']}/members", headers=admin.h)).json()
    assert members[0]["lastActiveAt"] is not None
    url = f"/v1/organizations/{org['id']}/billing-contacts"
    r = await client.put(url, headers=admin.h, json={"primaryIdentityId": str(admin.id)})
    assert r.status_code == 200 and r.json()[0]["isPrimary"] is True
    r = await client.put(url, headers=admin.h, json={"primaryIdentityId": str(uuid.uuid4())})
    assert r.status_code == 422 and r.json()["code"] == "NOT_A_MEMBER"
    outsider = await make_user("oz")
    assert (await client.get(url, headers=outsider.h)).status_code in (403, 404)


async def test_notification_preferences(client, make_user):
    u = await make_user("bea")
    defaults = (await client.get("/v1/notification-preferences", headers=u.h)).json()
    assert defaults["email"] is True and defaults["sms"] is False and "always sent by email" in defaults["mandatoryNotice"]
    r = await client.put("/v1/notification-preferences", headers=u.h, json={"email": True, "inApp": False, "sms": True, "marketing": False})
    assert r.json()["inApp"] is False and r.json()["sms"] is True
    assert (await client.get("/v1/notification-preferences", headers=u.h)).json()["sms"] is True


async def test_collections_compare_and_enriched_saved_list(client, make_user, drain):
    _, a = await publish(client, make_user, drain, "ann", headline="Fractional CFO", primary="fractional-cfo", offering_price=150000)
    _, b = await publish(client, make_user, drain, "ben", headline="Tax adviser", primary="transfer-pricing")
    buyer = await make_user("bea")
    c = (await client.post("/v1/saved/collections", headers=buyer.h, json={"name": "Q1 2027 Advisory"})).json()
    assert (await client.post("/v1/saved/collections", headers=buyer.h, json={"name": "Q1 2027 Advisory"})).status_code == 409
    r = await client.post(f"/v1/saved/collections/{c['id']}/items", headers=buyer.h, json={"professionalIds": [a["id"], b["id"]]})
    assert r.status_code == 200 and r.json()["count"] == 2

    saved = (await client.get("/v1/saved/professionals", headers=buyer.h)).json()  # adding to a collection also saves
    ann = next(s for s in saved if s["displayName"] == "Ann")
    assert ann["collectionIds"] == [c["id"]] and ann["startingPrice"] == {"amountMinor": 150000, "currency": "USD"}
    assert ann["specializations"] == ["Fractional CFO"] and ann["dimensions"]["restrictions"] == "CLEAR"

    await client.delete(f"/v1/saved/collections/{c['id']}/items/{b['id']}", headers=buyer.h)
    assert (await client.get("/v1/saved/collections", headers=buyer.h)).json()[0]["count"] == 1
    await client.delete(f"/v1/saved/collections/{c['id']}", headers=buyer.h)
    assert len((await client.get("/v1/saved/professionals", headers=buyer.h)).json()) == 2  # still saved
    other = await make_user("oli")
    assert (await client.post(f"/v1/saved/collections/{c['id']}/items", headers=other.h,
                              json={"professionalIds": [a["id"]]})).status_code == 404

    cmp = (await client.get("/v1/compare", params={"ids": f"{a['id']},{b['id']}"})).json()
    assert [x["displayName"] for x in cmp] == ["Ann", "Ben"] and cmp[0]["specializations"] == ["Fractional CFO"]
    four = ",".join(str(uuid.uuid4()) for _ in range(4))
    r = await client.get("/v1/compare", params={"ids": four})
    assert r.status_code == 422 and r.json()["code"] == "COMPARE_LIMIT"
