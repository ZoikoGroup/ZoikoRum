"""Single sign-on with OpenID Connect (organisation identity providers, Google) and SCIM provisioning, against a
stand-in identity provider with a real RSA signing key."""

from __future__ import annotations

import time
import uuid
from urllib.parse import parse_qs, urlparse

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from sqlalchemy import select

ISSUER = "https://idp.acme.test"


@pytest.fixture
def idp(monkeypatch):
    from zoikorum.domains.identity import sso

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwk = jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key(), as_dict=True) | {"kid": "k1", "use": "sig", "alg": "RS256"}
    state = {"claims": {}}
    docs = {ISSUER: {"issuer": ISSUER, "authorization_endpoint": f"{ISSUER}/authorize", "token_endpoint": f"{ISSUER}/token",
                     "jwks_uri": f"{ISSUER}/jwks"},
            "https://accounts.google.com": {"issuer": "https://accounts.google.com",
                                            "authorization_endpoint": "https://accounts.google.com/o/oauth2/v2/auth",
                                            "token_endpoint": "https://oauth2.googleapis.com/token", "jwks_uri": f"{ISSUER}/jwks"}}

    async def get_json(url):
        if url.endswith("/.well-known/openid-configuration"):
            return docs[url.rsplit("/.well-known", 1)[0]]
        return {"keys": [jwk]}

    async def post_form(url, data):
        assert data["code_verifier"] and data["redirect_uri"].endswith("/sso/callback")
        claims = {"iat": int(time.time()), "exp": int(time.time()) + 300, "aud": data["client_id"], **state["claims"]}
        return {"id_token": jwt.encode(claims, key, algorithm="RS256", headers={"kid": "k1"}), "access_token": "x"}

    monkeypatch.setattr(sso, "_get_json", get_json)
    monkeypatch.setattr(sso, "_post_form", post_form)
    sso._discovery.clear()
    return state


async def _sign_in(client, sf, idp, start_body, claims, issuer=ISSUER):
    from zoikorum.domains.identity.models import SsoLogin

    url = (await client.post("/v1/auth/sso/start", json=start_body)).json()["url"]
    q = parse_qs(urlparse(url).query)
    assert q["code_challenge_method"] == ["S256"]
    async with sf() as s:
        row = await s.get(SsoLogin, uuid.UUID(q["state"][0]))
    idp["claims"] = {"iss": issuer, "nonce": row.nonce, **claims}
    return await client.post("/v1/auth/sso/callback", json={"code": "abc", "state": q["state"][0]})


async def _enterprise_admin(client, make_user, drain, name, org_name):
    admin = await make_user(name, account_type="ENTERPRISE", organization=org_name)
    await drain()
    await admin.refresh()
    org = (await client.get("/v1/organizations/mine", headers=admin.h)).json()[0]
    await admin.step_up()
    return admin, org


async def test_organisation_sso_jit_enforcement_and_account_safety(client, make_user, drain, sf, idp):
    from zoikorum.domains.identity.models import Identity
    from zoikorum.domains.identity.service import _hasher

    domain = f"acme-{uuid.uuid4().hex[:6]}.example.com"
    admin, org = await _enterprise_admin(client, make_user, drain, "sso-admin", "Acme Ltd")
    cfg = {"issuer": ISSUER, "clientId": "zk-client", "clientSecret": "s3cret", "emailDomains": [domain]}
    r = await client.put(f"/v1/organizations/{org['id']}/sso", headers=admin.h, json=cfg)
    assert r.status_code == 200 and r.json()["configured"] and r.json()["emailDomains"] == [domain]

    signed = await _sign_in(client, sf, idp, {"email": f"nia@{domain}"}, {"sub": "u-nia", "email": f"nia@{domain}", "name": "Nia Obi"})
    assert signed.status_code == 200, signed.text
    nia = signed.json()["user"]
    await drain()
    members = (await client.get(f"/v1/organizations/{org['id']}/members", headers=admin.h)).json()
    assert any(m["email"] == f"nia@{domain}" and "REQUESTER" in m["roles"] for m in members)

    replay = await client.post("/v1/auth/sso/callback", json={"code": "abc", "state": "00000000-0000-0000-0000-000000000000"})
    assert replay.json()["code"] == "SSO_STATE_INVALID"
    bad = await _sign_in(client, sf, idp, {"email": f"nia@{domain}"}, {"sub": "u-nia", "email": f"nia@{domain}"}, issuer="https://evil.test")
    assert bad.json()["code"] == "SSO_INVALID_TOKEN"

    # An account outside the organisation with an address in the domain is never taken over.
    await client.post("/v1/auth/register", json={"email": f"outsider@{domain}", "password": "correct-horse-battery-staple",
                                                  "displayName": "Outsider", "country": "US", "accountType": "BUYER", "acceptTerms": True})
    taken = await _sign_in(client, sf, idp, {"email": f"outsider@{domain}"}, {"sub": "u-out", "email": f"outsider@{domain}"})
    assert taken.json()["code"] == "SSO_ACCOUNT_EXISTS"

    # Enforced: the member's password no longer signs them in.
    await client.put(f"/v1/organizations/{org['id']}/sso", headers=admin.h, json={**cfg, "clientSecret": None, "enforce": True})
    async with sf() as s, s.begin():
        i = await s.scalar(select(Identity).where(Identity.id == uuid.UUID(nia["id"])))
        i.password_hash = _hasher.hash("correct-horse-battery-staple")
    pw = await client.post("/v1/auth/login", json={"email": f"nia@{domain}", "password": "correct-horse-battery-staple"})
    assert pw.json()["code"] == "SSO_REQUIRED"


