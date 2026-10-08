from __future__ import annotations

import uuid
import secrets
from datetime import timedelta

from sqlalchemy import select, func
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from zoikorum.domains.notification.models import Preference, Notification, WebhookEndpoint, WebhookDelivery, DeliveryAttempt
from zoikorum.domains.notification import providers
from zoikorum.domains.buyer import facade as buyer
from zoikorum.domains.professional import facade as professional
from zoikorum.domains.identity import facade as identity
from zoikorum.domains.contract import facade as contract
from zoikorum.domains.notification.schemas import PreferencesIO
from zoikorum.shared.auth import Actor, OrgRole
from zoikorum.shared.event_catalog import E, ALL_EVENTS, domain_of
from zoikorum.shared.events import record_event, record_audit
from zoikorum.shared import clock
from zoikorum.shared.crypto import canonical_json, encrypt_field, decrypt_field, hmac_sha256_hex
from zoikorum.shared.errors import Forbidden, NotFound, Conflict, ValidationFailed
from zoikorum.shared.http import paginate, page_of
from zoikorum.shared.relay import schedule_timer
from zoikorum.config import get_settings

EMAIL_TIMER = 'notification.email_delivery'
WEBHOOK_TIMER = 'notification.webhook_delivery'
EVENT_TITLES = {
    E.IDENTITY_CREATED: 'Confirm your email address', E.PASSWORD_RESET_REQUESTED: 'Reset your password',
    E.MFA_ENROLLED: 'Two-step verification enabled', E.PASSWORD_CHANGED: 'Your password changed',
    E.AUTHENTICATION_FAILED: 'Account security alert', E.IDENTITY_SUSPENDED: 'Account restricted',
    E.IDENTITY_REINSTATED: 'Account restored',
    E.PROPOSAL_REQUESTED: 'New proposal request', E.PROPOSAL_REQUEST_DECLINED: 'Request declined',
    E.PROPOSAL_REQUEST_CANCELLED: 'Request cancelled', E.PROPOSAL_SUBMITTED: 'Proposal received',
    E.PROPOSAL_REVISION_REQUESTED: 'Proposal changes requested', E.PROPOSAL_REVISED: 'Revised proposal received',
    E.PROPOSAL_ACCEPTED: 'Proposal accepted', E.PROPOSAL_REJECTED: 'Proposal declined', E.PROPOSAL_EXPIRED: 'Proposal expired',
    E.CONTRACT_GENERATED: 'Agreement ready for signature', E.CONTRACT_SIGNED: 'Agreement signed',
    E.CONTRACT_ACTIVATED: 'Engagement activated', E.CONTRACT_COMPLETED: 'Engagement completed',
    E.CONTRACT_TERMINATED: 'Engagement terminated', E.SIGNATURE_DEADLINE_ESCALATED: 'Signature overdue',
    E.CHANGE_ORDER_REQUESTED: 'Contract change proposed', E.CHANGE_ORDER_APPROVED: 'Contract change approved',
    E.CHANGE_ORDER_REJECTED: 'Contract change declined', E.CONTRACT_AMENDED: 'Contract amendment signed',
    E.ESCROW_FUNDED: 'Payment held in escrow', E.ESCROW_RELEASED: 'Milestone payment released',
    E.ESCROW_REFUNDED: 'Escrow refund arranged', E.PAYMENT_FAILED: 'Payment unsuccessful',
    E.PAYOUT_SETTLED: 'Payout completed', E.PAYOUT_FAILED: 'Payout needs attention',
    E.MILESTONE_SUBMITTED: 'Work submitted for review', E.MILESTONE_ACCEPTED: 'Milestone accepted',
    E.MILESTONE_REVISION_REQUESTED: 'Work changes requested', E.MILESTONE_ACCEPTANCE_REMINDER: 'Review reminder',
    E.MILESTONE_ACCEPTANCE_OVERDUE: 'Milestone review overdue',
    E.VERIFICATION_NEEDS_INFO: 'Verification needs information', E.VERIFICATION_COMPLETED: 'Verification completed',
    E.VERIFICATION_FAILED: 'Verification unsuccessful', E.VERIFICATION_EXPIRING: 'Verification expires soon',
    E.VERIFICATION_EXPIRED: 'Verification expired',
    E.APPROVAL_REQUIRED: 'Approval required', E.APPROVAL_GRANTED: 'Approval granted',
    E.APPROVAL_DENIED: 'Approval denied', E.APPROVAL_ESCALATED: 'Approval escalated', E.APPROVAL_EXPIRED: 'Approval expired',
    E.EXCEPTION_REQUESTED: 'Policy exception requested', E.EXCEPTION_GRANTED: 'Policy exception granted',
    E.EXCEPTION_DENIED: 'Policy exception denied', E.EXCEPTION_EXPIRED: 'Policy exception expired',
    E.DISPUTE_INITIATED: 'Dispute opened', E.DISPUTE_EVIDENCE_SUBMITTED: 'Dispute evidence added',
    E.DISPUTE_RESOLUTION_PROPOSED: 'Dispute resolution proposed', E.DISPUTE_ESCALATED: 'Dispute escalated',
    E.DISPUTE_RECOMMENDATION_ISSUED: 'Mediator recommendation available', E.DISPUTE_RESOLVED: 'Dispute decision issued',
    E.DISPUTE_CLOSED: 'Dispute closed', E.DISPUTE_APPEALED: 'Dispute appeal filed', E.DISPUTE_APPEAL_DECIDED: 'Dispute appeal reviewed',
    E.ENFORCEMENT_ACTION_APPLIED: 'Account safety decision', E.ENFORCEMENT_ACTION_REVERSED: 'Restriction reversed',
    E.ENFORCEMENT_APPEAL_DECIDED: 'Safety appeal decided',
}
WEBHOOK_EVENTS = frozenset(e for e in EVENT_TITLES if domain_of(e) in {'proposal', 'contract', 'escrow', 'policy', 'dispute', 'verification'})


