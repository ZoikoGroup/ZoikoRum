"""Second documentation re-audit (Steps 0-9): verification appeals, partial acceptance, retainer cycles,
duplicate-account detection, weekly availability and search result eligibility fields."""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import text

from filehelp import upload
from test_contract import C, fund, signed_contract
from test_escrow import E as ESC, balanced, escrow_of
from test_proposal import P, R, _day, buyer_org, proposal_body, request_body, tier_b
from test_verification import new_pro, officer
from zoikorum.shared import clock

V = "/v1/verification"


# ---- Verification appeals ---------------------------------------------------------------------------------------------

async def failed_identity_case(client, make_user, drain):
    u, pro = await new_pro(client, make_user, drain)
    case = (await client.post(f"{V}/cases", headers=u.h, json={
        "verificationType": "IDENTITY", "subjectType": "PROFESSIONAL", "subjectId": pro["id"]})).json()
    await client.post(f"{V}/cases/{case['id']}/evidence", headers=u.h, json={"evidenceType": "ID_DOCUMENT", "items": [upload("scan.pdf", b"blurry")]})
    first = await officer(make_user, "cora")
    r = await client.post(f"{V}/cases/{case['id']}/decision", headers=first.h, json={
        "decision": "FAILED", "reasonCode": "UNREADABLE", "publicReason": "The document could not be read."})
    assert r.json()["status"] == "FAILED"
    return u, pro, case, first


async def test_an_appeal_is_decided_once_by_an_independent_reviewer(client, make_user, drain, sf):
    u, pro, case, first = await failed_identity_case(client, make_user, drain)
    mine = (await client.get(f"{V}/cases/{case['id']}", headers=u.h)).json()
    assert mine["appealDeadline"] and mine["appeal"] is None

    r = await client.post(f"{V}/cases/{case['id']}/appeal", headers=u.h, json={"statement": "The scan was fine; here is a clearer copy of my passport."})
    assert r.status_code == 201 and r.json()["appeal"]["status"] == "OPEN"
    assert (await client.post(f"{V}/cases/{case['id']}/appeal", headers=u.h, json={"statement": "Trying a second time with the same."})).json()["code"] == "APPEAL_EXISTS"
    # New evidence is accepted while the appeal is open.
    r = await client.post(f"{V}/cases/{case['id']}/evidence", headers=u.h, json={"evidenceType": "ID_DOCUMENT", "items": [upload("clear.pdf", b"clear")]})
    assert r.status_code == 200 and len(r.json()["evidence"]) == 2

    queue = (await client.get(f"{V}/appeals", headers=first.h)).json()
    assert len(queue) == 1 and queue[0]["canDecide"] is False  # the original reviewer cannot decide the appeal
    body = {"outcome": "OVERTURNED", "note": "The new scan is clear and matches the profile."}
    r = await client.post(f"{V}/appeals/{queue[0]['id']}/decision", headers=first.h, json=body)
    assert r.status_code == 403 and r.json()["code"] == "INDEPENDENT_REVIEWER_REQUIRED"

    second = await officer(make_user, "olu")
    assert (await client.get(f"{V}/appeals", headers=second.h)).json()[0]["canDecide"] is True
    r = await client.post(f"{V}/appeals/{queue[0]['id']}/decision", headers=second.h, json=body)
    assert r.json()["status"] == "OVERTURNED"
    assert (await client.post(f"{V}/appeals/{queue[0]['id']}/decision", headers=second.h, json=body)).json()["code"] == "APPEAL_DECIDED"
    assert (await client.get(f"{V}/cases/{case['id']}", headers=u.h)).json()["status"] == "VERIFIED"
    await drain()
    assert (await client.get(f"/v1/trust/professionals/{pro['id']}", headers=u.h)).json()["dimensions"]["identity"] == "VERIFIED"


