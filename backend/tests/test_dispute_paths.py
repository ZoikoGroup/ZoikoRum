"""Opt-in dispute decision paths (a binding mediator recommendation, an enterprise admin decision), the account
restriction hand-off to Trust & Safety, staff conflicts of interest, the buyer dispute dashboard and scheduled reports."""

from __future__ import annotations

from sqlalchemy import text

from test_dispute import D, dispute_body, funded_contract, staff
from test_escrow import escrow_of

REC = {"outcome": "FULL_RELEASE", "summary": "The delivered master file follows the agreed structure in full."}
APPEAL = {"grounds": "PROCEDURAL_ERROR", "explanation": "The mediator did not consider the second revision we submitted."}


async def _agree(client, d, kind, *parties):
    for p in parties:
        r = await client.post(f"{D}/{d['id']}/agreements", headers=p.h, json={"kind": kind, "consent": True})
        assert r.status_code == 200, r.text
    return r.json()


async def _in_mediation(client, make_user, buyer, pro_user, c, *, agree=True):
    d = (await client.post(D, headers=pro_user.idem(), json=dispute_body(c, category="PROFESSIONAL_CONDUCT", outcome="FULL_RELEASE"))).json()
    if agree:
        d = await _agree(client, d, "BINDING_RECOMMENDATION", buyer, pro_user)
        assert d["bindingRecommendation"] is True and d["agreements"]["BINDING_RECOMMENDATION"] == ["BUYER", "PROFESSIONAL"]
    await client.post(f"{D}/{d['id']}/evidence/complete", headers=buyer.h)
    d = (await client.post(f"{D}/{d['id']}/evidence/complete", headers=pro_user.h)).json()
    assert d["status"] == "MEDIATION"
    mediator = await staff(make_user, "med-" + d["id"][:6], "MEDIATOR")
    await client.post(f"{D}/{d['id']}/assign-mediator", headers=mediator.h, json={"mediatorIdentityId": str(mediator.id)})
    return d, mediator


async def _fire_challenge(sf, d):
    from zoikorum.domains.dispute import service
    async with sf() as s, s.begin():
        await service.challenge_ended(s, {"disputeId": d["id"], "issuedAt": d["provisionalDecision"]["issuedAt"]})


async def test_binding_recommendation_becomes_the_decision_after_the_challenge_period(client, make_user, drain, sf):
    pro_user, pro, buyer, c = await funded_contract(client, make_user, drain)
    d, mediator = await _in_mediation(client, make_user, buyer, pro_user, c)
    d = (await client.post(f"{D}/{d['id']}/recommendation", headers=mediator.h, json=REC)).json()
    assert d["recommendation"]["binding"] is True and d["provisionalDecision"]["path"] == "MEDIATION"
    assert "unless a party appeals" in d["nextStep"]
    r = await client.post(f"{D}/{d['id']}/recommendation/reject", headers=buyer.h)
    assert r.status_code == 409 and r.json()["code"] == "BINDING_RECOMMENDATION"
    r = await client.post(f"{D}/{d['id']}/agreements", headers=buyer.h, json={"kind": "BINDING_RECOMMENDATION", "consent": False})
    assert r.json()["code"] == "AGREEMENT_LOCKED"
    await drain()
    assert (await escrow_of(client, buyer, c))["allocations"][0]["state"] == "ON_HOLD"  # nothing moves during the challenge period

    await _fire_challenge(sf, d)
    d = (await client.get(f"{D}/{d['id']}", headers=buyer.h)).json()
    assert d["status"] == "DECIDED" and d["decision"]["decisionPath"] == "MEDIATION" and d["decision"]["binding"] is True
    assert d["decision"]["appealEligible"] is False and d["provisionalDecision"] is None
    await drain()
    assert (await client.get(f"{D}/{d['id']}", headers=buyer.h)).json()["status"] == "CLOSED"
    assert (await escrow_of(client, buyer, c))["allocations"][0]["state"] == "RELEASED"


