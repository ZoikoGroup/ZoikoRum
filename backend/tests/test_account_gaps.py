"""Verification and account gaps closed on 2026-10-12: abandoned partner sessions, decided checks, renewal, insurance
expiry, withdrawn credentials, name changes, firm detail changes, recovery codes, code-guessing lockout and suspended
accounts in search."""

from __future__ import annotations

import pyotp
from sqlalchemy import text

from test_search import URL, publish
from test_verification import case_of, officer, outbox
from test_veriff import identity_case, veriff, webhook  # noqa: F401  (veriff is a fixture)
from zoikorum.shared import clock
from zoikorum.shared.event_catalog import E

V = "/v1/verification"
PDF = {"name": "licence.pdf", "contentType": "application/pdf"}


def pdf_upload(body: bytes = b"licence") -> dict:
    import base64
    import hashlib

    data = b"%PDF-1.4\n" + body
    return {**PDF, "sha256": hashlib.sha256(data).hexdigest(), "size": len(data), "dataBase64": base64.b64encode(data).decode()}


async def test_an_abandoned_partner_session_cannot_be_verified_without_a_document(client, make_user, drain, veriff):  # noqa: F811
    u, pro, case = await identity_case(client, make_user, drain)
    await client.post(f"{V}/cases/{case['id']}/hosted-session", headers=u.h)
    await webhook(client, {"verification": {"id": "sess-1", "status": "abandoned", "code": 9104}})
    left = await case_of(client, u, pro, "IDENTITY")
    assert left["status"] == "PENDING"  # nothing was captured, so nothing reaches a reviewer
    o = await officer(make_user)
    r = await client.post(f"{V}/cases/{case['id']}/decision", headers=o.h, json={"decision": "VERIFIED", "reasonCode": "DOCUMENT_MATCH"})
    assert r.status_code == 422 and r.json()["code"] == "EVIDENCE_REQUIRED"
    again = (await client.post(f"{V}/cases/{case['id']}/hosted-session", headers=u.h)).json()
    assert again["url"].endswith("-2")  # a fresh session, not the dead link


async def test_decided_checks_are_not_decided_again_and_identity_uploads_count_as_id(client, make_user, drain, sf):
    u = await make_user("ivy", account_type="PROFESSIONAL")
    pro = (await client.post("/v1/professionals", headers=u.h, json={})).json()
    await drain()
    await u.step_up()
    case = (await client.post(f"{V}/cases", headers=u.h,
                              json={"verificationType": "IDENTITY", "subjectType": "PROFESSIONAL", "subjectId": pro["id"]})).json()
    await client.post(f"{V}/cases/{case['id']}/evidence", headers=u.h, json={"evidenceType": "OTHER", "items": [pdf_upload()]})
    async with sf() as s:
        assert await s.scalar(text("SELECT evidence_type FROM verification.evidence_items WHERE case_id = :c"), {"c": case["id"]}) == "ID_DOCUMENT"
    o = await officer(make_user)
    failed = await client.post(f"{V}/cases/{case['id']}/decision", headers=o.h,
                               json={"decision": "FAILED", "reasonCode": "DOCUMENT_UNRELATED", "publicReason": "Not an identity document."})
    assert failed.json()["status"] == "FAILED"
    again = await client.post(f"{V}/cases/{case['id']}/decision", headers=o.h, json={"decision": "VERIFIED", "reasonCode": "OTHER"})
    assert again.status_code == 409 and again.json()["code"] == "CASE_DECIDED"  # reversals go through an appeal


