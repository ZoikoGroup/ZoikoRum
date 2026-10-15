from zoikorum.domains.notification import service
from zoikorum.shared.events import subscribe
from zoikorum.shared.relay import on_timer


async def lifecycle(session, event):
    await service.queue_event(session, event)


for event_type in service.EVENT_TITLES:
    subscribe(event_type, consumer='notification.lifecycle')(lifecycle)


@on_timer(service.EMAIL_TIMER)
async def email_delivery(session, key, payload):
    await service.deliver_email(session, key)


@on_timer(service.WEBHOOK_TIMER)
async def webhook_delivery(session, key, payload):
    await service.deliver_webhook(session, key)


@on_timer(service.DIGEST_TIMER)
async def on_digest(session, key, payload):
    await service.send_digests(session)


@on_timer("notification.push")
async def on_push(session, key, payload):
    import uuid as _uuid

    from zoikorum.domains.notification import push
    await push.deliver(session, _uuid.UUID(key))
