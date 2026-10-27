"""Product funnels and the extended KPIs: funnel events from the web app (allowlisted, no personal data, server time),
onboarding / request / search funnel reports, payment, dispute, enforcement and board KPIs, and the per-policy dashboard."""

from __future__ import annotations

import csv
import io
import uuid
from datetime import timedelta
from types import SimpleNamespace

from sqlalchemy import text

from zoikorum.shared import clock

EVENTS = "/v1/analytics/events"


def ev(name, **props):
    return {"name": name, "props": props}


# ---- Pure rules -------------------------------------------------------------------------------------------------------

def test_props_keep_only_short_slugs_and_small_numbers():
    from zoikorum.domains.analytics.service import clean_props

    kept = clean_props({"step": "Credentials", "filter": "tier", "position": 3, "source": "jane@example.com",
                        "specialization": "Hello there", "email": "x", "step2": "a", "position2": 1})
    assert kept == {"step": "credentials", "filter": "tier", "position": 3}
    assert clean_props({"step": str(uuid.uuid4())}) == {}  # ids are never stored
    assert clean_props({"position": True, "step": 5, "filter": "x" * 61, "source": None}) == {}
    assert clean_props({"position": 10**9}) == {}


def test_step_waits_follow_sequential_routes_and_report_the_bottleneck():
    from zoikorum.domains.policy.insights import bottleneck, step_rows

    t0 = clock.now() - timedelta(hours=100)
    workflows = [{"mode": "SEQUENTIAL", "steps": [{"id": "r:0", "role": "FINANCE_APPROVER", "count": 1},
                                                  {"id": "r:1", "role": "ORG_ADMIN", "count": 1}]}]
    done = SimpleNamespace(id=1, created_at=t0, status="GRANTED", workflows=workflows)
    waiting = SimpleNamespace(id=2, created_at=t0, status="PENDING", workflows=workflows)
    vote = lambda step, hours: SimpleNamespace(step_id=step, decision="GRANT", created_at=t0 + timedelta(hours=hours))  # noqa: E731
    rows = step_rows([done, waiting], {1: [vote("r:0", 2), vote("r:1", 12)], 2: [vote("r:0", 4)]})
    assert [(r["step"], r["role"], r["completed"], r["medianHoursWait"], r["pending"]) for r in rows] == [
        (1, "FINANCE_APPROVER", 2, 3.0, 0), (2, "ORG_ADMIN", 1, 10.0, 1)]
    assert rows[1]["oldestPendingHours"] >= 95  # waiting since the first step was done
    assert bottleneck(rows)["role"] == "ORG_ADMIN"
    assert bottleneck([]) is None


# ---- Client events ----------------------------------------------------------------------------------------------------

async def test_events_are_allowlisted_anonymous_and_kept_out_of_the_ledger_projection(client, make_user, sf):
    sid = "visit-" + uuid.uuid4().hex[:12]
    r = await client.post(EVENTS, json={"sessionId": sid, "events": [
        ev("onboarding_step_viewed", step="basics", position=1, email="jane@example.com"),
        ev("made_up_event", step="x"), ev("filter_applied", filter="jurisdiction")]})
    assert r.status_code == 202, r.text
    assert r.json() == {"accepted": 2, "ignored": 1}
    async with sf() as s:
        rows = (await s.execute(text("SELECT event_type, aggregate_id, payload, occurred_at FROM analytics.event_facts "
                                     "WHERE event_type LIKE 'zoikorum.client.%' ORDER BY event_type"))).all()
    assert [r.event_type for r in rows] == ["zoikorum.client.funnel.filter_applied.v1", "zoikorum.client.funnel.onboarding_step_viewed.v1"]
    assert rows[1].payload == {"step": "basics", "position": 1, "signedIn": False}
    assert all(sid not in r.aggregate_id and r.aggregate_id.startswith("client:") for r in rows)  # hashed visit id only
    assert all(abs((r.occurred_at - clock.now()).total_seconds()) < 120 for r in rows)  # server time

    assert (await client.post(EVENTS, json={"events": []})).status_code == 422
    assert (await client.post(EVENTS, json={"sessionId": "bad id with spaces", "events": [ev("compare_opened")]})).status_code == 422
    assert (await client.post(EVENTS, json={"events": [ev("compare_opened")] * 26})).status_code == 422

    admin = await make_user("funnel-admin", platform_roles=("PLATFORM_ADMIN",))
    await admin.step_up()
    signed = await client.post(EVENTS, headers=admin.h, json={"sessionId": sid, "events": [ev("compare_opened")]})
    assert signed.status_code == 202 and signed.json()["accepted"] == 1
    health = (await client.get("/v1/analytics/marketplace-health", headers=admin.h)).json()
    assert not any(k.startswith("zoikorum.client.") for k in health["eventCounts"])
    rebuilt = (await client.post("/v1/admin/analytics/rebuild", headers=admin.h)).json()
    assert rebuilt["projectedEvents"] == sum(health["eventCounts"].values())
    async with sf() as s:  # funnel events survive a rebuild from the audit ledger
        assert await s.scalar(text("SELECT count(*) FROM analytics.event_facts WHERE event_type LIKE 'zoikorum.client.%'")) == 3


