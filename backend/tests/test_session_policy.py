"""Enterprise session policy (identity/session_policy.py): an organisation's idle timeout, maximum session age, two-step
requirement and allowed sign-in methods are inherited by its members' sessions and applied when they refresh."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from zoikorum.shared import clock


async def _admin(client, make_user, drain):
    admin = await make_user("policy-admin", account_type="ENTERPRISE", organization="Policy Co")
    await drain()
    await admin.refresh()
    org = (await client.get("/v1/organizations/mine", headers=admin.h)).json()[0]
    await admin.step_up()
    return admin, org


async def _refresh(client, user):
    r = await client.post("/v1/auth/refresh", json={"refreshToken": user.refresh_token})
    if r.status_code == 200:
        user.access, user.refresh_token = r.json()["accessToken"], r.json()["refreshToken"]
    return r


async def test_idle_timeout_and_max_age_end_member_sessions(client, make_user, drain):
    admin, org = await _admin(client, make_user, drain)
    other = await make_user("not-a-member")
    assert (await client.get(f"/v1/organizations/{org['id']}/session-policy", headers=other.h)).status_code == 403
    r = await client.put(f"/v1/organizations/{org['id']}/session-policy", headers=admin.h,
                         json={"idleTimeoutSeconds": 600, "maxSessionSeconds": 3600, "requireMfa": True})
    assert r.status_code == 200, r.text
    assert (await client.get(f"/v1/organizations/{org['id']}/session-policy", headers=admin.h)).json()["idleTimeoutSeconds"] == 600

    start = datetime.now(timezone.utc)
    clock.set_now(start + timedelta(minutes=5))
    assert (await _refresh(client, admin)).status_code == 200  # active, two-step session: fine
    clock.set_now(start + timedelta(minutes=20))  # 15 minutes since the last refresh
    idle = await _refresh(client, admin)
    assert idle.status_code == 401 and idle.json()["code"] == "SESSION_IDLE_TIMEOUT"
    assert (await _refresh(client, admin)).status_code == 401  # the whole family was revoked

    # A fresh sign-in, refreshed every 9 minutes, still ends at the maximum age.
    clock.set_now(None)
    login = await client.post("/v1/auth/login", json={"email": admin.email, "password": admin.password, "totpCode": admin.totp()})
    assert login.status_code == 200, login.text
    admin.access, admin.refresh_token = login.json()["tokens"]["accessToken"], login.json()["tokens"]["refreshToken"]
    t = datetime.now(timezone.utc)
    for i in range(1, 7):
        clock.set_now(t + timedelta(minutes=9 * i))
        r = await _refresh(client, admin)
        if r.status_code != 200:
            break
    assert r.json()["code"] == "SESSION_MAX_AGE" and 9 * i > 60


async def test_allowed_sign_in_methods(client, make_user, drain):
    admin, org = await _admin(client, make_user, drain)
    await client.put(f"/v1/organizations/{org['id']}/session-policy", headers=admin.h, json={"allowedIdps": ["SAML", "OIDC"]})
    r = await _refresh(client, admin)
    assert r.status_code == 401 and r.json()["code"] == "SIGN_IN_METHOD_NOT_ALLOWED"
    login = await client.post("/v1/auth/login", json={"email": admin.email, "password": admin.password, "totpCode": admin.totp()})
    assert login.status_code == 403 and login.json()["code"] == "SIGN_IN_METHOD_NOT_ALLOWED"


async def test_require_mfa_refuses_password_only_sessions_but_not_sso(monkeypatch):
    from zoikorum.domains.identity import session_policy as sp

    async def effective(session, identity_id):
        return sp.Effective(require_mfa=True)

    monkeypatch.setattr(sp, "effective_for", effective)
    now = datetime.now(timezone.utc)

    def sess(strength, idp):
        return SimpleNamespace(audience="APP", identity_id=uuid.uuid4(), created_at=now, family_id=uuid.uuid4(),
                               auth_strength=strength, idp=idp)

    assert (await sp.violation(None, sess("PASSWORD", "PASSWORD"), now))[0] == "MFA_REQUIRED_BY_ORGANISATION"
    assert await sp.violation(None, sess("MFA", "PASSWORD"), now) is None
    assert await sp.violation(None, sess("PASSKEY", "PASSKEY"), now) is None
    assert await sp.violation(None, sess("PASSWORD", "SAML"), now) is None  # the identity provider does the two-step
    staff = sess("PASSWORD", "PASSWORD")
    staff.audience = "ADMIN"
    assert await sp.violation(None, staff, now) is None


@pytest.mark.unit
def test_strictest_policy_wins():
    from zoikorum.domains.identity.session_policy import Effective

    assert Effective() == Effective(None, None, False, None)
