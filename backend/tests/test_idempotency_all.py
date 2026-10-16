"""Idempotency-Key on every change (Handbook ch. 12): a retry gets the first answer instead of a second change."""

from __future__ import annotations

from sqlalchemy import text


async def test_a_retried_change_is_answered_from_the_first_and_not_repeated(client, make_user, sf):
    u = await make_user("ivy")
    url = "/v1/me"
    headers = {**u.h, "Idempotency-Key": "edit-1"}
    first = await client.patch(url, headers=headers, json={"displayName": "Ivy First"})
    assert first.status_code == 200 and first.json()["displayName"] == "Ivy First"
    again = await client.patch(url, headers=headers, json={"displayName": "Ivy First"})
    assert again.status_code == 200 and again.headers.get("idempotent-replayed") == "true" and again.json() == first.json()
    # The same key with a different body is a mistake, not a retry.
    other = await client.patch(url, headers=headers, json={"displayName": "Someone Else"})
    assert other.status_code == 422 and other.json()["code"] == "IDEMPOTENCY_KEY_REUSED"
    assert (await client.get(url, headers=u.h)).json()["displayName"] == "Ivy First"

    # A failed request is not remembered: fixing it and sending again with the same key works.
    bad = await client.patch(url, headers={**u.h, "Idempotency-Key": "edit-2"}, json={"displayName": ""})
    assert bad.status_code == 422
    async with sf() as s:
        kept = await s.scalar(text("SELECT count(*) FROM platform.idempotency_keys WHERE scope LIKE 'mw:%edit-2'"))
    assert kept == 0

    # Keys belong to one person: someone else's request with the same key is their own.
    v = await make_user("val")
    r = await client.patch(url, headers={**v.h, "Idempotency-Key": "edit-1"}, json={"displayName": "Val"})
    assert r.status_code == 200 and r.json()["displayName"] == "Val" and "idempotent-replayed" not in r.headers
