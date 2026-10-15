"""User reports: anyone can report a profile; reports feed a Level 0 case for Trust & Safety; the reported person is never
told who reported; confidential reporters are named only to Risk Lead and Legal; reporters hear the outcome."""

from __future__ import annotations

from test_dispute import D, dispute_body, funded_contract, staff

R = "/v1/reports"
BODY = {"category": "OFF_PLATFORM_PAYMENT", "description": "They asked me to pay the next milestone by bank transfer instead."}


async def titles(client, user) -> list[str]:
    return [n["title"] for n in (await client.get("/v1/notifications", headers=user.h)).json()["items"]]


async def test_reports_feed_one_case_protect_the_reporter_and_close_the_loop(client, make_user, drain):
    pro_user, pro, buyer, c = await funded_contract(client, make_user, drain)
    report = {**BODY, "subjectType": "PROFESSIONAL", "subjectId": pro["id"]}
    r = await client.post(R, headers=buyer.h, json=report)
    assert r.status_code == 201 and r.json()["status"] == "RECEIVED" and r.json()["categoryLabel"] == "Asked to pay outside Zoikorum"
    assert (await client.post(R, headers=buyer.h, json=report)).json()["code"] == "REPORT_EXISTS"
    selfie = await client.post(R, headers=pro_user.h, json={**BODY, "subjectType": "PROFESSIONAL", "subjectId": pro["id"]})
    assert selfie.json()["code"] == "SELF_REPORT"

    other = await make_user("ola")  # a second, confidential report on the same profile joins the same case
    r2 = await client.post(R, headers=other.h, json={**report, "confidential": True})
    assert r2.status_code == 201
    await drain()
    assert "Report received" in await titles(client, buyer)
    assert not [t for t in await titles(client, pro_user) if "report" in t.lower()]  # the reported person is not told

    analyst = await staff(make_user, "tess", "TS_ANALYST")
    cases = (await client.get("/v1/admin/enforcement-cases", headers=analyst.h)).json()
    cases = cases["items"] if isinstance(cases, dict) else cases
    (case,) = [x for x in cases if x["signalSource"] == "USER_REPORT"]
    assert case["subjectId"] == pro["id"] and case["level"] == 0 and len(case["evidenceRefs"]) == 2
    seen = (await client.get(f"/v1/admin/enforcement-cases/{case['id']}/reports", headers=analyst.h)).json()
    assert {x["reporter"] for x in seen} == {buyer.user["displayName"], "Confidential reporter"}
    lead = await staff(make_user, "rhea", "RISK_LEAD")
    seen = (await client.get(f"/v1/admin/enforcement-cases/{case['id']}/reports", headers=lead.h)).json()
    assert "Confidential reporter" not in {x["reporter"] for x in seen}
    assert (await client.get(f"/v1/admin/enforcement-cases/{case['id']}/reports", headers=buyer.h)).status_code == 403

    r = await client.post(f"/v1/admin/enforcement-cases/{case['id']}/close", headers=analyst.h,
                          json={"reason": "Checked the conversation; the request came from a third party."})
    assert r.status_code == 200 and r.json()["status"] == "CLOSED_NO_ACTION"
    await drain()
    mine = (await client.get(f"{R}/mine", headers=buyer.h)).json()
    assert mine[0]["status"] == "CLOSED" and mine[0]["outcome"] == "NO_ACTION"
    assert "Your report was reviewed" in await titles(client, buyer)


async def test_a_report_from_the_other_side_of_an_open_dispute_is_marked(client, make_user, drain):
    pro_user, pro, buyer, c = await funded_contract(client, make_user, drain)
    assert (await client.post(D, headers=buyer.idem(), json=dispute_body(c))).status_code == 201
    await drain()
    r = await client.post(R, headers=pro_user.h, json={**BODY, "category": "HARASSMENT_OR_ABUSE",
                                                       "subjectType": "ORGANIZATION", "subjectId": c["organizationId"]})
    assert r.status_code == 201
    analyst = await staff(make_user, "tess", "TS_ANALYST")
    cases = (await client.get("/v1/admin/enforcement-cases", headers=analyst.h)).json()
    cases = cases["items"] if isinstance(cases, dict) else cases
    (case,) = [x for x in cases if x["signalSource"] == "USER_REPORT"]
    (seen,) = (await client.get(f"/v1/admin/enforcement-cases/{case['id']}/reports", headers=analyst.h)).json()
    assert seen["possibleRetaliation"] is True


async def test_reports_are_limited_per_day(client, make_user, drain):
    reporter = await make_user("rex")
    targets = [await make_user(f"t{i}") for i in range(6)]
    codes = [(await client.post(R, headers=reporter.h, json={**BODY, "subjectType": "IDENTITY", "subjectId": str(t.id)})).status_code
             for t in targets]
    assert codes[:5] == [201] * 5 and codes[5] == 429


async def test_platform_kpis_cover_engagements_money_disputes_and_enforcement(client, make_user, drain):
    from test_dispute import D, dispute_body, funded_contract

    pro_user, pro, buyer, c = await funded_contract(client, make_user, drain)
    await client.post(D, headers=buyer.idem(), json=dispute_body(c))
    await drain()
    admin = await make_user("kpi-admin", platform_roles=("PLATFORM_ADMIN",))
    await admin.step_up()  # staff sign in with two-step
    assert (await client.get("/v1/admin/kpis", headers=buyer.h)).status_code == 403
    k = (await client.get("/v1/admin/kpis", headers=admin.h)).json()
    assert k["engagements"]["engagementsStarted"] >= 1 and k["engagements"]["activeBuyerOrganisations"] >= 1
    usd = next(r for r in k["payments"]["byCurrency"] if r["currency"] == "USD")
    assert usd["fundedMinor"] > 0 and usd["frozenNowMinor"] > 0
    assert k["disputes"]["opened"] >= 1 and k["disputes"]["openNow"] >= 1 and k["board"]["disputeRatePct"] is not None
    assert k["onboarding"]["profilesPublished"] >= 1 and k["trust"]["tiersNow"].get("B", 0) >= 1
    assert set(k["enforcement"]) >= {"casesOpened", "openNow", "incidentsOpenNow"}
    health = (await client.get("/v1/analytics/marketplace-health", headers=admin.h)).json()
    assert health["activations"] >= 1 and health["disputesOpened"] >= 1 and health["trustTierDistribution"]


async def test_report_sessions_are_read_only():
    import pytest
    from sqlalchemy import text
    from sqlalchemy.exc import DBAPIError

    from zoikorum.shared.db import _read_only_session

    gen = _read_only_session()
    session = await gen.__anext__()
    assert (await session.execute(text("SELECT 1"))).scalar() == 1
    with pytest.raises(DBAPIError, match="read-only"):
        await session.execute(text("CREATE TEMP TABLE should_fail (x int)"))
    await gen.aclose()
