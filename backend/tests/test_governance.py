"""Trust & Safety governance: user impact at assessment, mandatory remediation as its own action, Level 3+ post-reviews,
Level 4 referrals (Legal only), staff conflicts of interest, third-party fraud alerts, new incident kinds, and the
message abuse detector."""

from __future__ import annotations

import hashlib
import hmac
import json
import time

from test_enforcement_queue import NOTICE, ROOT, staff_team


async def _case(client, team, subject_id, level, reason="CONFIRMED_RISK"):
    r = await client.post(ROOT, headers=team["analyst"].idem(), json={
        "subjectType": "IDENTITY", "subjectId": str(subject_id), "signalSource": "HUMAN_REVIEW",
        "summary": "Evidence of a serious breach on several engagements.", "evidenceRefs": ["ev:1"]})
    cid = r.json()["id"]
    r = await client.post(f"{ROOT}/{cid}/assess", headers=team["risk"].idem(), json={"level": level, "reasonCode": reason,
                          "userImpact": "Two active clients would lose their adviser mid-engagement."})
    assert r.status_code == 200, r.text
    assert r.json()["userImpact"].startswith("Two active clients")
    return cid


async def test_user_impact_is_required_at_assessment(client, make_user):
    team = await staff_team(make_user)
    subject = await make_user("impact-subject")
    cid = (await client.post(ROOT, headers=team["analyst"].idem(), json={
        "subjectType": "IDENTITY", "subjectId": str(subject.id), "signalSource": "HUMAN_REVIEW",
        "summary": "A report that needs an assessment.", "evidenceRefs": ["ev:1"]})).json()["id"]
    r = await client.post(f"{ROOT}/{cid}/assess", headers=team["risk"].idem(), json={"level": 1, "reasonCode": "MINOR"})
    assert r.status_code == 422


async def test_mandatory_remediation_ends_when_every_task_is_confirmed(client, make_user):
    team = await staff_team(make_user)
    subject = await make_user("remedy-subject")
    cid = await _case(client, team, subject.id, 2)
    r = await client.post(f"{ROOT}/{cid}/propose-action", headers=team["analyst"].idem(),
                          json={"action": "MANDATORY_REMEDIATION", "notice": NOTICE, "durationDays": 30})
    assert r.status_code == 422 and r.json()["code"] == "REMEDIATION_TASKS_REQUIRED"
    await client.post(f"{ROOT}/{cid}/propose-action", headers=team["analyst"].idem(),
                      json={"action": "MANDATORY_REMEDIATION", "notice": NOTICE, "durationDays": 30, "remediation": ["Complete the conduct course"]})
    assert (await client.post(f"{ROOT}/{cid}/approve-action", headers=team["risk2"].idem())).json()["status"] == "ACTIVE"
    await client.post(f"/v1/enforcement-cases/{cid}/remediation/0/done", headers=subject.h, json={"note": "Course finished today."})
    r = await client.post(f"{ROOT}/{cid}/remediation/0/confirm", headers=team["analyst"].h)
    assert r.json()["status"] == "REVERSED"


