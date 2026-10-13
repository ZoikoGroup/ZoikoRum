from zoikorum.domains.analytics import service
from zoikorum.shared.events import subscribe


async def project(session, event):
    await service.project(session, event)


for kind in service.EVENTS:
    subscribe(kind, consumer="analytics.event_facts")(project)
