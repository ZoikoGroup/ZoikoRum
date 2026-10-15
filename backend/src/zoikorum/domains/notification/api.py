from __future__ import annotations

import uuid
from datetime import timedelta
from fastapi import Request, Response, APIRouter, Query
from pydantic import BaseModel, Field
from sqlalchemy import select

from zoikorum.domains.notification import service
from zoikorum.domains.notification.schemas import PreferencesIO
from zoikorum.shared.auth import CurrentActor
from zoikorum.shared.db import DbSession
from zoikorum.shared import clock
from zoikorum.shared.errors import NotFound, Conflict
from zoikorum.shared.http import paginate, page_of
from zoikorum.shared.events import record_audit
from zoikorum.domains.notification.models import WebhookEndpoint, WebhookDelivery, DeliveryAttempt

router = APIRouter(tags=["notifications"])


@router.get("/v1/notification-preferences", response_model=PreferencesIO)
async def get_preferences(actor: CurrentActor, session: DbSession):
    return await service.get_preferences(session, actor)


@router.put("/v1/notification-preferences", response_model=PreferencesIO)
async def set_preferences(body: PreferencesIO, actor: CurrentActor, session: DbSession):
    """Settings > Notifications. Security messages stay mandatory."""
    return await service.set_preferences(session, actor, body)


@router.get('/v1/notifications')
async def inbox(actor: CurrentActor, session: DbSession, cursor: str | None = None, limit: int = Query(30, ge=1, le=100)):
    return await service.inbox(session, actor, cursor, limit)


@router.get('/v1/notifications/unread-count')
async def unread(actor: CurrentActor, session: DbSession):
    return await service.unread_count(session, actor)


@router.post('/v1/notifications/{notification_id}/read')
async def mark_read(notification_id: uuid.UUID, actor: CurrentActor, session: DbSession):
    return await service.mark_read(session, actor, notification_id)


class EndpointIn(BaseModel):
    organizationId: uuid.UUID
    url: str = Field(min_length=10, max_length=2000)
    eventTypes: list[str] = Field(min_length=1, max_length=100)


class EndpointPatch(BaseModel):
    enabled: bool


@router.get('/v1/webhook-event-types')
async def event_types(actor: CurrentActor):
    return [{'eventType': e, 'label': service.EVENT_TITLES[e]} for e in sorted(service.WEBHOOK_EVENTS)]


@router.get('/v1/webhook-endpoints')
async def endpoints(organizationId: uuid.UUID, actor: CurrentActor, session: DbSession):
    await service.require_webhook_admin(session, actor, organizationId)
    rows = (await session.scalars(select(WebhookEndpoint).where(WebhookEndpoint.organization_id == organizationId).order_by(WebhookEndpoint.created_at.desc()))).all()
    return [service.endpoint_out(row) for row in rows]


@router.post('/v1/webhook-endpoints', status_code=201)
async def create_endpoint(body: EndpointIn, actor: CurrentActor, session: DbSession):
    return await service.create_endpoint(session, actor, body)


@router.patch('/v1/webhook-endpoints/{endpoint_id}')
async def update_endpoint(endpoint_id: uuid.UUID, body: EndpointPatch, actor: CurrentActor, session: DbSession):
    endpoint = await session.get(WebhookEndpoint, endpoint_id, with_for_update=True)
    if not endpoint:
        raise NotFound('Webhook endpoint not found')
    await service.require_webhook_admin(session, actor, endpoint.organization_id)
    actor.require_step_up()
    endpoint.enabled = body.enabled
    record_audit(session, 'notification.webhook.updated', object_type='WebhookEndpoint', object_id=endpoint.id,
        tenant_id=endpoint.organization_id, details={'enabled': body.enabled})
    return service.endpoint_out(endpoint)


@router.post('/v1/webhook-endpoints/{endpoint_id}/test', status_code=202)
async def test_endpoint(endpoint_id: uuid.UUID, actor: CurrentActor, session: DbSession):
    endpoint = await session.get(WebhookEndpoint, endpoint_id)
    if not endpoint:
        raise NotFound('Webhook endpoint not found')
    await service.require_webhook_admin(session, actor, endpoint.organization_id)
    actor.require_step_up()
    if not endpoint.enabled:
        raise Conflict('Enable the endpoint before testing')
    source_id = uuid.uuid4()
    delivery = await service.queue_webhook(session, endpoint, source_id, {'eventId': str(source_id),
        'eventType': 'zoikorum.webhook.test.v1', 'organizationId': str(endpoint.organization_id), 'occurredAt': clock.now().isoformat()})
    record_audit(session, 'notification.webhook.tested', object_type='WebhookDelivery', object_id=delivery.id,
        tenant_id=endpoint.organization_id, details={'endpointId': str(endpoint.id)})
    return {'deliveryId': delivery.id, 'status': delivery.status}