def _uuid(value):
    try:
        return uuid.UUID(str(value)) if value else None
    except ValueError:
        return None


async def recipients(session, event):
    p, found = event.payload, set()
    for key in ('identityId', 'buyerIdentityId', 'requesterIdentityId', 'assignedMediatorIdentityId'):
        if value := _uuid(p.get(key)):
            found.add(value)
    found.update(v for raw in p.get('recipientIdentityIds', []) if (v := _uuid(raw)))
    org_id = _uuid(p.get('organizationId'))
    if not org_id and event.tenantId and await buyer.get_organization(session, _uuid(event.tenantId)):
        org_id = _uuid(event.tenantId)
    pro_id = _uuid(p.get('professionalId'))
    if p.get('subjectType') == 'PROFESSIONAL':
        pro_id = _uuid(p.get('subjectId'))
    if p.get('subjectType') == 'IDENTITY' and (subject := _uuid(p.get('subjectId'))):
        found.add(subject)
    if contract_id := _uuid(p.get('contractId')):
        engagement = await contract.get_contract(session, contract_id)
        if engagement:
            org_id, pro_id = engagement.organization_id, engagement.professional_id
    if org_id:
        wanted = [OrgRole.APPROVER, OrgRole.BUDGET_OWNER, OrgRole.LEGAL_REVIEWER, OrgRole.ORG_ADMIN] if event.eventType in (E.APPROVAL_REQUIRED, E.APPROVAL_ESCALATED) else None
        if event.eventType == E.EXCEPTION_REQUESTED:
            wanted = [OrgRole.EXCEPTION_AUTHORITY]
        found.update(await buyer.list_member_identities(session, org_id, wanted))
    pro = await professional.get_professional(session, pro_id) if pro_id else None
    if pro:
        found.add(pro.identity_id)
    return found, org_id, pro.identity_id if pro else None


