"""Step 4 - verification: screening at registration, identity review, credential checks with expiry,
revocation, firm registration, and the controls around human review."""

from __future__ import annotations

import base64
import hashlib
from datetime import timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from zoikorum.shared import clock

def pdf(name: str, body: bytes = b"scan") -> dict:
    """A small but real PDF evidence upload: bytes, type and the matching fingerprint."""
    data = b"%PDF-1.4\n" + body
    return {"name": name, "sha256": hashlib.sha256(data).hexdigest(), "size": len(data), "contentType": "application/pdf",
            "dataBase64": base64.b64encode(data).decode()}


PASSPORT = pdf("passport.pdf", b"passport")
SHA = PASSPORT["sha256"]
DOC = {"evidenceType": "ID_DOCUMENT", "items": [pdf("doc.pdf")]}


async def new_pro(client, make_user, drain, name="pia", **kw):
    u = await make_user(name, account_type="PROFESSIONAL", **kw)
    pro = (await client.post("/v1/professionals", headers=u.h, json={})).json()
    await drain()
    return u, pro


async def officer(make_user, name="cora", **kw):
    o = await make_user(name, platform_roles=("COMPLIANCE_OFFICER",), **kw)
    await o.step_up()
    return o


def cases_url(pro):
    return f"/v1/verification/subjects/PROFESSIONAL/{pro['id']}"


async def case_of(client, u, pro, vtype):
    return next(c for c in (await client.get(cases_url(pro), headers=u.h)).json() if c["verificationType"] == vtype)


async def outbox(sf, event_type):
    async with sf() as s:
        rows = await s.execute(text("SELECT envelope FROM platform.outbox WHERE event_type = :t ORDER BY seq"), {"t": event_type})
        return [r[0]["payload"] for r in rows]


async def test_registration_runs_sanctions_screening(client, make_user, drain):
    u, pro = await new_pro(client, make_user, drain)
    screening = await case_of(client, u, pro, "RESTRICTIONS")
    assert screening["status"] == "VERIFIED"  # FakeProvider: no potential match -> automatic PASS

    flagged, flagged_pro = await new_pro(client, make_user, drain, name="sanctioned")
    assert (await case_of(client, flagged, flagged_pro, "RESTRICTIONS"))["status"] == "PENDING"  # human review
    o = await officer(make_user)
    queue = (await client.get("/v1/verification/review-queue", headers=o.h)).json()["items"]
    assert [q["subjectName"] for q in queue] == ["Sanctioned"]


async def test_identity_review_flow(client, make_user, drain, sf):
    u, pro = await new_pro(client, make_user, drain)
    body = {"verificationType": "IDENTITY", "subjectType": "PROFESSIONAL", "subjectId": pro["id"]}
    r = await client.post("/v1/verification/cases", headers=u.h, json=body)
    assert r.status_code == 201 and r.json()["status"] == "PENDING" and r.json()["estimatedCompletion"]
    case = r.json()
    assert (await client.post("/v1/verification/cases", headers=u.h, json=body)).json()["code"] == "CASE_EXISTS"

    r = await client.post(f"/v1/verification/cases/{case['id']}/evidence", headers=u.h,
                          json={"evidenceType": "ID_DOCUMENT", "items": [PASSPORT]})
    assert r.status_code == 200 and r.json()["status"] == "IN_REVIEW" and r.json()["evidence"][0]["sha256"] == SHA

    # The professional cannot decide their own case; reviewers need the role and a fresh step-up.
    decide = f"/v1/verification/cases/{case['id']}/decision"
    assert (await client.post(decide, headers=u.h, json={"decision": "VERIFIED", "reasonCode": "OK"})).status_code == 403
    o = await make_user("cora", platform_roles=("COMPLIANCE_OFFICER",))
    assert (await client.post(decide, headers=o.h, json={"decision": "VERIFIED", "reasonCode": "OK"})).json()["code"] == "STEP_UP_REQUIRED"
    await o.step_up()
    r = await client.post(decide, headers=o.h, json={"decision": "FAILED", "reasonCode": "BLURRY"})
    assert r.status_code == 422 and r.json()["code"] == "PUBLIC_REASON_REQUIRED"
    r = await client.post(decide, headers=o.h, json={"decision": "NEEDS_INFO", "reasonCode": "BLURRY",
                                                      "publicReason": "The photo page is blurred. Please upload a clearer scan."})
    assert r.json()["status"] == "NEEDS_INFO"
    owner_view = (await client.get(f"/v1/verification/cases/{case['id']}", headers=u.h)).json()
    assert owner_view["publicReason"].startswith("The photo page") and owner_view["isMine"] is True

    await client.post(f"/v1/verification/cases/{case['id']}/evidence", headers=u.h,
                      json={"evidenceType": "ID_DOCUMENT", "items": [pdf("passport-2.pdf", b"clearer")]})
    r = await client.post(decide, headers=o.h, json={"decision": "VERIFIED", "reasonCode": "DOCUMENT_MATCH"})
    assert r.json()["status"] == "VERIFIED" and r.json()["verifiedAt"]
    (done,) = [e for e in await outbox(sf, "zoikorum.verification.case.completed.v1") if e["verificationType"] == "IDENTITY"]
    assert done["subjectId"] == pro["id"] and done["decidedBy"] == str(o.id)

    stranger = await make_user("sam")
    assert (await client.get(f"/v1/verification/cases/{case['id']}", headers=stranger.h)).status_code == 404