async def test_level_three_cases_need_a_post_review_before_closing(client, make_user):
    team = await staff_team(make_user)
    legal = await make_user("pr-legal", platform_roles=("LEGAL",))
    await legal.step_up()
    subject = await make_user("pr-subject")
    review = {"rootCause": "Credential check accepted an expired licence.", "uxImpact": "Clients saw a verified badge that was wrong.",
              "policyUpdates": "Re-check licences monthly."}

    cid = await _case(client, team, subject.id, 3)
    r = await client.post(f"{ROOT}/{cid}/close", headers=team["analyst"].h, json={"reason": "No breach after all."})
    assert r.json()["code"] == "POST_REVIEW_REQUIRED"
    assert (await client.post(f"{ROOT}/{cid}/post-review", headers=team["analyst"].h, json=review)).status_code == 403  # Risk or Legal
    assert (await client.post(f"{ROOT}/{cid}/post-review", headers=team["risk"].h, json=review)).json()["postReview"]["by"]
    assert (await client.post(f"{ROOT}/{cid}/close", headers=team["analyst"].h, json={"reason": "No breach after all."})).json()["status"] == "CLOSED_NO_ACTION"

    cid = await _case(client, team, subject.id, 3)
    await client.post(f"{ROOT}/{cid}/propose-action", headers=team["analyst"].idem(), json={"action": "ENGAGEMENT_SUSPENSION", "notice": NOTICE})
    assert (await client.post(f"{ROOT}/{cid}/approve-action", headers=team["risk2"].idem())).json()["status"] == "ACTIVE"
    r = await client.post(f"{ROOT}/{cid}/reverse", headers=legal.idem(), json={"reason": "The suspension served its purpose and ends now."})
    assert r.json()["canConclude"] is True and r.json()["postReviewRequired"] is True
    assert (await client.post(f"{ROOT}/{cid}/conclude", headers=team["risk"].h)).json()["code"] == "POST_REVIEW_REQUIRED"
    await client.post(f"{ROOT}/{cid}/post-review", headers=legal.h, json=review)
    done = (await client.post(f"{ROOT}/{cid}/conclude", headers=team["risk"].h)).json()
    assert done["status"] == "CONCLUDED" and done["concludedAt"]


async def test_level_four_referrals_are_legal_only(client, make_user):
    team = await staff_team(make_user)
    legal = await make_user("ref-legal", platform_roles=("LEGAL",))
    await legal.step_up()
    subject = await make_user("ref-subject")
    body = {"agency": "Action Fraud (UK)", "agencyReference": "NFRC-2026-1234", "referredOn": "2026-10-20",
            "legalSignOff": "Approved by Legal: evidence meets the referral threshold."}
    low = await _case(client, team, subject.id, 3)
    assert (await client.post(f"{ROOT}/{low}/referrals", headers=legal.idem(), json=body)).json()["code"] == "LEVEL_4_REQUIRED"
    cid = await _case(client, team, subject.id, 4)
    assert (await client.post(f"{ROOT}/{cid}/referrals", headers=team["risk"].idem(), json=body)).status_code == 403
    r = await client.post(f"{ROOT}/{cid}/referrals", headers=legal.idem(), json=body)
    assert r.status_code == 201 and r.json()["agencyReference"] == "NFRC-2026-1234"
    assert (await client.get(f"{ROOT}/{cid}/referrals", headers=team["exec"].h)).status_code == 403
    assert [x["agency"] for x in (await client.get(f"{ROOT}/{cid}/referrals", headers=legal.h)).json()] == ["Action Fraud (UK)"]
    queue = (await client.get(ROOT, headers=team["analyst"].h)).json()
    assert "referrals" not in next(q for q in queue if q["id"] == cid)


async def test_a_declared_conflict_blocks_the_assessor(client, make_user):
    team = await staff_team(make_user)
    subject = await make_user("coi-subject")
    cid = (await client.post(ROOT, headers=team["analyst"].idem(), json={
        "subjectType": "IDENTITY", "subjectId": str(subject.id), "signalSource": "HUMAN_REVIEW",
        "summary": "A report that needs an assessment.", "evidenceRefs": ["ev:1"]})).json()["id"]
    await client.post("/v1/admin/conflicts", headers=team["risk"].h, json={"kind": "DECLARATION", "subjectType": "IDENTITY",
                                                                            "subjectId": str(subject.id), "reason": "This is my brother-in-law."})
    r = await client.post(f"{ROOT}/{cid}/assess", headers=team["risk"].idem(), json={"level": 1, "reasonCode": "MINOR",
                                                                                      "userImpact": "A warning only; no clients affected."})
    assert r.status_code == 403 and r.json()["code"] == "CONFLICT_OF_INTEREST_DECLARED"
    assert (await client.post(f"{ROOT}/{cid}/assess", headers=team["risk2"].idem(), json={
        "level": 1, "reasonCode": "MINOR", "userImpact": "A warning only; no clients affected."})).status_code == 200


def _sign(body: bytes, secret="dev-webhook-secret") -> str:
    t = int(time.time())
    return f"t={t},v1=" + hmac.new(secret.encode(), f"{t}.".encode() + body, hashlib.sha256).hexdigest()


