"""Step 7: contract generated from the accepted proposal, buyer signs then professional countersigns (step-up),
milestones wait for funding, then deliver -> revise -> accept -> contract completed."""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from sqlalchemy import text

from filehelp import upload
from test_proposal import P, R, buyer_org, proposal_body, request_body, tier_b
from zoikorum.shared import clock
from zoikorum.shared.event_catalog import E
from zoikorum.shared.events import record_event

C = "/v1/contracts"


async def accepted_contract(client, make_user, drain):
    pro_user, pro = await tier_b(client, make_user, drain, "ann")
    buyer, org = await buyer_org(client, make_user, drain)
    req = (await client.post(R, headers=buyer.idem(), json=request_body(org, pro, ndaRequired=True))).json()[0]
    await client.post(f"{R}/{req['id']}/accept-nda", headers=pro_user.h)
    p = (await client.post(f"{R}/{req['id']}/proposals", headers=pro_user.h, json=proposal_body())).json()
    await client.post(f"{P}/{p['id']}/submit", headers=pro_user.idem())
    accepted = (await client.post(f"{P}/{p['id']}/accept", headers=buyer.idem())).json()
    await drain()
    contract = (await client.get(C, headers=buyer.h)).json()["items"][0]
    return pro_user, pro, buyer, org, accepted, contract


async def signed_contract(client, make_user, drain):
    pro_user, pro, buyer, org, accepted, c = await accepted_contract(client, make_user, drain)
    await buyer.step_up()
    await client.post(f"{C}/{c['id']}/sign", headers=buyer.idem(), json={"termsHash": c["termsHash"]})
    await pro_user.step_up()
    r = await client.post(f"{C}/{c['id']}/sign", headers=pro_user.idem(), json={"termsHash": c["termsHash"]})
    assert r.status_code == 200, r.text
    await drain()
    return pro_user, pro, buyer, r.json()


async def fund(sf, drain, contract, milestone_ids):
    """Stand-in for the escrow domain (Step 8) announcing that funds are held."""
    async with sf() as s, s.begin():
        record_event(s, E.ESCROW_FUNDED, aggregate_type="EscrowAccount", aggregate_id=uuid.uuid4(), tenant_id=contract["organizationId"],
                     payload={"escrowAccountId": uuid.uuid4(), "contractId": contract["id"], "fundingId": uuid.uuid4(),
                              "organizationId": contract["organizationId"], "milestoneIds": milestone_ids,
                              "amountMinor": 0, "currency": "USD"})
    await drain()


async def test_contract_is_generated_from_the_accepted_proposal(client, make_user, drain, sf):
    pro_user, pro, buyer, org, accepted, c = await accepted_contract(client, make_user, drain)
    assert c["status"] == "PENDING_SIGNATURE" and c["termsHash"] == accepted["termsHash"]
    assert c["reference"].startswith("ZK-ENG-") and c["ndaRequired"] is True
    assert c["total"] == {"amountMinor": 1_500_000, "currency": "USD"} and c["title"] == "Transfer pricing review"
    assert [(m["sequence"], m["status"]) for m in c["milestones"]] == [(1, "PENDING_FUNDING"), (2, "PENDING_FUNDING")]
    assert c["viewerRole"] == "BUYER" and c["canSign"] is True and c["nextAction"] == "Review and sign the contract"

    seen = (await client.get(f"{C}/{c['id']}", headers=pro_user.h)).json()
    assert seen["viewerRole"] == "PROFESSIONAL" and seen["canSign"] is False and seen["nextAction"] == "Waiting for the buyer to sign"
    doc = await client.get(f"{C}/{c['id']}/document", headers=buyer.h)
    assert doc.status_code == 200 and c["reference"] in doc.text and "Acceptance criteria: OECD-compliant master file" in doc.text
    assert "11. CONFIDENTIALITY" in doc.text and doc.headers["X-Document-SHA256"] == c["documentSha256"]
    stranger = await make_user("sam")
    assert (await client.get(f"{C}/{c['id']}", headers=stranger.h)).status_code == 404

    await drain()  # generation is idempotent per proposal
    assert len((await client.get(C, headers=buyer.h)).json()["items"]) == 1
    async with sf() as s:
        viewed = await s.scalar(text("SELECT count(*) FROM audit.audit_records WHERE action LIKE '%contract.document.viewed%'"))
    assert viewed == 1


