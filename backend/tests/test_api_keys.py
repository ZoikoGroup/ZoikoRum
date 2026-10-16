"""Organisation API keys: shown once, read-only or read-write, act as their creator and never more, never confirm
two-step actions, blocked from sign-in/staff/key endpoints, own rate budget; and the procurement pack."""

from __future__ import annotations

from sqlalchemy import text

from test_proposal import buyer_org


async def test_api_keys_act_as_their_creator_within_their_scope(client, make_user, drain, sf):
    from zoikorum.domains.buyer import api_keys

    buyer, org = await buyer_org(client, make_user, drain, "key-buyer")
    await buyer.step_up()
    K = f"/v1/organizations/{org['id']}/api-keys"
    read = (await client.post(K, headers=buyer.h, json={"name": "Reporting export", "scope": "READ"})).json()
    assert read["key"].startswith(read["prefix"] + "_") and "not shown again" in read["note"]
    assert "key" not in (await client.get(K, headers=buyer.h)).json()[0]  # never listed again
    rh = {"Authorization": f"Bearer {read['key']}"}

    assert (await client.get(f"/v1/organizations/{org['id']}/business-units", headers=rh)).status_code == 200
    assert (await client.post(f"/v1/organizations/{org['id']}/business-units", headers=rh, json={"name": "Ops"})).json()["code"] == "API_KEY_READ_ONLY"
    assert (await client.get("/v1/me", headers=rh)).json()["code"] == "API_KEY_NOT_ALLOWED"
    assert (await client.get(K, headers=rh)).json()["code"] == "API_KEY_NOT_ALLOWED"

    write = (await client.post(K, headers=buyer.h, json={"name": "ERP sync", "scope": "WRITE"})).json()
    wh = {"Authorization": f"Bearer {write['key']}"}
    unit = await client.post(f"/v1/organizations/{org['id']}/business-units", headers=wh, json={"name": "Ops"})
    assert unit.status_code == 201, unit.text
    other = (await client.post(f"/v1/organizations/{org['id']}/business-units", headers=wh, json={"name": "Tax"})).json()
    merged = await client.post(f"/v1/organizations/{org['id']}/business-units/{unit.json()['id']}/merge", headers=wh, json={"targetId": other["id"]})
    assert merged.status_code == 401 and merged.json()["code"] == "STEP_UP_REQUIRED"  # a key never confirms two-step actions

    async with sf() as s:
        budget = await api_keys.budget_of(s, write["key"])
    assert budget == (write["prefix"], api_keys.TIER_LIMITS["STANDARD"])

    await client.post(f"{K}/{read['id']}/revoke", headers=buyer.h)
    api_keys._cache.clear()
    assert (await client.get(f"/v1/organizations/{org['id']}/business-units", headers=rh)).status_code == 401
    async with sf() as s, s.begin():  # the creator stops administering the organisation: their keys stop too
        await s.execute(text("UPDATE buyer.members SET roles = array_remove(roles, 'ORG_ADMIN') WHERE identity_id = :i"), {"i": buyer.id})
    assert (await client.get(f"/v1/organizations/{org['id']}/business-units", headers=wh)).status_code == 401
    assert (await client.get("/v1/organizations/mine", headers={"Authorization": "Bearer zk_madeup_key"})).status_code == 401


async def test_procurement_pack_states_only_what_is_configured(client, make_user, drain):
    buyer, _ = await buyer_org(client, make_user, drain, "proc-buyer")
    pack = (await client.get("/v1/procurement-pack", headers=buyer.h, params={"format": "json"})).json()
    areas = {c["area"] for c in pack["controls"]}
    assert {"Sign-in", "Encryption at rest", "Audit", "Money"} <= areas
    assert "No third-party certification" in pack["certifications"] and len(pack["fingerprintSha256"]) == 64
    pdf = await client.get("/v1/procurement-pack", headers=buyer.h)
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF-")
    assert (await client.get("/v1/procurement-pack")).status_code == 401
