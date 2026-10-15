"""Browser push notifications (Web Push with VAPID). Only the notification's title, a short line and the link are sent;
the browser's push service sees them encrypted. Subscriptions the browser reports as gone (404/410) are removed."""

from __future__ import annotations

import asyncio
import json
import uuid

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from zoikorum.config import get_settings
from zoikorum.domains.notification.models import Notification, PushSubscription
from zoikorum.shared import clock
from zoikorum.shared.auth import Actor
from zoikorum.shared.errors import ServiceUnavailable

PUSH_TIMER = "notification.push"


def configured() -> bool:
    s = get_settings()
    return bool(s.vapid_public_key and s.vapid_private_key)


def public_key() -> str | None:
    return get_settings().vapid_public_key if configured() else None


async def subscribe(session: AsyncSession, actor: Actor, endpoint: str, p256dh: str, auth: str, user_agent: str | None) -> dict:
    if not configured():
        raise ServiceUnavailable("Push notifications are not available", code="PUSH_NOT_CONFIGURED")
    row = await session.scalar(select(PushSubscription).where(PushSubscription.endpoint == endpoint))
    if row is None:
        session.add(PushSubscription(identity_id=actor.identity_id, endpoint=endpoint, p256dh=p256dh, auth=auth, user_agent=(user_agent or "")[:300]))
    else:  # the same browser signed in as someone else: it now belongs to this person
        row.identity_id, row.p256dh, row.auth = actor.identity_id, p256dh, auth
    await session.flush()
    return {"subscribed": True}


async def unsubscribe(session: AsyncSession, actor: Actor, endpoint: str) -> dict:
    await session.execute(delete(PushSubscription).where(PushSubscription.endpoint == endpoint, PushSubscription.identity_id == actor.identity_id))
    return {"subscribed": False}


def _send(sub: PushSubscription, payload: str) -> int:
    """Send one push; returns the HTTP status. Imported lazily: the library is the optional "push" extra."""
    from pywebpush import WebPushException, webpush

    s = get_settings()
    try:
        r = webpush(subscription_info={"endpoint": sub.endpoint, "keys": {"p256dh": sub.p256dh, "auth": sub.auth}}, data=payload,
                    vapid_private_key=s.vapid_private_key, vapid_claims={"sub": s.vapid_subject}, ttl=86400, timeout=10)
        return getattr(r, "status_code", 201)
    except WebPushException as exc:
        return getattr(getattr(exc, "response", None), "status_code", 500) or 500


async def deliver(session: AsyncSession, notification_id: uuid.UUID) -> int:
    if not configured():
        return 0
    n = await session.get(Notification, notification_id)
    if n is None:
        return 0
    from zoikorum.config import web_url
    payload = json.dumps({"title": n.title, "body": (n.body or "").splitlines()[0][:160], "url": web_url() + n.url, "tag": str(n.id)})
    sent = 0
    for sub in (await session.scalars(select(PushSubscription).where(PushSubscription.identity_id == n.identity_id))).all():
        status = await asyncio.to_thread(_send, sub, payload)
        if status in (404, 410):
            await session.delete(sub)
        elif status < 300:
            sub.last_success_at = clock.now()
            sent += 1
    return sent