async def test_an_appeal_stops_a_binding_recommendation_and_can_set_it_aside(client, make_user, drain, sf):
    pro_user, pro, buyer, c = await funded_contract(client, make_user, drain)
    d, mediator = await _in_mediation(client, make_user, buyer, pro_user, c)
    d = (await client.post(f"{D}/{d['id']}/recommendation", headers=mediator.h, json=REC)).json()
    a = (await client.post(f"{D}/{d['id']}/appeal", headers=buyer.idem(), json=APPEAL)).json()
    assert a["against"] == "PROVISIONAL" and a["status"] == "PENDING"
    d = (await client.get(f"{D}/{d['id']}", headers=buyer.h)).json()
    assert d["provisionalDecision"]["appealed"] is True
    await _fire_challenge(sf, d)  # the challenge timer no longer decides anything
    assert (await client.get(f"{D}/{d['id']}", headers=buyer.h)).json()["status"] == "MEDIATION"

    legal = await staff(make_user, "lena", "LEGAL")
    body = {"outcome": "UPHELD", "reason": "The second revision was in the record and was not weighed.",
            "remediation": "The mediator reconsiders with the second revision."}
    assert (await client.post(f"{D}/{d['id']}/appeal/decision", headers=legal.idem(), json=body)).json()["status"] == "UPHELD"
    d = (await client.get(f"{D}/{d['id']}", headers=buyer.h)).json()
    assert d["status"] == "MEDIATION" and d["provisionalDecision"] is None and d["recommendation"]["setAside"] is True
    d = (await client.post(f"{D}/{d['id']}/decision", headers=mediator.h, json={**REC, "outcome": "REWORK"})).json()
    assert d["pendingDecision"]["outcome"] == "REWORK"  # the mediator may now propose a platform decision


async def test_enterprise_admin_decision_is_agreed_appealable_and_moves_money_only_when_final(client, make_user, drain, sf):
    pro_user, pro, buyer, c = await funded_contract(client, make_user, drain)
    m1 = c["milestones"][0]["id"]
    d = (await client.post(D, headers=pro_user.idem(), json=dispute_body(c, outcome="FULL_RELEASE"))).json()
    r = await client.post(f"{D}/{d['id']}/agreements", headers=pro_user.h, json={"kind": "ENTERPRISE_ADMIN", "consent": True})
    assert r.json()["code"] == "ENTERPRISE_ONLY"
    async with sf() as s, s.begin():
        await s.execute(text("UPDATE buyer.organizations SET org_type = 'ENTERPRISE' WHERE id = :o"), {"o": c["organizationId"]})
    d = await _agree(client, d, "ENTERPRISE_ADMIN", pro_user, buyer)
    assert d["enterpriseAdminPath"] is True and d["enterpriseEngagement"] is True
    await client.post(f"{D}/{d['id']}/evidence/complete", headers=buyer.h)
    await client.post(f"{D}/{d['id']}/evidence/complete", headers=pro_user.h)
    d = (await client.get(f"{D}/{d['id']}", headers=buyer.h)).json()
    assert d["status"] == "DIRECT_RESOLUTION" and d["canDecideAsEnterpriseAdmin"] is True

    decision = {"outcome": "PARTIAL_REFUND", "allocations": [{"milestoneId": m1, "releaseMinor": 700_000, "refundMinor": 300_000}],
                "summary": "Two of the three agreed sections were delivered to standard; the rest is refunded."}
    assert (await client.post(f"{D}/{d['id']}/enterprise-decision", headers=pro_user.idem(), json=decision)).status_code == 403
    d = (await client.post(f"{D}/{d['id']}/enterprise-decision", headers=buyer.idem(), json=decision)).json()
    assert d["provisionalDecision"]["path"] == "ENTERPRISE_ADMIN" and d["status"] == "DIRECT_RESOLUTION"
    r = await client.post(f"{D}/{d['id']}/resolution-proposals", headers=pro_user.h, json={"outcome": "FULL_RELEASE"})
    assert r.json()["code"] == "PROVISIONAL_DECISION_PENDING"

    assert (await client.post(f"{D}/{d['id']}/appeal", headers=pro_user.idem(), json=APPEAL)).json()["against"] == "PROVISIONAL"
    legal = await staff(make_user, "lars", "LEGAL")
    body = {"outcome": "REJECTED", "reason": "The admin weighed every revision; nothing procedural was missed."}
    assert (await client.post(f"{D}/{d['id']}/appeal/decision", headers=legal.idem(), json=body)).json()["status"] == "REJECTED"
    d = (await client.get(f"{D}/{d['id']}", headers=buyer.h)).json()
    assert d["status"] == "DECIDED" and d["decision"]["decisionPath"] == "ENTERPRISE_ADMIN"
    await drain()
    esc = await escrow_of(client, buyer, c)
    assert esc["refunded"]["amountMinor"] == 300_000 and esc["allocations"][0]["state"] == "PARTIALLY_RELEASED"


