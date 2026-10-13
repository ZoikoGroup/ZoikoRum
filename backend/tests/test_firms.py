"""Step 2 - firms: creation at signup, firm profile, members, authorized representative."""

from __future__ import annotations

from urllib.parse import parse_qs, urlparse


def token_of(invitation: dict) -> str:
    return parse_qs(urlparse(invitation["devInviteUrl"]).query)["token"][0]


async def firm_admin(make_user, drain, client):
    admin = await make_user("sam", account_type="FIRM", organization="Smith & Co Advisory LLP")
    await drain()
    await admin.step_up()
    firms = (await client.get("/v1/firms/mine", headers=admin.h)).json()
    return admin, firms[0]


async def test_firm_signup_creates_firm_pending_verification(client, make_user, drain):
    admin, firm = await firm_admin(make_user, drain, client)
    assert firm["legalName"] == "Smith & Co Advisory LLP"
    assert firm["status"] == "PENDING_VERIFICATION" and firm["myRoles"] == ["FIRM_ADMIN"]
    assert firm["hasAuthorizedRepresentative"] is False


async def test_update_firm_profile_with_optimistic_concurrency(client, make_user, drain):
    admin, firm = await firm_admin(make_user, drain, client)
    url = f"/v1/firms/{firm['id']}"
    r = await client.patch(url, headers={**admin.h, "If-Match": str(firm["version"])},
                           json={"tradingName": "Smith Advisory", "registrationNumber": "OC123456", "sizeBand": "6-20"})
    assert r.status_code == 200 and r.json()["sizeBand"] == "6-20" and r.json()["version"] == firm["version"] + 1
    stale = await client.patch(url, headers={**admin.h, "If-Match": str(firm["version"])}, json={"sizeBand": "1-5"})
    assert stale.status_code == 409 and stale.json()["code"] == "VERSION_CONFLICT"


async def test_invite_professional_and_designate_representative(client, make_user, drain):
    admin, firm = await firm_admin(make_user, drain, client)
    pro = await make_user("pat", account_type="BUYER")
    inv = (await client.post(f"/v1/firms/{firm['id']}/invitations", headers=admin.h,
                             json={"email": pro.email, "roles": ["FIRM_MEMBER"]})).json()
    r = await client.post("/v1/firms/invitations/accept", headers=pro.h, json={"token": token_of(inv)})
    assert r.status_code == 200 and r.json()["myRoles"] == ["FIRM_MEMBER"]

    await drain()
    await pro.refresh()
    # Joining a firm makes you a Professional (firm members offer services).
    assert "PROFESSIONAL" in (await client.get("/v1/me", headers=pro.h)).json()["personas"]

    r = await client.patch(f"/v1/firms/{firm['id']}/members/{pro.id}", headers=admin.h,
                           json={"roles": ["FIRM_MEMBER", "AUTHORIZED_REPRESENTATIVE"]})
    assert r.status_code == 200
    assert (await client.get(f"/v1/firms/{firm['id']}", headers=admin.h)).json()["hasAuthorizedRepresentative"] is True


async def test_promoting_to_firm_admin_grants_firm_workspace(client, make_user, drain):
    admin, firm = await firm_admin(make_user, drain, client)
    m = await make_user("max")
    inv = (await client.post(f"/v1/firms/{firm['id']}/invitations", headers=admin.h,
                             json={"email": m.email, "roles": ["FIRM_MEMBER"]})).json()
    await client.post("/v1/firms/invitations/accept", headers=m.h, json={"token": token_of(inv)})
    await client.patch(f"/v1/firms/{firm['id']}/members/{m.id}", headers=admin.h, json={"roles": ["FIRM_ADMIN"]})
    await drain()
    await m.refresh()
    assert "FIRM_ADMIN" in (await client.get("/v1/me", headers=m.h)).json()["personas"]


async def test_firm_member_cannot_manage_and_last_admin_is_protected(client, make_user, drain):
    admin, firm = await firm_admin(make_user, drain, client)
    m = await make_user("mia")
    inv = (await client.post(f"/v1/firms/{firm['id']}/invitations", headers=admin.h,
                             json={"email": m.email, "roles": ["FIRM_MEMBER"]})).json()
    await client.post("/v1/firms/invitations/accept", headers=m.h, json={"token": token_of(inv)})
    await m.step_up()
    r = await client.post(f"/v1/firms/{firm['id']}/invitations", headers=m.h, json={"email": "a@example.com"})
    assert r.status_code == 403
    r = await client.patch(f"/v1/firms/{firm['id']}", headers=m.h, json={"sizeBand": "100+"})
    assert r.status_code == 403
    r = await client.patch(f"/v1/firms/{firm['id']}/members/{admin.id}", headers=admin.h, json={"roles": ["FIRM_MEMBER"]})
    assert r.status_code == 409 and r.json()["code"] == "LAST_ADMIN"
    # A member may leave on their own.
    assert (await client.delete(f"/v1/firms/{firm['id']}/members/{m.id}", headers=m.h)).status_code == 204


async def test_professional_links_to_firm_after_joining_and_unlinks_on_removal(client, make_user, drain):
    """A professional who joins a firm after creating their profile practises under it; leaving ends the link."""
    from test_search import publish

    pro_user, pro = await publish(client, make_user, drain, "ann", headline="Tax adviser", primary="transfer-pricing")
    assert pro["firmId"] is None
    admin, firm = await firm_admin(make_user, drain, client)
    inv = (await client.post(f"/v1/firms/{firm['id']}/invitations", headers=admin.h, json={"email": pro_user.email})).json()
    await client.post("/v1/firms/invitations/accept", headers=pro_user.h, json={"token": token_of(inv)})
    await drain()

    assert (await client.get("/v1/professionals/me", headers=pro_user.h)).json()["firmId"] == firm["id"]
    public = (await client.get(f"/v1/professionals/{pro['id']}")).json()
    assert public["firm"] == {"id": firm["id"], "name": "Smith & Co Advisory LLP", "verified": False}

    # Practise independently, then link again by choice.
    r = await client.put("/v1/professionals/me/firm", headers=pro_user.h, json={"firmId": None})
    assert r.status_code == 200 and r.json()["firmId"] is None
    assert (await client.get(f"/v1/professionals/{pro['id']}")).json()["firm"] is None
    r = await client.put("/v1/professionals/me/firm", headers=pro_user.h, json={"firmId": firm["id"]})
    assert r.json()["firmId"] == firm["id"]

    # Only firms you belong to; removal from the firm ends the link.
    other_admin = await make_user("oz", account_type="FIRM", organization="Other Partners")
    await drain()
    other = (await client.get("/v1/firms/mine", headers=other_admin.h)).json()[0]
    r = await client.put("/v1/professionals/me/firm", headers=pro_user.h, json={"firmId": other["id"]})
    assert r.status_code == 403 and r.json()["code"] == "NOT_FIRM_MEMBER"
    assert (await client.delete(f"/v1/firms/{firm['id']}/members/{pro_user.id}", headers=admin.h)).status_code == 204
    await drain()
    assert (await client.get("/v1/professionals/me", headers=pro_user.h)).json()["firmId"] is None