async def test_events_have_their_own_budget(client, monkeypatch):
    from zoikorum.config import Settings
    from zoikorum.domains.analytics import api as analytics_api
    from zoikorum.shared import ratelimit

    shared = ratelimit.MemoryBuckets()
    monkeypatch.setattr(ratelimit, "get_buckets", lambda: shared)
    monkeypatch.setattr(analytics_api, "get_settings", lambda: Settings(_env_file=None, rate_limit_enabled=True))
    monkeypatch.setattr(analytics_api, "EVENTS_LIMIT", (60, 2))
    codes = [(await client.post(EVENTS, json={"events": [ev("compare_opened")]})).status_code for _ in range(3)]
    assert codes == [202, 202, 429]


# ---- Funnel reports ---------------------------------------------------------------------------------------------------

async def test_funnel_reports(client, make_user):
    async def visit(*events):
        r = await client.post(EVENTS, json={"sessionId": uuid.uuid4().hex, "events": list(events)})
        assert r.status_code == 202, r.text

    # Onboarding: three visits see "basics", two complete it, two see "credentials", one publishes.
    await visit(ev("onboarding_step_viewed", step="basics", position=1), ev("onboarding_step_completed", step="basics", position=1),
                ev("onboarding_step_viewed", step="credentials", position=2), ev("onboarding_step_completed", step="credentials", position=2),
                ev("profile_published"))
    await visit(ev("onboarding_step_viewed", step="basics", position=1), ev("onboarding_step_completed", step="basics", position=1),
                ev("onboarding_step_viewed", step="credentials", position=2))
    await visit(ev("onboarding_step_viewed", step="basics", position=1))
    # Request flow: two visits start, one abandons at "budget"; proposals: two started, one submitted.
    await visit(ev("request_step_viewed", step="scope", position=1), ev("request_step_completed", step="scope", position=1),
                ev("request_step_viewed", step="budget", position=2), ev("request_abandoned", step="budget"))
    await visit(ev("request_step_viewed", step="scope", position=1), ev("proposal_started"), ev("proposal_submitted"))
    await visit(ev("proposal_started"))
    # Search: filters and a comparison.
    await visit(ev("filter_applied", filter="tier"), ev("filter_applied", filter="tier"), ev("filter_applied", filter="jurisdiction"),
                ev("compare_opened"), ev("specialization_selected", specialization="fractional-cfo"))

    analyst = await make_user("funnel-analyst", platform_roles=("TS_ANALYST",))
    await analyst.step_up()
    onboarding = await client.get("/v1/admin/analytics/funnels/onboarding", headers=analyst.h)
    assert onboarding.status_code == 200, onboarding.text
    o = onboarding.json()
    assert o["visitsStarted"] == 3 and o["visitsPublished"] == 1 and o["completionRatePct"] == 33.3
    assert [(s["step"], s["viewed"], s["completed"], s["dropOffPct"]) for s in o["steps"]] == [
        ("basics", 3, 2, 33.3), ("credentials", 2, 1, 50.0)]
    assert "medianHoursSignupToPublish" in o

    r = (await client.get("/v1/admin/analytics/funnels/request", headers=analyst.h)).json()
    assert r["visitsStarted"] == 2 and r["visitsAbandoned"] == 1 and r["abandonmentRatePct"] == 50.0
    assert r["abandonedByStep"] == [{"step": "budget", "visits": 1}]
    assert [(s["step"], s["viewed"], s["completed"]) for s in r["steps"]] == [("scope", 2, 1), ("budget", 1, 0)]
    assert r["proposals"] == {"started": 2, "submitted": 1, "completionRatePct": 50.0}

    s = (await client.get("/v1/admin/analytics/funnels/search", headers=analyst.h)).json()
    actions = {a["event"]: a for a in s["actions"]}
    assert actions["filter_applied"]["count"] == 3 and actions["filter_applied"]["visits"] == 1
    assert actions["compare_opened"]["count"] == 1 and actions["quick_view_opened"]["count"] == 0
    assert s["topFilters"][0] == {"value": "tier", "count": 2}
    assert s["topSpecializations"] == [{"value": "fractional-cfo", "count": 1}]

    future = (clock.now() + timedelta(days=2)).isoformat()
    empty = (await client.get("/v1/admin/analytics/funnels/onboarding", headers=analyst.h, params={"from": future})).json()
    assert empty["visitsStarted"] == 0 and empty["steps"] == [] and empty["completionRatePct"] is None
    bad = await client.get("/v1/admin/analytics/funnels/search", headers=analyst.h, params={"from": "2026-01-01T00:00:00"})
    assert bad.status_code == 422

    buyer = await make_user("funnel-buyer")
    for path in ("onboarding", "request", "search"):
        assert (await client.get(f"/v1/admin/analytics/funnels/{path}", headers=buyer.h)).status_code == 403


