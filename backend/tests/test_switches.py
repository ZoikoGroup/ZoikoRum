"""Operational switches (Engineering Handbook 23.3): staff pause one kind of action at once. Refused actions answer
503 FEATURE_PAUSED; releases and payouts wait and go out on their own once the switch is back on. A change is a
maker-checker request: it takes effect only when a second person with the same authority approves it."""

from __future__ import annotations

from datetime import timedelta

from approvalhelp import approve, approved
from test_contract import C, signed_contract
from test_escrow import BANK, E, escrow_of
from zoikorum.shared import clock
from zoikorum.shared.relay import fire_due_timers

S = "/v1/admin/switches"


async def staff(make_user, name, *roles):
    u = await make_user(name, platform_roles=roles)
    await u.step_up()
    return u


async def flip(client, who, key, paused, reason="Partner incident under investigation"):
    return await client.put(f"{S}/{key}", headers=who.h, json={"paused": paused, "reason": reason})


async def switch(client, who, checker, key, paused, reason="Partner incident under investigation"):
    """A change that must go through: requested by one person, approved by another (two-step sign-in is only fresh for
    a few minutes: sign in again as staff would)."""
    await who.step_up()
    await approved(client, await flip(client, who, key, paused, reason), checker)


async def test_paused_sign_ups_are_refused_and_every_change_is_recorded(client, make_user):
    admin = await staff(make_user, "ada", "PLATFORM_ADMIN")
    checker = await staff(make_user, "cy", "PLATFORM_ADMIN")
    switches = {s["key"]: s for s in (await client.get(S, headers=admin.h)).json()}
    assert set(switches) == {"SIGN_UPS", "NEW_REQUESTS", "PROPOSAL_SUBMISSION", "FUNDING", "RELEASES", "PAYOUTS", "AI_ASSIST"}
    assert not any(s["paused"] for s in switches.values())

    r = await flip(client, admin, "SIGN_UPS", True, "Fraud wave of fake accounts")
    assert r.status_code == 202 and r.json()["status"] == "REQUESTED" and r.json()["kind"] == "SWITCH_CHANGE"
    assert not {s["key"]: s for s in (await client.get(S, headers=admin.h)).json()}["SIGN_UPS"]["paused"]  # not yet
    me_too = await client.post(f"/v1/admin/approval-requests/{r.json()['id']}/decision", headers=admin.h, json={"approve": True})
    assert me_too.status_code == 403 and me_too.json()["code"] == "FOUR_EYES"  # never the requester
    assert (await approve(client, checker, r.json()))["status"] == "APPLIED"
    now = {s["key"]: s for s in (await client.get(S, headers=admin.h)).json()}["SIGN_UPS"]
    assert now["paused"] and now["changedBy"] == str(admin.id)
    signup = await client.post("/v1/auth/register", json={
        "email": "new@example.com", "password": "correct-horse-battery-staple", "displayName": "New", "country": "US",
        "accountType": "BUYER", "acceptTerms": True})
    assert signup.status_code == 503 and signup.json()["code"] == "FEATURE_PAUSED"
    assert "New accounts is paused" in signup.json()["detail"]

    await approved(client, await flip(client, admin, "SIGN_UPS", False, "Fraud wave contained"), checker)
    await make_user("after")  # signs up again
    assert (await flip(client, admin, "SIGN_UPS", True, "short")).status_code == 422  # a real reason is required
    assert (await flip(client, admin, "NOT_A_SWITCH", True)).status_code == 404


async def test_financial_operations_change_money_switches_only(client, make_user):
    finance = await staff(make_user, "fin", "FINANCIAL_OPS")
    assert (await flip(client, finance, "FUNDING", True)).status_code == 202
    assert (await flip(client, finance, "SIGN_UPS", True)).status_code == 403
    buyer = await make_user("bea")
    assert (await client.get(S, headers=buyer.h)).status_code == 403
    assert (await flip(client, buyer, "FUNDING", False)).status_code == 403


async def later(sf, drain, minutes=11):
    """The worker some minutes from now: due timers fire (the clock itself stays real, so sign-ins stay valid)."""
    await fire_due_timers(sf, now=clock.now() + timedelta(minutes=minutes))
    await drain()


async def test_paused_releases_and_payouts_wait_then_go_out_on_their_own(client, make_user, drain, sf):
    admin = await staff(make_user, "ada", "PLATFORM_ADMIN")
    checker = await staff(make_user, "fin", "FINANCIAL_OPS")  # money switches: Financial Operations may approve
    pro_user, pro, buyer, c = await signed_contract(client, make_user, drain)
    assert (await client.put("/v1/payout-accounts/me", headers=pro_user.h, json=BANK)).status_code == 200
    esc = await escrow_of(client, buyer, c)
    m1 = c["milestones"][0]

    await switch(client, admin, checker, "FUNDING", True)
    fund = {"milestoneIds": [m1["id"]], "paymentMethodToken": "tok_visa"}
    refused = await client.post(f"{E}/{esc['id']}/fund", headers=buyer.idem(), json=fund)
    assert refused.status_code == 503 and refused.json()["code"] == "FEATURE_PAUSED"
    await switch(client, admin, checker, "FUNDING", False)
    assert (await client.post(f"{E}/{esc['id']}/fund", headers=buyer.idem(), json=fund)).status_code == 200
    await drain()

    await switch(client, admin, checker, "RELEASES", True)
    await switch(client, admin, checker, "PAYOUTS", True)
    await client.post(f"/v1/milestones/{m1['id']}/submit", headers=pro_user.h, json={"note": "Master file"})
    await client.post(f"/v1/milestones/{m1['id']}/accept", headers=buyer.idem())
    await drain()
    assert (await escrow_of(client, buyer, c))["allocations"][0]["state"] == "HELD"  # accepted, but releases are paused

    await switch(client, admin, checker, "RELEASES", False, "Partner incident resolved")
    await later(sf, drain)
    assert (await escrow_of(client, buyer, c))["allocations"][0]["state"] == "RELEASED"  # went out on its own
    earn = (await client.get("/v1/payments/earnings/me", headers=pro_user.h)).json()
    assert earn["payouts"][0]["status"] == "QUEUED"  # payouts still paused

    await switch(client, admin, checker, "PAYOUTS", False, "Partner incident resolved")
    await later(sf, drain)
    earn = (await client.get("/v1/payments/earnings/me", headers=pro_user.h)).json()
    assert earn["payouts"][0]["status"] == "SETTLED"
    assert (await client.get(f"{C}/{c['id']}", headers=buyer.h)).json()["milestones"][0]["status"] == "ACCEPTED"
