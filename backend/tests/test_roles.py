"""Step 1 - role-based login: account types, dashboards, role guards, staff roles, password reset."""

from __future__ import annotations

from datetime import timedelta

import pytest
from fastapi import APIRouter, Depends

from zoikorum.shared import clock
from zoikorum.shared.auth import Persona, PlatformRole, require_roles


@pytest.fixture(scope="session", autouse=True)
def _guarded_routes(app):
    """Tiny routes that only exist in tests, to prove the role guard."""
    r = APIRouter(prefix="/test-guard")

    @r.get("/professional", dependencies=[Depends(require_roles(Persona.PROFESSIONAL))])
    async def pro_only() -> dict:
        return {"ok": True}

    @r.get("/buyer-or-enterprise", dependencies=[Depends(require_roles(Persona.BUYER, Persona.ENTERPRISE_ADMIN))])
    async def buyers() -> dict:
        return {"ok": True}

    @r.get("/compliance", dependencies=[Depends(require_roles(PlatformRole.COMPLIANCE_OFFICER))])
    async def compliance() -> dict:
        return {"ok": True}

    app.include_router(r)


@pytest.mark.parametrize(
    "account_type,org,persona,dashboard,mfa_required",
    [
        ("BUYER", None, "BUYER", "buyer", False),
        ("PROFESSIONAL", None, "PROFESSIONAL", "professional", False),
        ("FIRM", "Smith & Co Advisory", "FIRM_ADMIN", "firm", True),
        ("ENTERPRISE", "Acme Corp", "ENTERPRISE_ADMIN", "enterprise", True),
    ],
)
async def test_signup_by_account_type_routes_to_the_right_dashboard(
    client, make_user, account_type, org, persona, dashboard, mfa_required
):
    u = await make_user("x", account_type=account_type, organization=org)
    assert u.user["personas"] == [persona]
    assert u.user["defaultDashboard"] == dashboard
    assert u.user["mfaRequired"] is mfa_required
    assert u.user["organizationName"] == org

    r = await client.post("/v1/auth/login", json={"email": u.email, "password": u.password})
    assert r.status_code == 200
    assert r.json()["user"]["defaultDashboard"] == dashboard


async def test_firm_and_enterprise_signup_require_an_organization_name(client):
    r = await client.post("/v1/auth/register", json={
        "email": "e@example.com", "password": "a-very-long-password", "displayName": "E",
        "country": "US", "accountType": "ENTERPRISE", "acceptTerms": True})
    assert r.status_code == 422


async def test_role_guard_allows_and_blocks_by_account_type(client, make_user):
    buyer = await make_user("buyer", account_type="BUYER")
    pro = await make_user("pro", account_type="PROFESSIONAL")
    ent = await make_user("ent", account_type="ENTERPRISE", organization="Acme")

    assert (await client.get("/test-guard/professional", headers=pro.h)).status_code == 200
    r = await client.get("/test-guard/professional", headers=buyer.h)
    assert r.status_code == 403 and r.json()["code"] == "ROLE_REQUIRED"
    assert "Professional" in r.json()["detail"]

    assert (await client.get("/test-guard/buyer-or-enterprise", headers=buyer.h)).status_code == 200
    assert (await client.get("/test-guard/buyer-or-enterprise", headers=ent.h)).status_code == 200
    assert (await client.get("/test-guard/buyer-or-enterprise", headers=pro.h)).status_code == 403
    assert (await client.get("/test-guard/professional")).status_code == 401  # no token


async def test_buyer_can_also_become_a_professional(client, make_user):
    u = await make_user("dual", account_type="BUYER")
    assert (await client.get("/test-guard/professional", headers=u.h)).status_code == 403
    r = await client.post("/v1/me/account-types", headers=u.h, json={"accountType": "PROFESSIONAL"})
    assert r.status_code == 200
    assert r.json()["user"]["personas"] == ["BUYER", "PROFESSIONAL"]
    u.access = r.json()["tokens"]["accessToken"]
    assert (await client.get("/test-guard/professional", headers=u.h)).status_code == 200
    # Firm/Enterprise admin cannot be self-granted.
    r = await client.post("/v1/me/account-types", headers=u.h, json={"accountType": "ENTERPRISE"})
    assert r.status_code == 422


