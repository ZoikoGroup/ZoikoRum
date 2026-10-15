"""Ending an engagement: at once while nothing is in escrow, by agreement while money is held, never by one side during
a dispute; offboarding a professional ends their open engagements."""

from __future__ import annotations

import uuid
from datetime import timedelta

from sqlalchemy import text

from test_contract import C, accepted_contract, signed_contract
from test_escrow import E, escrow_of
from zoikorum.shared import clock
from zoikorum.shared.event_catalog import E as EV
from zoikorum.shared.events import record_event

REASON = {"reason": "The project was cancelled internally."}


async def funded(client, buyer, c, drain, which=(0,)):
    esc = await escrow_of(client, buyer, c)
    ids = [c["milestones"][i]["id"] for i in which]
    r = await client.post(f"{E}/{esc['id']}/fund", headers=buyer.idem(), json={"milestoneIds": ids, "paymentMethodToken": "tok_visa"})
    assert r.status_code in (200, 202), r.text
    await drain()
    return esc


async def test_unsigned_or_unfunded_engagement_can_be_ended_by_either_side(client, make_user, drain, sf):
    pro_user, pro, buyer, org, accepted, c = await accepted_contract(client, make_user, drain)
    assert c["canEndNow"] is True and c["canRequestEnd"] is False  # nothing is funded before signing
    r = await client.post(f"{C}/{c['id']}/terminate", headers=buyer.idem(), json=REASON)
    assert r.json()["code"] == "STEP_UP_REQUIRED"
    await buyer.step_up()
    r = await client.post(f"{C}/{c['id']}/terminate", headers=buyer.idem(), json=REASON)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "TERMINATED" and {m["status"] for m in r.json()["milestones"]} == {"CANCELLED"}
    await drain()
    seen = (await client.get(f"{C}/{c['id']}", headers=pro_user.h)).json()
    assert seen["status"] == "TERMINATED" and seen["canEndNow"] is False
    r = await client.post(f"{C}/{c['id']}/terminate", headers=buyer.idem(), json=REASON)
    assert r.json()["code"] == "CONTRACT_CLOSED"

    # An active engagement with nothing funded yet: the professional may end it alone.
    pro_user, pro, buyer, c = await signed_contract(client, make_user, drain)
    assert c["canEndNow"] is True and c["canRequestEnd"] is False
    r = await client.post(f"{C}/{c['id']}/terminate", headers=pro_user.idem(), json=REASON)
    assert r.status_code == 200 and r.json()["status"] == "TERMINATED"


async def test_money_in_escrow_needs_the_other_sides_agreement(client, make_user, drain, sf):
    pro_user, pro, buyer, c = await signed_contract(client, make_user, drain)
    esc = await funded(client, buyer, c, drain)
    c = (await client.get(f"{C}/{c['id']}", headers=buyer.h)).json()
    assert c["canEndNow"] is False and c["canRequestEnd"] is True
    await buyer.step_up()
    r = await client.post(f"{C}/{c['id']}/terminate", headers=buyer.idem(), json=REASON)
    assert r.status_code == 409 and r.json()["code"] == "MONEY_IN_ESCROW"

    r = await client.post(f"{C}/{c['id']}/terminate", headers=buyer.idem(), json={**REASON, "mutual": True})
    assert r.status_code == 200 and r.json()["status"] == "ACTIVE"
    req = r.json()["terminationRequest"]
    assert req["status"] == "PENDING" and req["requesterParty"] == "BUYER" and req["canWithdraw"] and not req["canAnswer"]
    r = await client.post(f"{C}/{c['id']}/terminate", headers=buyer.idem(), json={**REASON, "mutual": True})
    assert r.json()["code"] == "TERMINATION_PENDING"
    # The asking side cannot answer its own request.
    r = await client.post(f"{C}/{c['id']}/termination/decision", headers=buyer.idem(), json={"agree": True})
    assert r.json()["code"] == "NOT_THE_OTHER_SIDE"

    # Declined: the engagement continues.
    await pro_user.step_up()
    seen = (await client.get(f"{C}/{c['id']}", headers=pro_user.h)).json()["terminationRequest"]
    assert seen["canAnswer"] and not seen["canWithdraw"]
    r = await client.post(f"{C}/{c['id']}/termination/decision", headers=pro_user.idem(), json={"agree": False, "note": "Work is nearly done."})
    assert r.status_code == 200 and r.json()["status"] == "ACTIVE" and r.json()["terminationRequest"]["status"] == "DECLINED"

    # Asked again and agreed: held money for work not accepted goes back to the buyer.
    await client.post(f"{C}/{c['id']}/terminate", headers=buyer.idem(), json={**REASON, "mutual": True})
    r = await client.post(f"{C}/{c['id']}/termination/decision", headers=pro_user.idem(), json={"agree": True})
    assert r.status_code == 200 and r.json()["status"] == "TERMINATED"
    await drain()
    allocs = (await client.get(f"{E}/{esc['id']}", headers=buyer.h)).json()["allocations"]
    assert {a["state"] for a in allocs} <= {"REFUNDED", "CANCELLED"} and any(a["state"] == "REFUNDED" for a in allocs)
    async with sf() as s:
        events = (await s.scalars(text("SELECT event_type FROM platform.outbox ORDER BY seq"))).all()
    assert EV.CONTRACT_TERMINATION_REQUESTED in events and EV.CONTRACT_TERMINATION_DECLINED in events