# ---- KPIs -------------------------------------------------------------------------------------------------------------

async def test_kpis_cover_payments_disputes_enforcement_and_the_board(client, make_user, drain):
    from test_dispute import funded_contract

    pro_user, _, buyer, c = await funded_contract(client, make_user, drain, both=True)
    for m in c["milestones"]:
        assert (await client.post(f"/v1/milestones/{m['id']}/submit", headers=pro_user.idem(), json={"note": "Completed agreed deliverables", "files": []})).status_code == 200
        assert (await client.post(f"/v1/milestones/{m['id']}/accept", headers=buyer.idem())).status_code == 200
        await drain()
    admin = await make_user("kpi-admin", platform_roles=("PLATFORM_ADMIN",))
    await admin.step_up()
    r = await client.get("/v1/admin/kpis", headers=admin.h)
    assert r.status_code == 200, r.text
    k = r.json()
    pay = k["payments"]
    assert pay["acceptance"]["milestonesAccepted"] >= 1 and pay["acceptance"]["medianHoursSubmitToAccept"] >= 0
    assert pay["paymentsCaptured"] >= 1 and pay["refunds"] == 0 and pay["refundsPer100Payments"] == 0
    assert all({"currency", "payments", "refunds", "refundedMinor"} <= set(row) for row in pay["refundsByCurrency"])
    assert pay["disputesPer100Payments"] == 0 and pay["approvals"]["requests"] == 0 and pay["approvals"]["bottleneck"] is None
    d = k["disputes"]
    assert {"escalationRatePct", "appealRatePct", "evidenceCompletenessPct", "repeatOrganisations", "repeatProfessionals"} <= set(d)
    e = k["enforcement"]
    assert {"byLevel", "reversalRatePct", "appealSuccessRatePct", "recurringSubjects"} <= set(e)
    b = k["board"]
    assert isinstance(b["trustTierTrend"], list) and b["credentialExpiryIncidents"] == 0
    if b["trustTierTrend"]:
        assert {"date", "A", "B", "C"} <= set(b["trustTierTrend"][-1])
    assert {"decided", "approved", "pendingNow", "medianDaysToDecision"} <= set(b["enterpriseOnboarding"])
    assert "enforcementReversalRatePct" in b


