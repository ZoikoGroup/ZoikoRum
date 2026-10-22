"""Case owners across the staff console: assign to yourself, reassign, release, escalate and de-escalate, with role
rules per kind of case, eligible owners only, an audit record for every change and a notification for the new owner.
Support requests keep their native owner (support ``assigned_to``)."""

from __future__ import annotations

import uuid

from sqlalchemy import text

from zoikorum.shared.event_catalog import E

A = "/v1/admin/assignments"


async def staff(make_user, name, *roles):
    u = await make_user(name, platform_roles=roles)
    await u.step_up()
    return u


async def audited(sf, action: str) -> int:
    async with sf() as s:
        return await s.scalar(text("SELECT count(*) FROM audit.audit_records WHERE action = :a"), {"a": action})


async def enforcement_case(client, make_user, analyst) -> str:
    subject = await make_user("subject")
    r = await client.post("/v1/admin/enforcement-cases", headers=analyst.idem(), json={
        "subjectType": "IDENTITY", "subjectId": str(subject.id), "signalSource": "MANUAL_REVIEW",
        "summary": "Repeated off-platform payment requests reported by buyers"})
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def test_assign_reassign_release_escalate(client, make_user, drain, sf):
    analyst = await staff(make_user, "ana", "TS_ANALYST")
    other = await staff(make_user, "oli", "FINANCIAL_OPS")  # every staff member works enforcement cases
    case = await enforcement_case(client, make_user, analyst)
    url = f"{A}/ENFORCEMENT_CASE/{case}"

    # Assign to me
    r = await client.put(url, headers=analyst.h, json={"ownerId": str(analyst.id)})
    assert r.status_code == 200, r.text
    assert r.json()["ownerId"] == str(analyst.id) and r.json()["ownerName"] == analyst.user["displayName"]
    mine = (await client.get(A, headers=analyst.h, params={"mine": "true"})).json()
    assert [(a["kind"], a["caseId"]) for a in mine] == [("ENFORCEMENT_CASE", case)]
    assert (await client.get(A, headers=other.h, params={"mine": "true"})).json() == []

    # Reassign to a colleague (the analyst holds the enforcement domain role): audited, the new owner is told.
    r = await client.put(url, headers=analyst.h, json={"ownerId": str(other.id), "note": "Payments angle: please take it"})
    assert r.status_code == 200 and r.json()["ownerId"] == str(other.id)
    await drain()
    async with sf() as s:
        told = (await s.execute(text("SELECT title, url FROM notification.notifications WHERE identity_id = :i AND event_type = :e"),
                                {"i": other.id, "e": E.CASE_ASSIGNED})).all()
    assert [tuple(t) for t in told] == [("A case was assigned to you", "/platform-admin/my-work-queue")]
    assert await audited(sf, "admin.case.assigned") == 1 and await audited(sf, "admin.case.reassigned") == 1

    # The colleague (no enforcement lead role) can take cases but not hand them to others.
    r = await client.put(url, headers=other.h, json={"ownerId": str(analyst.id)})
    assert r.status_code == 403 and r.json()["code"] == "ASSIGN_NOT_ALLOWED"

    # Escalate (reason required), shown to the team; de-escalate.
    assert (await client.post(f"{url}/escalate", headers=other.h, json={"reason": "short"})).status_code == 422
    r = await client.post(f"{url}/escalate", headers=other.h, json={"reason": "Possible organised fraud across accounts"})
    assert r.status_code == 200 and r.json()["escalated"] is True and r.json()["escalationReason"].startswith("Possible")
    team = (await client.get(A, headers=analyst.h, params={"kinds": "ENFORCEMENT_CASE"})).json()
    assert team[0]["escalated"] is True and team[0]["ownerId"] == str(other.id)
    r = await client.post(f"{url}/de-escalate", headers=analyst.h)
    assert r.status_code == 200 and r.json()["escalated"] is False
    assert (await client.post(f"{url}/de-escalate", headers=analyst.h)).status_code == 409
    await drain()
    assert await audited(sf, "admin.case.escalated") == 1 and await audited(sf, "admin.case.de_escalated") == 1

    # The owner releases it: unassigned again and no longer listed.
    r = await client.put(url, headers=other.h, json={"ownerId": None})
    assert r.status_code == 200 and r.json()["ownerId"] is None and r.json()["ownerName"] is None
    await drain()
    assert await audited(sf, "admin.case.released") == 1
    assert (await client.get(A, headers=analyst.h)).json() == []

    # Unknown cases are refused.
    assert (await client.put(f"{A}/ENFORCEMENT_CASE/{uuid.uuid4()}", headers=analyst.h, json={"ownerId": str(analyst.id)})).status_code == 404
    assert (await client.put(f"{A}/ENFORCEMENT_CASE/not-a-case", headers=analyst.h, json={"ownerId": str(analyst.id)})).status_code == 404


