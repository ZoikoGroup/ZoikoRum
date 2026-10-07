"""Stored documents (request attachments, delivered work, dispute evidence) and the buyer's review window."""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import text

from filehelp import raw, upload
from test_contract import C, fund, signed_contract
from test_dispute import D, dispute_body, funded_contract
from test_proposal import R, buyer_org, request_body, tier_b
from zoikorum.shared import clock


async def audited(sf, action: str) -> int:
    async with sf() as s:
        return await s.scalar(text("SELECT count(*) FROM audit.audit_records WHERE action LIKE :a"), {"a": f"%{action}%"})


async def outbox_count(sf, event: str, aggregate_id: str) -> int:
    async with sf() as s:
        return await s.scalar(text("SELECT count(*) FROM platform.outbox WHERE event_type LIKE :e AND aggregate_id = :a"),
                              {"e": f"%{event}%", "a": aggregate_id})


async def test_request_attachments_are_stored_and_respect_the_nda(client, make_user, drain, sf):
    pro_user, pro = await tier_b(client, make_user, drain, "ana")
    buyer, org = await buyer_org(client, make_user, drain)
    brief = upload("brief.pdf", b"group structure")

    bad = {**brief, "sha256": "0" * 64}
    r = await client.post(R, headers=buyer.idem(), json=request_body(org, pro, attachments=[bad]))
    assert r.json()["code"] == "FINGERPRINT_MISMATCH"
    renamed = upload("brief.pdf", b"MZ", content_type="image/png")  # a PNG pretending to be a PDF by name
    r = await client.post(R, headers=buyer.idem(), json=request_body(org, pro, attachments=[renamed]))
    assert r.json()["code"] == "INVALID_FILE_TYPE"

    req = (await client.post(R, headers=buyer.idem(), json=request_body(org, pro, ndaRequired=True, attachments=[brief]))).json()[0]
    assert req["attachments"][0]["hasFile"] is True
    url = f"{R}/{req['id']}/attachments/{brief['sha256']}"
    assert (await client.get(url, headers=buyer.h)).content == raw(brief)
    r = await client.get(url, headers=pro_user.h)
    assert r.status_code == 403 and r.json()["code"] == "NDA_NOT_ACCEPTED"
    await client.post(f"{R}/{req['id']}/accept-nda", headers=pro_user.h)
    r = await client.get(url, headers=pro_user.h)
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
    stranger = await make_user("sam")
    assert (await client.get(url, headers=stranger.h)).status_code == 404
    await drain()
    assert await audited(sf, "proposal.request.attachment.viewed") == 2


async def test_delivered_files_are_stored_and_viewable_by_the_parties(client, make_user, drain, sf):
    pro_user, pro, buyer, c = await signed_contract(client, make_user, drain)
    m1 = c["milestones"][0]
    await fund(sf, drain, c, [m1["id"]])
    work = upload("master-file.pdf", b"master file v1")
    r = await client.post(f"/v1/milestones/{m1['id']}/submit", headers=pro_user.h, json={"note": "Attached", "files": [work]})
    (f,) = r.json()["milestones"][0]["submissions"][0]["files"]
    assert f["hasFile"] and f["contentType"] == "application/pdf"
    url = f"{C}/{c['id']}/files/{work['sha256']}"
    assert (await client.get(url, headers=buyer.h)).content == raw(work)
    assert (await client.get(url, headers=pro_user.h)).status_code == 200
    assert (await client.get(f"{C}/{c['id']}/files/{'f' * 64}", headers=buyer.h)).status_code == 404
    stranger = await make_user("sam")
    assert (await client.get(url, headers=stranger.h)).status_code == 404
    await drain()
    assert await audited(sf, "contract.deliverable.viewed") == 2


async def test_dispute_evidence_files_are_viewable_by_both_parties(client, make_user, drain, sf):
    pro_user, pro, buyer, c = await funded_contract(client, make_user, drain)
    d = (await client.post(D, headers=buyer.idem(), json=dispute_body(c))).json()
    note = upload("review-notes.pdf", b"structure gaps")
    r = await client.post(f"{D}/{d['id']}/evidence", headers=buyer.h,
                          json={"evidenceType": "DELIVERABLE", "description": "Our review notes", "items": [note]})
    assert r.json()["evidence"][0]["items"][0]["hasFile"] is True
    url = f"{D}/{d['id']}/files/{note['sha256']}"
    assert (await client.get(url, headers=pro_user.h)).content == raw(note)
    stranger = await make_user("sam")
    assert (await client.get(url, headers=stranger.h)).status_code == 404
    await drain()
    assert await audited(sf, "dispute.evidence.viewed") == 1


async def test_review_window_reminds_then_flags_overdue_without_releasing(client, make_user, drain, sf):
    pro_user, pro, buyer, c = await signed_contract(client, make_user, drain)
    m1 = c["milestones"][0]
    await fund(sf, drain, c, [m1["id"]])
    await client.post(f"/v1/milestones/{m1['id']}/submit", headers=pro_user.h, json={"note": "Delivered"})
    m = (await client.get(f"{C}/{c['id']}", headers=buyer.h)).json()["milestones"][0]
    assert m["reviewOverdue"] is False

    clock.advance(timedelta(days=4, hours=1))  # one day before the 5-day window closes
    await drain()
    assert await outbox_count(sf, "milestone.acceptance_reminder", c["id"]) == 1
    assert await outbox_count(sf, "milestone.acceptance_overdue", c["id"]) == 0

    clock.advance(timedelta(days=1))
    await drain()
    clock.set_now(None)
    assert await outbox_count(sf, "milestone.acceptance_overdue", c["id"]) == 1


async def test_a_decision_or_resubmission_silences_the_old_review_timers(client, make_user, drain, sf):
    pro_user, pro, buyer, c = await signed_contract(client, make_user, drain)
    m1 = c["milestones"][0]
    await fund(sf, drain, c, [m1["id"]])
    await client.post(f"/v1/milestones/{m1['id']}/submit", headers=pro_user.h, json={"note": "First"})
    await client.post(f"/v1/milestones/{m1['id']}/request-revision", headers=buyer.h, json={"reason": "Add the appendix"})
    clock.advance(timedelta(days=6))
    await drain()
    clock.set_now(None)
    assert await outbox_count(sf, "milestone.acceptance_overdue", c["id"]) == 0
