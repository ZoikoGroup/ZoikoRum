"""Risk scoring from payment and behaviour signals (advisory only) and a steadier trust score."""

from __future__ import annotations

import uuid

from sqlalchemy import text

from test_proposal import buyer_org, tier_b
from zoikorum.shared import clock


async def test_signals_add_up_and_open_one_review(client, make_user, drain, sf):
    from zoikorum.domains.ai import risk

    buyer, org = await buyer_org(client, make_user, drain, "risk-buyer")
    oid = uuid.UUID(org["id"])
    async with sf() as s, s.begin():
        await risk.observe(s, uuid.uuid4(), "ORGANIZATION", oid, "PAYMENT_FAILED", clock.now())
        await risk.observe(s, uuid.uuid4(), "ORGANIZATION", oid, "CHARGEBACK", clock.now())
        assert (await risk.score(s, "ORGANIZATION", oid))["score"] == 38
        await risk.observe(s, uuid.uuid4(), "ORGANIZATION", oid, "CHARGEBACK", clock.now())  # 8 + 60 (capped) = 68: review
        await risk.observe(s, uuid.uuid4(), "ORGANIZATION", oid, "PAYMENT_FAILED", clock.now())  # still high: no second case
    async with sf() as s:
        flags = (await s.execute(text("SELECT envelope FROM platform.outbox WHERE event_type LIKE '%risk.flag_raised%'"))).all()
    raised = [f[0]["payload"] for f in flags if f[0]["payload"].get("reasonCode") == "RISK_SCORE_HIGH"]
    assert len(raised) == 1 and raised[0]["subjectType"] == "ORGANIZATION" and raised[0]["advisoryOnly"] is True
    assert "chargebacks" in raised[0]["summary"]

    analyst = await make_user("risk-analyst", platform_roles=("TS_ANALYST",))
    await analyst.step_up()
    detail = (await client.get(f"/v1/admin/risk/ORGANIZATION/{org['id']}", headers=analyst.h)).json()
    assert detail["score"] == 76 and detail["signals"][0]["signal"] == "CHARGEBACK"
    assert (await client.get("/v1/admin/risk", headers=analyst.h)).json()[0]["subjectId"] == org["id"]
    assert (await client.get("/v1/admin/risk", headers=buyer.h)).status_code == 403
    assert (await client.get("/v1/organizations/mine", headers=buyer.h)).status_code == 200  # nothing restricted by a score


async def test_small_score_moves_do_not_change_the_published_score(client, make_user, drain, sf):
    from zoikorum.domains.trust import service as trust_service
    from zoikorum.domains.trust.models import TrustProfile

    _, pro = await tier_b(client, make_user, drain, "steady-pro")
    pid = uuid.UUID(pro["id"])
    async with sf() as s, s.begin():
        prof = await s.scalar(text("SELECT score FROM trust.profiles WHERE professional_id = :p").bindparams(p=pid))
        await s.execute(text("UPDATE trust.profiles SET score = score + 1 WHERE professional_id = :p"), {"p": pid})
    async with sf() as s, s.begin():
        row = await s.get(TrustProfile, (await s.scalar(text("SELECT id FROM trust.profiles WHERE professional_id = :p").bindparams(p=pid))))
        await trust_service.recompute(s, row, "TEST")
        assert row.score == prof + 1  # a 1-point difference is kept
        row.score = prof + 5
        await trust_service.recompute(s, row, "TEST")
        assert row.score == prof  # a real difference is applied