async def test_requests_can_be_withdrawn_and_lapse(client, make_user, drain, sf):
    pro_user, pro, buyer, c = await signed_contract(client, make_user, drain)
    await funded(client, buyer, c, drain)
    await pro_user.step_up()
    r = await client.post(f"{C}/{c['id']}/terminate", headers=pro_user.idem(), json={**REASON, "mutual": True})
    assert r.json()["terminationRequest"]["requesterParty"] == "PROFESSIONAL"
    r = await client.post(f"{C}/{c['id']}/termination/withdraw", headers=buyer.h)
    assert r.json()["code"] == "NOT_THE_REQUESTER"
    r = await client.post(f"{C}/{c['id']}/termination/withdraw", headers=pro_user.h)
    assert r.status_code == 200 and r.json()["terminationRequest"]["status"] == "WITHDRAWN"

    await client.post(f"{C}/{c['id']}/terminate", headers=pro_user.idem(), json={**REASON, "mutual": True})
    clock.advance(timedelta(days=8))
    await drain()
    c2 = (await client.get(f"{C}/{c['id']}", headers=buyer.h)).json()
    assert c2["status"] == "ACTIVE" and c2["terminationRequest"]["status"] == "LAPSED" and c2["canRequestEnd"] is True


async def test_a_disputed_engagement_is_not_ended_by_one_side(client, make_user, drain, sf):
    pro_user, pro, buyer, c = await signed_contract(client, make_user, drain)
    await funded(client, buyer, c, drain)
    await buyer.step_up()
    await client.post(f"{C}/{c['id']}/terminate", headers=buyer.idem(), json={**REASON, "mutual": True})
    m1 = c["milestones"][0]
    r = await client.post("/v1/disputes", headers=buyer.idem(), json={
        "contractId": c["id"], "milestoneIds": [m1["id"]], "category": "QUALITY_ACCEPTANCE", "summary": "The work is not usable.",
        "desiredOutcome": "FULL_REFUND", "context": "Nothing delivered matches the agreed scope."})
    assert r.status_code in (200, 201), r.text
    await drain()
    c2 = (await client.get(f"{C}/{c['id']}", headers=buyer.h)).json()
    assert c2["status"] == "DISPUTED" and c2["terminationRequest"] is None  # the open request was closed by the dispute
    r = await client.post(f"{C}/{c['id']}/terminate", headers=buyer.idem(), json=REASON)
    assert r.json()["code"] == "CONTRACT_DISPUTED"


async def test_offboarding_a_professional_ends_their_open_engagements(client, make_user, drain, sf):
    pro_user, pro, buyer, c = await signed_contract(client, make_user, drain)
    esc = await funded(client, buyer, c, drain)
    async with sf() as s, s.begin():
        record_event(s, EV.ENFORCEMENT_ACTION_APPLIED, aggregate_type="EnforcementCase", aggregate_id=uuid.uuid4(),
                     payload={"caseId": uuid.uuid4(), "subjectType": "IDENTITY", "subjectId": pro_user.id,
                              "level": 4, "action": "OFFBOARD", "reasonCode": "FRAUD", "notice": {}, "expiresAt": None,
                              "organizationId": None})
    await drain()
    c2 = (await client.get(f"{C}/{c['id']}", headers=buyer.h)).json()
    assert c2["status"] == "TERMINATED"
    allocs = (await client.get(f"{E}/{esc['id']}", headers=buyer.h)).json()["allocations"]
    assert any(a["state"] == "REFUNDED" for a in allocs)


async def test_buyers_are_told_when_their_professional_is_suspended_or_a_check_lapses(client, make_user, drain, sf):
    pro_user, pro, buyer, c = await signed_contract(client, make_user, drain)

    async def emit(kind, payload):
        async with sf() as s, s.begin():
            record_event(s, kind, aggregate_type="Test", aggregate_id=uuid.uuid4(), payload=payload)
        await drain()

    await emit(EV.ENFORCEMENT_ACTION_APPLIED, {"caseId": uuid.uuid4(), "subjectType": "IDENTITY", "subjectId": pro_user.id,
                                              "level": 4, "action": "SUSPEND_ACCOUNT", "reasonCode": "X", "notice": {},
                                              "expiresAt": None, "organizationId": None})
    await emit(EV.VERIFICATION_EXPIRED, {"caseId": uuid.uuid4(), "subjectType": "PROFESSIONAL", "subjectId": pro["id"],
                                        "verificationType": "INSURANCE", "label": "Professional indemnity"})
    notes = [n for n in (await client.get("/v1/notifications", headers=buyer.h)).json()["items"]
             if n["title"] == "Change affecting your engagement"]
    assert len(notes) == 2 and all(n["url"].endswith(c["id"]) for n in notes)
    bodies = " ".join(n["body"] for n in notes)
    assert "account is suspended" in bodies and "insurance has expired" in bodies and "stays protected" in bodies
    pro_titles = [n["title"] for n in (await client.get("/v1/notifications", headers=pro_user.h)).json()["items"]]
    assert "Change affecting your engagement" not in pro_titles  # the professional has their own notice