async def test_dispute_and_enforcement_kpis_count_escalations_reversals_and_appeals(client, make_user, sf):
    from zoikorum.domains.admin import kpis
    from zoikorum.domains.dispute import facade as dispute_facade

    now = clock.now()
    org, pro, subject = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    async with sf() as s, s.begin():
        for i, (escalated, evidence) in enumerate(((True, '["BUYER","PROFESSIONAL"]'), (False, '["BUYER"]'))):
            await s.execute(text(
                "INSERT INTO dispute.cases (id, reference, contract_id, contract_reference, organization_id, professional_id, milestone_ids, "
                "category, summary, desired_outcome, context, initiator_party, status, currency, disputed_minor, evidence_deadline, "
                "evidence_complete, escalated_at, prefers_early_resolution, cooldown_used_by, clarifications, legal_hold, retention_review_due, "
                "version, created_at, updated_at) VALUES (gen_random_uuid(), :ref, gen_random_uuid(), 'ZK-C', :org, :pro, '[]', 'QUALITY', 's', "
                "'REFUND', '', 'BUYER', 'MEDIATION', 'USD', 0, :now, CAST(:ev AS jsonb), :esc, false, '[]', '[]', false, false, 1, :now, :now)"),
                {"ref": f"ZK-DSP-T{i}", "org": org, "pro": pro, "now": now, "ev": evidence, "esc": now if escalated else None})
        for status, appeal in (("REVERSED", {"status": "UPHELD", "filedAt": now.isoformat(), "decidedAt": now.isoformat()}),
                               ("ACTIVE", {"status": "REJECTED", "filedAt": now.isoformat(), "decidedAt": now.isoformat()})):
            await s.execute(text(
                "INSERT INTO admin.enforcement_cases (id, subject_type, subject_id, signal_source, summary, evidence_refs, level, status, "
                "approvals, applied_at, appeal, remediation, version, created_at, updated_at) VALUES (gen_random_uuid(), 'PROFESSIONAL', :sub, "
                "'test', 's', '[]', 2, :st, '[]', :now, CAST(:ap AS jsonb), '[]', 1, :now, :now)"),
                {"sub": subject, "st": status, "now": now, "ap": __import__("json").dumps(appeal)})
    since, until = now - timedelta(days=1), now + timedelta(days=1)
    async with sf() as s:
        d = await dispute_facade.quality_kpis(s, since, until)
        e = await kpis._enforcement(s, since, until)
    assert d["opened"] == 2 and d["escalationRatePct"] == 50.0 and d["evidenceCompletenessPct"] == 50.0
    assert d["repeatOrganisations"] == 1 and d["repeatProfessionals"] == 1
    assert e["byLevel"] == {"L2": 2} and e["actionsApplied"] == 2 and e["reversalRatePct"] == 50.0
    assert e["appealsDecided"] == 2 and e["appealSuccessRatePct"] == 50.0 and e["recurringSubjects"] == 1


# ---- Per-policy dashboard ---------------------------------------------------------------------------------------------

async def test_policy_dashboard_by_profile_and_csv_export(client, make_user, drain):
    from test_automatic_disputes import policy_contract

    pro_user, _, buyer, c = await policy_contract(client, make_user, drain, {"minTrustTier": "B"})
    org = c["organizationId"]
    r = await client.get("/v1/policy/dashboard/profiles", headers=buyer.h, params={"orgId": org})
    assert r.status_code == 200, r.text
    profiles = r.json()["profiles"]
    assert len(profiles) == 1
    p = profiles[0]
    assert p["status"] == "ACTIVE" and p["evaluations"] > 0 and p["decisions"].get("ALLOW", 0) > 0
    assert p["engagements"] >= 1 and all(set(m) == {"currency", "amountMinor"} for m in p["spendExposure"])
    assert p["approvals"]["requested"] == 0 and p["bottleneck"] is None

    exported = await client.get("/v1/policy/dashboard/profiles.csv", headers=buyer.h, params={"orgId": org, "days": 7})
    assert exported.status_code == 200 and exported.headers["content-type"].startswith("text/csv")
    rows = list(csv.DictReader(io.StringIO(exported.text)))
    assert [row["profile"] for row in rows] == [p["name"]] and rows[0]["evaluations"] == str(p["evaluations"])
    assert (await client.get("/v1/policy/dashboard/profiles", headers=pro_user.h, params={"orgId": org})).status_code == 404
    assert (await client.get("/v1/policy/dashboard/profiles.csv", headers=pro_user.h, params={"orgId": org})).status_code == 404