def target_url(event, recipient, professional_identity):
    p = event.payload
    if domain_of(event.eventType) == 'identity':
        return '/app/security'
    if domain_of(event.eventType) == 'admin':
        return '/app/safety'
    if domain_of(event.eventType) == 'policy':
        return '/app/policies?orgId=' + str(p.get('organizationId') or event.tenantId or '')
    if dispute_id := p.get('disputeId'):
        return f'/app/disputes/{dispute_id}'
    if contract_id := p.get('contractId'):
        prefix = '/app/professional/engagements' if recipient == professional_identity else '/app/engagements'
        return f'{prefix}/{contract_id}'
    if request_id := p.get('requestId'):
        prefix = '/app/professional/requests' if recipient == professional_identity else '/app/requests'
        return f'{prefix}/{request_id}'
    if domain_of(event.eventType) == 'verification':
        return '/app/professional/verification' if recipient == professional_identity else '/app/verification'
    return '/app/notifications'


async def queue_event(session, event):
    if event.eventType not in EVENT_TITLES:
        return
    if event.eventType == E.AUTHENTICATION_FAILED and event.payload.get('reason') not in {'LOCKED_OUT', 'ACCOUNT_LOCKED'} and not event.payload.get('lockedUntil'):
        return
    found, org_id, pro_identity = await recipients(session, event)
    mandatory = domain_of(event.eventType) in {'identity', 'admin'}
    notice = event.payload.get('notice') if domain_of(event.eventType) == 'admin' else None
    body = '\n'.join(f'{key}: {value}' for key, value in notice.items()) if notice else 'Open your workspace to review this update and any required action.'
    for recipient in found:
        prefs = await session.scalar(select(Preference).where(Preference.identity_id == recipient))
        email_on = mandatory or prefs is None or prefs.email
        in_app = mandatory or prefs is None or prefs.in_app
        if not email_on and not in_app:
            continue
        nid = uuid.uuid4()
        result = await session.execute(insert(Notification).values(id=nid, source_event_id=event.eventId,
            identity_id=recipient, event_type=event.eventType, title=EVENT_TITLES[event.eventType], body=body,
            url=target_url(event, recipient, pro_identity), notice=notice, mandatory=mandatory, in_app=in_app,
            email_status='PENDING' if email_on else 'DISABLED', created_at=event.occurredAt).on_conflict_do_nothing(
                index_elements=['source_event_id', 'identity_id']).returning(Notification.id))
        if result.scalar_one_or_none():
            if email_on:
                await schedule_timer(session, EMAIL_TIMER, f'{nid}:0', clock.now())
            record_event(session, E.NOTIFICATION_QUEUED, aggregate_type='Notification', aggregate_id=nid,
                tenant_id=org_id, payload={'identityId': recipient, 'notificationId': nid, 'sourceEventId': event.eventId})
    if org_id and event.eventType in WEBHOOK_EVENTS:
        endpoints = (await session.scalars(select(WebhookEndpoint).where(WebhookEndpoint.organization_id == org_id,
            WebhookEndpoint.enabled.is_(True)))).all()
        # Deliberately exclude tokens, documents, private text and authentication metadata.
        safe_payload = {k: v for k, v in event.payload.items() if k.endswith('Id') or k.endswith('Ids') or k.endswith('Minor') or k in {'currency', 'status', 'reference', 'decision', 'party', 'auto'}}
        body = {'eventId': str(event.eventId), 'eventType': event.eventType, 'occurredAt': event.occurredAt.isoformat(),
            'organizationId': str(org_id), 'aggregateId': event.aggregateId, 'payload': safe_payload}
        for endpoint in endpoints:
            if event.eventType in endpoint.event_types:
                await queue_webhook(session, endpoint, event.eventId, body)


def notification_out(n):
    return {'id': n.id, 'title': n.title, 'body': n.body, 'url': n.url, 'notice': n.notice,
        'mandatory': n.mandatory, 'readAt': n.read_at, 'createdAt': n.created_at, 'emailStatus': n.email_status}