async def test_reviewers_cannot_review_their_own_case(client, make_user, drain):
    o, pro = await new_pro(client, make_user, drain, name="otto", platform_roles=("COMPLIANCE_OFFICER",))
    await o.step_up()
    case = (await client.post("/v1/verification/cases", headers=o.h, json={
        "verificationType": "IDENTITY", "subjectType": "PROFESSIONAL", "subjectId": pro["id"]})).json()
    r = await client.post(f"/v1/verification/cases/{case['id']}/decision", headers=o.h, json={"decision": "VERIFIED", "reasonCode": "OK"})
    assert r.status_code == 403 and r.json()["code"] == "SELF_REVIEW"


async def test_credential_check_updates_the_claim_and_expires(client, make_user, drain, sf):
    u, pro = await new_pro(client, make_user, drain)
    expires = (clock.now() + timedelta(days=100)).date().isoformat()
    claim = (await client.post("/v1/professionals/me/credentials", headers=u.h, json={
        "credentialType": "LICENSE", "name": "CPA", "issuingBody": "Texas State Board", "registrationNumber": "TX-1",
        "jurisdiction": "US", "expiresOn": expires})).json()
    await drain()
    case = await case_of(client, u, pro, "CREDENTIAL")
    assert case["credentialClaimId"] == claim["id"] and case["label"] == "CPA (US)" and case["status"] == "PENDING"

    await client.post(f"/v1/verification/cases/{case['id']}/evidence", headers=u.h, json=DOC)
    o = await officer(make_user)
    r = await client.post(f"/v1/verification/cases/{case['id']}/decision", headers=o.h,
                          json={"decision": "VERIFIED", "reasonCode": "REGISTRY_MATCH"})
    assert r.json()["expiresAt"].startswith(expires)  # defaults to the credential's own expiry
    await drain()
    (c,) = (await client.get("/v1/professionals/me/credentials", headers=u.h)).json()
    assert c["status"] == "VERIFIED" and c["displayLabel"] == "Validated"

    clock.set_now(clock.now() + timedelta(days=71))  # 29 days left: the 30-day reminder is due
    await drain()
    (reminder,) = await outbox(sf, "zoikorum.verification.case.expiring.v1")
    assert reminder["caseId"] == case["id"] and reminder["daysLeft"] == 30  # the 30-day reminder says 30

    clock.set_now(clock.now() + timedelta(days=30))
    await drain()
    # The timer has fired, but the original session has also expired after 101 days.
    assert (await client.get(cases_url(pro), headers=u.h)).status_code == 401
    clock.set_now(None)  # Inspect the persisted expiry using the original, current-time session.
    assert (await case_of(client, u, pro, "CREDENTIAL"))["status"] == "EXPIRED"
    (c,) = (await client.get("/v1/professionals/me/credentials", headers=u.h)).json()
    assert c["status"] == "EXPIRED"
    assert len(await outbox(sf, "zoikorum.verification.case.expiring.v1")) == 3  # 30, 14 and 7 days


