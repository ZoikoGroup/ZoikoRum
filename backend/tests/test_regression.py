"""Regression: the complete business flows of Steps 1-9, end to end through the public API.

Each test is one customer journey, the way Venky (professional) and Lennox (customer) walk it in the app. If any step
of the platform breaks, one of these fails. Run them on their own with:  pytest -m regression
"""

from __future__ import annotations

import re

import pytest

from filehelp import raw, upload
from test_contract import C
from test_dispute import D, dispute_body, staff
from test_escrow import BANK, E, balanced, escrow_of
from test_proposal import P, R, buyer_org, proposal_body, request_body, tier_b
from zoikorum.shared import clock

pytestmark = pytest.mark.regression


async def test_customer_finds_hires_pays_and_receives_work(client, make_user, drain, sf):
    # Steps 1-4: a professional signs up, publishes a profile and is verified (Tier B).
    pro_user, pro = await tier_b(client, make_user, drain, "venky")
    trust = (await client.get(f"/v1/trust/professionals/{pro['id']}")).json()
    assert trust["tier"] == "B"

    # Step 5: the customer finds them in search.
    buyer, org = await buyer_org(client, make_user, drain, "lennox")
    found = (await client.get("/v1/search/professionals", params={"q": "Tax adviser"})).json()["items"]
    assert pro["id"] in [i["professionalId"] for i in found]

    # Step 6: request (with an NDA and a stored attachment) -> proposal -> acceptance.
    brief = upload("group-structure.pdf", b"two subsidiaries")
    req = (await client.post(R, headers=buyer.idem(), json=request_body(org, pro, ndaRequired=True, attachments=[brief]))).json()[0]
    hidden = (await client.get(f"{R}/{req['id']}", headers=pro_user.h)).json()
    assert hidden["detailsHidden"] is True and hidden["attachments"] == []
    await client.post(f"{R}/{req['id']}/accept-nda", headers=pro_user.h)
    assert (await client.get(f"{R}/{req['id']}/attachments/{brief['sha256']}", headers=pro_user.h)).content == raw(brief)
    p = (await client.post(f"{R}/{req['id']}/proposals", headers=pro_user.h, json=proposal_body())).json()
    assert (await client.post(f"{P}/{p['id']}/submit", headers=pro_user.idem())).json()["status"] == "SUBMITTED"
    assert (await client.post(f"{P}/{p['id']}/accept", headers=buyer.idem())).json()["status"] == "ACCEPTED"
    await drain()

    # Step 7: the contract is generated; buyer signs first, the professional countersigns (two-step each).
    c = (await client.get(C, headers=buyer.h)).json()["items"][0]
    assert c["status"] == "PENDING_SIGNATURE" and len(c["milestones"]) == 2
    await buyer.step_up()
    assert (await client.post(f"{C}/{c['id']}/sign", headers=buyer.idem(), json={"termsHash": c["termsHash"]})).status_code == 200
    await pro_user.step_up()
    c = (await client.post(f"{C}/{c['id']}/sign", headers=pro_user.idem(), json={"termsHash": c["termsHash"]})).json()
    assert c["status"] == "ACTIVE"
    await drain()
    m1, m2 = c["milestones"]

    # Step 8: fund M1 into escrow; work starts only once the money is held.
    esc = await escrow_of(client, buyer, c)
    await client.post(f"{E}/{esc['id']}/fund", headers=buyer.idem(), json={"milestoneIds": [m1["id"]], "paymentMethodToken": "tok_visa"})
    await drain()
    assert (await escrow_of(client, buyer, c))["held"]["amountMinor"] == 1_000_000
    assert (await client.get(f"{C}/{c['id']}", headers=pro_user.h)).json()["milestones"][0]["status"] == "IN_PROGRESS"

    # Delivery with a stored file; the buyer opens it, asks for a revision, then accepts the resubmission.
    work = upload("master-file.pdf", b"master file v1")
    await client.post(f"/v1/milestones/{m1['id']}/submit", headers=pro_user.h, json={"note": "Master file", "files": [work]})
    assert (await client.get(f"{C}/{c['id']}/files/{work['sha256']}", headers=buyer.h)).content == raw(work)
    await client.post(f"/v1/milestones/{m1['id']}/request-revision", headers=buyer.h, json={"reason": "Add the benchmarking appendix"})
    v2 = upload("master-file-v2.pdf", b"master file v2")
    await client.post(f"/v1/milestones/{m1['id']}/submit", headers=pro_user.h, json={"note": "Appendix added", "files": [v2]})
    accepted = (await client.post(f"/v1/milestones/{m1['id']}/accept", headers=buyer.idem())).json()
    assert accepted["milestones"][0]["status"] == "ACCEPTED" and accepted["milestones"][0]["revisionCount"] == 1
    await drain()

    # Release minus the 10% fee, invoice for the buyer, payout to the professional once a bank account exists.
    esc = await escrow_of(client, buyer, c)
    assert esc["allocations"][0]["released"]["amountMinor"] == 900_000 and esc["fees"]["amountMinor"] == 100_000
    invoices = (await client.get("/v1/payments/invoices", headers=buyer.h, params={"organizationId": org["id"]})).json()
    assert len(invoices) == 1 and re.fullmatch(r"ZK-INV-\d{6}", invoices[0]["number"])
    await client.put("/v1/payout-accounts/me", headers=pro_user.h, json=BANK)
    earnings = (await client.get("/v1/payments/earnings/me", headers=pro_user.h)).json()
    assert earnings["totals"]["settled"]["amountMinor"] == 900_000

    # Finish: fund and accept M2 -> escrow fully released, contract completed, ledger balanced.
    await client.post(f"{E}/{esc['id']}/fund", headers=buyer.idem(), json={"all": True, "paymentMethodToken": "tok_visa"})
    await drain()
    await client.post(f"/v1/milestones/{m2['id']}/submit", headers=pro_user.h, json={"note": "Local files"})
    await client.post(f"/v1/milestones/{m2['id']}/accept", headers=buyer.idem())
    await drain()
    assert (await escrow_of(client, buyer, c))["status"] == "FULLY_RELEASED"
    assert (await client.get(f"{C}/{c['id']}", headers=buyer.h)).json()["status"] == "COMPLETED"
    await balanced(sf)

    # The public profile now shows the completed engagement.
    profile = (await client.get(f"/v1/professionals/{pro['id']}")).json()
    assert profile["history"]["completedEngagements"] == 1

    # Step 8 operations: the day's books reconcile (escrow ledger = payments records).
    ops = await staff(make_user, "fin", "FINANCIAL_OPS")
    day = (await client.post("/v1/payments/reconciliations", headers=ops.h, json={"day": clock.now().date().isoformat()})).json()
    assert day["status"] == "MATCHED", day["checks"]


