"""SCIM 2.0 Groups (identity/scim.py): create, list, patch and delete groups; group membership maps to organisation
roles, never to Organisation Admin; a role managed by groups goes when the person leaves the last such group."""

from __future__ import annotations

import uuid

ISSUER = "https://idp.acme.test"


async def _setup(client, make_user, drain, monkeypatch):
    from zoikorum.domains.identity import sso

    async def get_json(url):
        return {"issuer": ISSUER, "authorization_endpoint": f"{ISSUER}/a", "token_endpoint": f"{ISSUER}/t", "jwks_uri": f"{ISSUER}/k"}

    monkeypatch.setattr(sso, "_get_json", get_json)
    sso._discovery.clear()
    domain = f"grp-{uuid.uuid4().hex[:6]}.example.com"
    admin = await make_user("grp-admin", account_type="ENTERPRISE", organization="Group Co")
    await drain()
    await admin.refresh()
    org = (await client.get("/v1/organizations/mine", headers=admin.h)).json()[0]
    await admin.step_up()
    r = await client.put(f"/v1/organizations/{org['id']}/sso", headers=admin.h, json={
        "issuer": ISSUER, "clientId": "zk", "clientSecret": "s", "emailDomains": [domain],
        "groupRoleMap": {"Finance approvers": "APPROVER"}})
    assert r.status_code == 200, r.text
    token = (await client.post(f"/v1/organizations/{org['id']}/sso/scim-token", headers=admin.h)).json()["token"]
    return admin, org, domain, {"Authorization": f"Bearer {token}"}


async def _roles(client, admin, org, email):
    members = (await client.get(f"/v1/organizations/{org['id']}/members", headers=admin.h)).json()
    return sorted(next(m["roles"] for m in members if m["email"] == email))


async def test_scim_groups_map_membership_to_roles(client, make_user, drain, monkeypatch):
    admin, org, domain, h = await _setup(client, make_user, drain, monkeypatch)
    users = []
    for name in ("ana", "ben"):
        r = await client.post("/v1/scim/v2/Users", headers=h, json={"userName": f"{name}@{domain}", "displayName": name.title()})
        assert r.status_code == 201, r.text
        users.append(r.json())
    ana, ben = users
    assert (await client.get("/v1/scim/v2/Groups", headers={"Authorization": "Bearer nope"})).status_code == 401

    g = await client.post("/v1/scim/v2/Groups", headers=h, json={"displayName": "Finance approvers", "externalId": "g-1",
                                                                  "members": [{"value": ana["id"]}]})
    assert g.status_code == 201, g.text
    group = g.json()
    assert group["urn:zoikorum:scim:Group"]["role"] == "APPROVER" and [m["value"] for m in group["members"]] == [ana["id"]]
    assert await _roles(client, admin, org, f"ana@{domain}") == ["APPROVER", "REQUESTER"]

    # A group named after a role maps to it; ORG_ADMIN never does.
    legal = (await client.post("/v1/scim/v2/Groups", headers=h, json={"displayName": "Legal Reviewer", "members": [{"value": ben["id"]}]})).json()
    admins = (await client.post("/v1/scim/v2/Groups", headers=h, json={"displayName": "ORG_ADMIN", "members": [{"value": ben["id"]}]})).json()
    assert legal["urn:zoikorum:scim:Group"]["role"] == "LEGAL_REVIEWER" and admins["urn:zoikorum:scim:Group"]["role"] is None
    assert await _roles(client, admin, org, f"ben@{domain}") == ["LEGAL_REVIEWER", "REQUESTER"]
    assert (await client.post("/v1/scim/v2/Groups", headers=h, json={"displayName": "Legal Reviewer"})).status_code == 409
    outsider = await client.post("/v1/scim/v2/Groups", headers=h, json={"displayName": "X", "members": [{"value": str(uuid.uuid4())}]})
    assert outsider.status_code == 422

    listed = (await client.get("/v1/scim/v2/Groups", headers=h, params={"filter": 'displayName eq "Finance approvers"'})).json()
    assert listed["totalResults"] == 1 and listed["Resources"][0]["id"] == group["id"]
    assert (await client.get(f"/v1/scim/v2/Groups/{group['id']}", headers=h)).json()["externalId"] == "g-1"

    # PATCH: add Ben, remove Ana (by filter path) - Ana loses the group-managed APPROVER role, Ben gains it.
    p = await client.patch(f"/v1/scim/v2/Groups/{group['id']}", headers=h, json={"Operations": [
        {"op": "add", "path": "members", "value": [{"value": ben["id"]}]},
        {"op": "remove", "path": f'members[value eq "{ana["id"]}"]'}]})
    assert p.status_code == 200, p.text
    assert [m["value"] for m in p.json()["members"]] == [ben["id"]]
    assert await _roles(client, admin, org, f"ana@{domain}") == ["REQUESTER"]
    assert await _roles(client, admin, org, f"ben@{domain}") == ["APPROVER", "LEGAL_REVIEWER", "REQUESTER"]

    # PUT replaces the members; DELETE removes the group and the role it gave.
    put = await client.put(f"/v1/scim/v2/Groups/{legal['id']}", headers=h, json={"displayName": "Legal Reviewer", "members": []})
    assert put.json()["members"] == []
    assert await _roles(client, admin, org, f"ben@{domain}") == ["APPROVER", "REQUESTER"]
    assert (await client.delete(f"/v1/scim/v2/Groups/{group['id']}", headers=h)).status_code == 204
    assert (await client.get(f"/v1/scim/v2/Groups/{group['id']}", headers=h)).status_code == 404
    assert await _roles(client, admin, org, f"ben@{domain}") == ["REQUESTER"]  # back to the default role
