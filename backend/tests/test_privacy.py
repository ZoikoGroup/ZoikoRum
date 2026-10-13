"""Privacy requests: download my data and delete my account (identity/privacy_requests.py, shared/privacy.py)."""

from __future__ import annotations

import json
from datetime import timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from zoikorum.shared import clock

R = "/v1/me/data-requests"


async def professional(client, make_user, drain, name="pat"):
    u = await make_user(name, account_type="PROFESSIONAL")
    pro = (await client.post("/v1/professionals", headers=u.h, json={})).json()
    await drain()
    return u, pro


async def test_download_my_data(client, make_user, drain, sf):
    u, pro = await professional(client, make_user, drain)
    saved = await client.post("/v1/saved/searches", headers=u.h, json={"name": "Tax help", "params": {"q": "tax"}})
    assert saved.status_code == 201
    req = (await client.post(R, headers=u.h, json={"requestType": "ACCESS"})).json()
    assert req["status"] == "RECEIVED" and req["downloadable"] is False
    assert (await client.post(R, headers=u.h, json={"requestType": "ACCESS"})).json()["id"] == req["id"]  # one at a time
    await drain()  # the worker builds the file
    ready = (await client.get(R, headers=u.h)).json()[0]
    assert ready["status"] == "COMPLETED" and ready["downloadable"] and ready["expiresAt"]

    url = f"{R}/{req['id']}/download"
    assert (await client.get(url, headers=u.h)).json()["code"] == "STEP_UP_REQUIRED"  # the file holds everything
    await u.step_up()
    r = await client.get(url, headers=u.h)
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store" and "attachment" in r.headers["content-disposition"]
    body = r.json()
    assert body["data"]["identity"]["account"]["email"] == u.email
    assert body["data"]["professional"]["profile"]["id"] == pro["id"]
    assert [x["name"] for x in body["data"]["marketplace"]["savedSearches"]] == ["Tax help"]
    assert set(body["keptByLaw"]) >= {"contract", "payments", "verification"}
    raw = r.text
    for secret in ("password_hash", "mfa_secret_enc", "refresh_token_hash", "export_key", "storage_key"):
        assert secret not in raw, secret
    stranger = await make_user("sam")
    await stranger.step_up()
    assert (await client.get(url, headers=stranger.h)).status_code == 404
    await drain()
    async with sf() as s:
        assert await s.scalar(text("SELECT count(*) FROM audit.audit_records WHERE action LIKE '%data_export.downloaded%'")) == 1

    async with sf() as s, s.begin():  # the download period (ZK_DATA_EXPORT_DAYS) has passed
        await s.execute(text("UPDATE identity.data_requests SET expires_at = now() - interval '1 minute' WHERE id = :i"),
                        {"i": req["id"]})
    assert (await client.get(url, headers=u.h)).json()["code"] == "EXPORT_EXPIRED"
    assert (await client.get(R, headers=u.h)).json()[0]["downloadable"] is False


async def test_delete_my_account_after_cooling_off(client, make_user, drain, sf):
    u, pro = await professional(client, make_user, drain, name="dora")
    assert (await client.post(R, headers=u.h, json={"requestType": "ERASURE"})).json()["code"] == "STEP_UP_REQUIRED"
    await u.step_up()
    first = (await client.post(R, headers=u.h, json={"requestType": "ERASURE"})).json()
    assert first["status"] == "SCHEDULED" and first["scheduledFor"] and "contract" in first["retained"]
    cancelled = (await client.post(f"{R}/{first['id']}/cancel", headers=u.h)).json()
    assert cancelled["status"] == "CANCELLED"
    clock.advance(timedelta(days=15))
    await drain()  # the cancelled request's timer does nothing
    async with sf() as s:
        assert await s.scalar(text("SELECT status FROM identity.identities WHERE email = :e"), {"e": u.email}) == "ACTIVE"
    clock.set_now(None)

    await u.step_up()
    second = (await client.post(R, headers=u.h, json={"requestType": "ERASURE"})).json()
    assert second["id"] != first["id"]
    clock.advance(timedelta(days=15))
    await drain()
    async with sf() as s:
        status = await s.scalar(text("SELECT status FROM identity.data_requests WHERE id = :i"), {"i": second["id"]})
        account = (await s.execute(text("SELECT email, display_name, status, password_hash FROM identity.identities "
                                        "WHERE email LIKE 'deleted-%' AND status = 'DELETED'"))).all()
        profile = (await s.execute(text("SELECT display_name, bio, status FROM professional.professionals WHERE id = :i"),
                                   {"i": pro["id"]})).one()
    assert status == "COMPLETED"
    assert len(account) == 1 and account[0].display_name == "Deleted user" and account[0].password_hash is None
    assert profile.display_name == "Deleted professional" and profile.bio is None
    r = await client.post("/v1/auth/login", json={"email": u.email, "password": u.password})
    assert r.status_code == 401  # the old email and password no longer sign in