async def test_account_restriction_outcome_opens_a_linked_trust_and_safety_case(client, make_user, drain):
    pro_user, pro, buyer, c = await funded_contract(client, make_user, drain)
    d, mediator = await _in_mediation(client, make_user, buyer, pro_user, c, agree=False)
    refer = {"forum": "ICC International Court of Arbitration", "reason": "The engagement names ICC arbitration for conduct cases."}
    await client.post(f"{D}/{d['id']}/arbitration", headers=mediator.h, json=refer)
    legal = await staff(make_user, "lyra", "LEGAL")
    award = {**REC, "outcome": "FULL_REFUND", "awardReference": "ICC-2026-0999",
             "accountRestriction": {"party": "PROFESSIONAL", "reason": "The award finds repeated abusive conduct towards the buyer."}}
    d = (await client.post(f"{D}/{d['id']}/arbitration/award", headers=legal.idem(), json=award)).json()
    ref = d["decision"]["accountRestriction"]
    assert ref["party"] == "PROFESSIONAL" and ref["enforcementCaseId"]
    analyst = await staff(make_user, "tina", "TS_ANALYST")
    queue = (await client.get("/v1/admin/enforcement-cases", headers=analyst.h, params={"source": "DISPUTE_DECISION"})).json()
    case = next(q for q in queue if q["id"] == ref["enforcementCaseId"])
    assert case["status"] == "TRIAGE" and case["level"] == 0 and case["subjectId"] == pro["id"] and case["action"] is None


async def test_declared_conflicts_and_recusals_block_mediators_and_approvers(client, make_user, drain):
    pro_user, pro, buyer, c = await funded_contract(client, make_user, drain)
    d = (await client.post(D, headers=pro_user.idem(), json=dispute_body(c, category="PROFESSIONAL_CONDUCT"))).json()
    await client.post(f"{D}/{d['id']}/evidence/complete", headers=buyer.h)
    await client.post(f"{D}/{d['id']}/evidence/complete", headers=pro_user.h)
    mediator = await staff(make_user, "mona", "MEDIATOR")
    decl = await client.post("/v1/admin/conflicts", headers=mediator.h, json={
        "kind": "DECLARATION", "subjectType": "ORGANIZATION", "subjectId": c["organizationId"], "reason": "I used to work for this buyer."})
    assert decl.status_code == 201, decl.text
    r = await client.post(f"{D}/{d['id']}/assign-mediator", headers=mediator.h, json={"mediatorIdentityId": str(mediator.id)})
    assert r.status_code == 403 and r.json()["code"] == "CONFLICT_OF_INTEREST_DECLARED"
    assert (await client.get("/v1/admin/conflicts", headers=mediator.h)).status_code == 403  # the register: Legal, Risk, Exec, Admin
    assert [x["kind"] for x in (await client.get("/v1/admin/conflicts", headers=mediator.h, params={"mine": "true"})).json()] == ["DECLARATION"]
    assert (await client.post(f"/v1/admin/conflicts/{decl.json()['id']}/withdraw", headers=mediator.h)).json()["status"] == "WITHDRAWN"
    assert (await client.post(f"{D}/{d['id']}/assign-mediator", headers=mediator.h, json={"mediatorIdentityId": str(mediator.id)})).status_code == 200

    rec = {**REC, "outcome": "REWORK"}
    await client.post(f"{D}/{d['id']}/recommendation", headers=mediator.h, json=rec)
    await client.post(f"{D}/{d['id']}/recommendation/reject", headers=pro_user.h)
    await client.post(f"{D}/{d['id']}/decision", headers=mediator.h, json=rec)
    legal = await staff(make_user, "levi", "LEGAL")
    await client.post("/v1/admin/conflicts", headers=legal.h, json={"kind": "RECUSAL", "caseKind": "DISPUTE", "caseId": d["id"],
                                                                     "reason": "A close friend works at the buyer."})
    r = await client.post(f"{D}/{d['id']}/decision/approve", headers=legal.idem())
    assert r.status_code == 403 and r.json()["code"] == "CONFLICT_OF_INTEREST_DECLARED"
    register = (await client.get("/v1/admin/conflicts", headers=legal.h)).json()
    assert {x["kind"] for x in register} >= {"DECLARATION", "RECUSAL"}