async def test_disagreement_is_resolved_through_a_dispute_with_money_frozen(client, make_user, drain, sf):
    # Steps 1-8 in short: a signed, funded engagement with submitted work.
    pro_user, pro = await tier_b(client, make_user, drain, "venky")
    buyer, org = await buyer_org(client, make_user, drain, "lennox")
    req = (await client.post(R, headers=buyer.idem(), json=request_body(org, pro))).json()[0]
    p = (await client.post(f"{R}/{req['id']}/proposals", headers=pro_user.h, json=proposal_body())).json()
    await client.post(f"{P}/{p['id']}/submit", headers=pro_user.idem())
    await client.post(f"{P}/{p['id']}/accept", headers=buyer.idem())
    await drain()
    c = (await client.get(C, headers=buyer.h)).json()["items"][0]
    await buyer.step_up()
    await client.post(f"{C}/{c['id']}/sign", headers=buyer.idem(), json={"termsHash": c["termsHash"]})
    await pro_user.step_up()
    await client.post(f"{C}/{c['id']}/sign", headers=pro_user.idem(), json={"termsHash": c["termsHash"]})
    await drain()
    esc = await escrow_of(client, buyer, c)
    await client.post(f"{E}/{esc['id']}/fund", headers=buyer.idem(), json={"milestoneIds": [c["milestones"][0]["id"]], "paymentMethodToken": "tok_visa"})
    await drain()
    m1 = c["milestones"][0]["id"]
    await client.post(f"/v1/milestones/{m1}/submit", headers=pro_user.h, json={"note": "Master file"})

    # Step 9: the buyer disputes; the money freezes and the contract pauses at once.
    d = (await client.post(D, headers=buyer.idem(), json=dispute_body(c))).json()
    await drain()
    assert (await escrow_of(client, buyer, c))["allocations"][0]["state"] == "ON_HOLD"
    assert (await client.post(f"/v1/milestones/{m1}/accept", headers=buyer.idem())).status_code == 409

    # Messaging must pause in both the request and engagement, while evidence remains readable.
    threads = (await client.get("/v1/threads", headers=buyer.h)).json()["items"]
    engagement_thread = next(t for t in threads if t["contextType"] == "CONTRACT")
    request_thread = next(t for t in threads if t["contextType"] == "PROPOSAL_REQUEST")
    assert engagement_thread["locked"] and request_thread["locked"]
    for thread in (engagement_thread, request_thread):
        response = await client.post(f"/v1/threads/{thread['id']}/messages", headers=buyer.idem(), json={"body": "Paused"})
        assert response.status_code == 409 and response.json()["code"] == "THREAD_READ_ONLY"
        assert (await client.get(f"/v1/threads/{thread['id']}/messages", headers=pro_user.h)).status_code == 200
    assert (await client.post(f"{C}/{c['id']}/change-orders", headers=buyer.idem(), json={
        "type": "EXTEND_TIMELINE", "delta": {"endDate": "2030-01-01"}, "impact": "Later delivery",
    })).status_code == 409

    # Evidence with stored files that both sides can open, then a structured 60/40 settlement.
    notes = upload("review-notes.pdf", b"structure gaps")
    await client.post(f"{D}/{d['id']}/evidence", headers=buyer.h,
                      json={"evidenceType": "DELIVERABLE", "description": "Our review notes", "items": [notes]})
    assert (await client.get(f"{D}/{d['id']}/files/{notes['sha256']}", headers=pro_user.h)).content == raw(notes)
    await client.post(f"{D}/{d['id']}/evidence/complete", headers=buyer.h)
    d = (await client.post(f"{D}/{d['id']}/evidence/complete", headers=pro_user.h)).json()
    assert d["status"] == "DIRECT_RESOLUTION"
    d = (await client.post(f"{D}/{d['id']}/resolution-proposals", headers=pro_user.h, json={
        "outcome": "PARTIAL_REFUND", "allocations": [{"milestoneId": m1, "releaseMinor": 600_000, "refundMinor": 400_000}]})).json()
    await client.post(f"/v1/resolution-proposals/{d['proposals'][0]['id']}/accept", headers=buyer.idem())
    await drain()

    threads = (await client.get("/v1/threads", headers=buyer.h)).json()["items"]
    assert all(not t["locked"] for t in threads if t["contextType"] in {"CONTRACT", "PROPOSAL_REQUEST"})

    # Enforced exactly through escrow: 600k released (minus fee), 400k refunded, case closed, books balanced.
    assert (await client.get(f"{D}/{d['id']}", headers=buyer.h)).json()["status"] == "CLOSED"
    esc = await escrow_of(client, buyer, c)
    assert esc["refunded"]["amountMinor"] == 400_000 and esc["allocations"][0]["released"]["amountMinor"] == 540_000
    refunds = (await client.get("/v1/payments/refunds", headers=buyer.h, params={"organizationId": org["id"]})).json()
    assert [r["status"] for r in refunds] == ["SETTLED"]
    await balanced(sf)