async def test_staff_see_the_name_and_details_to_compare_and_insurance_needs_an_end_date(client, make_user, drain):
    u = await make_user("ina", account_type="PROFESSIONAL")
    pro = (await client.post("/v1/professionals", headers=u.h, json={})).json()
    await client.patch("/v1/professionals/me", headers=u.h, json={"legalName": "Ina Example"})
    await drain()
    await u.step_up()
    case = (await client.post(f"{V}/cases", headers=u.h, json={"verificationType": "INSURANCE", "subjectType": "PROFESSIONAL",
                                                               "subjectId": pro["id"], "details": {"insurer": "Acme Mutual"}})).json()
    await client.post(f"{V}/cases/{case['id']}/evidence", headers=u.h,
                      json={"evidenceType": "INSURANCE_POLICY", "items": [pdf_upload(b"policy")]})
    o = await officer(make_user)
    seen = (await client.get(f"{V}/cases/{case['id']}", headers=o.h)).json()
    assert seen["subjectLegalName"] == "Ina Example" and seen["details"] == {"insurer": "Acme Mutual"}
    assert (await client.get(f"{V}/cases/{case['id']}", headers=u.h)).json()["subjectLegalName"] is None  # staff view only
    r = await client.post(f"{V}/cases/{case['id']}/decision", headers=o.h, json={"decision": "VERIFIED", "reasonCode": "DOCUMENT_MATCH"})
    assert r.status_code == 422 and r.json()["code"] == "EXPIRY_REQUIRED"
    reasons = (await client.get(f"{V}/decision-reasons", headers=o.h, params={"verificationType": "INSURANCE"})).json()
    unrelated = next(x for x in reasons if x["code"] == "DOCUMENT_UNRELATED")
    assert "indemnity insurance certificate" in unrelated["message"] and "FAILED" in unrelated["decisions"]
    codes = {x["code"] for x in reasons}  # only reasons that fit an insurance check
    assert "DOCUMENT_MATCH" in codes and not codes & {"PARTNER_VERIFIED", "REGISTRY_MATCH", "NOT_IN_REGISTER"}
    missing = next(x for x in reasons if x["code"] == "NO_DOCUMENT")  # nothing uploaded yet: ask for it
    assert missing["decisions"] == ["NEEDS_INFO"] and "indemnity insurance certificate" in missing["message"]
    identity = {x["code"] for x in (await client.get(f"{V}/decision-reasons", headers=o.h,
                                                     params={"verificationType": "IDENTITY"})).json()}
    assert "PARTNER_VERIFIED" in identity and "REGISTRY_MATCH" not in identity


async def test_a_legal_name_change_means_identity_is_verified_again(client, make_user, drain, sf):
    u = await make_user("lia", account_type="PROFESSIONAL")
    pro = (await client.post("/v1/professionals", headers=u.h, json={})).json()
    await drain()
    await u.step_up()
    case = (await client.post(f"{V}/cases", headers=u.h,
                              json={"verificationType": "IDENTITY", "subjectType": "PROFESSIONAL", "subjectId": pro["id"]})).json()
    await client.post(f"{V}/cases/{case['id']}/evidence", headers=u.h, json={"evidenceType": "ID_DOCUMENT", "items": [pdf_upload(b"id")]})
    o = await officer(make_user)
    await client.post(f"{V}/cases/{case['id']}/decision", headers=o.h, json={"decision": "VERIFIED", "reasonCode": "DOCUMENT_MATCH"})
    await drain()
    await client.patch("/v1/professionals/me", headers=u.h, json={"legalName": "Someone Else Entirely"})
    await drain()
    identity = await case_of(client, u, pro, "IDENTITY")
    assert identity["status"] == "REVOKED" and identity["reasonCode"] == "NAME_CHANGED"
    screenings = await outbox(sf, E.VERIFICATION_STARTED)
    assert sum(1 for p in screenings if p["verificationType"] == "RESTRICTIONS" and p["subjectId"] == pro["id"]) == 2  # re-screened


async def test_a_withdrawn_credential_leaves_the_queue(client, make_user, drain):
    u = await make_user("wes", account_type="PROFESSIONAL")
    pro = (await client.post("/v1/professionals", headers=u.h, json={})).json()
    await drain()
    claim = (await client.post("/v1/professionals/me/credentials", headers=u.h, json={
        "credentialType": "LICENSE", "name": "CPA", "issuingBody": "State Board", "registrationNumber": "CPA-1",
        "jurisdiction": "us"})).json()
    await drain()
    await client.delete(f"/v1/professionals/me/credentials/{claim['id']}", headers=u.h)
    await drain()
    credential = await case_of(client, u, pro, "CREDENTIAL")
    assert credential["status"] == "FAILED" and credential["reasonCode"] == "WITHDRAWN"


