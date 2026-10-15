"""Enterprise dispute controls from the buyer organisation's policy (mandatory mediation, legal review, escalation
authority) and referral to external arbitration, where money stays frozen until Legal records the award."""

from __future__ import annotations

from test_automatic_disputes import policy_contract
from test_dispute import D, dispute_body, staff
from test_escrow import escrow_of


async def _without_legal_reviewer(sf, buyer):
    from sqlalchemy import text
    async with sf() as s, s.begin():
        await s.execute(text("UPDATE buyer.members SET roles = array_remove(roles, 'LEGAL_REVIEWER') WHERE identity_id = :i"), {"i": buyer.id})


async def _to_direct(client, buyer, pro_user, c):
    d = (await client.post(D, headers=buyer.idem(), json=dispute_body(c))).json()
    await client.post(f"{D}/{d['id']}/evidence/complete", headers=pro_user.h)
    return (await client.post(f"{D}/{d['id']}/evidence/complete", headers=buyer.h)).json()


async def test_mandatory_mediation_escalation_authority_and_arbitration(client, make_user, drain, sf):
    pro_user, pro, buyer, c = await policy_contract(client, make_user, drain, {
        "disputeMediationAboveMinor": 0, "disputeEscalationRoles": ["LEGAL_REVIEWER"]})
    await _without_legal_reviewer(sf, buyer)
    d = await _to_direct(client, buyer, pro_user, c)
    assert d["status"] == "DIRECT_RESOLUTION" and d["mediationRequired"] is True and d["canEscalate"] is True
    assert "mediator" in d["nextStep"]
    r = await client.post(f"{D}/{d['id']}/resolution-proposals", headers=pro_user.h, json={"outcome": "FULL_RELEASE"})
    assert r.json()["code"] == "MEDIATION_REQUIRED"
    assert (await client.post(f"{D}/{d['id']}/escalate", headers=buyer.h)).json()["code"] == "ESCALATION_ROLE_REQUIRED"
    d = (await client.post(f"{D}/{d['id']}/escalate", headers=pro_user.h)).json()  # the professional is not bound by the buyer's roles
    assert d["status"] == "MEDIATION"

    mediator = await staff(make_user, "mo", "MEDIATOR")
    await client.post(f"{D}/{d['id']}/assign-mediator", headers=mediator.h, json={"mediatorIdentityId": str(mediator.id)})
    refer = {"forum": "ICC International Court of Arbitration", "reason": "The engagement names ICC arbitration for disputes of this size."}
    d = (await client.post(f"{D}/{d['id']}/arbitration", headers=mediator.h, json=refer)).json()
    assert d["arbitration"]["forum"].startswith("ICC") and "frozen" in d["nextStep"]
    rec = {"outcome": "FULL_RELEASE", "summary": "The delivered master file follows the agreed structure in full."}
    assert (await client.post(f"{D}/{d['id']}/recommendation", headers=mediator.h, json=rec)).json()["code"] == "REFERRED_TO_ARBITRATION"
    await drain()
    assert (await escrow_of(client, buyer, c))["allocations"][0]["state"] == "ON_HOLD"  # still frozen

    award = {**rec, "awardReference": "ICC-2026-0412"}
    assert (await client.post(f"{D}/{d['id']}/arbitration/award", headers=mediator.idem(), json=award)).status_code == 403  # Legal only
    legal = await staff(make_user, "lee", "LEGAL")
    d = (await client.post(f"{D}/{d['id']}/arbitration/award", headers=legal.idem(), json=award)).json()
    assert d["status"] == "DECIDED" and d["decision"]["decisionPath"] == "ARBITRATION" and d["decision"]["appealEligible"] is False
    assert d["arbitration"]["awardReference"] == "ICC-2026-0412"
    assert any("ICC-2026-0412" in x for x in d["decision"]["policyCitations"])
    await drain()
    assert (await escrow_of(client, buyer, c))["allocations"][0]["state"] == "RELEASED"


async def test_settling_above_the_threshold_needs_the_legal_reviewer(client, make_user, drain, sf):
    pro_user, pro, buyer, c = await policy_contract(client, make_user, drain, {"disputeLegalReviewAboveMinor": 0})
    await _without_legal_reviewer(sf, buyer)
    d = await _to_direct(client, buyer, pro_user, c)
    assert d["legalReviewRequired"] is True and d["mediationRequired"] is False
    d = (await client.post(f"{D}/{d['id']}/resolution-proposals", headers=pro_user.h, json={"outcome": "FULL_RELEASE"})).json()
    r = await client.post(f"/v1/resolution-proposals/{d['proposals'][0]['id']}/accept", headers=buyer.idem())
    assert r.status_code == 403 and r.json()["code"] == "LEGAL_REVIEW_REQUIRED"


async def test_closed_records_keep_the_longest_retention_and_legal_can_hold_them(client, make_user, drain, sf):
    from zoikorum.domains.dispute import service as dispute_service
    from zoikorum.shared import clock

    pro_user, pro, buyer, c = await policy_contract(client, make_user, drain, {"disputeRetentionYears": 12})
    d = await _to_direct(client, buyer, pro_user, c)
    d = (await client.post(f"{D}/{d['id']}/resolution-proposals", headers=pro_user.h, json={"outcome": "FULL_RELEASE"})).json()
    await client.post(f"/v1/resolution-proposals/{d['proposals'][0]['id']}/accept", headers=buyer.idem())
    await drain()
    d = (await client.get(f"{D}/{d['id']}", headers=buyer.h)).json()
    assert d["status"] == "CLOSED" and d["retentionBasis"] == "12 years: organisation policy"
    assert d["retainUntil"].startswith(str(clock.now().year + 12))

    legal = await staff(make_user, "lex", "LEGAL")
    body = {"hold": True, "reason": "Regulator asked us to keep this record."}
    assert (await client.post(f"{D}/{d['id']}/legal-hold", headers=buyer.h, json=body)).status_code == 403
    assert (await client.post(f"{D}/{d['id']}/legal-hold", headers=legal.h, json=body)).json()["legalHold"] is True
    async with sf() as s, s.begin():
        await dispute_service.retention_due(s, {"disputeId": d["id"]})  # on hold: not flagged
    queue = (await client.get("/v1/admin/disputes/retention", headers=legal.h)).json()
    assert [(q["reference"], q["legalHold"], q["reviewDue"]) for q in queue] == [(d["reference"], True, False)]
    await client.post(f"{D}/{d['id']}/legal-hold", headers=legal.h, json={**body, "hold": False})
    async with sf() as s, s.begin():
        await dispute_service.retention_due(s, {"disputeId": d["id"]})
    assert (await client.get("/v1/admin/disputes/retention", headers=legal.h)).json()[0]["reviewDue"] is True
    assert (await client.get("/v1/admin/disputes/retention", headers=buyer.h)).status_code == 403
