from __future__ import annotations

from datetime import timedelta

from zoikorum.shared import clock


async def test_register_login_and_me(client, make_user):
    u = await make_user("alice")
    r = await client.get("/v1/me", headers=u.h)
    assert r.status_code == 200
    assert r.json()["email"] == u.email and r.json()["emailConfirmed"] is False

    r = await client.post("/v1/auth/confirm-email", json={"token": u.confirm_token})
    assert r.status_code == 200 and r.json()["emailConfirmed"] is True

    r = await client.post("/v1/auth/login", json={"email": u.email, "password": u.password})
    assert r.status_code == 200 and r.json()["accessToken"]


async def test_duplicate_email_and_short_password_rejected(client, make_user):
    u = await make_user("bob")
    r = await client.post("/v1/auth/register", json={
        "email": u.email, "password": "another-long-password", "displayName": "B", "country": "US", "acceptTerms": True})
    assert r.status_code == 409 and r.json()["code"] == "EMAIL_TAKEN"
    r = await client.post("/v1/auth/register", json={
        "email": "x@example.com", "password": "short", "displayName": "B", "country": "US", "acceptTerms": True})
    assert r.status_code == 422
    assert r.headers["content-type"].startswith("application/problem+json")


async def test_lockout_after_repeated_failures_persists(client, make_user):
    u = await make_user("carol")
    for _ in range(5):
        r = await client.post("/v1/auth/login", json={"email": u.email, "password": "wrong-password-123"})
        assert r.status_code == 401
    r = await client.post("/v1/auth/login", json={"email": u.email, "password": u.password})
    assert r.status_code == 401 and r.json()["code"] == "ACCOUNT_LOCKED"
    clock.advance(timedelta(minutes=16))
    r = await client.post("/v1/auth/login", json={"email": u.email, "password": u.password})
    assert r.status_code == 200


async def test_refresh_rotation_and_reuse_revokes_family(client, make_user):
    u = await make_user("dave")
    old = u.refresh_token
    await u.refresh()
    r = await client.post("/v1/auth/refresh", json={"refreshToken": old})
    assert r.status_code == 401 and r.json()["code"] == "REFRESH_REUSE"
    # The legitimately rotated token is now revoked too (whole family).
    r = await client.post("/v1/auth/refresh", json={"refreshToken": u.refresh_token})
    assert r.status_code == 401


async def test_mfa_login_and_step_up(client, make_user):
    u = await make_user("erin")
    await u.enable_mfa()
    r = await client.post("/v1/auth/login", json={"email": u.email, "password": u.password})
    assert r.status_code == 401 and r.json()["code"] == "MFA_REQUIRED"
    r = await client.post("/v1/auth/login", json={"email": u.email, "password": u.password, "totpCode": u.totp()})
    assert r.status_code == 200
    await u.step_up()
    assert (await client.get("/v1/me", headers=u.h)).status_code == 200


async def test_platform_role_grant_requires_admin_and_step_up(client, make_user):
    admin = await make_user("admin", platform_roles=("PLATFORM_ADMIN",))
    target = await make_user("target")
    url = f"/v1/admin/identities/{target.id}/platform-roles"
    r = await client.post(url, headers=target.h, json={"role": "MEDIATOR"})
    assert r.status_code == 403
    r = await client.post(url, headers=admin.h, json={"role": "MEDIATOR"})
    assert r.status_code == 401 and r.json()["code"] == "STEP_UP_REQUIRED"
    await admin.step_up()
    r = await client.post(url, headers=admin.h, json={"role": "MEDIATOR"})
    assert r.status_code == 200 and "MEDIATOR" in r.json()["platformRoles"]