async def test_access_boundaries_hold_across_the_journey(client, make_user, drain):
    """Outsiders see nothing; each side can only do its own part."""
    pro_user, pro = await tier_b(client, make_user, drain, "venky")
    buyer, org = await buyer_org(client, make_user, drain, "lennox")
    req = (await client.post(R, headers=buyer.idem(), json=request_body(org, pro))).json()[0]
    outsider = await make_user("eve")
    assert (await client.get(f"{R}/{req['id']}", headers=outsider.h)).status_code == 404
    p = (await client.post(f"{R}/{req['id']}/proposals", headers=pro_user.h, json=proposal_body())).json()
    await client.post(f"{P}/{p['id']}/submit", headers=pro_user.idem())
    assert (await client.post(f"{P}/{p['id']}/accept", headers=pro_user.idem())).status_code in (403, 404)  # not the buyer
    await client.post(f"{P}/{p['id']}/accept", headers=buyer.idem())
    await drain()
    c = (await client.get(C, headers=buyer.h)).json()["items"][0]
    assert (await client.get(f"{C}/{c['id']}", headers=outsider.h)).status_code == 404
    # Signing without a fresh two-step confirmation is refused.
    r = await client.post(f"{C}/{c['id']}/sign", headers=buyer.idem(), json={"termsHash": c["termsHash"]})
    assert r.json()["code"] == "STEP_UP_REQUIRED"
