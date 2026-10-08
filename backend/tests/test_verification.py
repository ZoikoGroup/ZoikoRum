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