async def test_roles_and_eligible_owners(client, make_user, drain, sf):
    analyst = await staff(make_user, "ana", "TS_ANALYST")
    case = await enforcement_case(client, make_user, analyst)
    buyer = await make_user("bea")
    agent = await staff(make_user, "sam", "SUPPORT_AGENT")
    admin = await staff(make_user, "pat", "PLATFORM_ADMIN")

    # Not staff: refused everywhere.
    assert (await client.get(A, headers=buyer.h)).status_code == 403
    assert (await client.put(f"{A}/ENFORCEMENT_CASE/{case}", headers=buyer.h, json={"ownerId": str(buyer.id)})).status_code == 403
    assert (await client.get("/v1/admin/assignable-staff", headers=buyer.h, params={"kind": "DISPUTE"})).status_code == 403

    # A role that does not work the kind cannot touch it.
    r = await client.post(f"{A}/DISPUTE/{uuid.uuid4()}/escalate", headers=agent.h, json={"reason": "Needs a senior mediator now"})
    assert r.status_code == 403 and r.json()["code"] == "CASE_KIND_NOT_ALLOWED"
    assert (await client.get("/v1/admin/assignable-staff", headers=agent.h, params={"kind": "DEAD_LETTER"})).status_code == 403

    # The owner must be staff who works the kind.
    r = await client.put(f"{A}/ENFORCEMENT_CASE/{case}", headers=admin.h, json={"ownerId": str(buyer.id)})
    assert r.status_code == 422 and r.json()["code"] == "OWNER_NOT_ELIGIBLE"
    who = (await client.get("/v1/admin/assignable-staff", headers=admin.h, params={"kind": "SUPPORT_REQUEST"})).json()
    assert {w["name"] for w in who} == {agent.user["displayName"], admin.user["displayName"]}
    assert [w["you"] for w in who if w["id"] == str(admin.id)] == [True]

    # Support requests: the native owner (set by the first answer) is the owner here too, and assigning writes it back.
    req = (await client.post("/v1/support/requests", headers=buyer.h, json={
        "topic": "ACCOUNT", "subject": "Cannot change my email", "message": "The change email form keeps failing for me.",
        "context": {}})).json()
    await client.post(f"/v1/admin/support/requests/{req['id']}/messages", headers=agent.h, json={"message": "Looking into it now.", "resolve": False})
    listed = (await client.get(A, headers=admin.h, params={"kinds": "SUPPORT_REQUEST"})).json()
    assert [(a["caseId"], a["ownerId"]) for a in listed] == [(req["id"], str(agent.id))]
    r = await client.put(f"{A}/SUPPORT_REQUEST/{req['id']}", headers=admin.h, json={"ownerId": str(admin.id)})
    assert r.status_code == 200 and r.json()["ownerId"] == str(admin.id)
    seen = (await client.get(f"/v1/admin/support/requests/{req['id']}", headers=agent.h)).json()
    assert seen["assignedTo"] == str(admin.id) and seen["assignedToName"] == admin.user["displayName"]
    # Assign-to-me needs no lead role; assigning someone else's case to a third person does.
    assert (await client.put(f"{A}/SUPPORT_REQUEST/{req['id']}", headers=agent.h, json={"ownerId": str(agent.id)})).status_code == 200
    assert (await client.put(f"{A}/SUPPORT_REQUEST/{req['id']}", headers=analyst.h, json={"ownerId": str(analyst.id)})).status_code == 403
