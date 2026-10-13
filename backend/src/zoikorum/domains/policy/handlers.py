from zoikorum.domains.policy import service
from zoikorum.shared.relay import on_timer


@on_timer(service.APPROVAL_TIMER)
async def approval_deadline(session, key, payload):
    await service.approval_deadline(session, key)


@on_timer(service.EXCEPTION_TIMER)
async def exception_expiry(session, key, payload):
    await service.exception_expiry(session, key)