async def test_scim_provisions_updates_and_removes_members(client, make_user, drain, sf, idp):
    domain = f"scim-{uuid.uuid4().hex[:6]}.example.com"
    admin, org = await _enterprise_admin(client, make_user, drain, "scim-admin", "Scim Co")
    await client.put(f"/v1/organizations/{org['id']}/sso", headers=admin.h,
                     json={"issuer": ISSUER, "clientId": "zk", "clientSecret": "s", "emailDomains": [domain]})
    token = (await client.post(f"/v1/organizations/{org['id']}/sso/scim-token", headers=admin.h)).json()["token"]
    h = {"Authorization": f"Bearer {token}"}
    assert (await client.get("/v1/scim/v2/Users", headers={"Authorization": "Bearer nope"})).status_code == 401

    created = await client.post("/v1/scim/v2/Users", headers=h, json={"userName": f"sam@{domain}", "displayName": "Sam Lee",
                                                                       "roles": [{"value": "APPROVER"}, {"value": "ORG_ADMIN"}]})
    assert created.status_code == 201, created.text
    user = created.json()
    assert user["active"] and [r["value"] for r in user["roles"]] == ["APPROVER"]  # admin is never given by provisioning
    assert (await client.post("/v1/scim/v2/Users", headers=h, json={"userName": "someone@elsewhere.test"})).status_code == 422
    found = (await client.get("/v1/scim/v2/Users", headers=h, params={"filter": f'userName eq "sam@{domain}"'})).json()
    assert found["totalResults"] == 1 and found["Resources"][0]["id"] == user["id"]

    off = await client.patch(f"/v1/scim/v2/Users/{user['id']}", headers=h,
                             json={"Operations": [{"op": "replace", "path": "active", "value": False}]})
    assert off.json()["active"] is False
    on = await client.put(f"/v1/scim/v2/Users/{user['id']}", headers=h, json={"userName": f"sam@{domain}", "active": True})
    assert on.json()["active"] is True
    assert (await client.delete(f"/v1/scim/v2/Users/{user['id']}", headers=h)).status_code == 204
    assert (await client.get(f"/v1/scim/v2/Users/{user['id']}", headers=h)).status_code == 404


async def test_google_sign_in_creates_then_reuses_the_account(client, sf, idp, monkeypatch):
    from zoikorum.config import get_settings

    s = get_settings()
    monkeypatch.setattr(s, "google_client_id", "g-client")
    monkeypatch.setattr(s, "google_client_secret", "g-secret")
    assert (await client.get("/v1/auth/sso/providers")).json() == {"google": True, "microsoft": False}
    email = f"gina-{uuid.uuid4().hex[:6]}@gmail.test"
    claims = {"sub": "g-1", "email": email, "email_verified": True, "name": "Gina"}
    r = await _sign_in(client, sf, idp, {"provider": "google"}, claims, issuer="https://accounts.google.com")
    assert r.status_code == 200 and r.json()["user"]["email"] == email
    again = await _sign_in(client, sf, idp, {"provider": "google"}, claims, issuer="https://accounts.google.com")
    assert again.json()["user"]["id"] == r.json()["user"]["id"]  # the same account, by the linked subject
    assert (await client.post("/v1/auth/sso/start", json={"provider": "microsoft"})).json()["code"] == "PROVIDER_NOT_CONFIGURED"
