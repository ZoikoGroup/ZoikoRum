"""Staff MFA lasts for the validated session; customer freshness checks remain."""
import uuid
from dataclasses import replace
from datetime import timedelta

import pytest

from zoikorum.config import Settings
from zoikorum.shared import auth, clock
from zoikorum.shared.errors import StepUpRequired


@pytest.fixture
def settings(monkeypatch):
    monkeypatch.setattr(auth, "get_settings", lambda: Settings(env="test", dev_skip_mfa=False, _env_file=None))


def staff():
    return auth.Actor(identity_id=uuid.uuid4(), session_id=uuid.uuid4(), email=None,
        platform_roles=frozenset({auth.PlatformRole.PLATFORM_ADMIN}),
        auth_strength=auth.AuthStrength.MFA, auth_time=clock.now() - timedelta(days=1))


@pytest.mark.parametrize("role", sorted(auth.PlatformRole.ALL))
@pytest.mark.parametrize("strength", sorted(auth.AuthStrength.ELEVATED))
def test_staff_mfa_does_not_expire_after_five_minutes(settings, role, strength):
    actor = replace(staff(), platform_roles=frozenset({role}), auth_strength=strength)
    actor.require_platform_role(role)
    actor.require_step_up()


@pytest.mark.parametrize("overrides", [
    {"auth_strength": auth.AuthStrength.PASSWORD}, {"auth_time": None},
])
def test_staff_still_needs_mfa(settings, overrides):
    with pytest.raises(StepUpRequired):
        replace(staff(), **overrides).require_step_up()


def test_customer_and_explicit_freshness_limits_remain(settings):
    with pytest.raises(StepUpRequired):
        replace(staff(), platform_roles=frozenset()).require_step_up()
    with pytest.raises(StepUpRequired):
        staff().require_step_up(max_age_seconds=60)
    with pytest.raises(StepUpRequired):
        replace(staff(), session_id=None).require_step_up()
    with pytest.raises(StepUpRequired):
        replace(staff(), platform_roles=frozenset({"UNKNOWN_ROLE"})).require_step_up()


async def test_staff_confirmation_survives_refresh_but_not_logout(client, make_user, sf):
    admin = await make_user("session-admin", platform_roles=("PLATFORM_ADMIN",))
    target = await make_user("session-role-target")
    await admin.step_up()
    # Age the confirmation without minting a token in the future relative to JWT's real clock.
    from sqlalchemy import text
    session_id = auth.decode_access_token(admin.access).session_id
    async with sf() as session, session.begin():
        await session.execute(text("UPDATE identity.sessions SET auth_time = :confirmed WHERE id = :id"),
            {"confirmed": clock.now() - timedelta(minutes=40), "id": session_id})
    await admin.refresh()
    url = f"/v1/admin/identities/{target.id}/platform-roles"
    granted = await client.post(url, headers=admin.h, json={"role": "COMPLIANCE_OFFICER"})
    assert granted.status_code == 200, granted.text
    assert "COMPLIANCE_OFFICER" in granted.json()["platformRoles"]
    logged_out = await client.post("/v1/auth/logout", headers=admin.h)
    assert logged_out.status_code == 204, logged_out.text
    assert (await client.post(url, headers=admin.h, json={"role": "MEDIATOR"})).status_code == 401
    refreshed = await client.post("/v1/auth/refresh", json={"refreshToken": admin.refresh_token})
    assert refreshed.status_code == 401
