"""Step 2 - enterprise organizations: creation at signup, team invitations, roles, spend authority."""

from __future__ import annotations

from datetime import timedelta
from urllib.parse import parse_qs, urlparse

from zoikorum.domains.buyer import facade as buyer_facade
from zoikorum.shared import clock


def token_of(invitation: dict) -> str:
    return parse_qs(urlparse(invitation["devInviteUrl"]).query)["token"][0]


async def enterprise_admin(make_user, drain, client):
    admin = await make_user("dana", account_type="ENTERPRISE", organization="Acme Corp")
    await drain()  # IDENTITY_CREATED -> organization created
    await admin.step_up()  # admins must use MFA; team changes need an MFA session
    orgs = (await client.get("/v1/organizations/mine", headers=admin.h)).json()
    return admin, orgs[0]


async def test_enterprise_signup_creates_org_with_admin_roles(client, make_user, drain):
    admin, org = await enterprise_admin(make_user, drain, client)
    assert org["name"] == "Acme Corp" and org["orgType"] == "ENTERPRISE"
    assert org["myRoles"] == ["APPROVER", "BUDGET_OWNER", "ORG_ADMIN", "REQUESTER"]
    assert "EXCEPTION_AUTHORITY" not in org["myRoles"]  # role separation: granted deliberately


async def test_buyer_signup_creates_individual_org_with_all_roles(client, make_user, drain):
    buyer = await make_user("bo", account_type="BUYER")
    await drain()
    orgs = (await client.get("/v1/organizations/mine", headers=buyer.h)).json()
    assert len(orgs) == 1 and orgs[0]["orgType"] == "INDIVIDUAL" and len(orgs[0]["myRoles"]) == 6
    # Individual accounts cannot invite a team.
    await buyer.step_up()
    r = await client.post(f"/v1/organizations/{orgs[0]['id']}/invitations", headers=buyer.h,
                          json={"email": "x@example.com", "roles": ["APPROVER"]})
    assert r.status_code == 409 and r.json()["code"] == "INDIVIDUAL_ORG"


async def test_invite_accept_and_roles_reach_the_token(client, make_user, drain):
    admin, org = await enterprise_admin(make_user, drain, client)
    approver = await make_user("ann", account_type="BUYER")
    r = await client.post(f"/v1/organizations/{org['id']}/invitations", headers=admin.h, json={
        "email": approver.email, "roles": ["APPROVER", "REQUESTER"],
        "spendLimit": {"amountMinor": 50_000_00, "currency": "USD"}})
    assert r.status_code == 201, r.text
    inv = r.json()
    assert inv["status"] == "PENDING" and inv["devInviteUrl"]

    # The invitee sees it in their inbox and accepts with the emailed link.
    mine = (await client.get("/v1/organizations/invitations/mine", headers=approver.h)).json()
    assert [i["id"] for i in mine] == [inv["id"]]
    r = await client.post("/v1/organizations/invitations/accept", headers=approver.h, json={"token": token_of(inv)})
    assert r.status_code == 200 and r.json()["myRoles"] == ["APPROVER", "REQUESTER"]

    await drain()
    await approver.refresh()
    me = (await client.get("/v1/me", headers=approver.h)).json()
    assert "ENTERPRISE_MEMBER" in me["personas"]
    assert any(l["targetId"] == org["id"] and l["roles"] == ["APPROVER", "REQUESTER"] for l in me["links"])

    members = (await client.get(f"/v1/organizations/{org['id']}/members", headers=approver.h)).json()
    assert {m["email"] for m in members} == {admin.email, approver.email}
    async with __import__("zoikorum.shared.db", fromlist=["x"]).session_factory()() as s:
        limit = await buyer_facade.get_member_spend_limit(s, org["id"], approver.id)
    assert limit.minor == 50_000_00 and limit.currency == "USD"


async def test_invitation_is_bound_to_the_invited_email(client, make_user, drain):
    admin, org = await enterprise_admin(make_user, drain, client)
    inv = (await client.post(f"/v1/organizations/{org['id']}/invitations", headers=admin.h,
                             json={"email": "someone.else@example.com", "roles": ["REQUESTER"]})).json()
    intruder = await make_user("eve")
    r = await client.post("/v1/organizations/invitations/accept", headers=intruder.h, json={"token": token_of(inv)})
    assert r.status_code == 403 and r.json()["code"] == "INVITATION_EMAIL_MISMATCH"


async def test_accepting_from_inbox_requires_confirmed_email(client, make_user, drain):
    admin, org = await enterprise_admin(make_user, drain, client)
    u = await make_user("unconfirmed")
    inv = (await client.post(f"/v1/organizations/{org['id']}/invitations", headers=admin.h,
                             json={"email": u.email, "roles": ["REQUESTER"]})).json()
    r = await client.post(f"/v1/organizations/invitations/{inv['id']}/accept", headers=u.h)
    assert r.status_code == 403 and r.json()["code"] == "EMAIL_NOT_CONFIRMED"
    await client.post("/v1/auth/confirm-email", json={"token": u.confirm_token})
    r = await client.post(f"/v1/organizations/invitations/{inv['id']}/accept", headers=u.h)
    assert r.status_code == 200


