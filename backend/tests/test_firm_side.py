"""Firm side: verified authorized representative, firm credentials, the firm's work overview, and what buyers see."""

from __future__ import annotations

from test_firms import firm_admin, token_of
from test_search import URL, pdf, publish


async def officer(make_user, name):
    o = await make_user(name, platform_roles=("COMPLIANCE_OFFICER",))
    await o.step_up()
    return o


async def verify(client, make_user, drain, owner, subject_type, subject_id, verification_type, evidence_type):
    r = await client.post("/v1/verification/cases", headers=owner.h, json={
        "verificationType": verification_type, "subjectType": subject_type, "subjectId": subject_id})
    assert r.status_code < 300, r.text
    case = r.json()
    await client.post(f"/v1/verification/cases/{case['id']}/evidence", headers=owner.h,
                      json={"evidenceType": evidence_type, "items": [pdf("doc.pdf")]})
    o = await officer(make_user, f"officer-{case['id'][:6]}")
    r = await client.post(f"/v1/verification/cases/{case['id']}/decision", headers=o.h, json={"decision": "VERIFIED", "reasonCode": "OK"})
    assert r.status_code == 200, r.text
    await drain()


async def join(client, drain, admin, firm, user, roles=("FIRM_MEMBER",)):
    inv = (await client.post(f"/v1/firms/{firm['id']}/invitations", headers=admin.h, json={"email": user.email, "roles": list(roles)})).json()
    assert (await client.post("/v1/firms/invitations/accept", headers=user.h, json={"token": token_of(inv)})).status_code == 200
    await drain()


async def test_representative_counts_only_once_their_own_identity_is_verified(client, make_user, drain):
    admin, firm = await firm_admin(make_user, drain, client)
    rep = await make_user("rob")
    await join(client, drain, admin, firm, rep, roles=("FIRM_MEMBER", "AUTHORIZED_REPRESENTATIVE"))
    got = (await client.get(f"/v1/firms/{firm['id']}", headers=admin.h)).json()
    assert got["hasAuthorizedRepresentative"] is True and got["hasVerifiedRepresentative"] is False
    assert got["representatives"] == [{"identityId": str(rep.id), "displayName": "Rob", "identityVerified": False}]

    # Only the person can start their own identity check, and only an identity check; a firm cannot run personal checks.
    person = {"verificationType": "IDENTITY", "subjectType": "IDENTITY", "subjectId": str(rep.id)}
    assert (await client.post("/v1/verification/cases", headers=admin.h, json=person)).status_code == 403
    wrong = await client.post("/v1/verification/cases", headers=rep.h, json={**person, "verificationType": "INSURANCE"})
    assert wrong.status_code == 422 and wrong.json()["code"] == "WRONG_SUBJECT_TYPE"
    firm_identity = await client.post("/v1/verification/cases", headers=admin.h, json={
        "verificationType": "IDENTITY", "subjectType": "FIRM", "subjectId": firm["id"]})
    assert firm_identity.status_code == 422

    await verify(client, make_user, drain, rep, "IDENTITY", str(rep.id), "IDENTITY", "ID_DOCUMENT")
    got = (await client.get(f"/v1/firms/{firm['id']}", headers=admin.h)).json()
    assert got["hasVerifiedRepresentative"] is True and got["representatives"][0]["identityVerified"] is True
    assert [c["verificationType"] for c in (await client.get(f"/v1/verification/subjects/IDENTITY/{rep.id}", headers=rep.h)).json()] == ["IDENTITY"]


async def test_firm_credentials_overview_public_page_and_search(client, make_user, drain):
    pro_user, pro = await publish(client, make_user, drain, "ann", headline="Transfer pricing adviser", primary="transfer-pricing")
    admin, firm = await firm_admin(make_user, drain, client)
    await join(client, drain, admin, firm, pro_user)

    # The firm's own credentials: a licence for a country and indemnity insurance.
    for body in ({"verificationType": "JURISDICTION", "jurisdiction": "GB"}, {"verificationType": "INSURANCE"}):
        r = await client.post("/v1/verification/cases", headers=admin.h, json={**body, "subjectType": "FIRM", "subjectId": firm["id"]})
        assert r.status_code < 300, r.text

    overview = await client.get(f"/v1/firms/{firm['id']}/overview", headers=admin.h)
    assert overview.status_code == 200, overview.text
    work = overview.json()
    assert [p["professionalId"] for p in work["professionals"]] == [pro["id"]]
    assert work["openRequests"] == work["activeContracts"] == 0 and work["money"] == []
    await pro_user.step_up()
    assert (await client.get(f"/v1/firms/{firm['id']}/overview", headers=pro_user.h)).status_code == 403
    outsider = await make_user("otto")
    assert (await client.get(f"/v1/firms/{firm['id']}/overview", headers=outsider.h)).status_code == 404

    public = (await client.get(f"/v1/firms/{firm['id']}/public")).json()
    assert public["name"] == "Smith & Co Advisory LLP" and public["verified"] is False
    assert [p["professionalId"] for p in public["professionals"]] == [pro["id"]]
    assert "registrationNumber" not in public

    def firm_on_result():
        return next(r["firm"] for r in results["items"] if r["professionalId"] == pro["id"])
    results = (await client.get(URL, params={"q": "transfer pricing"})).json()
    assert firm_on_result() == {"id": firm["id"], "name": "Smith & Co Advisory LLP", "verified": False}

    await verify(client, make_user, drain, admin, "FIRM", firm["id"], "FIRM_REGISTRATION", "REGISTRATION_DOCUMENT")
    assert (await client.get(f"/v1/firms/{firm['id']}/public")).json()["verified"] is True
    results = (await client.get(URL, params={"q": "transfer pricing"})).json()
    assert firm_on_result()["verified"] is True


async def test_overview_counts_contracts_and_money_per_currency(client, make_user, drain):
    from test_dispute import funded_contract

    pro_user, pro, buyer, c = await funded_contract(client, make_user, drain)
    admin, firm = await firm_admin(make_user, drain, client)
    await join(client, drain, admin, firm, pro_user)
    work = (await client.get(f"/v1/firms/{firm['id']}/overview", headers=admin.h)).json()
    row = next(p for p in work["professionals"] if p["professionalId"] == pro["id"])
    assert row["activeContracts"] == work["activeContracts"] == 1
    held = {m["currency"]: m["heldMinor"] for m in work["money"]}
    assert held[c["milestones"][0]["amount"]["currency"]] > 0