async def test_revoking_a_check_reaches_the_claim(client, make_user, drain):
    u, pro = await new_pro(client, make_user, drain)
    await client.post("/v1/professionals/me/credentials", headers=u.h, json={
        "credentialType": "CERTIFICATION", "name": "CMA", "issuingBody": "IMA"})
    await drain()
    case = await case_of(client, u, pro, "CREDENTIAL")
    await client.post(f"/v1/verification/cases/{case['id']}/evidence", headers=u.h, json=DOC)
    o = await officer(make_user)
    await client.post(f"/v1/verification/cases/{case['id']}/decision", headers=o.h, json={"decision": "VERIFIED", "reasonCode": "OK"})
    r = await client.post(f"/v1/verification/cases/{case['id']}/revoke", headers=o.h,
                          json={"reasonCode": "ISSUER_REVOKED", "publicReason": "The issuing body withdrew this certification."})
    assert r.json()["status"] == "REVOKED"
    again = await client.post(f"/v1/verification/cases/{case['id']}/revoke", headers=o.h,
                              json={"reasonCode": "AGAIN", "publicReason": "Second attempt"})
    assert again.status_code == 409
    await drain()
    (c,) = (await client.get("/v1/professionals/me/credentials", headers=u.h)).json()
    assert c["status"] == "REVOKED"
    public = (await client.get(f"/v1/professionals/{pro['id']}", headers=u.h)).json()
    assert public["credentials"] == []  # revoked claims are not shown to buyers


async def test_firm_registration_verifies_the_firm(client, make_user, drain, sf):
    admin = await make_user("fay", account_type="FIRM", organization="Fay Advisory LLP")
    await drain()
    await admin.step_up()
    firm = (await client.get("/v1/firms/mine", headers=admin.h)).json()[0]
    r = await client.post("/v1/verification/cases", headers=admin.h, json={
        "verificationType": "FIRM_REGISTRATION", "subjectType": "FIRM", "subjectId": firm["id"]})
    assert r.status_code == 201
    await client.post(f"/v1/verification/cases/{r.json()['id']}/evidence", headers=admin.h, json=DOC)
    o = await officer(make_user)
    await client.post(f"/v1/verification/cases/{r.json()['id']}/decision", headers=o.h,
                      json={"decision": "VERIFIED", "reasonCode": "COMPANIES_HOUSE_MATCH"})
    await drain()
    assert (await client.get(f"/v1/firms/{firm['id']}", headers=admin.h)).json()["status"] == "VERIFIED"
    assert len(await outbox(sf, "zoikorum.firm.firm.verified.v1")) == 1

    u, pro = await new_pro(client, make_user, drain)
    wrong = await client.post("/v1/verification/cases", headers=u.h, json={
        "verificationType": "FIRM_REGISTRATION", "subjectType": "PROFESSIONAL", "subjectId": pro["id"]})
    assert wrong.status_code == 422
    not_mine = await client.post("/v1/verification/cases", headers=u.h, json={
        "verificationType": "FIRM_REGISTRATION", "subjectType": "FIRM", "subjectId": firm["id"]})
    assert not_mine.status_code == 403


async def test_evidence_is_append_only(client, make_user, drain, sf):
    u, pro = await new_pro(client, make_user, drain)
    case = (await client.post("/v1/verification/cases", headers=u.h, json={
        "verificationType": "IDENTITY", "subjectType": "PROFESSIONAL", "subjectId": pro["id"]})).json()
    await client.post(f"/v1/verification/cases/{case['id']}/evidence", headers=u.h,
                      json={"evidenceType": "ID_DOCUMENT", "items": [pdf("id.pdf")]})
    with pytest.raises(DBAPIError):
        async with sf() as s, s.begin():
            await s.execute(text("UPDATE verification.evidence_items SET sha256 = :x"), {"x": "c" * 64})


