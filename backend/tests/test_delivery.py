"""Delivering milestone work deliverable by deliverable: a private draft, evidence (files or links), checks before
sending, a declaration, and the buyer's verdict per deliverable (all met accepts; anything else goes back)."""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest
from sqlalchemy import text

from filehelp import upload
from test_contract import C, fund, signed_contract
from zoikorum.domains.contract import delivery
from zoikorum.shared.errors import ValidationFailed

NOW = datetime(2026, 10, 14, tzinfo=timezone.utc)
DELIVERABLES = [{"key": "master", "title": "Master file", "acceptanceCriteria": "OECD-compliant master file"}]


def _draft(m_id: str) -> str:
    return f"/v1/milestones/{m_id}/submission-draft"


async def _funded(client, make_user, drain, sf):
    pro_user, pro, buyer, c = await signed_contract(client, make_user, drain)
    m1 = c["milestones"][0]
    await fund(sf, drain, c, [m1["id"]])
    return pro_user, buyer, c, m1


async def test_professional_prepares_checks_and_sends_a_delivery(client, make_user, drain, sf):
    pro_user, buyer, c, m1 = await _funded(client, make_user, drain, sf)

    d = (await client.get(_draft(m1["id"]), headers=pro_user.h)).json()
    assert [(i["deliverableKey"], i["title"], i["acceptanceCriteria"]) for i in d["items"]] == [
        ("master", "Master file", "OECD-compliant master file")]
    assert d["canSubmit"] is False and [b["code"] for b in d["blockers"]] == ["NO_EVIDENCE"]
    assert d["savedAt"] is None and d["revisionNumber"] == 0 and d["declaration"] == delivery.DECLARATION
    assert (await client.get(_draft(m1["id"]), headers=buyer.h)).status_code == 403  # the buyer never sees a draft

    work = upload("master-file.pdf", b"master")
    d = (await client.post(f"{_draft(m1['id'])}/items/master/evidence", headers=pro_user.h, json={"file": work})).json()
    assert d["canSubmit"] is True and d["items"][0]["ready"] and d["items"][0]["evidence"][0]["file"]["name"] == "master-file.pdf"
    d = (await client.patch(_draft(m1["id"]), headers=pro_user.h,
                            json={"note": "Ready for review", "itemNotes": {"master": "Sections 1-4 follow the OECD outline"}})).json()
    assert d["note"] == "Ready for review" and d["items"][0]["note"] == "Sections 1-4 follow the OECD outline" and d["savedAt"]
    assert (await client.get(f"{_draft(m1['id'])}/files/{work['sha256']}", headers=pro_user.h)).status_code == 200
    assert (await client.get(f"{C}/{c['id']}/files/{work['sha256']}", headers=buyer.h)).status_code == 404  # not sent yet

    r = await client.post(f"/v1/milestones/{m1['id']}/submit", headers=pro_user.h, json={"note": "One step", "files": []})
    assert r.status_code == 409 and r.json()["code"] == "DRAFT_IN_PROGRESS"
    r = await client.post(f"/v1/milestones/{m1['id']}/submit", headers=pro_user.h, json={})
    assert r.status_code == 409 and r.json()["code"] == "DECLARATION_REQUIRED"
    r = await client.post(f"/v1/milestones/{m1['id']}/submit", headers=pro_user.h, json={"confirmed": True})
    assert r.status_code == 200, r.text
    m = r.json()["milestones"][0]
    (sub,) = m["submissions"]
    assert m["status"] == "SUBMITTED" and sub["revisionNumber"] == 0 and sub["declaredAt"] and sub["note"] == "Ready for review"
    assert sub["items"][0]["note"] == "Sections 1-4 follow the OECD outline" and sub["items"][0]["carriedOver"] is False
    assert [f["name"] for f in sub["files"]] == ["master-file.pdf"]  # also listed flat, for disputes and older screens
    assert (await client.get(f"{C}/{c['id']}/files/{work['sha256']}", headers=buyer.h)).status_code == 200
    assert (await client.get(_draft(m1["id"]), headers=pro_user.h)).json()["savedAt"] is None  # the draft became the submission

    async with sf() as s:
        with pytest.raises(Exception, match="append-only"):
            await s.execute(text("UPDATE contract.submissions SET note = 'changed'"))