async def test_appeals_are_time_bounded_and_upheld_decisions_stand(client, make_user, drain):
    u, pro, case, first = await failed_identity_case(client, make_user, drain)
    clock.advance(timedelta(days=15))
    r = await client.post(f"{V}/cases/{case['id']}/appeal", headers=u.h, json={"statement": "Late appeal after the window has closed."})
    clock.set_now(None)
    assert r.json()["code"] == "APPEAL_WINDOW_CLOSED"

    u2, pro2, case2, first2 = await failed_identity_case(client, make_user, drain)
    await client.post(f"{V}/cases/{case2['id']}/appeal", headers=u2.h, json={"statement": "I believe the document was readable enough."})
    second = await officer(make_user, "olu")
    appeal = (await client.get(f"{V}/appeals", headers=second.h)).json()[0]
    r = await client.post(f"{V}/appeals/{appeal['id']}/decision", headers=second.h,
                          json={"outcome": "UPHELD", "note": "Still unreadable. Please start a new check with a clear scan."})
    assert r.json()["status"] == "UPHELD"
    view = (await client.get(f"{V}/cases/{case2['id']}", headers=u2.h)).json()
    assert view["status"] == "FAILED" and view["appeal"]["decisionNote"].startswith("Still unreadable")


# ---- Partial acceptance -------------------------------------------------------------------------------------------------

async def test_partial_acceptance_needs_the_professionals_agreement(client, make_user, drain, sf):
    pro_user, pro, buyer, c = await signed_contract(client, make_user, drain)
    m1 = c["milestones"][0]
    esc = await escrow_of(client, buyer, c)
    await client.post(f"{ESC}/{esc['id']}/fund", headers=buyer.idem(), json={"milestoneIds": [m1["id"]], "paymentMethodToken": "tok_visa"})
    await drain()
    await client.post(f"/v1/milestones/{m1['id']}/submit", headers=pro_user.h, json={"note": "Delivered"})

    url = f"/v1/milestones/{m1['id']}/partial-acceptance"
    assert (await client.post(url, headers=buyer.h, json={"amountMinor": 1_000_000, "reason": "Full amount is not partial"})).json()["code"] == "NOT_PARTIAL"
    assert (await client.post(url, headers=pro_user.h, json={"amountMinor": 700_000, "reason": "Professionals cannot offer"})).status_code == 403
    r = await client.post(url, headers=buyer.h, json={"amountMinor": 700_000, "reason": "Appendix B is missing from the master file."})
    offer = r.json()["milestones"][0]["partialOffer"]
    assert offer["amount"]["amountMinor"] == 700_000 and offer["refund"]["amountMinor"] == 300_000
    assert (await escrow_of(client, buyer, c))["held"]["amountMinor"] == 1_000_000  # nothing moves on the offer alone

    # Declining keeps everything as it was.
    r = await client.post(f"{url}/decline", headers=pro_user.idem())
    assert r.json()["milestones"][0]["partialOffer"] is None and r.json()["milestones"][0]["status"] == "SUBMITTED"
    await client.post(url, headers=buyer.h, json={"amountMinor": 800_000, "reason": "Appendix B is still missing; 80% is fair."})
    r = await client.post(f"{url}/agree", headers=pro_user.idem())
    m = r.json()["milestones"][0]
    assert m["status"] == "ACCEPTED" and m["acceptedRelease"]["amountMinor"] == 800_000
    await drain()

    esc = await escrow_of(client, buyer, c)
    a1 = esc["allocations"][0]
    assert a1["state"] == "PARTIALLY_RELEASED" and a1["released"]["amountMinor"] == 720_000 and a1["fee"]["amountMinor"] == 80_000
    assert esc["refunded"]["amountMinor"] == 200_000 and esc["held"]["amountMinor"] == 0
    refunds = (await client.get("/v1/payments/refunds", headers=buyer.h, params={"organizationId": c["organizationId"]})).json()
    assert [(x["amount"]["amountMinor"], x["status"]) for x in refunds] == [(200_000, "SETTLED")]
    invoices = (await client.get("/v1/payments/invoices", headers=buyer.h, params={"organizationId": c["organizationId"]})).json()
    assert invoices[0]["total"]["amountMinor"] == 800_000
    await balanced(sf)


