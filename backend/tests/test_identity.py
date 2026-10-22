from __future__ import annotations

from datetime import timedelta

from approvalhelp import approved
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
    checker = await make_user("checker", platform_roles=("PLATFORM_ADMIN",))
    target = await make_user("target")
    url = f"/v1/admin/identities/{target.id}/platform-roles"
    body = {"role": "MEDIATOR", "justification": "Covers mediation while the team is short"}
    r = await client.post(url, headers=target.h, json=body)
    assert r.status_code == 403
    r = await client.post(url, headers=admin.h, json=body)
    assert r.status_code == 401 and r.json()["code"] == "STEP_UP_REQUIRED"
    await admin.step_up()
    r = await client.post(url, headers=admin.h, json=body)
    assert r.status_code == 202 and r.json()["status"] == "REQUESTED"  # nothing granted yet
    assert (await client.get("/v1/admin/identities/lookup", params={"email": target.email}, headers=admin.h)).json()["platformRoles"] == []
    assert "MEDIATOR" in (await approved(client, r, checker))["result"]["platformRoles"]


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


async def test_an_authenticator_code_works_only_once(client, make_user):
    """RFC 6238 s.5.2: a code seen over someone's shoulder or replayed cannot be used again, even within its window."""
    u = await make_user("otto")
    await u.enable_mfa()
    code = u.totp()
    first = await client.post("/v1/auth/step-up", headers=u.h, json={"totpCode": code})
    assert first.status_code == 200
    again = await client.post("/v1/auth/step-up", headers=u.h, json={"totpCode": code})
    assert again.status_code in (400, 401) and again.json()["code"] == "MFA_INVALID" and "already used" in again.json()["detail"]
    assert (await client.post("/v1/auth/step-up", headers=u.h, json={"totpCode": u.totp()})).status_code == 200  # the next code works


async def test_the_web_app_keeps_its_refresh_token_in_an_httponly_cookie(client, make_user):
    """Page scripts cannot read the refresh token: it is set as an HttpOnly cookie for /v1/auth only and never put in a
    response body for the web app. API clients without the header keep the token in the body."""
    u = await make_user("cora")
    web = {"X-Zk-Client": "web"}
    r = await client.post("/v1/auth/login", headers=web, json={"email": u.email, "password": u.password})
    assert r.status_code == 200 and r.json()["tokens"]["refreshToken"] == "" and r.json()["tokens"]["accessToken"]
    cookie = r.headers["set-cookie"]
    assert cookie.startswith("zk_refresh=") and "HttpOnly" in cookie and "Path=/v1/auth" in cookie and "SameSite=strict" in cookie

    # The cookie alone refreshes, and the rotated token is again only in the cookie.
    r = await client.post("/v1/auth/refresh", headers=web, json={})
    assert r.status_code == 200 and r.json()["refreshToken"] == "" and r.json()["accessToken"]
    assert "zk_refresh=" in r.headers["set-cookie"]
    access = r.json()["accessToken"]

    # Signing out deletes the cookie; a refresh then has nothing to work with.
    r = await client.post("/v1/auth/logout", headers={**web, "Authorization": f"Bearer {access}"})
    assert r.status_code == 204 and 'zk_refresh=""' in r.headers["set-cookie"]
    client.cookies.clear()
    r = await client.post("/v1/auth/refresh", headers=web, json={})
    assert r.status_code == 401 and r.json()["code"] == "SESSION_EXPIRED"

    # Other API clients: the token stays in the body and no cookie is set.
    r = await client.post("/v1/auth/login", json={"email": u.email, "password": u.password})
    assert r.json()["tokens"]["refreshToken"] and "set-cookie" not in r.headers


async def test_a_sign_in_from_a_new_device_is_announced(client, make_user, drain):
    u = await make_user("nina")
    chrome = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/130.0 Safari/537.36"}
    iphone = {"User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 Safari/604.1"}
    login = {"email": u.email, "password": u.password}
    await client.post("/v1/auth/login", headers=chrome, json=login)
    await client.post("/v1/auth/login", headers=chrome, json=login)  # same device again: no alert
    await client.post("/v1/auth/login", headers=iphone, json=login)
    await drain()
    alerts = [n for n in (await client.get("/v1/notifications", headers=u.h)).json()["items"] if n["title"] == "New sign-in to your account"]
    assert len(alerts) == 2  # Chrome on Windows (first after sign-up) and Safari on iPhone
    assert any("Safari on iPhone" in n["body"] for n in alerts) and all("change your password" in n["body"] for n in alerts)
