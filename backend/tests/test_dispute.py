"""Step 9: disputes - funds freeze on submission, evidence, structured direct resolution, mediation with a two-person
platform decision, enforcement through escrow (release / refund / back to work), closure; termination refunds."""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import text

from filehelp import upload
from test_contract import C, signed_contract
from test_escrow import E as ESC, balanced, escrow_of
from zoikorum.shared import clock

D = "/v1/disputes"
FILE = upload("review-notes.pdf", b"notes")


async def funded_contract(client, make_user, drain, *, both=False):
    pro_user, pro, buyer, c = await signed_contract(client, make_user, drain)
    esc = await escrow_of(client, buyer, c)
    body = {"all": True, "paymentMethodToken": "tok_visa"} if both else {"milestoneIds": [c["milestones"][0]["id"]], "paymentMethodToken": "tok_visa"}
    await client.post(f"{ESC}/{esc['id']}/fund", headers=buyer.idem(), json=body)
    await drain()
    return pro_user, pro, buyer, (await client.get(f"{C}/{c['id']}", headers=buyer.h)).json()


def dispute_body(c, category="QUALITY_ACCEPTANCE", outcome="PARTIAL_REFUND", milestones=None):
    return {"contractId": c["id"], "milestoneIds": milestones or [c["milestones"][0]["id"]], "category": category,
            "summary": "The master file does not follow the agreed OECD structure.", "desiredOutcome": outcome}


async def staff(make_user, name, *roles):
    u = await make_user(name, platform_roles=roles)
    await u.step_up()
    return u


async def test_direct_resolution_partial_refund(client, make_user, drain, sf):
    pro_user, pro, buyer, c = await funded_contract(client, make_user, drain)
    m1 = c["milestones"][0]["id"]
    r = await client.post(D, headers=buyer.idem(), json=dispute_body(c))
    assert r.status_code == 201, r.text
    d = r.json()
    assert d["status"] == "EVIDENCE_COLLECTION" and d["reference"].startswith("ZK-DSP-") and d["disputed"]["amountMinor"] == 1_000_000
    await drain()

    # Automatic stabilisation: money frozen, milestone and contract paused, no duplicate case.
    esc = await escrow_of(client, buyer, c)
    assert esc["status"] == "DISPUTED" and esc["allocations"][0]["state"] == "ON_HOLD"
    k = (await client.get(f"{C}/{c['id']}", headers=pro_user.h)).json()
    assert k["status"] == "DISPUTED" and k["milestones"][0]["status"] == "DISPUTED"
    assert (await client.post(D, headers=pro_user.idem(), json=dispute_body(c))).json()["code"] == "DUPLICATE_DISPUTE"
    assert (await client.post(f"/v1/milestones/{m1}/submit", headers=pro_user.h, json={"note": "x"})).status_code == 409

    # Evidence from both sides (append-only), then both mark complete -> direct resolution.
    r = await client.post(f"{D}/{d['id']}/evidence", headers=pro_user.h, json={"evidenceType": "DELIVERABLE", "description": "Delivered master file", "items": [FILE]})
    assert r.json()["evidence"][0]["party"] == "PROFESSIONAL"
    await client.post(f"{D}/{d['id']}/evidence/complete", headers=pro_user.h)
    d = (await client.post(f"{D}/{d['id']}/evidence/complete", headers=buyer.h)).json()
    assert d["status"] == "DIRECT_RESOLUTION" and d["directDeadline"]
    with pytest.raises(Exception, match="append-only"):
        async with sf() as s, s.begin():
            await s.execute(text("UPDATE dispute.evidence_items SET description = 'changed'"))

    # Structured proposals: amounts must add up; the other party accepts.
    bad = await client.post(f"{D}/{d['id']}/resolution-proposals", headers=buyer.h,
                            json={"outcome": "PARTIAL_REFUND", "allocations": [{"milestoneId": m1, "releaseMinor": 1, "refundMinor": 1}]})
    assert bad.status_code == 422 and bad.json()["code"] == "ALLOCATION_MISMATCH"
    d = (await client.post(f"{D}/{d['id']}/resolution-proposals", headers=buyer.h, json={
        "outcome": "PARTIAL_REFUND", "allocations": [{"milestoneId": m1, "releaseMinor": 600_000, "refundMinor": 400_000}], "note": "60/40"})).json()
    pid = d["proposals"][0]["id"]
    assert (await client.post(f"/v1/resolution-proposals/{pid}/accept", headers=buyer.idem())).status_code == 403  # not your own
    d = (await client.post(f"/v1/resolution-proposals/{pid}/accept", headers=pro_user.idem())).json()
    assert d["status"] == "DECIDED" and d["decision"]["decisionPath"] == "DIRECT"
    await drain()

    d = (await client.get(f"{D}/{d['id']}", headers=buyer.h)).json()
    assert d["status"] == "CLOSED" and [t["kind"] for t in d["timeline"]][-1] == "CLOSED"
    esc = await escrow_of(client, buyer, c)
    a1 = esc["allocations"][0]
    assert a1["state"] == "PARTIALLY_RELEASED" and a1["released"]["amountMinor"] == 540_000 and a1["fee"]["amountMinor"] == 60_000
    assert esc["refunded"]["amountMinor"] == 400_000 and esc["held"]["amountMinor"] == 0
    k = (await client.get(f"{C}/{c['id']}", headers=buyer.h)).json()
    assert k["status"] == "ACTIVE" and k["milestones"][0]["status"] == "ACCEPTED"  # the second milestone continues
    refunds = (await client.get("/v1/payments/refunds", headers=buyer.h, params={"organizationId": c["organizationId"]})).json()
    assert [(x["amount"]["amountMinor"], x["status"]) for x in refunds] == [(400_000, "SETTLED")]
    assert (await client.get("/v1/payments/earnings/me", headers=pro_user.h)).json()["payouts"][0]["net"]["amountMinor"] == 540_000
    await balanced(sf)


