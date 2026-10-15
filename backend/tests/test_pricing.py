"""Pricing guidance: middle half of the range, from at least five data points, never a single price."""

from __future__ import annotations

from test_search import publish

URL = "/v1/pricing/estimate"


async def test_rates_show_only_from_enough_professionals(client, make_user, drain):
    users = []
    for i, rate in enumerate((10_000, 12_000, 15_000, 18_000)):
        u, _ = await publish(client, make_user, drain, f"rate{i}", headline="Fractional CFO", primary="fractional-cfo")
        await client.patch("/v1/professionals/me", headers=u.h, json={"indicativeRate": {"amountMinor": rate, "currency": "USD"}, "rateUnit": "HOUR"})
        users.append(u)
    viewer = users[0]
    few = (await client.get(URL, headers=viewer.h, params={"specialization": "fractional-cfo"})).json()
    assert few["rates"] == {} and few["engagements"] is None  # four people: nothing that could identify one of them

    u, _ = await publish(client, make_user, drain, "rate4", headline="Fractional CFO", primary="fractional-cfo")
    await client.patch("/v1/professionals/me", headers=u.h, json={"indicativeRate": {"amountMinor": 30_000, "currency": "USD"}, "rateUnit": "HOUR"})
    est = (await client.get(URL, headers=viewer.h, params={"specialization": "fractional-cfo"})).json()
    hour = est["rates"]["HOUR"]
    assert est["basis"]["level"] == "specialization" and hour["sampleSize"] == 5
    assert hour["low"] == 12_000 and hour["typical"] == 15_000 and hour["high"] == 18_000
    assert (await client.get(URL, headers=viewer.h, params={"specialization": "fractional-cfo", "currency": "EUR"})).json()["basis"] is None
    assert (await client.get(URL, params={"specialization": "fractional-cfo"})).status_code == 401