# ---- Retainer cycles ----------------------------------------------------------------------------------------------------

async def retainer_contract(client, make_user, drain):
    pro_user, pro = await tier_b(client, make_user, drain, "ann")
    buyer, org = await buyer_org(client, make_user, drain)
    r = await client.post(R, headers=buyer.idem(), json=request_body(org, pro, engagementType="RETAINER", estimatedDuration="THREE_SIX_MONTHS"))
    assert r.status_code == 201, r.text
    req = r.json()[0]
    cycles = [{"title": f"Cycle {i}", "amountMinor": 300_000, "dueDate": _day(30 * i), "deliverableKeys": ["monthly"]} for i in (1, 2, 3)]
    monthly = [{"key": "monthly", "title": "Monthly finance support", "acceptanceCriteria": "Month-end pack delivered"}]
    p = (await client.post(f"{R}/{req['id']}/proposals", headers=pro_user.h,
                           json=proposal_body(total=900_000, pricingModel="RETAINER", milestones=cycles, deliverables=monthly, endDate=_day(95)))).json()
    assert p.get("id"), p
    r = await client.post(f"{P}/{p['id']}/submit", headers=pro_user.idem())
    assert r.status_code == 200, r.text
    r = await client.post(f"{P}/{p['id']}/accept", headers=buyer.idem())
    assert r.status_code == 200, r.text
    await drain()
    c = (await client.get(C, headers=buyer.h)).json()["items"][0]
    await buyer.step_up()
    await client.post(f"{C}/{c['id']}/sign", headers=buyer.idem(), json={"termsHash": c["termsHash"]})
    await pro_user.step_up()
    c = (await client.post(f"{C}/{c['id']}/sign", headers=pro_user.idem(), json={"termsHash": c["termsHash"]})).json()
    await drain()
    return pro_user, buyer, c


async def test_retainer_cycles_get_funding_reminders_and_can_be_cancelled(client, make_user, drain, sf):
    pro_user, buyer, c = await retainer_contract(client, make_user, drain)
    assert c["status"] == "ACTIVE" and [m["title"] for m in c["milestones"]] == ["Cycle 1", "Cycle 2", "Cycle 3"]
    await fund(sf, drain, c, [c["milestones"][0]["id"]])

    clock.advance(timedelta(days=24))  # 7 days before cycle 1 is due: it is funded, so only cycle 2/3 timers remain pending
    await drain()
    clock.advance(timedelta(days=30))  # 7 days before cycle 2 is due, and it is still unfunded
    await drain()
    clock.set_now(None)
    async with sf() as s:
        reminders = await s.scalar(text("SELECT count(*) FROM platform.outbox WHERE event_type LIKE '%milestone.funding_reminder%'"))
    assert reminders == 1

    other = await make_user("eve")
    url = f"{C}/{c['id']}/cancel-remaining-cycles"
    assert (await client.post(url, headers=pro_user.idem(), json={"reason": "No longer needed"})).status_code == 403
    r = await client.post(url, headers=buyer.idem(), json={"reason": "Budget moved to next year"})
    statuses = [m["status"] for m in r.json()["milestones"]]
    assert statuses == ["IN_PROGRESS", "CANCELLED", "CANCELLED"] and r.json()["status"] == "ACTIVE"
    assert (await client.post(url, headers=buyer.idem(), json={"reason": "Again"})).json()["code"] == "NOTHING_TO_CANCEL"
    assert (await client.get(f"{C}/{c['id']}", headers=other.h)).status_code == 404
    await drain()
    esc = await escrow_of(client, buyer, c)
    # Cancelled cycles no longer count as money to fund (cycle 1 was funded through the test stand-in, not escrow).
    assert [x["state"] for x in esc["allocations"]][1:] == ["CANCELLED", "CANCELLED"] and esc["unfunded"]["amountMinor"] == 300_000

    m1 = c["milestones"][0]["id"]
    await client.post(f"/v1/milestones/{m1}/submit", headers=pro_user.h, json={"note": "October work"})
    r = await client.post(f"/v1/milestones/{m1}/accept", headers=buyer.idem())
    assert r.json()["status"] == "COMPLETED"  # the funded cycle finished; the cancelled ones do not hold it open


