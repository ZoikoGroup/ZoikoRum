"""Saved buyers (Professional Dashboard s.17): a professional's client list, limited to organisations that made contact."""

from __future__ import annotations

from sqlalchemy import text

from test_proposal import R, buyer_org, request_body, tier_b

S = "/v1/professionals/me/saved-buyers"


async def test_save_only_buyers_who_made_contact(client, make_user, drain):
    pro_user, pro = await tier_b(client, make_user, drain, "ines")
    buyer, org = await buyer_org(client, make_user, drain)
    other_buyer, other_org = await buyer_org(client, make_user, drain, "olaf")
    assert (await client.get("/v1/professionals/me/buyer-candidates", headers=pro_user.h)).json() == []

    await client.post(R, headers=buyer.idem(), json=request_body(org, pro))
    await drain()
    (candidate,) = (await client.get("/v1/professionals/me/buyer-candidates", headers=pro_user.h)).json()
    assert candidate["organizationId"] == org["id"] and candidate["requests"] == 1 and candidate["saved"] is False

    refused = await client.post(S, headers=pro_user.h, json={"organizationId": other_org["id"]})
    assert refused.json()["code"] == "NO_RELATIONSHIP"  # no buyer directory, no cold outreach
    saved = await client.post(S, headers=pro_user.h, json={"organizationId": org["id"], "note": "Prefers calls on Tuesdays"})
    assert saved.status_code == 201
    entry = saved.json()
    assert entry["requests"] == 1 and entry["note"] == "Prefers calls on Tuesdays" and entry["alerts"] is True and entry["name"]
    again = await client.post(S, headers=pro_user.h, json={"organizationId": org["id"]})
    assert again.json()["id"] == entry["id"]  # saving twice keeps one entry

    patched = await client.patch(f"{S}/{entry['id']}", headers=pro_user.h, json={"note": "  ", "alerts": False})
    assert patched.json()["note"] is None and patched.json()["alerts"] is False
    stranger_pro, _ = await tier_b(client, make_user, drain, "sven")
    assert (await client.patch(f"{S}/{entry['id']}", headers=stranger_pro.h, json={"note": "x"})).status_code == 404
    assert (await client.delete(f"{S}/{entry['id']}", headers=stranger_pro.h)).status_code == 404
    assert [b["id"] for b in (await client.get(S, headers=pro_user.h)).json()] == [entry["id"]]
    assert (await client.delete(f"{S}/{entry['id']}", headers=pro_user.h)).status_code == 204
    assert (await client.get(S, headers=pro_user.h)).json() == []


async def test_saved_buyer_requests_are_always_emailed(client, make_user, drain, sf):
    pro_user, pro = await tier_b(client, make_user, drain, "ivy")
    buyer, org = await buyer_org(client, make_user, drain)
    await client.post(R, headers=buyer.idem(), json=request_body(org, pro))
    await drain()
    await client.post(S, headers=pro_user.h, json={"organizationId": org["id"]})
    prefs = await client.put("/v1/notification-preferences", headers=pro_user.h,
                             json={"email": False, "inApp": True, "sms": False, "marketing": False})
    assert prefs.status_code == 200, prefs.text

    await client.post(R, headers=buyer.idem(), json=request_body(org, pro))
    await drain()
    me = (await client.get("/v1/me", headers=pro_user.h)).json()
    async with sf() as s:
        rows = (await s.execute(text("SELECT title, email_status FROM notification.notifications WHERE identity_id = :i "
                                     "AND event_type LIKE '%proposal.request.created%' ORDER BY created_at"), {"i": me["id"]})).all()
    assert rows[-1].title == "New request from a saved buyer" and rows[-1].email_status != "DISABLED"