async def test_expired_and_revoked_invitations_cannot_be_used(client, make_user, drain):
    admin, org = await enterprise_admin(make_user, drain, client)
    u = await make_user("late")
    inv = (await client.post(f"/v1/organizations/{org['id']}/invitations", headers=admin.h,
                             json={"email": u.email, "roles": ["REQUESTER"]})).json()
    clock.advance(timedelta(days=8))
    r = await client.post("/v1/organizations/invitations/accept", headers=u.h, json={"token": token_of(inv)})
    assert r.status_code == 409 and r.json()["code"] == "INVITATION_EXPIRED"

    clock.set_now(None)
    await admin.step_up()
    inv2 = (await client.post(f"/v1/organizations/{org['id']}/invitations", headers=admin.h,
                              json={"email": u.email, "roles": ["REQUESTER"]})).json()
    assert (await client.delete(f"/v1/organizations/{org['id']}/invitations/{inv2['id']}", headers=admin.h)).status_code == 204
    r = await client.post("/v1/organizations/invitations/accept", headers=u.h, json={"token": token_of(inv2)})
    assert r.status_code == 409 and r.json()["code"] == "INVITATION_NOT_PENDING"


async def test_only_org_admin_with_mfa_manages_the_team(client, make_user, drain):
    admin, org = await enterprise_admin(make_user, drain, client)
    member = await make_user("req")
    inv = (await client.post(f"/v1/organizations/{org['id']}/invitations", headers=admin.h,
                             json={"email": member.email, "roles": ["REQUESTER"]})).json()
    await client.post("/v1/organizations/invitations/accept", headers=member.h, json={"token": token_of(inv)})

    # A Requester cannot invite or change roles.
    await member.step_up()
    r = await client.post(f"/v1/organizations/{org['id']}/invitations", headers=member.h,
                          json={"email": "x@example.com", "roles": ["ORG_ADMIN"]})
    assert r.status_code == 403 and r.json()["code"] == "ORG_ROLE_REQUIRED"

    # An admin session without MFA must step up.
    r = await client.post("/v1/auth/login", json={"email": admin.email, "password": admin.password, "totpCode": admin.totp()})
    pwd_only = await make_user("x2", account_type="ENTERPRISE", organization="Other Co")
    await drain()
    other = (await client.get("/v1/organizations/mine", headers=pwd_only.h)).json()[0]
    r = await client.post(f"/v1/organizations/{other['id']}/invitations", headers=pwd_only.h,
                          json={"email": "y@example.com", "roles": ["REQUESTER"]})
    assert r.status_code == 401 and r.json()["code"] == "STEP_UP_REQUIRED"

    # Outsiders cannot even see the organization.
    assert (await client.get(f"/v1/organizations/{org['id']}", headers=pwd_only.h)).status_code == 404


async def test_role_change_spend_limit_and_last_admin_protection(client, make_user, drain):
    admin, org = await enterprise_admin(make_user, drain, client)
    m = await make_user("bob")
    inv = (await client.post(f"/v1/organizations/{org['id']}/invitations", headers=admin.h,
                             json={"email": m.email, "roles": ["REQUESTER"]})).json()
    await client.post("/v1/organizations/invitations/accept", headers=m.h, json={"token": token_of(inv)})

    url = f"/v1/organizations/{org['id']}/members"
    r = await client.patch(f"{url}/{m.id}", headers=admin.h, json={
        "roles": ["APPROVER", "EXCEPTION_AUTHORITY"], "spendLimit": {"amountMinor": 1_000_000, "currency": "USD"}})
    assert r.status_code == 200 and r.json()["roles"] == ["APPROVER", "EXCEPTION_AUTHORITY"]
    assert r.json()["spendLimit"] == {"amountMinor": 1_000_000, "currency": "USD"}

    # The only Org Admin cannot demote or remove themselves.
    r = await client.patch(f"{url}/{admin.id}", headers=admin.h, json={"roles": ["REQUESTER"]})
    assert r.status_code == 409 and r.json()["code"] == "LAST_ADMIN"
    assert (await client.delete(f"{url}/{admin.id}", headers=admin.h)).json()["code"] == "LAST_ADMIN"

    # Removing a member drops their access and their enterprise workspace.
    assert (await client.delete(f"{url}/{m.id}", headers=admin.h)).status_code == 204
    assert (await client.get(f"/v1/organizations/{org['id']}", headers=m.h)).status_code == 404
    await drain()
    await m.refresh()
    assert "ENTERPRISE_MEMBER" not in (await client.get("/v1/me", headers=m.h)).json()["personas"]


async def test_business_units_and_cost_centers(client, make_user, drain):
    admin, org = await enterprise_admin(make_user, drain, client)
    base = f"/v1/organizations/{org['id']}"
    bu = await client.post(f"{base}/business-units", headers=admin.h, json={"name": "Finance"})
    assert bu.status_code == 201
    cc = await client.post(f"{base}/cost-centers", headers=admin.h, json={
        "name": "FP&A", "code": "FIN-100", "businessUnitId": bu.json()["id"],
        "quarterlyBudget": {"amountMinor": 250_000_00, "currency": "USD"}})
    assert cc.status_code == 201 and cc.json()["quarterlyBudget"]["amountMinor"] == 250_000_00
    dup = await client.post(f"{base}/cost-centers", headers=admin.h, json={"name": "Dup", "code": "FIN-100"})
    assert dup.status_code == 409
    assert len((await client.get(f"{base}/cost-centers", headers=admin.h)).json()) == 1


async def test_team_events_are_audited(client, make_user, drain, sf):
    from sqlalchemy import text

    admin, org = await enterprise_admin(make_user, drain, client)
    await client.post(f"/v1/organizations/{org['id']}/invitations", headers=admin.h,
                      json={"email": "z@example.com", "roles": ["LEGAL_REVIEWER"]})
    await drain()
    async with sf() as s:
        actions = set((await s.execute(text("SELECT action FROM audit.audit_records"))).scalars().all())
    assert {"zoikorum.buyer.organization.created.v1", "zoikorum.buyer.organization.member_added.v1",
            "zoikorum.buyer.organization.member_invited.v1"} <= actions
