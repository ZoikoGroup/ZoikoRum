"""Maker-checker for privileged staff actions (admin/approvals.py), just-in-time staff roles, the admin session audience
and staff suspension (staff admin console handoff, P0)."""

from __future__ import annotations

import uuid
from datetime import timedelta

from sqlalchemy import text

from approvalhelp import A, approve
from test_dispute import staff
from zoikorum.shared import clock
from zoikorum.shared.relay import fire_due_timers

WHY = "Needed for the payments incident rota this week"


def grant_url(who) -> str:
    return f"/v1/admin/identities/{who.id}/platform-roles"


async def decide(client, who, request, approve_: bool, note: str | None = None):
    await who.step_up()
    return await client.post(f"{A}/{request['id']}/decision", headers=who.h, json={"approve": approve_, "note": note})


async def staff_sign_in(client, user) -> None:
    """Signs in on the staff sign-in page (admin audience) with two-step verification."""
    if not user.totp_secret:
        await user.enable_mfa()
    r = await client.post("/v1/auth/login", json={"email": user.email, "password": user.password, "totpCode": user.totp(),
                                                  "portal": "staff"})
    assert r.status_code == 200, r.text
    user.access, user.refresh_token = r.json()["tokens"]["accessToken"], r.json()["tokens"]["refreshToken"]


async def titles(sf, identity_id) -> list[str]:
    async with sf() as s:
        return list((await s.scalars(text("SELECT title FROM notification.notifications WHERE identity_id = :i"),
                                     {"i": identity_id})).all())


async def test_a_role_grant_waits_for_an_independent_admin_then_applies(client, make_user, drain, sf):
    maker = await staff(make_user, "maker", "PLATFORM_ADMIN")
    checker = await staff(make_user, "checker", "PLATFORM_ADMIN")
    analyst = await staff(make_user, "analyst", "TS_ANALYST")
    target = await make_user("target")

    r = await client.post(grant_url(target), headers=maker.h, json={"role": "FINANCIAL_OPS", "justification": "short"})
    assert r.status_code == 422  # a real justification is required
    r = await client.post(grant_url(target), headers=maker.h, json={"role": "FINANCIAL_OPS", "justification": WHY})
    assert r.status_code == 202
    req = r.json()
    assert req["status"] == "REQUESTED" and req["kind"] == "GRANT_PLATFORM_ROLE" and req["approverRoles"] == ["PLATFORM_ADMIN"]
    assert req["requestedBy"]["id"] == str(maker.id) and req["canCancel"] and not req["canDecide"]
    assert "Financial Ops to Target" in req["summary"] and "(permanent)" in req["summary"]
    lookup = await client.get("/v1/admin/identities/lookup", params={"email": target.email}, headers=maker.h)
    assert lookup.json()["platformRoles"] == []  # nothing changes before approval
    again = await client.post(grant_url(target), headers=maker.h, json={"role": "FINANCIAL_OPS", "justification": WHY})
    assert again.status_code == 409 and again.json()["code"] == "APPROVAL_ALREADY_PENDING"

    assert (await decide(client, maker, req, True)).json()["code"] == "FOUR_EYES"  # never the requester
    assert (await decide(client, analyst, req, True)).status_code == 403  # needs a Platform Admin
    assert (await decide(client, checker, req, False)).json()["code"] == "NOTE_REQUIRED"  # a rejection says why

    mine = (await client.get(A, headers=maker.h, params={"mine": "true"})).json()
    waiting = (await client.get(A, headers=checker.h, params={"awaitingMe": "true"})).json()
    assert [x["id"] for x in mine] == [req["id"]] and [x["id"] for x in waiting] == [req["id"]] and waiting[0]["canDecide"]
    assert (await client.get(A, headers=maker.h, params={"awaitingMe": "true"})).json() == []
    kpis = (await client.get(f"{A}/summary", headers=checker.h)).json()
    assert kpis["awaitingMe"] == 1 and kpis["myOpen"] == 0

    done = (await decide(client, checker, req, True, "Confirmed with the finance lead")).json()
    assert done["status"] == "APPLIED" and done["decidedBy"]["id"] == str(checker.id) and done["appliedAt"]
    assert done["result"]["platformRoles"] == ["FINANCIAL_OPS"]
    assert (await decide(client, checker, req, True)).json()["code"] == "APPROVAL_NOT_PENDING"  # decided once
    assert (await client.get(f"{A}/summary", headers=maker.h)).json()["applied7d"] == 1

    await drain()
    assert "A staff action is waiting for your approval" in await titles(sf, checker.id)  # approvers are told
    assert "A staff action is waiting for your approval" not in await titles(sf, maker.id)
    assert "Your request was approved and applied" in await titles(sf, maker.id)  # the requester hears the outcome
    async with sf() as s:
        trail = (await s.scalars(text("SELECT action FROM audit.audit_records WHERE object_id = :i ORDER BY seq"),
                                 {"i": req["id"]})).all()
    assert [a.split(".")[-2] for a in trail] == ["requested", "applied"]  # every step is in the audit trail