async def test_open_engagement_puts_deletion_on_hold(client, make_user, drain, sf):
    from test_contract import signed_contract

    pro_user, pro, buyer, contract = await signed_contract(client, make_user, drain)
    await buyer.step_up()
    req = (await client.post(R, headers=buyer.h, json={"requestType": "ERASURE"})).json()
    clock.advance(timedelta(days=15))
    await drain()
    async with sf() as s:  # (the test's sign-in token has expired after 15 days, so read the records directly)
        held = (await s.execute(text("SELECT status, detail FROM identity.data_requests WHERE id = :i"), {"i": req["id"]})).one()
        account = await s.scalar(text("SELECT status FROM identity.identities WHERE email = :e"), {"e": buyer.email})
    assert held.status == "BLOCKED" and any("engagement" in reason for reason in held.detail["reasons"])
    assert account == "ACTIVE"  # nothing was erased


async def test_append_only_tables_allow_only_name_erasure(sf):
    """messaging.messages and review.reviews: the name may become "Deleted user" during an erasure, nothing else."""
    async with sf() as s, s.begin():  # a real table: every attempt below runs on its own connection
        await s.execute(text("DROP TABLE IF EXISTS platform.privacy_trigger_check"))
        await s.execute(text("CREATE TABLE platform.privacy_trigger_check (id int, sender_name text, body text)"))
        await s.execute(text("CREATE TRIGGER t BEFORE UPDATE OR DELETE ON platform.privacy_trigger_check FOR EACH ROW "
                             "EXECUTE FUNCTION platform.prevent_mutation_except_name_erasure('sender_name')"))
        await s.execute(text("INSERT INTO platform.privacy_trigger_check VALUES (1, 'Ana Real', 'hello')"))

    async def attempt(sql: str, erasure: bool) -> bool:
        try:
            async with sf() as s, s.begin():
                if erasure:
                    await s.execute(text("SELECT set_config('zoikorum.privacy_erasure', 'on', true)"))
                await s.execute(text(sql))
            return True
        except DBAPIError:
            return False

    t = "platform.privacy_trigger_check"
    try:
        rename = f"UPDATE {t} SET sender_name = 'Deleted user'"
        assert not await attempt(rename, erasure=False)  # outside an erasure
        assert not await attempt(f"UPDATE {t} SET sender_name = 'Someone else'", erasure=True)
        assert not await attempt(f"UPDATE {t} SET body = 'changed', sender_name = 'Deleted user'", erasure=True)
        assert not await attempt(f"DELETE FROM {t}", erasure=True)
        assert await attempt(rename, erasure=True)
        async with sf() as s:
            assert (await s.execute(text(f"SELECT sender_name, body FROM {t}"))).one() == ("Deleted user", "hello")
    finally:
        async with sf() as s, s.begin():
            await s.execute(text(f"DROP TABLE IF EXISTS {t}"))


@pytest.mark.unit
def test_every_area_with_personal_data_is_registered():
    from zoikorum.main import load_domains
    from zoikorum.shared import privacy

    load_domains()
    assert {p.domain for p in privacy.registered()} >= {
        "identity", "professional", "buyer", "firm", "proposal", "contract", "dispute", "payments",
        "messaging", "notification", "marketplace", "review", "verification"}