async def inbox(session, actor, cursor=None, limit=30):
    stmt, lim = paginate(select(Notification).where(Notification.identity_id == actor.identity_id,
        Notification.in_app.is_(True)), Notification, cursor, limit)
    return page_of(list((await session.scalars(stmt)).all()), lim, notification_out)


async def unread_count(session, actor):
    return {'unread': await session.scalar(select(func.count()).select_from(Notification).where(
        Notification.identity_id == actor.identity_id, Notification.in_app.is_(True), Notification.read_at.is_(None))) or 0}


async def mark_read(session, actor, nid):
    row = await session.scalar(select(Notification).where(Notification.id == nid,
        Notification.identity_id == actor.identity_id, Notification.in_app.is_(True)).with_for_update())
    if not row:
        raise NotFound('Notification not found')
    row.read_at = row.read_at or clock.now()
    return notification_out(row)


async def deliver_email(session, key):
    row = await session.get(Notification, uuid.UUID(key.split(':')[0]), with_for_update=True)
    if not row or row.email_status != 'PENDING':
        return
    recipient = await identity.get_identity(session, row.identity_id)
    if not recipient or recipient.status == 'DELETED':
        row.email_status = 'CANCELLED'
        return
    prefs = await session.scalar(select(Preference).where(Preference.identity_id == row.identity_id))
    if not row.mandatory and prefs and not prefs.email:
        row.email_status = 'DISABLED'
        return
    url = get_settings().frontend_url.rstrip('/') + row.url
    if row.event_type in {E.IDENTITY_CREATED, E.PASSWORD_RESET_REQUESTED}:
        purpose = 'email_confirm' if row.event_type == E.IDENTITY_CREATED else 'password_reset'
        url = await identity.notification_account_link(session, row.identity_id, purpose, requested_at=row.created_at)
        if not url:
            row.email_status = 'CANCELLED'
            return
    row.email_attempts += 1
    try:
        row.email_status = await providers.email_provider().send(recipient.email, row.title, row.body + '\n\n' + url, str(row.id))
        row.delivered_at, row.last_error = clock.now(), None
        record_event(session, E.NOTIFICATION_DELIVERED, aggregate_type='Notification', aggregate_id=row.id,
            payload={'notificationId': row.id, 'identityId': row.identity_id, 'channel': 'EMAIL', 'status': row.email_status})
    except Exception:
        row.last_error = 'Email provider could not deliver this message'
        if row.created_at + timedelta(hours=24) > clock.now():
            await schedule_timer(session, EMAIL_TIMER, f'{row.id}:{row.email_attempts}',
                clock.now() + timedelta(seconds=min(3600, 30 * 2 ** min(row.email_attempts, 10))))
        else:
            row.email_status = 'FAILED'
            record_event(session, E.NOTIFICATION_FAILED, aggregate_type='Notification', aggregate_id=row.id,
                payload={'notificationId': row.id, 'identityId': row.identity_id, 'channel': 'EMAIL'})


async def require_webhook_admin(session, actor, org_id):
    roles = await buyer.get_member_roles(session, org_id, actor.identity_id)
    account = await identity.get_identity(session, actor.identity_id)
    if not account or account.status != 'ACTIVE' or OrgRole.ORG_ADMIN not in roles:
        raise Forbidden('Webhook management requires an active organisation administrator')


def endpoint_out(endpoint):
    return {'id': endpoint.id, 'organizationId': endpoint.organization_id, 'url': endpoint.url,
        'eventTypes': endpoint.event_types, 'enabled': endpoint.enabled, 'createdAt': endpoint.created_at}