async def test_nobody_grants_themselves_or_approves_their_own_role_change(client, make_user):
    maker = await staff(make_user, "maker", "PLATFORM_ADMIN")
    other = await staff(make_user, "other", "PLATFORM_ADMIN")
    r = await client.post(grant_url(maker), headers=maker.h, json={"role": "FINANCIAL_OPS", "justification": WHY})
    assert r.status_code == 403 and r.json()["code"] == "SELF_GRANT"
    # Another admin asks for a role for `other`: `other` cannot approve their own grant.
    third = await staff(make_user, "third", "PLATFORM_ADMIN")
    req = (await client.post(grant_url(other), headers=third.h, json={"role": "FINANCIAL_OPS", "justification": WHY})).json()
    assert (await decide(client, other, req, True)).json()["code"] == "FOUR_EYES"
    assert (await decide(client, maker, req, True)).json()["status"] == "APPLIED"


async def test_just_in_time_role_stops_counting_at_its_end_then_is_removed(client, make_user, drain, sf):
    maker = await staff(make_user, "maker", "PLATFORM_ADMIN")
    checker = await staff(make_user, "checker", "PLATFORM_ADMIN")
    target = await make_user("oncall")
    ends = clock.now() + timedelta(hours=1)
    r = await client.post(grant_url(target), headers=maker.h,
                          json={"role": "TS_ANALYST", "justification": WHY, "expiresAt": ends.isoformat()})
    assert " until " in r.json()["summary"]
    assert (await decide(client, checker, r.json(), True)).json()["status"] == "APPLIED"
    listed = {s["email"]: s for s in (await client.get("/v1/admin/staff", headers=maker.h)).json()}
    assert "TS_ANALYST" in listed[target.email]["roleExpiries"]

    await staff_sign_in(client, target)
    assert (await client.get("/v1/admin/overview", headers=target.h)).status_code == 200

    clock.set_now(ends + timedelta(minutes=1))
    # Past its end the role no longer counts, even before the clean-up timer has run.
    assert (await client.get("/v1/admin/overview", headers=target.h)).status_code == 403
    await fire_due_timers(sf, now=clock.now())
    await drain()
    async with sf() as s:
        roles = await s.scalar(text("SELECT platform_roles FROM identity.identities WHERE id = :i"), {"i": target.id})
        audited = await s.scalar(text("SELECT count(*) FROM audit.audit_records WHERE action LIKE '%platform_role_expired%'"))
    assert roles == [] and audited >= 1
    assert "A time-limited staff role ended" in await titles(sf, target.id)

    past = await client.post(grant_url(target), headers=maker.h, json={"role": "TS_ANALYST", "justification": WHY,
                                                                      "expiresAt": (clock.now() - timedelta(hours=1)).isoformat()})
    assert past.json()["code"] == "EXPIRY_IN_PAST"


async def test_customer_session_of_a_staff_member_cannot_use_staff_tools(client, make_user):
    admin = await staff(make_user, "dual", "PLATFORM_ADMIN")
    assert (await client.get("/v1/admin/overview", headers=admin.h)).status_code == 200  # staff sign-in session

    # The same person signed in elsewhere (API client, no staff sign-in page): a customer session.
    r = await client.post("/v1/auth/login", json={"email": admin.email, "password": admin.password, "totpCode": admin.totp()})
    customer = {"Authorization": f"Bearer {r.json()['tokens']['accessToken']}"}
    refused = await client.get("/v1/admin/overview", headers=customer)
    assert refused.status_code == 403 and refused.json()["code"] == "ADMIN_SESSION_REQUIRED"
    assert (await client.get(A, headers=customer)).status_code == 403
    assert (await client.get("/v1/payments/ops/worklist", headers=customer)).status_code == 403  # roles do not apply
    assert (await client.get("/v1/me", headers=customer)).status_code == 200  # customer endpoints still work
    # Refreshing keeps the audience it started with.
    fresh = await client.post("/v1/auth/refresh", json={"refreshToken": r.json()["tokens"]["refreshToken"]})
    assert (await client.get("/v1/admin/overview", headers={"Authorization": f"Bearer {fresh.json()['accessToken']}"})).status_code == 403

    await staff_sign_in(client, admin)
    assert (await client.get("/v1/admin/overview", headers=admin.h)).status_code == 200


async def test_suspending_a_staff_member_ends_their_sessions_and_authority_at_once(client, make_user, sf):
    from zoikorum.domains.identity import facade as identity_facade
    from zoikorum.domains.identity import service as identity_service

    officer = await staff(make_user, "officer", "PLATFORM_ADMIN", "FINANCIAL_OPS")
    assert (await client.get("/v1/admin/overview", headers=officer.h)).status_code == 200
    async with sf() as s, s.begin():
        await identity_service.set_status(s, officer.id, "SUSPENDED", "ENFORCEMENT")  # what an applied suspension does
    async with sf() as s:
        assert await identity_facade.live_platform_roles(s, officer.id) == frozenset()
        open_sessions = await s.scalar(text("SELECT count(*) FROM identity.sessions WHERE identity_id = :i AND revoked_at IS NULL"),
                                       {"i": officer.id})
    assert open_sessions == 0
    assert (await client.get("/v1/admin/overview", headers=officer.h)).status_code in (401, 403)
    assert (await client.post("/v1/auth/refresh", json={"refreshToken": officer.refresh_token})).status_code == 401


