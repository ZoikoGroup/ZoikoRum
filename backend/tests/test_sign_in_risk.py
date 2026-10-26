"""Advisory sign-in risk signals (identity/risk.py): new device, new country, impossible travel, velocity, many accounts
from one address. They never block a sign-in."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from zoikorum.shared import clock

LONDON, SYDNEY = "51.5072,-0.1276", "-33.8688,151.2093"
CHROME = "Mozilla/5.0 (Windows NT 10.0) Chrome/130.0 Safari/537.36"
FIREFOX = "Mozilla/5.0 (X11; Linux x86_64) Firefox/131.0"


@pytest.mark.unit
def test_distance_and_grading():
    from zoikorum.domains.identity import risk

    assert 16_900 < risk.distance_km((51.5072, -0.1276), (-33.8688, 151.2093)) < 17_100
    assert risk.grade([]) == "LOW" and risk.grade(["NEW_DEVICE"]) == "MEDIUM"
    assert risk.grade(["IMPOSSIBLE_TRAVEL"]) == "HIGH" and risk.grade(["VELOCITY", "NEW_DEVICE"]) == "HIGH"


async def _login(client, user, ua, country, latlong):
    r = await client.post("/v1/auth/login", json={"email": user.email, "password": user.password},
                          headers={"User-Agent": ua, "X-Client-Geo-Country": country, "X-Client-Geo-Lat-Long": latlong})
    assert r.status_code == 200, r.text  # advisory: never refused
    user.access = r.json()["tokens"]["accessToken"]


async def _signals(sf, user) -> list[dict]:
    """Read from the database: a token minted at a travelled clock is not valid at the real time."""
    from zoikorum.domains.identity import risk

    async with sf() as s:
        return await risk.recent(s, user.id)


async def test_new_device_country_and_impossible_travel(client, make_user, sf):
    user = await make_user("traveller")
    start = datetime.now(timezone.utc)
    await _login(client, user, CHROME, "GB", LONDON)
    clock.set_now(start + timedelta(hours=2))  # London to Sydney in two hours
    await _login(client, user, FIREFOX, "AU", SYDNEY)
    latest = (await _signals(sf, user))[0]
    assert {"NEW_DEVICE", "NEW_COUNTRY", "IMPOSSIBLE_TRAVEL"} <= set(latest["signals"]) and latest["risk"] == "HIGH"
    assert latest["country"] == "AU" and "ip" not in latest
    clock.set_now(start + timedelta(days=2))  # a day later the same trip is plausible
    await _login(client, user, FIREFOX, "GB", LONDON)
    assert "IMPOSSIBLE_TRAVEL" not in (await _signals(sf, user))[0]["signals"]
    clock.set_now(None)
    await _login(client, user, FIREFOX, "GB", LONDON)
    mine = (await client.get("/v1/me/sign-in-signals", headers=user.h)).json()
    assert len(mine) == 5 and all("ip" not in x and "ipHash" not in x for x in mine)


async def test_velocity(client, make_user, monkeypatch):
    from zoikorum.config import get_settings

    monkeypatch.setattr(get_settings(), "sign_in_velocity_per_hour", 3)
    user = await make_user("busy")
    for _ in range(4):
        await _login(client, user, CHROME, "GB", LONDON)
    assert "VELOCITY" in (await client.get("/v1/me/sign-in-signals", headers=user.h)).json()[0]["signals"]
    other = await make_user("nosy")
    assert (await client.get(f"/v1/admin/identities/{user.id}/sign-in-signals", headers=other.h)).status_code == 403
