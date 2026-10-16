"""Open briefs: a buyer posts a need; matching professionals (specialization and served country) say they are interested."""

from __future__ import annotations

from sqlalchemy import text

from test_proposal import buyer_org
from test_search import publish

B = "/v1/open-briefs"


def brief(org, **over):
    return {"organizationId": org["id"], "service": "Transfer pricing documentation", "specialization": "transfer-pricing",
            "objective": "Master and local files for FY2026", "budget": {"maxMinor": 1_500_000, "currency": "USD"}, **over}


async def test_a_brief_reaches_matching_professionals_and_the_buyer_sees_who_is_interested(client, make_user, drain, sf):
    buyer, org = await buyer_org(client, make_user, drain, "brief-buyer")
    fit, fit_pro = await publish(client, make_user, drain, "brief-fit", headline="TP adviser", primary="transfer-pricing")
    other, _ = await publish(client, make_user, drain, "brief-cfo", headline="CFO", primary="fractional-cfo")
    away, _ = await publish(client, make_user, drain, "brief-away", headline="TP adviser", primary="transfer-pricing", served=("IN",))

    r = await client.post(B, headers=buyer.idem(), json=brief(org))
    assert r.status_code == 201, r.text
    b = r.json()
    assert b["status"] == "OPEN" and b["specializationName"] and b["interests"] == []
    assert (await client.post(B, headers=buyer.idem(), json=brief(org, specialization="no-such-thing"))).json()["code"] == "UNKNOWN_SPECIALIZATION"

    seen = (await client.get(f"{B}/matching", headers=fit.h)).json()
    assert [x["id"] for x in seen] == [b["id"]]
    assert seen[0]["organizationId"] is None and seen[0]["interests"] is None  # no buyer name, no other professionals
    assert (await client.get(f"{B}/matching", headers=other.h)).json() == []  # another specialization
    assert (await client.get(f"{B}/matching", headers=away.h)).json() == []  # does not serve the buyer's country
    blocked = await client.post(f"{B}/{b['id']}/interest", headers=away.idem(), json={})
    assert blocked.json()["code"] == "JURISDICTION_CONFLICT"

    r = await client.post(f"{B}/{b['id']}/interest", headers=fit.idem(), json={"note": "Done this for three SaaS groups."})
    assert r.status_code == 200 and r.json()["myInterest"] is True and r.json()["interestCount"] == 1
    await client.post(f"{B}/{b['id']}/interest", headers=fit.idem(), json={})  # saying it twice changes nothing
    mine = (await client.get(f"{B}/mine", headers=buyer.h, params={"organizationId": org["id"]})).json()
    assert [i["professional"]["id"] for i in mine[0]["interests"]] == [fit_pro["id"]]
    assert mine[0]["interests"][0]["note"] == "Done this for three SaaS groups."
    await drain()
    async with sf() as s:
        told = await s.scalar(text("SELECT count(*) FROM notification.notifications WHERE identity_id = :b AND title LIKE '%interested%'"),
                              {"b": str(buyer.id)})
    assert told == 1

    closed = (await client.post(f"{B}/{b['id']}/close", headers=buyer.idem())).json()
    assert closed["status"] == "CLOSED"
    assert (await client.get(f"{B}/matching", headers=fit.h)).json() == []
    late = await client.post(f"{B}/{b['id']}/interest", headers=other.idem(), json={})
    assert late.status_code == 404  # not their specialization