async def test_third_party_fraud_alerts_open_an_advisory_review(client, make_user):
    team = await staff_team(make_user)
    subject = await make_user("fraud-subject")
    raw = json.dumps({"provider": "sift", "alertId": "A-77", "subjectType": "IDENTITY", "subjectId": str(subject.id),
                      "reasonCode": "STOLEN_CARD_PATTERN", "score": 88}).encode()
    bad = await client.post("/v1/integrations/fraud-alerts", content=raw, headers={"Webhook-Signature": _sign(raw, "wrong"), "Content-Type": "application/json"})
    assert bad.status_code == 403
    r = await client.post("/v1/integrations/fraud-alerts", content=raw, headers={"Webhook-Signature": _sign(raw), "Content-Type": "application/json"})
    assert r.status_code == 202 and r.json()["duplicate"] is False and r.json()["caseId"]
    again = await client.post("/v1/integrations/fraud-alerts", content=raw, headers={"Webhook-Signature": _sign(raw), "Content-Type": "application/json"})
    assert again.json()["duplicate"] is True and again.json()["caseId"] == r.json()["caseId"]
    alerts = (await client.get("/v1/admin/fraud-alerts", headers=team["risk"].h)).json()
    assert alerts[0]["provider"] == "sift" and alerts[0]["caseStatus"] == "TRIAGE"
    case = next(q for q in (await client.get(ROOT, headers=team["analyst"].h)).json() if q["id"] == r.json()["caseId"])
    assert case["level"] == 0 and case["signalSource"] == "THIRD_PARTY_FRAUD:sift" and case["action"] is None


async def test_new_incident_kinds_and_review_fields(client, make_user):
    lead = await make_user("inc-lead", platform_roles=("RISK_LEAD",))
    await lead.step_up()
    r = await client.post("/v1/admin/incidents", headers=lead.h, json={"title": "Licence checks passing wrongly", "kind": "CREDENTIAL_FAILURE",
                                                                       "severity": "SEV3", "summary": "Expired licences were accepted."})
    assert r.status_code == 201 and r.json()["kind"] == "CREDENTIAL_FAILURE"
    r = await client.patch(f"/v1/admin/incidents/{r.json()['id']}", headers=lead.h, json={
        "uxImpact": "Buyers saw wrong verified badges.", "policyUpdates": "Monthly licence re-checks."})
    assert r.json()["uxImpact"] == "Buyers saw wrong verified badges." and r.json()["policyUpdates"] == "Monthly licence re-checks."
    r = await client.post("/v1/admin/incidents", headers=lead.h, json={"title": "Ledger mismatch", "kind": "SYSTEM_INTEGRITY",
                                                                       "severity": "SEV2", "summary": "Audit chain gap found."})
    assert r.status_code == 201


def test_message_abuse_detection_sees_through_disguises():
    from zoikorum.domains.messaging.abuse import signals

    assert signals("jo dot doe at gmail dot com") == ["CONTACT_EMAIL"]
    assert signals("five five five one two three four five six seven") == ["CONTACT_PHONE"]
    assert "CONTACT_HANDLE" in signals("w h a t s a p p me")
    assert signals("pay me on p@yp4l to avoid the fee") == ["OFF_PLATFORM_PAYMENT"]
    assert signals("you 1d10t") == ["POSSIBLE_HARASSMENT"]
    for clean in ("my skill you will see", "Fee is USD 1,000,000.00", "meeting 2026-10-23 10:00", "stupidity aside, it works"):
        assert signals(clean) == [], clean


def test_message_abuse_terms_are_configurable(monkeypatch):
    from zoikorum.config import get_settings
    from zoikorum.domains.messaging.abuse import signals

    monkeypatch.setattr(get_settings(), "messaging_circumvention_terms", ["pigeon post"])
    monkeypatch.setattr(get_settings(), "messaging_abuse_terms", ["clown"])
    assert signals("send it by p1ge0n post, you clown") == ["OFF_PLATFORM_PAYMENT", "POSSIBLE_HARASSMENT"]