async def test_mediation_and_two_person_platform_decision(client, make_user, drain):
    pro_user, pro, buyer, c = await funded_contract(client, make_user, drain)
    d = (await client.post(D, headers=pro_user.idem(), json=dispute_body(c, outcome="FULL_RELEASE"))).json()
    await drain()
    clock.advance(timedelta(days=4))  # evidence window ends on its own
    await drain()
    clock.set_now(None)  # back to real time so new sign-ins get valid tokens
    d = (await client.get(f"{D}/{d['id']}", headers=buyer.h)).json()
    assert d["status"] == "DIRECT_RESOLUTION"
    assert (await client.post(f"{D}/{d['id']}/escalate", headers=buyer.h)).json()["code"] == "ESCALATION_LOCKED"

    d = (await client.post(f"{D}/{d['id']}/resolution-proposals", headers=pro_user.h, json={"outcome": "FULL_RELEASE"})).json()
    await client.post(f"/v1/resolution-proposals/{d['proposals'][0]['id']}/reject", headers=buyer.h)
    d = (await client.post(f"{D}/{d['id']}/escalate", headers=buyer.h)).json()
    assert d["status"] == "MEDIATION"

    mediator = await staff(make_user, "mia", "MEDIATOR", "PLATFORM_ADMIN", "LEGAL")
    r = await client.post(f"{D}/{d['id']}/assign-mediator", headers=mediator.h, json={"mediatorIdentityId": str(buyer.id)})
    assert r.status_code == 403 and r.json()["code"] == "CONFLICT_OF_INTEREST"
    await client.post(f"{D}/{d['id']}/assign-mediator", headers=mediator.h, json={"mediatorIdentityId": str(mediator.id)})
    rec = {"outcome": "REWORK", "summary": "The deliverable misses two required sections; rework within the agreed scope is fair.",
           "citations": ["Evidence: delivered master file", "Agreement clause 8"]}
    d = (await client.post(f"{D}/{d['id']}/recommendation", headers=mediator.h, json=rec)).json()
    assert d["recommendation"]["outcome"] == "REWORK"
    await client.post(f"{D}/{d['id']}/recommendation/accept", headers=buyer.idem())
    d = (await client.post(f"{D}/{d['id']}/recommendation/reject", headers=pro_user.h)).json()
    assert d["status"] == "MEDIATION"  # binding only if both accept

    d = (await client.post(f"{D}/{d['id']}/decision", headers=mediator.h, json=rec)).json()
    assert d["pendingDecision"]["outcome"] == "REWORK"
    r = await client.post(f"{D}/{d['id']}/decision/approve", headers=mediator.idem())
    assert r.status_code == 403 and r.json()["code"] == "FOUR_EYES"  # even with the Legal role, never approve your own decision
    legal = await staff(make_user, "lou", "LEGAL")
    r = await client.post(f"{D}/{d['id']}/decision/approve", headers=legal.idem())
    assert r.status_code == 200 and r.json()["decision"]["decisionPath"] == "PLATFORM"
    await drain()

    esc = await escrow_of(client, buyer, c)
    assert esc["allocations"][0]["state"] == "HELD" and esc["status"] == "FUNDED"  # rework: unfrozen, still protected
    k = (await client.get(f"{C}/{c['id']}", headers=pro_user.h)).json()
    assert k["status"] == "ACTIVE" and k["milestones"][0]["status"] == "IN_PROGRESS"
    assert (await client.get(f"{D}/{d['id']}", headers=buyer.h)).json()["status"] == "CLOSED"


