from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

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
    await drain()
    body = {"objectId": str(user.id), "format": "json"}
    assert (await client.post("/v1/audit/exports", headers=user.h, json=body)).status_code == 403
    r = await client.post("/v1/audit/exports", headers=officer.h, json=body)
    assert r.status_code == 201 and r.json()["recordCount"] >= 1
    r = await client.get(f"/v1/audit/exports/{r.json()['id']}/download", headers=officer.h)
    assert r.status_code == 200 and r.headers["X-Content-SHA256"]
