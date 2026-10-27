"""Request -> proposal -> engagement gaps: success criteria carried into the contract, tracked scope suggestions decided one
by one, proposal readiness signals, "Awaiting payment protection" until the first funding, payment protection setup,
funding expiry, buyer screening before funding, paged escrow ledger, release receipts and the release-approval SLA."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

from sqlalchemy import text

from test_contract import C, accepted_contract, signed_contract
from test_escrow import E, escrow_of
from test_proposal import P, R, buyer_org, proposal_body, request_body, tier_b
from zoikorum.shared import clock
from zoikorum.shared.event_catalog import E as EV
from zoikorum.shared.events import record_event
from zoikorum.shared.relay import fire_due_timers

SUCCESS = {"successDefinition": "Both files accepted by the tax authority without queries",
           "successMeasures": ["No queries within 60 days of filing", "Board sign-off"]}


async def test_success_criteria_and_tracked_scope_changes_flow_into_the_contract(client, make_user, drain):
    pro_user, pro = await tier_b(client, make_user, drain, "ann")
    buyer, org = await buyer_org(client, make_user, drain)
    r = await client.post(R, headers=buyer.idem(), json=request_body(org, pro, **SUCCESS))
    assert r.status_code == 201, r.text
    req = r.json()[0]
    assert req["successCriteria"] == {"definition": SUCCESS["successDefinition"], "measures": SUCCESS["successMeasures"]}

    bad = proposal_body(scopeChanges=[{"kind": "REMOVE_DELIVERABLE", "proposed": "Drop it"}])
    assert (await client.post(f"{R}/{req['id']}/proposals", headers=pro_user.h, json=bad)).status_code == 422  # which one?
    changes = [{"kind": "ADD_DELIVERABLE", "proposed": "Benchmarking study", "reason": "Needed for the local files"},
               {"kind": "REMOVE_DELIVERABLE", "target": "Local files", "proposed": "Only one local file, for the main subsidiary"}]
    p = (await client.post(f"{R}/{req['id']}/proposals", headers=pro_user.h,
                           json=proposal_body(scopeChanges=changes, scopeNotes="Context: the second subsidiary is dormant"))).json()
    assert p["scopeAlignment"] == "ADJUSTED" and [c["status"] for c in p["scopeChanges"]] == ["PENDING", "PENDING"]
    assert p["successCriteria"]["measures"] == SUCCESS["successMeasures"]
    assert (await client.post(f"{P}/{p['id']}/submit", headers=pro_user.idem())).status_code == 200

    seen = (await client.get(f"{P}/{p['id']}", headers=buyer.h)).json()
    assert seen["readiness"]["contractReady"] is False and "2 suggested scope changes" in seen["readiness"]["contractReadyNote"]
    assert seen["readiness"]["paymentProtection"] is True and seen["readiness"]["auditRecord"] is True
    assert next(d for d in seen["deltas"] if d["field"] == "scope")["proposed"].startswith("2 suggested changes")
    r = await client.post(f"{P}/{p['id']}/accept", headers=buyer.idem())
    assert r.status_code == 409 and r.json()["code"] == "SCOPE_CHANGES_PENDING"

    add, remove = seen["scopeChanges"]
    url = f"{P}/{p['id']}/scope-changes"
    assert (await client.post(f"{url}/{add['id']}/decide", headers=pro_user.h, json={"accept": True})).status_code == 404
    r = await client.post(f"{url}/{add['id']}/decide", headers=buyer.h, json={"accept": True, "note": "Yes please"})
    assert r.status_code == 200 and r.json()["scopeChanges"][0]["status"] == "ACCEPTED"
    r = await client.post(f"{url}/{remove['id']}/decide", headers=buyer.h, json={"accept": False})
    assert r.json()["scopeChanges"][1]["status"] == "REJECTED" and r.json()["readiness"]["contractReady"] is True
    r = await client.post(f"{url}/{remove['id']}/decide", headers=buyer.h, json={"accept": True})
    assert r.status_code == 409 and r.json()["code"] == "SCOPE_CHANGE_DECIDED"
    assert (await client.post(f"{url}/nope/decide", headers=buyer.h, json={"accept": True})).status_code == 404

    assert (await client.post(f"{P}/{p['id']}/accept", headers=buyer.idem())).status_code == 200
    await drain()
    c = (await client.get(C, headers=buyer.h)).json()["items"][0]
    assert c["terms"]["successCriteria"]["definition"] == SUCCESS["successDefinition"]
    assert [x["proposed"] for x in c["terms"]["scopeChanges"]] == ["Benchmarking study"]  # only the accepted one
    assert "Agreed scope changes:" in c["terms"]["scope"] and "dormant" in c["terms"]["scope"]
    doc = (await client.get(f"{C}/{c['id']}/document", headers=buyer.h)).text
    assert "Success criteria (what done looks like): Both files accepted" in doc and "Measured by: Board sign-off" in doc
    assert "Add deliverable: Benchmarking study" in doc and "Only one local file" not in doc


async def test_awaiting_payment_protection_until_the_first_funding(client, make_user, drain):
    pro_user, pro, buyer, c = await signed_contract(client, make_user, drain)
    assert c["status"] == "ACTIVE" and c["stage"] == "AWAITING_PAYMENT_PROTECTION"
    assert c["nextAction"].startswith("Awaiting payment protection: do not start work")  # the professional countersigned
    mine = (await client.get(f"{C}/{c['id']}", headers=buyer.h)).json()
    assert mine["nextAction"] == "Set up payment protection and fund M1 to start work"
    assert (await client.get(f"{C}/summary", headers=buyer.h)).json()["awaitingPaymentProtection"] == 1
    m1, m2 = c["milestones"]
    assert (await client.post(f"/v1/milestones/{m1['id']}/submit", headers=pro_user.h, json={"note": "early"})).status_code == 409

    esc = await escrow_of(client, buyer, c)
    assert esc["protection"]["releaseModel"] is None and esc["protection"]["firstFunding"] == [m1["id"]]
    assert esc["buyerScreening"]["status"] == "NOT_SCREENED"
    url = f"{E}/{esc['id']}/protection"
    r = await client.put(url, headers=buyer.h, json={"releaseModel": "FIXED"})
    assert r.status_code == 422 and r.json()["code"] == "DISPUTE_HOLD_ACK_REQUIRED"
    r = await client.put(url, headers=buyer.h, json={"releaseModel": "RETAINER", "disputeHoldAcknowledged": True})
    assert r.status_code == 422 and r.json()["code"] == "RELEASE_MODEL_INVALID"
    r = await client.put(url, headers=buyer.h, json={"releaseModel": "FIXED", "disputeHoldAcknowledged": True,
                                                     "approverIdentityId": str(pro_user.id)})
    assert r.status_code == 422 and r.json()["code"] == "APPROVER_INVALID"
    assert (await client.put(url, headers=pro_user.h, json={"releaseModel": "FIXED", "disputeHoldAcknowledged": True})).status_code == 403
    r = await client.put(url, headers=buyer.h, json={"releaseModel": "FIXED", "disputeHoldAcknowledged": True})
    assert r.status_code == 200, r.text
    prot = r.json()["protection"]
    assert prot["releaseModel"] == "FIXED" and prot["approverIdentityId"] == str(buyer.id) and prot["confirmedAt"]
    assert sorted(prot["firstFunding"]) == sorted([m1["id"], m2["id"]]) and "frozen" in prot["disputeHold"]

    fund = f"{E}/{esc['id']}/fund"
    r = await client.post(fund, headers=buyer.idem(), json={"milestoneIds": [m1["id"]], "paymentMethodToken": "tok_visa"})
    assert r.status_code == 409 and r.json()["code"] == "FIXED_FUNDS_ALL"
    assert (await client.post(fund, headers=buyer.idem(), json={"all": True, "paymentMethodToken": "tok_visa"})).status_code == 200
    # Still awaiting while the payment is processing: the funding is not in place yet.
    assert (await client.get(f"{C}/{c['id']}", headers=buyer.h)).json()["stage"] == "AWAITING_PAYMENT_PROTECTION"
    await drain()
    after = (await client.get(f"{C}/{c['id']}", headers=pro_user.h)).json()
    assert after["stage"] == "ACTIVE" and after["nextAction"].startswith("Deliver M1")
    assert (await client.get(f"{C}/summary", headers=buyer.h)).json()["awaitingPaymentProtection"] == 0
    r = await client.put(url, headers=buyer.h, json={"releaseModel": "MILESTONE", "disputeHoldAcknowledged": True})
    assert r.status_code == 409 and r.json()["code"] == "PROTECTION_LOCKED"


async def test_never_funded_engagement_expires(client, make_user, drain, sf):
    pro_user, pro, buyer, c = await signed_contract(client, make_user, drain)
    await fire_due_timers(sf, now=clock.now() + timedelta(days=29))
    await drain()
    assert (await escrow_of(client, buyer, c))["status"] == "UNFUNDED"  # not yet: the window is 30 days

    await fire_due_timers(sf, now=clock.now() + timedelta(days=31))
    await drain()
    esc = await escrow_of(client, buyer, c)
    assert esc["status"] == "EXPIRED" and {a["state"] for a in esc["allocations"]} == {"EXPIRED"} and esc["canFund"] is False
    after = (await client.get(f"{C}/{c['id']}", headers=buyer.h)).json()
    assert after["status"] == "TERMINATED" and {m["status"] for m in after["milestones"]} == {"CANCELLED"}
    r = await client.post(f"{E}/{esc['id']}/fund", headers=buyer.idem(), json={"all": True, "paymentMethodToken": "tok_visa"})
    assert r.status_code == 409
    async with sf() as s:
        moved = await s.scalar(text("SELECT count(*) FROM escrow.ledger_entries"))
    assert moved == 0  # nothing was ever paid in, so nothing moved


async def test_funded_engagement_does_not_expire(client, make_user, drain, sf):
    pro_user, pro, buyer, c = await signed_contract(client, make_user, drain)
    esc = await escrow_of(client, buyer, c)
    await client.post(f"{E}/{esc['id']}/fund", headers=buyer.idem(), json={"milestoneIds": [c["milestones"][0]["id"]],
                                                                           "paymentMethodToken": "tok_visa"})
    await drain()
    await fire_due_timers(sf, now=clock.now() + timedelta(days=31))
    await drain()
    esc = await escrow_of(client, buyer, c)
    assert [a["state"] for a in esc["allocations"]] == ["HELD", "UNFUNDED"]
    assert (await client.get(f"{C}/{c['id']}", headers=buyer.h)).json()["status"] == "ACTIVE"


async def test_buyer_screening_blocks_or_warns_before_funding(client, make_user, drain, sf):
    from zoikorum.domains.verification.models import VerificationCase

    pro_user, pro, buyer, c = await signed_contract(client, make_user, drain)
    case_id = uuid.uuid4()
    async with sf() as s, s.begin():
        s.add(VerificationCase(id=case_id, subject_type="ORGANIZATION", subject_id=uuid.UUID(c["organizationId"]),
                               owner_identity_id=buyer.id, verification_type="RESTRICTIONS", status="FAILED",
                               label="Sanctions & restrictions screening"))
    esc = await escrow_of(client, buyer, c)
    assert esc["buyerScreening"]["status"] == "FLAGGED"
    assert (await client.get(f"{E}/{esc['id']}", headers=pro_user.h)).json()["buyerScreening"] is None  # buyers only
    r = await client.post(f"{E}/{esc['id']}/fund", headers=buyer.idem(), json={"all": True, "paymentMethodToken": "tok_visa"})
    assert r.status_code == 403 and r.json()["code"] == "BUYER_SCREENING_FLAGGED"

    async with sf() as s, s.begin():
        await s.execute(text("UPDATE verification.cases SET status = 'IN_REVIEW' WHERE id = :i"), {"i": case_id})
    esc = await escrow_of(client, buyer, c)
    assert esc["buyerScreening"]["status"] == "PENDING" and "in progress" in esc["buyerScreening"]["message"]
    r = await client.post(f"{E}/{esc['id']}/fund", headers=buyer.idem(), json={"all": True, "paymentMethodToken": "tok_visa"})
    assert r.status_code == 200  # pending screening warns, it does not block

    async with sf() as s, s.begin():
        await s.execute(text("UPDATE verification.cases SET status = 'VERIFIED' WHERE id = :i"), {"i": case_id})
    assert (await escrow_of(client, buyer, c))["buyerScreening"]["status"] == "CLEAR"


async def test_ledger_pages_and_release_receipt(client, make_user, drain, sf):
    pro_user, pro, buyer, c = await signed_contract(client, make_user, drain)
    esc = await escrow_of(client, buyer, c)
    m1 = c["milestones"][0]["id"]
    await client.post(f"{E}/{esc['id']}/fund", headers=buyer.idem(), json={"milestoneIds": [m1], "paymentMethodToken": "tok_visa"})
    await drain()
    await client.post(f"/v1/milestones/{m1}/submit", headers=pro_user.h, json={"note": "Master file"})
    await client.post(f"/v1/milestones/{m1}/accept", headers=buyer.idem())
    await drain()

    full = (await client.get(f"{E}/{esc['id']}/ledger", headers=buyer.h)).json()
    assert len(full["items"]) == 5 and full["nextCursor"] is None
    seen, cursor = [], None
    while True:
        page = (await client.get(f"{E}/{esc['id']}/ledger", headers=buyer.h,
                                 params={"limit": 2, **({"cursor": cursor} if cursor else {})})).json()
        seen += page["items"]
        cursor = page["nextCursor"]
        if not cursor:
            break
    assert [x["id"] for x in seen] == [x["id"] for x in full["items"]]  # every line once, in order: nothing truncated

    esc = await escrow_of(client, buyer, c)
    a1 = esc["allocations"][0]
    assert a1["state"] == "RELEASED" and a1["releaseId"] and a1["releaseReference"]
    for who in (buyer, pro_user):
        r = await client.get(f"{E}/releases/{a1['releaseId']}/receipt", headers=who.h)
        assert r.status_code == 200 and r.headers["content-type"] == "application/pdf" and r.content.startswith(b"%PDF")
        assert a1["releaseReference"] in r.headers["content-disposition"]
    stranger = await make_user("sam")
    assert (await client.get(f"{E}/releases/{a1['releaseId']}/receipt", headers=stranger.h)).status_code == 404
    assert (await client.get(f"{E}/releases/{uuid.uuid4()}/receipt", headers=buyer.h)).status_code == 404
    await drain()
    async with sf() as s:
        audited = await s.scalar(text("SELECT count(*) FROM audit.audit_records WHERE action LIKE '%escrow.release.receipt_downloaded%'"))
    assert audited == 2


async def test_release_approval_due_date_is_shown_to_buyers(client, make_user, drain, sf):
    pro_user, pro, buyer, c = await signed_contract(client, make_user, drain)
    m1 = c["milestones"][0]["id"]
    async with sf() as s, s.begin():
        await s.execute(text("UPDATE escrow.allocations SET state = 'RELEASE_PENDING_APPROVAL' WHERE milestone_id = :m"), {"m": m1})
    due = clock.now() + timedelta(hours=24)
    for kind, deadline in ((EV.APPROVAL_REQUIRED, due), (EV.APPROVAL_ESCALATED, due + timedelta(hours=48))):
        async with sf() as s, s.begin():
            record_event(s, kind, aggregate_type="ApprovalRequest", aggregate_id=uuid.uuid4(), tenant_id=c["organizationId"],
                         payload={"organizationId": c["organizationId"], "subjectType": "Milestone", "subjectId": m1,
                                  "action": "ESCROW_RELEASE", "approvalRequestId": uuid.uuid4(), "deadline": deadline})
        await drain()
        a1 = (await escrow_of(client, buyer, c))["allocations"][0]
        assert a1["releaseApprovalDueAt"] and abs((datetime.fromisoformat(a1["releaseApprovalDueAt"].replace("Z", "+00:00")) - deadline).total_seconds()) < 1


async def test_contract_scope_change_shapes_still_generate_for_plain_requests(client, make_user, drain):
    # A request without success criteria or scope suggestions keeps the original terms shape.
    pro_user, pro, buyer, org, accepted, c = await accepted_contract(client, make_user, drain)
    assert "successCriteria" not in c["terms"] and "scopeChanges" not in c["terms"] and c["stage"] == "AWAITING_SIGNATURES"