def delivery_out(delivery):
    return {'id': delivery.id, 'endpointId': delivery.endpoint_id, 'eventType': delivery.body.get('eventType'),
        'status': delivery.status, 'attempts': delivery.attempts, 'createdAt': delivery.created_at,
        'deliveredAt': delivery.delivered_at, 'retryUntil': delivery.retry_until}


@router.get('/v1/webhook-deliveries')
async def deliveries(endpointId: uuid.UUID, actor: CurrentActor, session: DbSession,
    cursor: str | None = None, limit: int = Query(30, ge=1, le=100)):
    endpoint = await session.get(WebhookEndpoint, endpointId)
    if not endpoint:
        raise NotFound('Webhook endpoint not found')
    await service.require_webhook_admin(session, actor, endpoint.organization_id)
    stmt, lim = paginate(select(WebhookDelivery).where(WebhookDelivery.endpoint_id == endpointId), WebhookDelivery, cursor, limit)
    return page_of(list((await session.scalars(stmt)).all()), lim, delivery_out)


@router.get('/v1/webhook-deliveries/{delivery_id}/attempts')
async def attempts(delivery_id: uuid.UUID, actor: CurrentActor, session: DbSession):
    delivery = await session.get(WebhookDelivery, delivery_id)
    endpoint = await session.get(WebhookEndpoint, delivery.endpoint_id) if delivery else None
    if not endpoint:
        raise NotFound('Webhook delivery not found')
    await service.require_webhook_admin(session, actor, endpoint.organization_id)
    rows = (await session.scalars(select(DeliveryAttempt).where(DeliveryAttempt.delivery_id == delivery_id).order_by(DeliveryAttempt.created_at))).all()
    return [{'attempt': r.attempt, 'responseStatus': r.response_status, 'error': r.error, 'createdAt': r.created_at} for r in rows]


@router.post('/v1/webhook-deliveries/{delivery_id}/replay', status_code=202)
async def replay(delivery_id: uuid.UUID, actor: CurrentActor, session: DbSession):
    delivery = await session.get(WebhookDelivery, delivery_id, with_for_update=True)
    endpoint = await session.get(WebhookEndpoint, delivery.endpoint_id) if delivery else None
    if not endpoint:
        raise NotFound('Webhook delivery not found')
    await service.require_webhook_admin(session, actor, endpoint.organization_id)
    actor.require_step_up()
    if delivery.status == 'PENDING' or not endpoint.enabled:
        raise Conflict('Only finished deliveries on enabled endpoints can be replayed')
    delivery.status, delivery.retry_until = 'PENDING', clock.now() + timedelta(hours=24)
    from zoikorum.shared.relay import schedule_timer
    await schedule_timer(session, service.WEBHOOK_TIMER, f'{delivery.id}:replay:{uuid.uuid4()}', clock.now())
    record_audit(session, 'notification.webhook.replayed', object_type='WebhookDelivery', object_id=delivery.id,
        tenant_id=endpoint.organization_id, details={'endpointId': str(endpoint.id)})
    return delivery_out(delivery)


class CalendarIn(BaseModel):
    enabled: bool


@router.put("/v1/calendar/link")
async def calendar_link(body: CalendarIn, actor: CurrentActor, session: DbSession) -> dict:
    """Create a new private calendar address (the old one stops working), or turn the feed off."""
    return await service.calendar_link(session, actor, body.enabled)


@router.get("/v1/calendar/{token}.ics", include_in_schema=False)
async def calendar_feed(token: str, session: DbSession) -> Response:
    """Private calendar feed: milestone due dates and signature deadlines (iCalendar), for calendar apps to subscribe to."""
    body = await service.calendar_feed(session, token)
    return Response(body, media_type="text/calendar; charset=utf-8", headers={"Cache-Control": "private, max-age=300"})


class PushKeys(BaseModel):
    p256dh: str = Field(min_length=10, max_length=200)
    auth: str = Field(min_length=4, max_length=100)


class PushSubscriptionIn(BaseModel):
    endpoint: str = Field(min_length=10, max_length=1000, pattern=r"^https://")
    keys: PushKeys


class PushEndpointIn(BaseModel):
    endpoint: str = Field(min_length=10, max_length=1000)


@router.get("/v1/push/key")
async def push_key() -> dict:
    """The public VAPID key browsers subscribe with; null when push notifications are not set up."""
    from zoikorum.domains.notification import push
    return {"publicKey": push.public_key()}


@router.post("/v1/push/subscriptions")
async def push_subscribe(body: PushSubscriptionIn, request: Request, actor: CurrentActor, session: DbSession) -> dict:
    from zoikorum.domains.notification import push
    return await push.subscribe(session, actor, body.endpoint, body.keys.p256dh, body.keys.auth, request.headers.get("user-agent"))


@router.post("/v1/push/subscriptions/remove")
async def push_unsubscribe(body: PushEndpointIn, actor: CurrentActor, session: DbSession) -> dict:
    from zoikorum.domains.notification import push
    return await push.unsubscribe(session, actor, body.endpoint)
