"""Staff and home-page tools the web app calls: ledger verification and the dashboard summaries with their freshness."""

from __future__ import annotations

from sqlalchemy import text


async def test_ledger_verification_from_the_audit_page(client, make_user, drain, sf):
    officer = await make_user("auditor", platform_roles=("COMPLIANCE_OFFICER",))
    analyst = await make_user("analyst", platform_roles=("TS_ANALYST",))
    buyer = await make_user("buyer")
    await officer.step_up()
    await analyst.step_up()
    await drain()

    ok = await client.post("/v1/audit/chain/verify", headers=officer.h)
    assert ok.status_code == 200, ok.text
    assert ok.json()["valid"] is True and ok.json()["checked"] > 0 and len(ok.json()["headHash"]) == 64
    assert (await client.post("/v1/audit/chain/verify", headers=analyst.h)).status_code == 403
    assert (await client.post("/v1/audit/chain/verify", headers=buyer.h)).status_code == 403

    async with sf() as s, s.begin():
        await s.execute(text("SET session_replication_role = replica"))  # a DBA bypassing the append-only triggers
        await s.execute(text("UPDATE audit.audit_records SET details = '{\"forged\": true}' WHERE seq = 2"))
    broken = (await client.post("/v1/audit/chain/verify", headers=officer.h)).json()
    assert broken == {"valid": False, "checked": 1, "brokenAtSeq": 2}


async def test_dashboard_summaries_report_protected_money_and_freshness(client, make_user, drain):
    from test_dispute import funded_contract

    pro_user, _, buyer, c = await funded_contract(client, make_user, drain)
    currency = c["milestones"][0]["amount"]["currency"]
    funded = c["milestones"][0]["amount"]["amountMinor"]

    mine = await client.get("/v1/dashboards/buyer", headers=buyer.h, params={"organizationId": c["organizationId"]})
    assert mine.status_code == 200, mine.text
    assert mine.json()["fundsInProtectionMinor"] == {currency: funded} and mine.json()["lastEventAt"]
    theirs = (await client.get("/v1/dashboards/professional", headers=pro_user.h)).json()
    assert theirs["pendingReleaseMinor"] == {currency: funded} and theirs["lastEventAt"]

    outsider = await make_user("nosy")
    assert (await client.get("/v1/dashboards/buyer", headers=outsider.h, params={"organizationId": c["organizationId"]})).status_code == 404
