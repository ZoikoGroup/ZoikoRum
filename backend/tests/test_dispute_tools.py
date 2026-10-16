"""Dispute tools: the conversation as evidence, a once-per-side 24-hour pause, mediator clarifications, linked timeline
entries, and a timeline extension that really moves the due date."""

from __future__ import annotations

from datetime import date, timedelta

from test_contract import C
from test_dispute import D, dispute_body, funded_contract, staff
from zoikorum.shared import clock


async def test_conversation_evidence_cooldown_and_links(client, make_user, drain):
    pro_user, pro, buyer, c = await funded_contract(client, make_user, drain)
    thread = (await client.post("/v1/messaging/threads", headers=buyer.idem(), json={"contextType": "CONTRACT", "contextId": c["id"]})).json()
    await client.post(f"/v1/messaging/threads/{thread['id']}/messages", headers=buyer.idem(), json={"body": "Please send the master file.", "attachments": []})
    d = (await client.post(D, headers=buyer.idem(), json={**dispute_body(c), "prefersEarlyResolution": True})).json()
    assert d["prefersEarlyResolution"] is True and d["canCooldown"] is True

    d2 = (await client.post(f"{D}/{d['id']}/evidence/messages", headers=buyer.h)).json()
    (ev,) = [e for e in d2["evidence"] if e["evidenceType"] == "COMMUNICATION"]
    assert ev["items"][0]["name"].endswith("-conversation.csv") and "messages" in ev["description"]
    assert any(t["ref"] == f"evidence:{ev['id']}" for t in d2["timeline"])

    before = d2["evidenceDeadline"]
    paused = (await client.post(f"{D}/{d['id']}/cooldown", headers=buyer.h)).json()
    assert paused["evidenceDeadline"] > before and paused["canCooldown"] is False
    assert (await client.post(f"{D}/{d['id']}/cooldown", headers=buyer.h)).json()["code"] == "COOLDOWN_USED"
    assert (await client.post(f"{D}/{d['id']}/cooldown", headers=pro_user.h)).status_code == 200  # each side once


async def test_clarifications_and_a_timeline_extension_that_moves_the_due_date(client, make_user, drain):
    pro_user, pro, buyer, c = await funded_contract(client, make_user, drain)
    m1 = c["milestones"][0]
    d = (await client.post(D, headers=pro_user.idem(), json=dispute_body(c, outcome="TIMELINE_EXTENSION"))).json()
    await drain()
    clock.advance(timedelta(days=4))
    await drain()
    clock.set_now(None)
    d = (await client.post(f"{D}/{d['id']}/resolution-proposals", headers=pro_user.h, json={"outcome": "FULL_RELEASE"})).json()
    await client.post(f"/v1/resolution-proposals/{d['proposals'][0]['id']}/reject", headers=buyer.h)
    d = (await client.post(f"{D}/{d['id']}/escalate", headers=buyer.h)).json()
    mediator = await staff(make_user, "mia", "MEDIATOR", "PLATFORM_ADMIN", "LEGAL")
    await client.post(f"{D}/{d['id']}/assign-mediator", headers=mediator.h, json={"mediatorIdentityId": str(mediator.id)})

    q = await client.post(f"{D}/{d['id']}/clarification", headers=mediator.h,
                          json={"to": "PROFESSIONAL", "question": "When can the remaining sections be delivered?"})
    assert q.status_code == 200 and q.json()["clarifications"][0]["to"] == "PROFESSIONAL"
    assert (await client.post(f"{D}/{d['id']}/clarification", headers=buyer.h,
                              json={"to": "BUYER", "question": "Can a party ask this themselves?"})).status_code == 403
    await drain()
    titles = [n["title"] for n in (await client.get("/v1/notifications", headers=pro_user.h)).json()["items"]]
    assert "The mediator has a question" in titles
    assert "The mediator has a question" not in [n["title"] for n in (await client.get("/v1/notifications", headers=buyer.h)).json()["items"]]

    rec = {"outcome": "TIMELINE_EXTENSION", "summary": "Two sections are missing; two more weeks is fair to finish them.",
           "citations": ["Evidence: delivered master file"]}
    assert (await client.post(f"{D}/{d['id']}/recommendation", headers=mediator.h, json=rec)).json()["code"] == "EXTENSION_DAYS_REQUIRED"
    await client.post(f"{D}/{d['id']}/recommendation", headers=mediator.h, json={**rec, "extendDays": 14})
    await client.post(f"{D}/{d['id']}/recommendation/accept", headers=buyer.idem())
    await client.post(f"{D}/{d['id']}/recommendation/accept", headers=pro_user.idem())
    await drain()
    after = next(m for m in (await client.get(f"{C}/{c['id']}", headers=buyer.h)).json()["milestones"] if m["id"] == m1["id"])
    base = date.fromisoformat(m1["dueDate"]) if m1["dueDate"] else date.today()
    assert after["status"] == "IN_PROGRESS" and date.fromisoformat(after["dueDate"]) == base + timedelta(days=14)


async def test_the_case_record_can_be_downloaded_and_checked(client, make_user, drain):
    import hashlib
    import json

    pro_user, pro, buyer, c = await funded_contract(client, make_user, drain)
    d = (await client.post(D, headers=buyer.idem(), json=dispute_body(c))).json()
    await client.post(f"{D}/{d['id']}/evidence", headers=buyer.h, json={"evidenceType": "OTHER", "description": "Screenshots of the missing sections."})
    r = await client.get(f"{D}/{d['id']}/record", headers=pro_user.h, params={"format": "json"})
    pack = r.json()
    body = json.dumps(pack["record"], sort_keys=True, separators=(",", ":"), default=str)
    assert hashlib.sha256(body.encode()).hexdigest() == pack["fingerprintSha256"]
    assert pack["record"]["case"]["reference"] == d["reference"] and pack["record"]["evidence"][0]["description"].startswith("Screenshots")
    pdf = await client.get(f"{D}/{d['id']}/record", headers=buyer.h)
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF-")
    assert (await client.get(f"{D}/{d['id']}/record", headers=(await make_user("sam")).h)).status_code == 404


async def test_repeated_lost_disputes_raise_an_advisory_case(sf):
    import uuid as _uuid

    from sqlalchemy import select, text
    from zoikorum.domains.dispute import service as dispute_service
    from zoikorum.domains.dispute.models import DisputeCase

    opener = _uuid.uuid4()
    async with sf() as s, s.begin():
        cases = []
        for i in range(3):
            c = DisputeCase(reference=f"ZK-DSP-T{i}", contract_id=_uuid.uuid4(), contract_reference="ZK-ENG-T", organization_id=_uuid.uuid4(),
                            professional_id=_uuid.uuid4(), milestone_ids=[], category="QUALITY_ACCEPTANCE", summary="Not as agreed.",
                            desired_outcome="FULL_REFUND", initiated_by=opener, initiator_party="BUYER", status="DECIDED", currency="USD",
                            evidence_deadline=clock.now(), decided_at=clock.now(), decision={"outcome": "FULL_RELEASE"})
            s.add(c)
            cases.append(c)
        await s.flush()
        await dispute_service._check_bad_faith(s, cases[-1], "FULL_RELEASE")
    async with sf() as s:
        flagged = (await s.execute(text("SELECT count(*) FROM platform.outbox WHERE event_type LIKE '%pattern_flagged%'"))).scalar()
    assert flagged == 1