async def create_endpoint(session, actor, body):
    await require_webhook_admin(session, actor, body.organizationId)
    actor.require_step_up()
    providers.checked_url(body.url)
    if not body.eventTypes or not set(body.eventTypes) <= WEBHOOK_EVENTS:
        raise ValidationFailed('Select supported lifecycle events')
    secret = secrets.token_urlsafe(32)
    endpoint = WebhookEndpoint(organization_id=body.organizationId, url=body.url,
        event_types=sorted(set(body.eventTypes)), secret_encrypted=encrypt_field(secret))
    session.add(endpoint); await session.flush()
    record_audit(session, 'notification.webhook.created', object_type='WebhookEndpoint', object_id=endpoint.id,
        tenant_id=body.organizationId, details={'eventTypes': endpoint.event_types})
    return {**endpoint_out(endpoint), 'secret': secret}


async def queue_webhook(session, endpoint, source_id, body):
    delivery = WebhookDelivery(endpoint_id=endpoint.id, source_event_id=source_id, body=body,
        retry_until=clock.now() + timedelta(hours=24))
    session.add(delivery); await session.flush()
    await schedule_timer(session, WEBHOOK_TIMER, f'{delivery.id}:0', clock.now())
    return delivery


async def deliver_webhook(session, key):
    delivery = await session.get(WebhookDelivery, uuid.UUID(key.split(':')[0]), with_for_update=True)
    if not delivery or delivery.status != 'PENDING':
        return
    endpoint = await session.get(WebhookEndpoint, delivery.endpoint_id)
    if not endpoint.enabled:
        delivery.status = 'CANCELLED'; return
    if clock.now() >= delivery.retry_until:
        delivery.status = 'FAILED'; return
    delivery.attempts += 1
    raw = canonical_json(delivery.body)
    timestamp = str(int(clock.now().timestamp()))
    signature = hmac_sha256_hex(decrypt_field(endpoint.secret_encrypted), timestamp.encode() + b'.' + raw)
    status, error = None, None
    try:
        status = await providers.post_webhook(endpoint.url, raw, {'Content-Type': 'application/json',
            'X-Zoikorum-Signature': f't={timestamp},v1={signature}', 'X-Zoikorum-Delivery-Id': str(delivery.id)})
        if not 200 <= status < 300:
            error = f'Destination returned HTTP {status}'
    except Exception:
        error = 'Webhook destination is unreachable or unsafe'
    session.add(DeliveryAttempt(delivery_id=delivery.id, response_status=status, error=error, attempt=delivery.attempts))
    if error:
        when = clock.now() + timedelta(seconds=min(3600, 30 * 2 ** min(delivery.attempts, 10)))
        if when < delivery.retry_until:
            await schedule_timer(session, WEBHOOK_TIMER, f'{delivery.id}:{delivery.attempts}', when)
        else:
            delivery.status = 'FAILED'
    else:
        delivery.status, delivery.delivered_at = 'DELIVERED', clock.now()


def _out(p: Preference | None) -> PreferencesIO:
    return PreferencesIO() if p is None else PreferencesIO(email=p.email, inApp=p.in_app, sms=p.sms, marketing=p.marketing)


async def get_preferences(session: AsyncSession, actor: Actor) -> PreferencesIO:
    return _out(await session.scalar(select(Preference).where(Preference.identity_id == actor.identity_id)))


async def set_preferences(session: AsyncSession, actor: Actor, body: PreferencesIO) -> PreferencesIO:
    p = await session.scalar(select(Preference).where(Preference.identity_id == actor.identity_id).with_for_update())
    if p is None:
        p = Preference(id=uuid.uuid4(), identity_id=actor.identity_id)
        session.add(p)
    p.email, p.in_app, p.sms, p.marketing = body.email, body.inApp, body.sms, body.marketing
    await session.flush()
    record_event(session, E.NOTIFICATION_PREFERENCES_UPDATED, aggregate_type="NotificationPreferences", aggregate_id=p.id,
                 payload={"identityId": actor.identity_id, "email": p.email, "inApp": p.in_app, "sms": p.sms,
                          "marketing": p.marketing})
    return _out(p)