async def test_conduct_skips_negotiation_and_guardrails(client, make_user, drain):
    pro_user, pro, buyer, c = await funded_contract(client, make_user, drain)
    m2 = c["milestones"][1]["id"]
    r = await client.post(D, headers=buyer.idem(), json=dispute_body(c, milestones=[m2]))
    assert r.status_code == 409 and r.json()["code"] == "MILESTONE_NOT_DISPUTABLE"  # not funded
    stranger = await make_user("sam")
    assert (await client.post(D, headers=stranger.idem(), json=dispute_body(c))).status_code == 404

    d = (await client.post(D, headers=buyer.idem(), json=dispute_body(c, category="PROFESSIONAL_CONDUCT", outcome="TERMINATION"))).json()
    await drain()
    await client.post(f"{D}/{d['id']}/evidence/complete", headers=buyer.h)
    d = (await client.post(f"{D}/{d['id']}/evidence/complete", headers=pro_user.h)).json()
    assert d["status"] == "MEDIATION"  # conduct disputes bypass direct negotiation
    assert (await client.get(f"{D}/{d['id']}", headers=stranger.h)).status_code == 404


async def test_termination_refunds_everything_still_held(client, make_user, drain, sf):
    pro_user, pro, buyer, c = await funded_contract(client, make_user, drain, both=True)
    d = (await client.post(D, headers=buyer.idem(), json=dispute_body(c, outcome="TERMINATION"))).json()
    await drain()
    await client.post(f"{D}/{d['id']}/evidence/complete", headers=buyer.h)
    d = (await client.post(f"{D}/{d['id']}/evidence/complete", headers=pro_user.h)).json()
    d = (await client.post(f"{D}/{d['id']}/resolution-proposals", headers=buyer.h, json={"outcome": "TERMINATION"})).json()
    await client.post(f"/v1/resolution-proposals/{d['proposals'][0]['id']}/accept", headers=pro_user.idem())
    await drain()

    k = (await client.get(f"{C}/{c['id']}", headers=buyer.h)).json()
    assert k["status"] == "TERMINATED" and {m["status"] for m in k["milestones"]} == {"CANCELLED"}
    esc = await escrow_of(client, buyer, c)
    assert {a["state"] for a in esc["allocations"]} == {"REFUNDED"} and esc["refunded"]["amountMinor"] == 1_500_000
    assert esc["status"] == "REFUNDED" and esc["released"]["amountMinor"] == 0
    async with sf() as s:
        active = await s.scalar(text("SELECT active_engagements FROM professional.professionals WHERE id = :p"), {"p": pro["id"]})
    assert active == 0
    await balanced(sf)
