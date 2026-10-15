"""Browser push notifications: subscribe, deliver each new in-app notification, drop browsers that are gone."""

from __future__ import annotations

import pytest

from test_proposal import buyer_org


@pytest.fixture
def push_on(monkeypatch):
    from zoikorum.config import get_settings
    from zoikorum.domains.notification import push

    s = get_settings()
    monkeypatch.setattr(s, "vapid_public_key", "BPublicKeyForTests")
    monkeypatch.setattr(s, "vapid_private_key", "private-for-tests")
    sent: list[tuple[str, str]] = []
    gone = set()

    def fake_send(sub, payload):
        sent.append((sub.endpoint, payload))
        return 410 if sub.endpoint in gone else 201

    monkeypatch.setattr(push, "_send", fake_send)
    return sent, gone


async def test_push_reaches_subscribed_browsers_and_drops_gone_ones(client, make_user, drain, sf, push_on):
    from sqlalchemy import func, select

    from zoikorum.domains.notification.models import PushSubscription

    sent, gone = push_on
    buyer, org = await buyer_org(client, make_user, drain, "push-buyer")
    assert (await client.get("/v1/push/key")).json()["publicKey"] == "BPublicKeyForTests"
    sub = {"endpoint": "https://push.example.com/send/abc", "keys": {"p256dh": "BNcRdreALRFXTkOOUHK1EtK2wtaz5Ry4YfYCA_0QTpQtUbVlUls0VJXg7A8u-Ts1XbjhazAkj7I99e8QcYP7DkM", "auth": "tBHItJI5svbpez7KI4CCXg"}}
    assert (await client.post("/v1/push/subscriptions", headers=buyer.h, json=sub)).json() == {"subscribed": True}
    other = {**sub, "endpoint": "https://push.example.com/send/old"}
    await client.post("/v1/push/subscriptions", headers=buyer.h, json=other)
    gone.add(other["endpoint"])

    from uuid import uuid4

    from zoikorum.domains.notification import push
    from zoikorum.domains.notification.models import Notification
    nid = uuid4()
    async with sf() as s, s.begin():
        s.add(Notification(id=nid, source_event_id=uuid4(), identity_id=buyer.id, event_type="zoikorum.contract.retainer.paused.v1",
                           title="Retainer paused", body="Your retainer was paused.\nMore detail", url="/app/engagements", in_app=True,
                           mandatory=False, email_status="DISABLED", email_attempts=0))
    async with sf() as s, s.begin():
        assert await push.deliver(s, nid) == 1
    assert {e for e, _ in sent} == {sub["endpoint"], other["endpoint"]}
    assert '"title": "Retainer paused"' in sent[0][1] and "More detail" not in sent[0][1]  # first line only
    async with sf() as s:
        left = await s.scalar(select(func.count()).select_from(PushSubscription).where(PushSubscription.identity_id == buyer.id))
    assert left == 1  # the browser that is gone was removed
    assert (await client.post("/v1/push/subscriptions/remove", headers=buyer.h, json={"endpoint": sub["endpoint"]})).json() == {"subscribed": False}