async def test_buyer_reviews_each_deliverable_and_the_revision_starts_from_the_last_delivery(client, make_user, drain, sf):
    pro_user, buyer, c, m1 = await _funded(client, make_user, drain, sf)
    url = f"{_draft(m1['id'])}/items/master/evidence"
    await client.post(url, headers=pro_user.h, json={"file": upload("master-file.pdf", b"v1")})
    await client.post(f"/v1/milestones/{m1['id']}/submit", headers=pro_user.h, json={"confirmed": True})

    review = f"/v1/milestones/{m1['id']}/review"
    r = await client.post(review, headers=buyer.idem(), json={"verdicts": [{"deliverableKey": "master", "verdict": "CHANGES_REQUESTED"}]})
    assert r.status_code == 422 and r.json()["code"] == "COMMENT_REQUIRED"
    r = await client.post(review, headers=buyer.idem(), json={"verdicts": [{"deliverableKey": "local", "verdict": "MET"}]})
    assert r.status_code == 422 and r.json()["code"] == "VERDICTS_INCOMPLETE"
    assert (await client.post(review, headers=pro_user.idem(), json={"verdicts": [{"deliverableKey": "master", "verdict": "MET"}]})).status_code == 403
    r = await client.post(review, headers=buyer.idem(), json={"verdicts": [
        {"deliverableKey": "master", "verdict": "CHANGES_REQUESTED", "comment": "Add the benchmarking appendix"}]})
    m = r.json()["milestones"][0]
    assert m["status"] == "REVISION_REQUESTED" and m["lastRevisionReason"] == "Master file: Add the benchmarking appendix"
    assert m["submissions"][0]["review"]["outcome"] == "REVISION_REQUESTED"

    d = (await client.get(_draft(m1["id"]), headers=pro_user.h)).json()
    assert d["revisionNumber"] == 1 and d["items"][0]["changesRequested"] == "Add the benchmarking appendix"
    assert d["items"][0]["evidence"][0]["file"]["name"] == "master-file.pdf"  # carried over: nothing to upload again
    assert [b["code"] for b in d["blockers"]] == ["NO_CHANGES"]
    await client.patch(_draft(m1["id"]), headers=pro_user.h, json={"note": "No change yet"})  # creates the draft
    r = await client.post(f"/v1/milestones/{m1['id']}/submit", headers=pro_user.h, json={"confirmed": True})
    assert r.status_code == 409 and r.json()["code"] == "DELIVERY_INCOMPLETE" and r.json()["extra"]["blockers"][0]["code"] == "NO_CHANGES"

    d = (await client.post(url, headers=pro_user.h, json={"file": upload("appendix.pdf", b"appendix")})).json()
    assert d["canSubmit"] is True and len(d["items"][0]["evidence"]) == 2
    r = await client.post(f"/v1/milestones/{m1['id']}/submit", headers=pro_user.h, json={"confirmed": True})
    latest = r.json()["milestones"][0]["submissions"][0]
    assert latest["revisionNumber"] == 1 and latest["items"][0]["carriedOver"] is False and len(latest["files"]) == 2

    r = await client.post(review, headers=buyer.idem(), json={"verdicts": [{"deliverableKey": "master", "verdict": "MET"}]})
    m = r.json()["milestones"][0]
    assert m["status"] == "ACCEPTED" and m["submissions"][0]["review"]["outcome"] == "ACCEPTED" and m["revisionCount"] == 1
    r = await client.post(review, headers=buyer.idem(), json={"verdicts": [{"deliverableKey": "master", "verdict": "MET"}]})
    assert r.status_code == 409 and r.json()["code"] == "MILESTONE_NOT_SUBMITTED"
    await drain()
    async with sf() as s:
        audited = await s.scalar(text("SELECT count(*) FROM audit.audit_records WHERE action LIKE '%contract.submission.reviewed%'"))
    assert audited == 2