async def test_unanswered_requests_expire_and_requesters_can_cancel(client, make_user, drain, sf):
    maker = await staff(make_user, "maker", "PLATFORM_ADMIN")
    checker = await staff(make_user, "checker", "PLATFORM_ADMIN")
    body = {"kind": "SWITCH_CHANGE", "payload": {"key": "AI_ASSIST", "paused": True}, "justification": "Model provider outage"}
    r = await client.post(A, headers=maker.h, json=body)
    assert r.status_code == 201 and r.json()["status"] == "REQUESTED"
    assert (await client.post(f"{A}/{r.json()['id']}/cancel", headers=checker.h)).json()["code"] == "NOT_REQUESTER"
    cancelled = await client.post(f"{A}/{r.json()['id']}/cancel", headers=maker.h)
    assert cancelled.json()["status"] == "CANCELLED"

    r = await client.post(A, headers=maker.h, json=body)
    clock.set_now(clock.now() + timedelta(hours=25))  # ZK_APPROVAL_EXPIRY_HOURS defaults to 24
    await fire_due_timers(sf, now=clock.now())
    clock.set_now(None)  # back to now, so new sign-ins are not dated in the future
    await drain()
    assert (await client.get(f"{A}/{r.json()['id']}", headers=maker.h)).json()["status"] == "EXPIRED"
    assert (await decide(client, checker, r.json(), True)).json()["code"] == "APPROVAL_NOT_PENDING"
    switches = {s["key"]: s for s in (await client.get("/v1/admin/switches", headers=maker.h)).json()}
    assert not switches["AI_ASSIST"]["paused"]  # never carried out
    assert "Your request expired without a decision" in await titles(sf, maker.id)
    bad = await client.post(A, headers=maker.h, json={**body, "payload": {"key": "AI_ASSIST"}})
    assert bad.status_code == 422


async def test_an_approved_action_that_can_no_longer_be_done_is_recorded_as_failed(client, make_user, sf):
    from zoikorum.domains.identity import service as identity_service

    maker = await staff(make_user, "maker", "PLATFORM_ADMIN")
    checker = await staff(make_user, "checker", "PLATFORM_ADMIN")
    target = await make_user("target")
    req = (await client.post(grant_url(target), headers=maker.h, json={"role": "MEDIATOR", "justification": WHY})).json()
    async with sf() as s, s.begin():
        await identity_service.set_status(s, target.id, "SUSPENDED", "ENFORCEMENT")
    done = (await decide(client, checker, req, True)).json()
    assert done["status"] == "FAILED" and "active account" in done["applyError"]
    async with sf() as s:
        roles = await s.scalar(text("SELECT platform_roles FROM identity.identities WHERE id = :i"), {"i": target.id})
    assert roles == []  # never optimistic: nothing was granted


async def test_money_event_replay_needs_a_second_financial_operations_member(client, make_user, sf):
    admin = await staff(make_user, "admin", "PLATFORM_ADMIN")
    finance = await staff(make_user, "fin", "FINANCIAL_OPS")
    finance2 = await staff(make_user, "fin2", "FINANCIAL_OPS")
    ids = {}
    async with sf() as s, s.begin():
        for name, financial in (("money", True), ("plain", False)):
            ids[name] = uuid.uuid4()
            await s.execute(text(
                "INSERT INTO platform.consumer_failures (id, consumer, event_id, event_type, envelope, attempts, status, financial, created_at) "
                "VALUES (:id, 'nobody.listens', :e, 'zoikorum.escrow.account.released.v1', '{}', 5, 'DEAD', :f, now())"),
                {"id": ids[name], "e": uuid.uuid4(), "f": financial})

    plain = await client.post(f"/v1/admin/dead-letters/{ids['plain']}/replay", headers=admin.h)
    assert plain.status_code == 200 and "replayed" in plain.json()  # other events replay at once
    url = f"/v1/admin/dead-letters/{ids['money']}/replay"
    assert (await client.post(url, headers=finance.h)).json()["code"] == "JUSTIFICATION_REQUIRED"
    r = await client.post(url, headers=finance.h, json={"justification": "Ledger fixed; release must be re-applied"})
    assert r.status_code == 202 and r.json()["kind"] == "DEAD_LETTER_REPLAY_FINANCIAL"
    assert (await decide(client, admin, r.json(), True)).status_code == 403  # only Financial Operations replay money events
    done = (await decide(client, finance2, r.json(), True)).json()
    assert done["status"] == "FAILED" and done["applyError"].startswith("The delivery failed again")  # reported, not hidden
