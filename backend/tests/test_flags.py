"""Feature flags: declared in code, rolled out by percentage or organisation, audited; ranking experiments need a
passing fairness check first."""

from __future__ import annotations

from test_proposal import buyer_org, tier_b
from zoikorum.domains.admin.flags import bucket

KEY = "search.new_talent_boost"


def test_the_same_person_always_lands_in_the_same_bucket():
    assert bucket(KEY, "org-1") == bucket(KEY, "org-1") and 0 <= bucket(KEY, "org-1") < 100
    assert len({bucket(KEY, f"org-{i}") for i in range(200)}) > 50  # spread across buckets


async def test_rollout_to_named_organisations_and_the_ranking_experiment(client, make_user, drain):
    pro_user, pro = await tier_b(client, make_user, drain, "flag-pro")
    buyer, org = await buyer_org(client, make_user, drain, "flag-buyer")
    other, _ = await buyer_org(client, make_user, drain, "flag-other")
    admin = await make_user("flag-admin", platform_roles=("PLATFORM_ADMIN",))
    await admin.step_up()
    assert (await client.get("/v1/flags", headers=buyer.h)).json() == {KEY: False}

    fairness = (await client.get(f"/v1/admin/flags/{KEY}/fairness", headers=admin.h)).json()
    assert fairness["passes"] is True and {g["group"] for g in fairness["groups"]} >= {"Amber light"}
    body = {"rolloutPct": 0, "organizationIds": [org["id"]], "reason": "Pilot with one buyer organisation"}
    assert (await client.put(f"/v1/admin/flags/{KEY}", headers=buyer.h, json=body)).status_code == 403
    r = (await client.put(f"/v1/admin/flags/{KEY}", headers=admin.h, json=body)).json()
    assert r["organizationIds"] == [org["id"]] and r["rankingExperiment"] is True
    assert (await client.get("/v1/flags", headers=buyer.h)).json() == {KEY: True}
    assert (await client.get("/v1/flags", headers=other.h)).json() == {KEY: False}
    assert (await client.put("/v1/admin/flags/unknown.flag", headers=admin.h, json=body)).status_code == 404

    found = (await client.get("/v1/search/professionals", headers=buyer.h, params={"q": "Tax adviser"})).json()
    item = next(i for i in found["items"] if i["professionalId"] == pro["id"])
    assert "Verified and new to Zoikorum" in item["whyThisResult"]
    plain = (await client.get("/v1/search/professionals", headers=other.h, params={"q": "Tax adviser"})).json()
    assert "Verified and new to Zoikorum" not in next(i for i in plain["items"] if i["professionalId"] == pro["id"])["whyThisResult"]
