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
