from zoikorum.domains.policy import service
from zoikorum.shared.relay import on_timer


@on_timer(service.APPROVAL_TIMER)
async def approval_deadline(session, key, payload):
    await service.approval_deadline(session, key)


@on_timer(service.EXCEPTION_TIMER)
async def exception_expiry(session, key, payload):
    await service.exception_expiry(session, key)


from zoikorum.shared.event_catalog import E  # noqa: E402
from zoikorum.shared.events import EventEnvelope, subscribe  # noqa: E402


@subscribe(E.BUSINESS_UNITS_MERGED, consumer="policy.business_unit_merge")
async def business_units_merged(session, event: EventEnvelope):
    await service.business_units_merged(session, event.payload)