async def test_signing_order_step_up_and_receipts(client, make_user, drain, sf):
    pro_user, pro, buyer, org, accepted, c = await accepted_contract(client, make_user, drain)
    url, body = f"{C}/{c['id']}/sign", {"termsHash": c["termsHash"]}

    r = await client.post(url, headers=pro_user.idem(), json=body)
    assert r.status_code == 409 and r.json()["code"] == "BUYER_SIGNS_FIRST"
    r = await client.post(url, headers=buyer.idem(), json=body)
    assert r.json()["code"] == "STEP_UP_REQUIRED"  # signing needs a fresh two-step confirmation
    await buyer.step_up()
    r = await client.post(url, headers=buyer.idem(), json={"termsHash": "0" * 64})
    assert r.status_code == 409 and r.json()["code"] == "TERMS_CHANGED"
    r = await client.post(url, headers=buyer.idem(), json=body)
    assert r.status_code == 200 and r.json()["status"] == "PENDING_SIGNATURE"
    assert r.json()["nextAction"] == "Waiting for Ann to countersign"
    assert (await client.post(url, headers=buyer.idem(), json=body)).json()["code"] == "ALREADY_SIGNED"

    await pro_user.step_up()
    r = await client.post(url, headers=pro_user.idem(), json=body)
    assert r.status_code == 200 and r.json()["status"] == "ACTIVE" and r.json()["activatedAt"]
    assert [(s["party"], s["authStrength"]) for s in r.json()["signatures"]] == [("BUYER", "MFA"), ("PROFESSIONAL", "MFA")]
    await drain()

    async with sf() as s:
        active = await s.scalar(text("SELECT active_engagements FROM professional.professionals WHERE id = :p"), {"p": pro["id"]})
    assert active == 1
    with pytest.raises(Exception, match="append-only"):  # receipts can never be edited
        async with sf() as s, s.begin():
            await s.execute(text("UPDATE contract.signatures SET signer_name = 'x'"))


async def test_milestones_wait_for_funding_then_deliver_revise_accept_complete(client, make_user, drain, sf):
    pro_user, pro, buyer, c = await signed_contract(client, make_user, drain)
    m1, m2 = c["milestones"]
    r = await client.post(f"/v1/milestones/{m1['id']}/submit", headers=pro_user.h, json={"note": "Draft"})
    assert r.status_code == 409 and r.json()["code"] == "NOT_FUNDED"  # no work without funding

    await fund(sf, drain, c, [m1["id"]])
    c = (await client.get(f"{C}/{c['id']}", headers=pro_user.h)).json()
    assert [m["status"] for m in c["milestones"]] == ["IN_PROGRESS", "PENDING_FUNDING"] and c["nextAction"].startswith("Deliver M1")

    file = upload("master-file.pdf", b"master")
    r = await client.post(f"/v1/milestones/{m1['id']}/submit", headers=pro_user.h, json={"note": "Master file attached", "files": [file]})
    assert r.json()["milestones"][0]["status"] == "SUBMITTED" and r.json()["milestones"][0]["acceptanceDueAt"]
    assert (await client.post(f"/v1/milestones/{m1['id']}/accept", headers=pro_user.idem())).status_code == 403

    r = await client.post(f"/v1/milestones/{m1['id']}/request-revision", headers=buyer.h, json={"reason": "Add the benchmarking appendix"})
    assert r.json()["milestones"][0]["status"] == "REVISION_REQUESTED"
    await client.post(f"/v1/milestones/{m1['id']}/submit", headers=pro_user.h, json={"note": "Appendix added", "files": [file]})
    r = await client.post(f"/v1/milestones/{m1['id']}/accept", headers=buyer.idem())
    m = r.json()["milestones"][0]
    assert m["status"] == "ACCEPTED" and m["revisionCount"] == 1 and len(m["submissions"]) == 2
    assert r.json()["acceptedAmount"]["amountMinor"] == 1_000_000 and r.json()["status"] == "ACTIVE"

    await fund(sf, drain, c, [m2["id"]])
    await client.post(f"/v1/milestones/{m2['id']}/submit", headers=pro_user.h, json={"note": "Local files"})
    r = await client.post(f"/v1/milestones/{m2['id']}/accept", headers=buyer.idem())
    assert r.json()["status"] == "COMPLETED" and r.json()["completedAt"]
    await drain()
    async with sf() as s:
        active = await s.scalar(text("SELECT active_engagements FROM professional.professionals WHERE id = :p"), {"p": pro["id"]})
        events = (await s.scalars(text("SELECT event_type FROM platform.outbox WHERE aggregate_id = :c ORDER BY seq"), {"c": c["id"]})).all()
    assert active == 0
    assert events[-1].endswith("contract.completed.v1")
    summary = (await client.get(f"{C}/summary", headers=buyer.h)).json()
    assert summary["contracts"] == {"COMPLETED": 1} and summary["milestones"] == {"ACCEPTED": 2}


async def test_unsigned_contract_escalates_after_the_deadline(client, make_user, drain, sf):
    pro_user, pro, buyer, org, accepted, c = await accepted_contract(client, make_user, drain)
    clock.advance(timedelta(days=8))
    await drain()
    async with sf() as s:
        escalated = await s.scalar(text("SELECT envelope->'payload'->'waitingFor' FROM platform.outbox "
                                        "WHERE event_type LIKE '%signature_deadline_escalated%' AND aggregate_id = :c"), {"c": c["id"]})
    assert escalated == ["BUYER", "PROFESSIONAL"]