async def test_verified_needs_a_document_and_provider_fail_goes_to_a_person(client, make_user, drain, monkeypatch):
    u, pro = await new_pro(client, make_user, drain)
    case = (await client.post("/v1/verification/cases", headers=u.h, json={
        "verificationType": "IDENTITY", "subjectType": "PROFESSIONAL", "subjectId": pro["id"]})).json()
    o = await officer(make_user)
    r = await client.post(f"/v1/verification/cases/{case['id']}/decision", headers=o.h, json={"decision": "VERIFIED", "reasonCode": "OK"})
    assert r.status_code == 422 and r.json()["code"] == "EVIDENCE_REQUIRED"

    from zoikorum.domains.verification import service as verification_service

    class Failing:
        async def check(self, verification_type, details):
            return "FAIL"

    monkeypatch.setattr(verification_service, "get_provider", lambda: Failing())
    insurance = (await client.post("/v1/verification/cases", headers=u.h, json={
        "verificationType": "INSURANCE", "subjectType": "PROFESSIONAL", "subjectId": pro["id"]})).json()
    assert insurance["status"] == "IN_REVIEW"  # never rejected without a person


async def test_provider_pass_never_approves_a_credential_on_its_own(client, make_user, drain, monkeypatch):
    """Ethics code / regulator: no automated credential approval. A provider PASS verifies identity and screening
    (sampled for a second look); on a credential, jurisdiction or insurance check it is evidence for an officer."""
    from zoikorum.domains.verification import service as verification_service

    class Passing:
        async def check(self, verification_type, details):
            return "PASS"

    monkeypatch.setattr(verification_service, "get_provider", lambda: Passing())
    u, pro = await new_pro(client, make_user, drain)
    start = lambda vtype, **kw: client.post("/v1/verification/cases", headers=u.h, json={
        "verificationType": vtype, "subjectType": "PROFESSIONAL", "subjectId": pro["id"], **kw})
    assert (await start("IDENTITY")).json()["status"] == "VERIFIED"
    insurance = (await start("INSURANCE")).json()
    jurisdiction = (await start("JURISDICTION", jurisdiction="GB")).json()
    await client.post("/v1/professionals/me/credentials", headers=u.h, json={
        "credentialType": "LICENSE", "name": "CPA", "issuingBody": "Texas State Board", "registrationNumber": "TX-1",
        "jurisdiction": "US"})
    await drain()
    credential = await case_of(client, u, pro, "CREDENTIAL")
    assert {c["status"] for c in (insurance, jurisdiction, credential)} == {"IN_REVIEW"}

    o = await officer(make_user)
    queue = {row["id"]: row for row in (await client.get("/v1/verification/review-queue", headers=o.h)).json()["items"]}
    assert all(queue[c["id"]]["providerResult"] == "PASS" for c in (insurance, jurisdiction, credential))  # kept as evidence
    await client.post(f"/v1/verification/cases/{credential['id']}/evidence", headers=u.h, json=DOC)
    r = await client.post(f"/v1/verification/cases/{credential['id']}/decision", headers=o.h,
                          json={"decision": "VERIFIED", "reasonCode": "REGISTRY_MATCH"})
    assert r.status_code == 200 and r.json()["status"] == "VERIFIED"


async def test_screening_flag_is_private_and_hides_the_profile(client, make_user, drain, sf):
    from test_search import publish

    u, pro = await publish(client, make_user, drain, "sanctioned", headline="Fractional CFO", primary="fractional-cfo")
    screening = await case_of(client, u, pro, "RESTRICTIONS")
    assert screening["status"] == "PENDING"  # possible match: a person reviews it
    assert (await client.get(f"/v1/trust/professionals/{pro['id']}", headers=u.h)).json()["tier"] == "C"
    assert [i["displayName"] for i in (await client.get("/v1/search/professionals")).json()["items"]] == ["Sanctioned"]

    o = await officer(make_user)
    await client.post(f"/v1/verification/cases/{screening['id']}/decision", headers=o.h, json={
        "decision": "FAILED", "reasonCode": "SANCTIONS_MATCH", "publicReason": "Screening found a match. Contact support."})
    await drain()
    assert (await client.get("/v1/search/professionals")).json()["items"] == []  # flagged profiles never surface
    public = (await client.get(f"/v1/professionals/{pro['id']}")).json()
    assert public["trust"]["dimensions"]["restrictions"] == "UNKNOWN" and "score" not in public["trust"]
    assert not any("screening" in line for line in public["trust"]["explanation"])
    owner = (await client.get(f"/v1/trust/professionals/{pro['id']}", headers=u.h)).json()
    assert owner["dimensions"]["restrictions"] == "FLAGGED"  # the professional still sees why