async def test_buyer_dashboard_and_scheduled_reports(client, make_user, drain, sf):
    from zoikorum.domains.dispute import reports
    from zoikorum.domains.dispute.models import ReportSubscription
    from sqlalchemy import select

    pro_user, pro, buyer, c = await funded_contract(client, make_user, drain)
    org = c["organizationId"]
    d = (await client.post(D, headers=buyer.idem(), json=dispute_body(c))).json()
    dash = (await client.get(f"{D}/dashboard", headers=buyer.h, params={"orgId": org})).json()
    assert dash["open"] == 1 and dash["closed"] == 0 and dash["frozen"] == [{"currency": d["disputed"]["currency"], "amountMinor": 1_000_000, "cases": 1}]
    assert dash["recent"][0]["reference"] == d["reference"]
    assert (await client.get(f"{D}/dashboard", headers=pro_user.h, params={"orgId": org})).status_code == 404

    assert (await client.get(f"{D}/reports/subscription", headers=buyer.h, params={"orgId": org})).json() is None
    sub = (await client.put(f"{D}/reports/subscription", headers=buyer.h, json={"orgId": org, "frequency": "WEEKLY"})).json()
    assert sub["frequency"] == "WEEKLY" and sub["nextRunAt"]
    csv = await client.get(f"{D}/reports/export", headers=buyer.h, params={"orgId": org})
    assert csv.status_code == 200 and d["reference"] in csv.text and csv.text.startswith("reference,")

    async with sf() as s, s.begin():
        row = await s.scalar(select(ReportSubscription).where(ReportSubscription.identity_id == buyer.id))
        first = row.next_run_at
        await reports.report_due(s, {"subscriptionId": str(row.id), "runAt": first.isoformat()})
    await drain()
    notes = (await client.get("/v1/notifications", headers=buyer.h)).json()
    items = notes["items"] if isinstance(notes, dict) else notes
    report = next(n for n in items if n["title"] == "Your dispute report is ready")
    assert "1 still open" in report["body"]
    after = (await client.get(f"{D}/reports/subscription", headers=buyer.h, params={"orgId": org})).json()
    assert after["lastSentAt"] and after["nextRunAt"] > sub["nextRunAt"]
    assert (await client.put(f"{D}/reports/subscription", headers=buyer.h, json={"orgId": org, "frequency": None})).json() is None


def test_report_schedule_dates():
    from datetime import datetime, timezone
    from zoikorum.domains.dispute.reports import next_run, period_of

    wed = datetime(2026, 10, 21, 12, tzinfo=timezone.utc)
    assert next_run("WEEKLY", wed) == datetime(2026, 10, 26, 6, tzinfo=timezone.utc)
    assert next_run("MONTHLY", wed) == datetime(2026, 11, 1, 6, tzinfo=timezone.utc)
    assert next_run("MONTHLY", datetime(2026, 12, 1, 6, tzinfo=timezone.utc)) == datetime(2027, 1, 1, 6, tzinfo=timezone.utc)
    assert period_of("MONTHLY", datetime(2026, 11, 1, 6, tzinfo=timezone.utc))[0] == datetime(2026, 10, 1, 6, tzinfo=timezone.utc)
