from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from approvalhelp import approve, approved
from zoikorum.domains.audit import service as audit


async def test_every_event_is_audited_with_valid_hash_chain(client, make_user, drain, sf):
    await make_user("a")
    await make_user("b")
    await drain()
    async with sf() as s:
        n = await s.scalar(text("SELECT count(*) FROM audit.audit_records"))
        events = await s.scalar(text("SELECT count(*) FROM platform.outbox"))
        assert n == events and n >= 2  # every event became an audit record
        result = await audit.verify_chain(s)
    assert result["valid"] is True and result["checked"] == n


async def test_audit_ledger_rejects_update_and_delete(make_user, drain, sf):
    await make_user("a")
    await drain()
    with pytest.raises(DBAPIError):
        async with sf() as s, s.begin():
            await s.execute(text("UPDATE audit.audit_records SET action = 'tampered'"))
    with pytest.raises(DBAPIError):
        async with sf() as s, s.begin():
            await s.execute(text("DELETE FROM audit.audit_records"))


async def test_tampering_is_detected_by_chain_validation(make_user, drain, sf):
    await make_user("a")
    await make_user("b")
    await drain()
    async with sf() as s, s.begin():
        await s.execute(text("SET session_replication_role = replica"))  # simulate a DBA bypassing triggers
        await s.execute(text("UPDATE audit.audit_records SET details = '{\"forged\": true}' WHERE seq = 2"))
    async with sf() as s, s.begin():
        result = await audit.verify_chain(s)
    assert result == {"valid": False, "checked": 1, "brokenAtSeq": 2}


async def test_export_requires_compliance_authority(client, make_user, drain):
    user = await make_user("u")
    officer = await make_user("officer", platform_roles=("COMPLIANCE_OFFICER",))
    legal = await make_user("legal", platform_roles=("LEGAL",))
    await drain()
    body = {"objectId": str(user.id), "format": "json", "justification": "Regulator asked for this account's trail"}
    assert (await client.post("/v1/audit/exports", headers=user.h, json=body)).status_code == 403
    assert (await client.post("/v1/audit/exports", headers=officer.h, json=body)).status_code == 401  # staff need two-step first
    await officer.step_up()
    no_reason = await client.post("/v1/audit/exports", headers=officer.h, json={k: v for k, v in body.items() if k != "justification"})
    assert no_reason.json()["code"] == "JUSTIFICATION_REQUIRED"
    r = await client.post("/v1/audit/exports", headers=officer.h, json=body)
    assert r.status_code == 202 and r.json()["kind"] == "AUDIT_EXPORT"  # evidence leaves only with a second person's approval
    export_id = r.json()["payload"]["exportId"]
    assert (await client.get(f"/v1/audit/exports/{export_id}", headers=officer.h)).json()["status"] == "REQUESTED"
    assert (await client.get(f"/v1/audit/exports/{export_id}/download", headers=officer.h)).json()["code"] == "EXPORT_NOT_READY"
    done = await approved(client, r, legal)
    assert done["result"]["exportId"] == export_id and done["result"]["recordCount"] >= 1
    r = await client.get(f"/v1/audit/exports/{export_id}/download", headers=officer.h)
    assert r.status_code == 200 and r.headers["X-Content-SHA256"]

    # Rejected: the export is never made.
    r = await client.post("/v1/audit/exports", headers=officer.h, json=body)
    await legal.step_up()
    no = await client.post(f"/v1/admin/approval-requests/{r.json()['id']}/decision", headers=legal.h,
                           json={"approve": False, "note": "Use the regulator pack instead"})
    assert no.json()["status"] == "REJECTED"
    assert (await client.get(f"/v1/audit/exports/{r.json()['payload']['exportId']}", headers=officer.h)).json()["status"] == "REJECTED"


async def test_activity_feed_newest_first(client, make_user, drain):
    buyer = await make_user("bea")
    await drain()
    await buyer.refresh()  # organization roles reach the token on refresh
    org = (await client.get("/v1/organizations/mine", headers=buyer.h)).json()[0]
    params = {"tenantId": org["id"], "limit": 10}
    oldest = (await client.get("/v1/audit/records", headers=buyer.h, params=params)).json()["items"]
    newest = (await client.get("/v1/audit/records", headers=buyer.h, params={**params, "newestFirst": "true"})).json()["items"]
    assert len(oldest) >= 2 and [r["seq"] for r in newest] == sorted((r["seq"] for r in oldest), reverse=True)