async def test_evidence_files_are_stored_checked_and_viewable(client, make_user, drain, sf):
    """The document itself is stored; its type and fingerprint are checked; owner and reviewers can open it (audited)."""
    u, pro = await new_pro(client, make_user, drain)
    case = (await client.post("/v1/verification/cases", headers=u.h, json={
        "verificationType": "IDENTITY", "subjectType": "PROFESSIONAL", "subjectId": pro["id"]})).json()
    url = f"/v1/verification/cases/{case['id']}/evidence"

    tampered = {**pdf("a.pdf"), "sha256": "e" * 64}
    assert (await client.post(url, headers=u.h, json={"evidenceType": "ID_DOCUMENT", "items": [tampered]})).json()["code"] == "FINGERPRINT_MISMATCH"
    fake = pdf("b.pdf")
    exe = b"MZ not a pdf"
    fake.update(dataBase64=base64.b64encode(exe).decode(), size=len(exe), sha256=hashlib.sha256(exe).hexdigest())
    assert (await client.post(url, headers=u.h, json={"evidenceType": "ID_DOCUMENT", "items": [fake]})).json()["code"] == "INVALID_FILE_TYPE"

    r = await client.post(url, headers=u.h, json={"evidenceType": "ID_DOCUMENT", "items": [PASSPORT]})
    (ev,) = r.json()["evidence"]
    assert ev["hasFile"] is True and ev["contentType"] == "application/pdf"
    file_url = f"/v1/verification/evidence/{ev['id']}/file"

    own = await client.get(file_url, headers=u.h)
    assert own.status_code == 200 and own.content == base64.b64decode(PASSPORT["dataBase64"])
    assert own.headers["content-type"] == "application/pdf" and own.headers["cache-control"] == "no-store"
    o = await officer(make_user)
    assert (await client.get(file_url, headers=o.h)).status_code == 200
    stranger = await make_user("sam")
    assert (await client.get(file_url, headers=stranger.h)).status_code == 404

    await drain()
    async with sf() as s:
        viewed = await s.scalar(text("SELECT count(*) FROM audit.audit_records WHERE action LIKE '%verification.evidence.viewed%'"))
    assert viewed == 2


async def test_document_first_look_runs_outside_the_transaction_and_is_still_logged(client, make_user, drain, sf, monkeypatch):
    """The model call (up to 30 s) happens before the consumer's transaction; its hint and inference record are stored."""
    from zoikorum.domains.ai import facade as ai_facade
    from zoikorum.domains.verification import service as verification_service

    calls = []

    async def looks_unrelated(data, content_type, expected, *, subject_id=None, requested_by=None, inference_log=None, **_):
        async with sf() as s:  # nothing of this delivery is locked or open: the inbox row is not written yet
            calls.append(await s.scalar(text("SELECT count(*) FROM platform.inbox WHERE consumer = 'verification.document_check'")))
        inference_log.append(dict(prompt_version=None, model="test-model", input_sha256=hashlib.sha256(data).hexdigest(),
                                  purpose="document-check", output='{"verdict":"UNRELATED"}', subject_id=subject_id,
                                  requested_by=requested_by, latency_ms=5, fallback_used=False))
        return ai_facade.DocumentCheck("UNRELATED", "a holiday photo", "This is not an identity document.", "ai:test")

    monkeypatch.setattr(verification_service.ai_facade, "assess_document", looks_unrelated)
    u, pro = await new_pro(client, make_user, drain)
    case = (await client.post("/v1/verification/cases", headers=u.h, json={
        "verificationType": "IDENTITY", "subjectType": "PROFESSIONAL", "subjectId": pro["id"]})).json()
    await client.post(f"/v1/verification/cases/{case['id']}/evidence", headers=u.h,
                      json={"evidenceType": "ID_DOCUMENT", "items": [PASSPORT]})
    await drain()
    await drain()  # a second delivery attempt changes nothing
    assert calls == [0]
    o = await officer(make_user)
    (ev,) = (await client.get(f"/v1/verification/cases/{case['id']}", headers=o.h)).json()["evidence"]
    assert ev["automaticCheck"]["verdict"] == "UNRELATED" and ev["automaticCheck"]["seen"] == "a holiday photo"
    async with sf() as s:
        assert await s.scalar(text("SELECT count(*) FROM ai.inference_logs WHERE purpose = 'document-check'")) == 1
    from zoikorum.shared.event_catalog import E
    assert len(await outbox(sf, E.VERIFICATION_EVIDENCE_FLAGGED)) == 1


