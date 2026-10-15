"""Running the Trust & Safety queue: triage targets and filters, appeal windows with evidence, remediation tracking,
the executive override, and the dispute-access restriction."""

from __future__ import annotations

import uuid

from sqlalchemy import text

from test_dispute import D, dispute_body, funded_contract

ROOT = "/v1/admin/enforcement-cases"
NOTICE = {k: "Review the documented action and contact support if anything is unclear." for k in
          ["whatHappened", "whyItHappened", "whatChanged", "whatYouCanDo", "whatHappensNext", "howToGetHelp"]}


async def staff_team(make_user):
    team = {}
    for name, role in [("analyst", "TS_ANALYST"), ("risk", "RISK_LEAD"), ("risk2", "RISK_LEAD"), ("exec", "EXECUTIVE")]:
        team[name] = await make_user("q-" + name, platform_roles=(role,))
        await team[name].step_up()
    return team


async def level2(client, team, subject_id, action="DISPUTE_ACCESS_RESTRICTION", remediation=()):
    r = await client.post(ROOT, headers=team["analyst"].idem(), json={
        "subjectType": "IDENTITY", "subjectId": str(subject_id), "signalSource": "HUMAN_REVIEW",
        "summary": "Repeated bad-faith disputes on several engagements.", "evidenceRefs": ["dispute:ZK-DSP-1"]})
    cid = r.json()["id"]
    await client.post(f"{ROOT}/{cid}/assess", headers=team["risk"].idem(), json={"level": 2, "reasonCode": "BAD_FAITH_DISPUTES"})
    r = await client.post(f"{ROOT}/{cid}/propose-action", headers=team["analyst"].idem(),
                          json={"action": action, "notice": NOTICE, "durationDays": 30, "remediation": list(remediation)})
    assert r.status_code == 200, r.text
    r = await client.post(f"{ROOT}/{cid}/approve-action", headers=team["risk2"].idem())
    assert r.json()["status"] == "ACTIVE", r.text
    return cid


async def test_overdue_cases_come_first_and_filters_work(client, make_user, sf):
    team = await staff_team(make_user)
    subject = await make_user("subject")
    ids = []
    for summary in ("An older signal that nobody has looked at yet.", "A fresh signal opened just now for review."):
        r = await client.post(ROOT, headers=team["analyst"].idem(), json={"subjectType": "IDENTITY", "subjectId": str(subject.id),
                              "signalSource": "HUMAN_REVIEW", "summary": summary, "evidenceRefs": ["ref"]})
        ids.append(r.json()["id"])
    async with sf() as s, s.begin():
        await s.execute(text("UPDATE admin.enforcement_cases SET created_at = now() - interval '3 days' WHERE id = :i"), {"i": ids[0]})
    queue = (await client.get(ROOT, headers=team["analyst"].h)).json()
    assert queue[0]["id"] == ids[0] and queue[0]["overdue"] is True and queue[1]["overdue"] is False
    assert [c["id"] for c in (await client.get(ROOT, headers=team["analyst"].h, params={"overdue": "true"})).json()] == [ids[0]]
    assert (await client.get(ROOT, headers=team["analyst"].h, params={"level": 3})).json() == []


async def test_dispute_access_restriction_remediation_appeal_window_and_executive_override(client, make_user, drain, sf):
    pro_user, pro, buyer, c = await funded_contract(client, make_user, drain)
    team = await staff_team(make_user)
    cid = await level2(client, team, buyer.id, remediation=["Read the dispute guidance", "Confirm you will use revisions first"])
    await drain()

    blocked = await client.post(D, headers=buyer.idem(), json=dispute_body(c))
    assert blocked.status_code == 403 and blocked.json()["code"] == "DISPUTE_ACCESS_RESTRICTED"

    mine = (await client.get("/v1/enforcement-cases", headers=buyer.h)).json()[0]
    assert mine["canAppeal"] is True and mine["appealDeadline"] and len(mine["remediation"]) == 2
    r = await client.post(f"/v1/enforcement-cases/{cid}/remediation/0/done", headers=buyer.h, json={"note": "Read it all."})
    assert r.json()["remediation"][0]["done"] is True
    assert (await client.post(f"{ROOT}/{cid}/remediation/1/confirm", headers=team["analyst"].h)).json()["code"] == "TASK_NOT_DONE"
    assert (await client.post(f"{ROOT}/{cid}/remediation/0/confirm", headers=team["analyst"].h)).json()["remediation"][0]["confirmedBy"]

    # Appeals close after the window.
    async with sf() as s, s.begin():
        await s.execute(text("UPDATE admin.enforcement_cases SET applied_at = now() - interval '20 days' WHERE id = :i"), {"i": cid})
    late = await client.post(f"/v1/enforcement-cases/{cid}/appeal", headers={**buyer.h, "Idempotency-Key": str(uuid.uuid4())},
                             json={"reason": "I only opened disputes when work was not delivered at all."})
    assert late.json()["code"] == "APPEAL_WINDOW_CLOSED"

    # Executive override ends it, with a recorded justification; people involved in the case cannot.
    r = await client.post(f"{ROOT}/{cid}/executive-override", headers=team["exec"].h,
                          json={"reason": "The underlying disputes were later found to be justified by the mediator."})
    assert r.status_code == 200 and r.json()["status"] == "REVERSED"
    await drain()
    assert (await client.post(D, headers=buyer.idem(), json=dispute_body(c))).status_code == 201
    async with sf() as s:
        events = (await s.execute(text("SELECT envelope FROM platform.outbox WHERE event_type LIKE '%action_applied%'"))).all()
    payload = events[0][0]["payload"]
    assert payload["evidenceRefs"] == ["dispute:ZK-DSP-1"] and payload["policyVersion"].startswith("trust-safety-playbook")