async def test_links_are_recognised_and_checked_without_being_opened(client, make_user, drain, sf):
    pro_user, buyer, c, m1 = await _funded(client, make_user, drain, sf)
    url = f"{_draft(m1['id'])}/items/master/evidence"
    for bad in ("http://example.com/report", "https://10.0.0.5/admin", "https://localhost:8000/x", "https://intranet/x",
                "https://user:secret@example.com/x"):
        r = await client.post(url, headers=pro_user.h, json={"url": bad})
        assert r.status_code == 422 and r.json()["code"] == "INVALID_LINK", bad
    assert (await client.post(url, headers=pro_user.h, json={})).json()["code"] == "EVIDENCE_REQUIRED"
    r = await client.post(f"{_draft(m1['id'])}/items/nope/evidence", headers=pro_user.h, json={"url": "https://example.com"})
    assert r.status_code == 422 and r.json()["code"] == "UNKNOWN_DELIVERABLE"

    await client.post(url, headers=pro_user.h, json={"url": "https://docs.google.com/spreadsheets/d/abc/edit"})
    d = (await client.post(url, headers=pro_user.h, json={"url": "https://github.com/acme/tp-model"})).json()
    links = d["items"][0]["evidence"]
    assert [(e["provider"], e["kind"]) for e in links] == [("GOOGLE_SHEET", "DOCUMENT"), ("GITHUB", "REPOSITORY")]
    assert {w["code"] for w in d["warnings"]} == {"LIVE_DOCUMENT", "NO_VERSION"} and d["canSubmit"] is True

    d = (await client.delete(f"{url}/{links[1]['id']}", headers=pro_user.h)).json()
    d = (await client.post(url, headers=pro_user.h, json={"url": "https://github.com/acme/tp-model", "version": "a1b2c3d"})).json()
    assert {w["code"] for w in d["warnings"]} == {"LIVE_DOCUMENT"}
    assert (await client.delete(f"{url}/missing", headers=pro_user.h)).status_code == 404
    r = await client.post(f"/v1/milestones/{m1['id']}/submit", headers=pro_user.h, json={"confirmed": True})
    sub = r.json()["milestones"][0]["submissions"][0]
    assert sub["files"] == [] and sub["items"][0]["evidence"][1]["version"] == "a1b2c3d"


async def test_discarding_a_draft_allows_the_one_step_delivery(client, make_user, drain, sf):
    pro_user, buyer, c, m1 = await _funded(client, make_user, drain, sf)
    await client.patch(_draft(m1["id"]), headers=pro_user.h, json={"itemNotes": {"master": "Started"}})
    assert (await client.delete(_draft(m1["id"]), headers=pro_user.h)).json()["savedAt"] is None
    r = await client.post(f"/v1/milestones/{m1['id']}/submit", headers=pro_user.h, json={"note": "Master file"})
    sub = r.json()["milestones"][0]["submissions"][0]
    assert r.json()["milestones"][0]["status"] == "SUBMITTED" and sub["items"] == [] and sub["declaredAt"] is None
    # A one-step delivery has no items: the buyer reviews the milestone's deliverables from the contract.
    r = await client.post(f"/v1/milestones/{m1['id']}/review", headers=buyer.idem(),
                          json={"verdicts": [{"deliverableKey": "master", "verdict": "MET"}]})
    assert r.json()["milestones"][0]["status"] == "ACCEPTED"


@pytest.mark.unit
def test_link_recognition():
    sheet = delivery.link_record("https://docs.google.com/spreadsheets/d/x/edit", "Revenue", None, NOW)
    assert (sheet["provider"], sheet["kind"], sheet["label"]) == ("GOOGLE_SHEET", "DOCUMENT", "Revenue")
    assert delivery.link_record("https://acme.notion.site/page", None, None, NOW)["provider"] == "NOTION"
    assert delivery.link_record("https://dash.acme-staging.app", None, None, NOW)["kind"] == "WEBSITE"
    for bad in ("ftp://example.com", "https://[::1]/", "https://192.168.1.4", "https://printer.local/x", "javascript:alert(1)"):
        with pytest.raises(ValidationFailed):
            delivery.link_record(bad, None, None, NOW)


@pytest.mark.unit
def test_checks_before_sending():
    blockers, warnings = delivery.check(DELIVERABLES, {}, date(2026, 10, 1), date(2026, 10, 14), None)
    assert [b["code"] for b in blockers] == ["NO_EVIDENCE"] and [w["code"] for w in warnings] == ["LATE"]
    item = {"note": "", "evidence": [{"id": "e1", "type": "FILE", "name": "a.pdf", "sha256": "f" * 64}]}
    assert delivery.check(DELIVERABLES, {"master": item}, None, date(2026, 10, 14), None) == ([], [])
    previous = delivery.frozen_items(DELIVERABLES, {"master": item}, None)
    blockers, _ = delivery.check(DELIVERABLES, delivery.seed_from(previous), None, date(2026, 10, 14), previous)
    assert [b["code"] for b in blockers] == ["NO_CHANGES"]
    whole = delivery.deliverables_for({"deliverables": []}, [], "Advice", "Monthly advisory")
    assert whole == [{"key": delivery.WHOLE_MILESTONE, "title": "Advice", "acceptanceCriteria": "Monthly advisory"}]