async def test_automatic_approvals_get_a_human_second_look(client, make_user, drain, monkeypatch):
    """Ethics code: no approval without human oversight. A share of partner approvals waits for a compliance officer,
    who confirms it or overturns it with a reason (the check is revoked and the person can appeal)."""
    from zoikorum.config import get_settings

    monkeypatch.setattr(get_settings(), "verification_second_look_pct", 100)
    u, pro = await new_pro(client, make_user, drain)
    screening = await case_of(client, u, pro, "RESTRICTIONS")
    assert screening["status"] == "VERIFIED" and screening.get("secondLook") is None  # not shown to the person
    v, pro2 = await new_pro(client, make_user, drain, name="vic")

    o = await officer(make_user)
    waiting = (await client.get("/v1/verification/second-looks", headers=o.h)).json()
    assert {w["subjectId"] for w in waiting} == {pro["id"], pro2["id"]} and {w["secondLook"] for w in waiting} == {"SAMPLED"}

    first = next(w for w in waiting if w["subjectId"] == pro["id"])
    r = await client.post(f"/v1/verification/cases/{first['id']}/second-look", headers=o.h, json={"confirm": True})
    assert r.status_code == 200 and r.json()["secondLook"] == "CONFIRMED" and r.json()["status"] == "VERIFIED"

    second = next(w for w in waiting if w["subjectId"] == pro2["id"])
    r = await client.post(f"/v1/verification/cases/{second['id']}/second-look", headers=o.h, json={"confirm": False})
    assert r.json()["code"] == "REASON_REQUIRED"
    r = await client.post(f"/v1/verification/cases/{second['id']}/second-look", headers=o.h, json={
        "confirm": False, "reasonCode": "SCREENING_MATCH", "publicReason": "A possible match needs a closer check."})
    assert r.json()["status"] == "REVOKED" and r.json()["secondLook"] == "OVERTURNED"
    assert (await client.get("/v1/verification/second-looks", headers=o.h)).json() == []


async def test_open_review_queue_keeps_needs_info_cases_visible(client, make_user, drain):
    user, profile = await new_pro(client, make_user, drain, name="waiting-on-evidence")
    reviewer = await officer(make_user)
    response = await client.post("/v1/verification/cases", headers=user.h, json={
        "subjectType": "PROFESSIONAL", "subjectId": profile["id"], "verificationType": "IDENTITY"})
    assert response.status_code in (200, 201), response.text
    case = response.json()
    result = await client.post(f"/v1/verification/cases/{case['id']}/decision", headers=reviewer.h, json={
        "decision": "NEEDS_INFO", "reasonCode": "BLURRY", "publicReason": "Please upload a readable ID."})
    assert result.status_code == 200, result.text
    page = (await client.get("/v1/verification/review-queue", headers=reviewer.h)).json()
    assert any(row["id"] == case["id"] and row["status"] == "NEEDS_INFO" for row in page["items"])

    history = (await client.get("/v1/verification/review-queue", headers=reviewer.h, params={"status": "ALL"})).json()["items"]
    assert any(row["id"] == case["id"] for row in history)
    assert any(row["status"] == "VERIFIED" for row in history)
    verified = (await client.get("/v1/verification/review-queue", headers=reviewer.h, params={"status": "VERIFIED"})).json()["items"]
    assert verified and all(row["status"] == "VERIFIED" for row in verified)