async def test_recovery_codes_replace_a_lost_authenticator_and_wrong_codes_lock(client, make_user, drain):
    u = await make_user("rex")
    await u.enable_mfa()
    codes = u.recovery_codes
    assert len(codes) == 10 and len(set(codes)) == 10
    login = {"email": u.email, "password": u.password}
    ok = await client.post("/v1/auth/login", json={**login, "recoveryCode": codes[0]})
    assert ok.status_code == 200, ok.text
    reused = await client.post("/v1/auth/login", json={**login, "recoveryCode": codes[0]})
    assert reused.status_code == 401 and reused.json()["code"] == "MFA_INVALID"  # one use only

    wrong = pyotp.TOTP(u.totp_secret).at(clock.now().timestamp() + 3600)  # a code from an hour away is never valid now
    for _ in range(4):
        await client.post("/v1/auth/login", json={**login, "totpCode": wrong})
    locked = await client.post("/v1/auth/login", json={**login, "totpCode": u.totp()})
    assert locked.json()["code"] == "ACCOUNT_LOCKED"  # 5 wrong secrets of any kind lock the account for a while


async def test_staff_can_reset_two_step_for_someone_who_lost_everything(client, make_user, drain, sf):
    u = await make_user("lou")
    await u.enable_mfa()
    admin = await make_user("ada", platform_roles=("PLATFORM_ADMIN",))
    await admin.step_up()
    me = (await client.get("/v1/me", headers=admin.h)).json()
    assert (await client.post(f"/v1/admin/identities/{me['id']}/mfa-reset", headers=admin.h,
                              json={"reason": "Checked passport on a video call"})).json()["code"] == "SELF_RESET"
    r = await client.post(f"/v1/admin/identities/{u.id}/mfa-reset", headers=admin.h, json={"reason": "Checked passport on a video call"})
    assert r.status_code == 200, r.text
    assert (await client.post("/v1/auth/login", json={"email": u.email, "password": u.password})).status_code == 200  # no code now
    assert len(await outbox(sf, E.MFA_RESET)) == 1


async def test_a_suspended_account_is_not_listed(client, make_user, drain, sf):
    u, pro = await publish(client, make_user, drain, "sue", headline="Tax adviser", primary="transfer-pricing")
    assert pro["id"] in [i["professionalId"] for i in (await client.get(URL, params={"q": "Tax adviser", "limit": 50})).json()["items"]]
    from zoikorum.domains.identity import service as identity_service
    async with sf() as s, s.begin():
        await identity_service.set_status(s, u.id, "SUSPENDED", "Confirmed duplicate account")
    await drain()
    assert pro["id"] not in [i["professionalId"] for i in (await client.get(URL, params={"q": "Tax adviser", "limit": 50})).json()["items"]]
    assert (await client.get(f"/v1/professionals/{pro['id']}")).status_code == 404


async def test_staff_and_customers_each_sign_in_on_their_own_page(client, make_user):
    customer = await make_user("cam")
    staff = await make_user("stan", platform_roles=("COMPLIANCE_OFFICER",))
    sign_in = lambda u, portal: client.post("/v1/auth/login", json={"email": u.email, "password": u.password, "portal": portal})  # noqa: E731
    refused = await sign_in(customer, "staff")
    assert refused.status_code == 401 and refused.json()["code"] == "NOT_STAFF_ACCOUNT"
    assert (await sign_in(staff, "customer")).json()["code"] == "USE_STAFF_SIGN_IN"
    assert (await sign_in(customer, "customer")).status_code == 200
    assert (await sign_in(staff, "staff")).status_code == 200
    wrong = await client.post("/v1/auth/login", json={"email": staff.email, "password": "not-the-password", "portal": "customer"})
    assert wrong.json()["code"] != "USE_STAFF_SIGN_IN"  # the page check runs only after the password: no hint who is staff


async def test_locally_a_quick_second_resend_still_gives_the_development_link(client, make_user, monkeypatch):
    from zoikorum.config import Settings
    from zoikorum.domains.identity import api as identity_api

    u = await make_user("quick")
    monkeypatch.setattr(identity_api, "get_settings", lambda: Settings(_env_file=None, env="local"))
    await client.post("/v1/me/email-confirmation", headers=u.h)  # a link was just sent (sign-up counts too)
    again = await client.post("/v1/me/email-confirmation", headers=u.h)
    assert again.status_code == 200 and again.json()["emailConfirmationToken"]  # no 60-second wait without an inbox
    confirmed = await client.post("/v1/auth/confirm-email", json={"token": again.json()["emailConfirmationToken"]})
    assert confirmed.status_code == 200 and confirmed.json()["emailConfirmed"] is True