async def test_only_retainers_can_cancel_remaining_cycles(client, make_user, drain):
    pro_user, pro, buyer, c = await signed_contract(client, make_user, drain)
    r = await client.post(f"{C}/{c['id']}/cancel-remaining-cycles", headers=buyer.idem(), json={"reason": "Trying on a project"})
    assert r.json()["code"] == "NOT_A_RETAINER"


# ---- Duplicate accounts --------------------------------------------------------------------------------------------------

async def test_the_same_id_document_from_two_accounts_opens_a_merge_flow(client, make_user, drain, sf):
    passport = upload("passport.pdf", b"same passport scan")
    accounts = []
    for name in ("raj", "raj2"):
        u, pro = await new_pro(client, make_user, drain, name)
        case = (await client.post(f"{V}/cases", headers=u.h, json={
            "verificationType": "IDENTITY", "subjectType": "PROFESSIONAL", "subjectId": pro["id"]})).json()
        await client.post(f"{V}/cases/{case['id']}/evidence", headers=u.h, json={"evidenceType": "ID_DOCUMENT", "items": [passport]})
        accounts.append(u)
    await drain()
    first, second = accounts

    (mine,) = (await client.get("/v1/me/duplicate-accounts", headers=second.h)).json()
    assert mine["status"] == "OPEN" and "•" in mine["otherAccount"] and mine["identityId"] is None
    assert len((await client.get("/v1/me/duplicate-accounts", headers=first.h)).json()) == 1  # both sides see it
    r = await client.post(f"/v1/me/duplicate-accounts/{mine['id']}/answer", headers=second.h,
                          json={"answer": "MERGE_REQUESTED", "note": "I opened a second account by mistake."})
    assert r.json()["status"] == "ANSWERED"

    admin = await make_user("ada", platform_roles=("PLATFORM_ADMIN",))
    await admin.step_up()
    (case,) = (await client.get("/v1/admin/duplicate-accounts", headers=admin.h)).json()
    assert case["userAnswer"] == "MERGE_REQUESTED" and case["account"] and case["otherAccount"]
    r = await client.post(f"/v1/admin/duplicate-accounts/{case['id']}/resolve", headers=admin.h,
                          json={"outcome": "MERGED", "keepIdentityId": str(first.id), "note": "Same passport; keeping the first account."})
    assert r.json()["status"] == "MERGED"
    async with sf() as s:
        status = await s.scalar(text("SELECT status FROM identity.identities WHERE id = :i"), {"i": str(second.id)})
    assert status == "SUSPENDED"
    # Sessions are revoked: the closed account can no longer sign in (access tokens already issued expire within minutes).
    r = await client.post("/v1/auth/login", json={"email": second.email, "password": second.password})
    assert r.status_code in (401, 403)
    assert (await client.get("/v1/admin/duplicate-accounts", headers=admin.h)).json() == []


# ---- Weekly hours and search eligibility fields ----------------------------------------------------------------------------

async def test_weekly_hours_and_served_countries_are_visible(client, make_user, drain):
    pro_user, pro = await tier_b(client, make_user, drain, "ann")
    r = await client.put("/v1/professionals/me/availability", headers=pro_user.h,
                         json={"availability": "NOW", "maxConcurrentEngagements": 3, "weeklyHours": 20})
    assert r.json()["weeklyHours"] == 20
    assert (await client.put("/v1/professionals/me/availability", headers=pro_user.h,
                             json={"availability": "NOW", "weeklyHours": 90})).status_code == 422
    await drain()
    assert (await client.get(f"/v1/professionals/{pro['id']}")).json()["weeklyHours"] == 20
    item = (await client.get("/v1/search/professionals", params={"q": "Tax adviser"})).json()["items"][0]
    assert item["servedJurisdictions"] == ["US"] and "licensedJurisdictions" in item
