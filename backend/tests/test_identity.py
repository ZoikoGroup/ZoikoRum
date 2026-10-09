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
    assert r.status_code == 200 and r.json()["tokens"]["accessToken"]


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


async def test_resend_email_confirmation(client, make_user, drain, sf):
    from sqlalchemy import text

    u = await make_user("erin")
    me = (await client.get("/v1/me", headers=u.h)).json()
    url = "/v1/me/email-confirmation"
    r = await client.post(url, headers=u.h)
    assert r.status_code == 429 and r.json()["code"] == "RESEND_TOO_SOON"  # the sign-up link was just sent
    clock.advance(timedelta(seconds=61))
    r = await client.post(url, headers=u.h)
    assert r.status_code == 200 and r.json()["emailConfirmationToken"]
    assert (await client.post(url, headers=u.h)).json()["code"] == "RESEND_TOO_SOON"  # one link a minute
    await drain()
    async with sf() as s:
        queued = (await s.execute(text("SELECT title, email_status FROM notification.notifications "
                                       "WHERE identity_id = :i AND event_type LIKE '%email_confirmation_requested%'"),
                                  {"i": me["id"]})).all()
    assert [q.title for q in queued] == ["Confirm your email address"]  # emailed by the notification domain

    confirmed = await client.post("/v1/auth/confirm-email", json={"token": r.json()["emailConfirmationToken"]})
    assert confirmed.json()["emailConfirmed"] is True
    clock.advance(timedelta(seconds=61))
    assert (await client.post(url, headers=u.h)).json()["code"] == "EMAIL_ALREADY_CONFIRMED"


async def test_staff_users_list(client, make_user, drain, sf):
    from sqlalchemy import text

    buyer = await make_user("zelda", account_type="BUYER")
    pro = await make_user("zeno-pro", account_type="PROFESSIONAL")
    admin = await make_user("admin", platform_roles=("PLATFORM_ADMIN",))
    url = "/v1/admin/users"
    assert (await client.get(url, headers=buyer.h)).status_code == 403  # staff only

    await admin.step_up()  # staff tools need two-step verification
    found = (await client.get(url, headers=admin.h, params={"q": "ZENO"})).json()["items"]
    assert [u["email"] for u in found] == [pro.email]
    assert found[0]["personas"] == ["PROFESSIONAL"] and found[0]["emailConfirmed"] is False and found[0]["lastSignInAt"]
    pros = (await client.get(url, headers=admin.h, params={"role": "PROFESSIONAL", "limit": 100})).json()["items"]
    assert pro.email in [u["email"] for u in pros] and buyer.email not in [u["email"] for u in pros]
    staff = (await client.get(url, headers=admin.h, params={"role": "STAFF", "limit": 100})).json()["items"]
    assert admin.email in [u["email"] for u in staff] and pro.email not in [u["email"] for u in staff]
    assert (await client.get(url, headers=admin.h, params={"q": "%"})).json()["items"] == []  # % is literal, not "everything"
    assert (await client.get(url, headers=admin.h, params={"role": "NOPE"})).json()["code"] == "INVALID_FILTER"
    await drain()
    async with sf() as s:
        audited = await s.scalar(text("SELECT count(*) FROM audit.audit_records WHERE action LIKE '%users_listed%'"))
    assert audited >= 4  # every staff read of the users list is recorded
