import uuid
from zoikorum.domains.admin import service
from zoikorum.shared.events import subscribe
from zoikorum.shared.event_catalog import E
from zoikorum.shared.relay import on_timer
from zoikorum.shared import clock


async def signal(session, event):
    await service.triage_signal(session, event)


for kind in (E.RISK_FLAG_RAISED, E.MESSAGE_FLAGGED, E.TRUST_PROFILE_FLAGGED):
    subscribe(kind, consumer="admin.triage")(signal)


@on_timer(service.EXPIRY_TIMER)
async def expire(session, key, payload):
    c = await service.case_get(session, uuid.UUID(key), True)
    if c.status == "ACTIVE" and c.expires_at and c.expires_at <= clock.now():
        await service.reverse(session, c, None, "The restriction duration ended")