async def test_staff_roles_need_mfa_session(client, make_user):
    officer = await make_user("officer", platform_roles=(PlatformRole.COMPLIANCE_OFFICER,))
    assert officer.user["defaultDashboard"] == "buyer"  # registered as buyer before promotion
    r = await client.get("/test-guard/compliance", headers=officer.h)
    assert r.status_code == 401 and r.json()["code"] == "STEP_UP_REQUIRED"
    await officer.step_up()  # enables MFA and elevates the session
    assert (await client.get("/test-guard/compliance", headers=officer.h)).status_code == 200
    me = await client.get("/v1/me", headers=officer.h)
    assert me.json()["defaultDashboard"] == "ops" and me.json()["mfaRequired"] is False


async def test_admin_grants_lists_and_revokes_staff_roles(client, make_user):
    admin = await make_user("admin", platform_roles=(PlatformRole.PLATFORM_ADMIN,))
    target = await make_user("analyst")
    await admin.step_up()

    r = await client.get("/v1/admin/identities/lookup", params={"email": target.email}, headers=admin.h)
    assert r.status_code == 200 and r.json()["id"] == str(target.id)

    r = await client.post(f"/v1/admin/identities/{target.id}/platform-roles", headers=admin.h, json={"role": "TS_ANALYST"})
    assert r.status_code == 200 and r.json()["platformRoles"] == ["TS_ANALYST"]

    staff = (await client.get("/v1/admin/staff", headers=admin.h)).json()
    assert {s["email"] for s in staff} == {admin.email, target.email}

    r = await client.delete(f"/v1/admin/identities/{target.id}/platform-roles/TS_ANALYST", headers=admin.h)
    assert r.status_code == 200 and r.json()["platformRoles"] == []
    # Revocation kills the target's sessions so the role disappears immediately.
    assert (await client.post("/v1/auth/refresh", json={"refreshToken": target.refresh_token})).status_code == 401

    r = await client.delete(f"/v1/admin/identities/{admin.id}/platform-roles/PLATFORM_ADMIN", headers=admin.h)
    assert r.status_code == 409 and r.json()["code"] == "SELF_DEMOTION"


async def test_non_admin_cannot_manage_staff(client, make_user):
    officer = await make_user("officer", platform_roles=(PlatformRole.COMPLIANCE_OFFICER,))
    await officer.step_up()
    assert (await client.get("/v1/admin/staff", headers=officer.h)).status_code == 403


async def test_password_reset_is_single_use_and_signs_out_everywhere(client, make_user):
    u = await make_user("forgetful")
    r = await client.post("/v1/auth/password/forgot", json={"email": u.email})
    assert r.status_code == 202
    token = r.json()["resetToken"]
    # Unknown email gets the same answer (no account enumeration) and no token.
    r = await client.post("/v1/auth/password/forgot", json={"email": "nobody@example.com"})
    assert r.status_code == 202 and r.json()["resetToken"] is None

    r = await client.post("/v1/auth/password/reset", json={"token": token, "newPassword": "brand-new-password-42"})
    assert r.status_code == 204
    r = await client.post("/v1/auth/password/reset", json={"token": token, "newPassword": "another-password-4242"})
    assert r.status_code == 422 and r.json()["code"] == "RESET_TOKEN_INVALID"

    assert (await client.post("/v1/auth/refresh", json={"refreshToken": u.refresh_token})).status_code == 401
    assert (await client.post("/v1/auth/login", json={"email": u.email, "password": u.password})).status_code == 401
    r = await client.post("/v1/auth/login", json={"email": u.email, "password": "brand-new-password-42"})
    assert r.status_code == 200


async def test_password_reset_token_expires(client, make_user):
    u = await make_user("slow")
    token = (await client.post("/v1/auth/password/forgot", json={"email": u.email})).json()["resetToken"]
    clock.advance(timedelta(minutes=31))
    r = await client.post("/v1/auth/password/reset", json={"token": token, "newPassword": "brand-new-password-42"})
    assert r.status_code == 422
