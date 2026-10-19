"""The first staff account: created on deploy from secrets; running it again changes nothing (password and roles kept)."""

from __future__ import annotations

from sqlalchemy import text

from zoikorum.domains.identity import service
from zoikorum.shared.auth import PlatformRole


async def test_creating_the_first_admin_twice_keeps_the_password_and_records_the_role_once(client, sf):
    email = "first.admin@example.com"
    async with sf() as s, s.begin():
        await service.create_platform_admin(s, email, "First-password-123", "First Admin", "IN", (PlatformRole.LEGAL,))
    async with sf() as s, s.begin():  # the next deploy, with a different secret: must not take over the account
        await service.create_platform_admin(s, email, "Another-password-456", "First Admin", "IN", (PlatformRole.LEGAL,))

    assert (await client.post("/v1/auth/login", json={"email": email, "password": "Another-password-456"})).status_code == 401
    r = await client.post("/v1/auth/login", json={"email": email, "password": "First-password-123"})
    assert r.status_code == 200, r.text
    async with sf() as s:
        grants = (await s.execute(text("SELECT envelope->'payload'->>'role' FROM platform.outbox WHERE event_type LIKE '%platform_role_granted%' "
                                       "AND aggregate_id IN (SELECT id::text FROM identity.identities WHERE email = :e)"),
                                  {"e": email})).scalars().all()
    assert sorted(grants) == [PlatformRole.LEGAL, PlatformRole.PLATFORM_ADMIN]
