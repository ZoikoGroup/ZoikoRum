import uuid
from zoikorum.domains.admin import approvals, service, switches
from zoikorum.shared.events import subscribe
from zoikorum.shared.event_catalog import E
from zoikorum.shared.relay import on_timer
from zoikorum.shared import clock
from zoikorum.shared.metrics import gauge_source

gauge_source(switches.gauges)


async def signal(session, event):
    await service.triage_signal(session, event)


for kind in (E.RISK_FLAG_RAISED, E.MESSAGE_FLAGGED, E.TRUST_PROFILE_FLAGGED, E.VERIFICATION_FRAUD_SUSPECTED, E.DISPUTE_PATTERN_FLAGGED):
    subscribe(kind, consumer="admin.triage")(signal)


@on_timer(approvals.EXPIRY_TIMER)
async def approval_expired(session, key, payload):
    await approvals.expire(session, uuid.UUID(key))


@on_timer(service.EXPIRY_TIMER)
async def expire(session, key, payload):
    c = await service.case_get(session, uuid.UUID(key), True)
    if c.status == "ACTIVE" and c.expires_at and c.expires_at <= clock.now():
        await service.reverse(session, c, None, "The restriction duration ended")



@subscribe(E.ENFORCEMENT_ACTION_APPLIED, consumer="admin.reports_action_taken")
async def reports_action_taken(session, event_):
    from zoikorum.domains.admin import reports
    await reports.close_for_case(session, uuid.UUID(str(event_.payload["caseId"])), "ACTION_TAKEN")


@subscribe(E.ENFORCEMENT_CASE_CLOSED, consumer="admin.reports_no_action")
async def reports_no_action(session, event_):
    from zoikorum.domains.admin import reports
    await reports.close_for_case(session, uuid.UUID(str(event_.payload["caseId"])), "NO_ACTION")
