"""Staff and customers use separate web apps (frontend src/portal.ts): links in emails to staff open the staff app."""

from __future__ import annotations

from zoikorum import config
from zoikorum.config import Settings
from zoikorum.domains.identity import facade as identity_facade


async def test_account_links_open_the_right_web_app(make_user, sf, monkeypatch):
    staff = await make_user("sam", platform_roles=("COMPLIANCE_OFFICER",))
    customer = await make_user("cat")
    split = Settings(_env_file=None, frontend_url="https://app.example.com", staff_frontend_url="https://staff.example.com")
    monkeypatch.setattr(config, "get_settings", lambda: split)
    async with sf() as s:
        to_staff = await identity_facade.notification_account_link(s, staff.id, "password_reset")
        to_customer = await identity_facade.notification_account_link(s, customer.id, "password_reset")
        assert (await identity_facade.get_identity(s, staff.id)).staff is True
    assert to_staff.startswith("https://staff.example.com/reset-password?token=")
    assert to_customer.startswith("https://app.example.com/reset-password?token=")

    one_app = Settings(_env_file=None, frontend_url="https://app.example.com")  # no staff app configured: one address
    monkeypatch.setattr(config, "get_settings", lambda: one_app)
    async with sf() as s:
        assert (await identity_facade.notification_account_link(s, staff.id, "password_reset")).startswith("https://app.example.com/")
