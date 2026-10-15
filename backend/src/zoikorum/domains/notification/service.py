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
from zoikorum.shared.retry import exponential
from zoikorum.config import get_settings, web_url

EMAIL_TIMER = 'notification.email_delivery'
WEBHOOK_TIMER = 'notification.webhook_delivery'
EVENT_TITLES = {
    E.IDENTITY_CREATED: 'Confirm your email address', E.EMAIL_CONFIRMATION_REQUESTED: 'Confirm your email address',
    E.PASSWORD_RESET_REQUESTED: 'Reset your password',
    E.DATA_REQUEST_CREATED: 'Privacy request received', E.DATA_REQUEST_COMPLETED: 'Your privacy request is complete',
    E.DATA_REQUEST_BLOCKED: 'Account deletion on hold', E.DATA_REQUEST_CANCELLED: 'Account deletion cancelled',
    E.MFA_ENROLLED: 'Two-step verification enabled', E.PASSWORD_CHANGED: 'Your password changed',
    E.PASSKEY_ADDED: 'A passkey was added to your account', E.PASSKEY_REMOVED: 'A passkey was removed from your account',
    E.MFA_RECOVERY_CODE_USED: 'A recovery code was used to sign in', E.MFA_RESET: 'Two-step verification was reset',
    E.AUTHENTICATION_FAILED: 'Account security alert', E.IDENTITY_SUSPENDED: 'Account restricted',
    E.IDENTITY_REINSTATED: 'Account restored',
    E.PROPOSAL_REQUESTED: 'New proposal request', E.PROPOSAL_REQUEST_DECLINED: 'Request declined',
    E.PROPOSAL_REQUEST_CANCELLED: 'Request cancelled', E.PROPOSAL_SUBMITTED: 'Proposal received',
    E.PROPOSAL_REVISION_REQUESTED: 'Proposal changes requested', E.PROPOSAL_REVISED: 'Revised proposal received',
    E.PROPOSAL_ACCEPTED: 'Proposal accepted', E.PROPOSAL_REJECTED: 'Proposal declined', E.PROPOSAL_EXPIRED: 'Proposal expired',
    E.CONTRACT_GENERATED: 'Agreement ready for signature', E.CONTRACT_SIGNED: 'Agreement signed',
    E.CONTRACT_ACTIVATED: 'Engagement activated', E.CONTRACT_COMPLETED: 'Engagement completed',
    E.RETAINER_PAUSED: 'Retainer paused', E.RETAINER_RESUMED: 'Retainer resumed',
    E.ESCROW_AUTO_FUNDING_FAILED: 'Automatic funding failed', E.ESCROW_AUTO_FUNDING_CHANGED: 'Automatic funding changed',
    E.ENTERPRISE_READINESS_DECIDED: 'Enterprise readiness decided',
    E.PROPOSAL_REQUEST_REMINDER: 'A request is waiting for your answer', E.PROPOSAL_REQUEST_UNANSWERED: 'No proposal yet',
    E.CONTRACT_TERMINATED: 'Engagement terminated', E.CONTRACT_PROFESSIONAL_STATUS_CHANGED: 'Change affecting your engagement',
    E.CONTRACT_TERMINATION_REQUESTED: 'Request to end the engagement',
    E.CONTRACT_TERMINATION_DECLINED: 'Request to end the engagement declined',
    E.CONTRACT_TERMINATION_WITHDRAWN: 'Request to end the engagement closed', E.SIGNATURE_DEADLINE_ESCALATED: 'Signature overdue',
    E.CHANGE_ORDER_REQUESTED: 'Contract change proposed', E.CHANGE_ORDER_APPROVED: 'Contract change approved',
    E.CHANGE_ORDER_REJECTED: 'Contract change declined', E.CONTRACT_AMENDED: 'Contract amendment signed',
    E.ESCROW_FUNDED: 'Payment held in escrow', E.ESCROW_RELEASED: 'Milestone payment released',
    E.ESCROW_REFUNDED: 'Escrow refund arranged', E.PAYMENT_FAILED: 'Payment unsuccessful',
    E.PAYOUT_SETTLED: 'Payout completed', E.PAYOUT_FAILED: 'Payout needs attention',
    E.MILESTONE_SUBMITTED: 'Work submitted for review', E.MILESTONE_ACCEPTED: 'Milestone accepted',
    E.MILESTONE_REVISION_REQUESTED: 'Work changes requested', E.MILESTONE_ACCEPTANCE_REMINDER: 'Review reminder',
    E.MILESTONE_ACCEPTANCE_OVERDUE: 'Milestone review overdue',
    E.MILESTONE_FUNDING_REMINDER: 'Funding due soon', E.MILESTONE_FUNDING_REVERSED: 'Payment reversed: pause work on this milestone',
    E.MILESTONE_PARTIAL_ACCEPTANCE_OFFERED: 'Partial acceptance offered', E.MILESTONE_PARTIAL_ACCEPTANCE_DECLINED: 'Partial acceptance declined',
    E.ESCROW_RELEASE_BLOCKED: 'Payment release not approved', E.REFUND_SETTLED: 'Refund completed',
    E.REFUND_FAILED: 'Refund could not be completed',
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
    E.SAVED_PROFESSIONAL_AVAILABLE: 'A saved professional is available', E.SAVED_SEARCH_MATCHES: 'New matches for your saved search',
    E.DISPUTE_CLARIFICATION_REQUESTED: 'The mediator has a question',
    E.DISPUTE_REFERRED_TO_ARBITRATION: 'Dispute referred to external arbitration',
    E.SESSION_CREATED: 'New sign-in to your account', E.TRUST_TIER_NUDGE: 'Verify to work with this buyer',
    E.USER_REPORT_SUBMITTED: 'Report received', E.USER_REPORT_CLOSED: 'Your report was reviewed',
    E.SUPPORT_REQUEST_ANSWERED: 'Support replied to your request', E.SUPPORT_REQUEST_RESOLVED: 'Your support request was resolved',
}
# Always shown in the app (email still follows the person's preferences): disputes and money that needs action.
MUST_SEE = frozenset({E.PAYMENT_FAILED, E.MILESTONE_FUNDING_REVERSED, E.REFUND_FAILED, E.ESCROW_RELEASE_BLOCKED, E.PAYOUT_FAILED,
                      E.CONTRACT_PROFESSIONAL_STATUS_CHANGED})
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
    audience = 'BUYER' if p.get('buyersOnly') else p.get('audience')  # a notice for one side only
    if org_id and audience != 'PROFESSIONAL':
        wanted = [OrgRole.APPROVER, OrgRole.BUDGET_OWNER, OrgRole.LEGAL_REVIEWER, OrgRole.ORG_ADMIN] if event.eventType in (E.APPROVAL_REQUIRED, E.APPROVAL_ESCALATED) else None
        if event.eventType == E.EXCEPTION_REQUESTED:
            wanted = [OrgRole.EXCEPTION_AUTHORITY]
        found.update(await buyer.list_member_identities(session, org_id, wanted))
    pro = await professional.get_professional(session, pro_id) if pro_id else None
    if pro and audience != 'BUYER':
        found.add(pro.identity_id)
    if audience == 'PROFESSIONAL':  # only the professional, even when the event names the buyer
        found = {pro.identity_id} if pro else set()
    elif audience == 'BUYER' and pro:
        found.discard(pro.identity_id)
    return found, org_id, pro.identity_id if pro else None


def target_url(event, recipient, professional_identity):
    p = event.payload
    if event.eventType in (E.DATA_REQUEST_CREATED, E.DATA_REQUEST_COMPLETED, E.DATA_REQUEST_BLOCKED, E.DATA_REQUEST_CANCELLED):
        return '/app/settings'  # Settings > Privacy
    if domain_of(event.eventType) == 'identity':
        return '/app/security'
    if domain_of(event.eventType) == 'admin':
        return '/app/safety'
    if event.eventType == E.SAVED_SEARCH_MATCHES:
        return '/app/find?' + str(p.get('query') or '')
    if event.eventType == E.SAVED_PROFESSIONAL_AVAILABLE:
        return f"/professionals/{p.get('professionalRef') or ''}"
    if domain_of(event.eventType) == 'support':
        return '/app/help?request=' + str(p.get('requestId') or '')
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
    if event.eventType == E.SESSION_CREATED and not event.payload.get('newDevice'):
        return
    found, org_id, pro_identity = await recipients(session, event)
    mandatory = domain_of(event.eventType) in {'identity', 'admin'}
    must_see = mandatory or domain_of(event.eventType) == 'dispute' or event.eventType in MUST_SEE
    saved_buyer = (event.eventType == E.PROPOSAL_REQUESTED and org_id and _uuid(event.payload.get('professionalId'))
                   and await professional.saved_buyer_alerts(session, _uuid(event.payload['professionalId']), org_id))
    notice = event.payload.get('notice') if domain_of(event.eventType) == 'admin' else None
    body = '\n'.join(f'{key}: {value}' for key, value in notice.items()) if notice else \
        event.payload.get('message') or 'Open your workspace to review this update and any required action.'
    for recipient in found:
        prefs = await session.scalar(select(Preference).where(Preference.identity_id == recipient))
        priority = bool(saved_buyer and recipient == pro_identity)  # the professional asked to always hear from this buyer
        email_on = mandatory or priority or prefs is None or prefs.email
        in_app = must_see or priority or prefs is None or prefs.in_app
        if not email_on and not in_app:
            continue
        nid = uuid.uuid4()
        result = await session.execute(insert(Notification).values(id=nid, source_event_id=event.eventId,
            identity_id=recipient, event_type=event.eventType,
            title='New request from a saved buyer' if priority else EVENT_TITLES[event.eventType], body=body,
            url=target_url(event, recipient, pro_identity), notice=notice, mandatory=mandatory or priority, in_app=in_app,
            email_status='PENDING' if email_on else 'DISABLED', created_at=event.occurredAt).on_conflict_do_nothing(
                index_elements=['source_event_id', 'identity_id']).returning(Notification.id))
        if result.scalar_one_or_none():
            if email_on:
                await schedule_timer(session, EMAIL_TIMER, f'{nid}:0', clock.now())
            if in_app:
                from zoikorum.domains.notification import push
                if push.configured():
                    await schedule_timer(session, push.PUSH_TIMER, str(nid), clock.now())
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
    if not row.mandatory and prefs and prefs.digest != 'OFF' and row.event_type not in MUST_SEE:
        row.email_status = 'DIGEST'  # sent in the next daily or weekly summary
        return
    url = web_url(staff=recipient.staff) + row.url  # staff open links in the staff web app
    if row.event_type in {E.IDENTITY_CREATED, E.EMAIL_CONFIRMATION_REQUESTED, E.PASSWORD_RESET_REQUESTED}:
        purpose = 'password_reset' if row.event_type == E.PASSWORD_RESET_REQUESTED else 'email_confirm'
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
                clock.now() + timedelta(seconds=exponential(row.email_attempts + 1)))
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
        when = clock.now() + timedelta(seconds=exponential(delivery.attempts + 1))
        if when < delivery.retry_until:
            await schedule_timer(session, WEBHOOK_TIMER, f'{delivery.id}:{delivery.attempts}', when)
        else:
            delivery.status = 'FAILED'
    else:
        delivery.status, delivery.delivered_at = 'DELIVERED', clock.now()


def _out(p: Preference | None) -> PreferencesIO:
    return PreferencesIO() if p is None else PreferencesIO(email=p.email, inApp=p.in_app, sms=p.sms, marketing=p.marketing, digest=p.digest)


async def get_preferences(session: AsyncSession, actor: Actor) -> PreferencesIO:
    return _out(await session.scalar(select(Preference).where(Preference.identity_id == actor.identity_id)))


async def set_preferences(session: AsyncSession, actor: Actor, body: PreferencesIO) -> PreferencesIO:
    p = await session.scalar(select(Preference).where(Preference.identity_id == actor.identity_id).with_for_update())
    if p is None:
        p = Preference(id=uuid.uuid4(), identity_id=actor.identity_id)
        session.add(p)
    p.email, p.in_app, p.sms, p.marketing, p.digest = body.email, body.inApp, body.sms, body.marketing, body.digest
    await session.flush()
    record_event(session, E.NOTIFICATION_PREFERENCES_UPDATED, aggregate_type="NotificationPreferences", aggregate_id=p.id,
                 payload={"identityId": actor.identity_id, "email": p.email, "inApp": p.in_app, "sms": p.sms,
                          "marketing": p.marketing})
    return _out(p)



# ---- Email digests (Notifications: daily or weekly summary instead of one email per update) ---------------------------

DIGEST_TIMER = "notification.digest"  # daily at 06:00 UTC, re-arms itself; weekly digests go out on Mondays


def _next_digest(now):
    from datetime import datetime as _dt, time as _time, timezone as _tz
    run = _dt.combine(now.date(), _time(6, 0), tzinfo=_tz.utc)
    return run if run > now else run + timedelta(days=1)


async def bootstrap_digests(session) -> None:
    nxt = _next_digest(clock.now())
    await schedule_timer(session, DIGEST_TIMER, nxt.date().isoformat(), nxt)


async def send_digests(session, *, rearm: bool = True) -> int:
    """One email per person with everything held for the digest since the last one; urgent and security messages are
    never held."""
    sent = 0
    weekly_day = clock.now().weekday() == 0
    for p in (await session.scalars(select(Preference).where(Preference.digest.in_(("DAILY", "WEEKLY"))).with_for_update(skip_locked=True))).all():
        if p.digest == "WEEKLY" and not weekly_day:
            continue
        held = (await session.scalars(select(Notification).where(Notification.identity_id == p.identity_id,
                                                                  Notification.email_status == "DIGEST").order_by(Notification.created_at))).all()
        if not held:
            continue
        recipient = await identity.get_identity(session, p.identity_id)
        if not recipient or recipient.status != "ACTIVE":
            continue
        base = web_url(staff=recipient.staff)
        lines = [f"- {n.title}: {n.body.splitlines()[0][:200] if n.body else ''}\n  {base}{n.url}" for n in held[:50]]
        more = f"\n...and {len(held) - 50} more in your notifications." if len(held) > 50 else ""
        subject = f"Your Zoikorum {'daily' if p.digest == 'DAILY' else 'weekly'} summary: {len(held)} update{'s' if len(held) != 1 else ''}"
        try:
            await providers.email_provider().send(recipient.email, subject, "\n".join(lines) + more, f"digest-{p.identity_id}-{clock.now():%Y%m%d}")
        except Exception:
            continue  # tried again at the next run; nothing is lost
        now = clock.now()
        for n in held:
            n.email_status, n.delivered_at = "DIGESTED", now
        p.digest_sent_at = now
        sent += 1
    if rearm:
        nxt = _next_digest(clock.now())
        await schedule_timer(session, DIGEST_TIMER, nxt.date().isoformat(), nxt)
    return sent


# ---- Private calendar feed (milestone due dates and deadlines in Google, Outlook or Apple Calendar) ---------------------

async def calendar_link(session, actor, rotate: bool) -> dict:
    """Create (or replace) the private address of the person's calendar feed. Only its SHA-256 is stored; replacing it
    stops the old address at once."""
    import hashlib
    import secrets as _secrets

    p = await session.scalar(select(Preference).where(Preference.identity_id == actor.identity_id).with_for_update())
    if p is None:
        p = Preference(id=uuid.uuid4(), identity_id=actor.identity_id)
        session.add(p)
    if not rotate:
        p.calendar_token_hash = None
        await session.flush()
        return {"url": None}
    token = _secrets.token_urlsafe(24)
    p.calendar_token_hash = hashlib.sha256(token.encode()).hexdigest()
    await session.flush()
    return {"url": f"/v1/calendar/{token}.ics", "note": "Anyone with this address can see your dates. Replace it if it is shared."}


def _ics_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


async def calendar_feed(session, token: str) -> str:
    import hashlib

    from zoikorum.domains.contract import facade as contract_facade
    from zoikorum.domains.professional import facade as professional_facade

    p = await session.scalar(select(Preference).where(Preference.calendar_token_hash == hashlib.sha256(token.encode()).hexdigest()))
    if p is None:
        raise NotFound("Calendar not found")
    account = await identity.get_identity(session, p.identity_id)
    if not account or account.status != "ACTIVE":
        raise NotFound("Calendar not found")
    orgs = await buyer.list_identity_organizations(session, p.identity_id)
    pro = await professional_facade.get_professional_by_identity(session, p.identity_id)
    items = await contract_facade.upcoming_dates(session, orgs, pro.id if pro else None)
    base = web_url(staff=account.staff)
    stamp = clock.now().strftime("%Y%m%dT%H%M%SZ")
    out = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Zoikorum//Engagement dates//EN", "CALSCALE:GREGORIAN",
           "X-WR-CALNAME:Zoikorum", "REFRESH-INTERVAL;VALUE=DURATION:PT6H"]
    for it in items:
        day = it["date"].strftime("%Y%m%d")
        nxt = (it["date"] + timedelta(days=1)).strftime("%Y%m%d")
        out += ["BEGIN:VEVENT", f"UID:{it['uid']}@zoikorum", f"DTSTAMP:{stamp}", f"DTSTART;VALUE=DATE:{day}", f"DTEND;VALUE=DATE:{nxt}",
                f"SUMMARY:{_ics_escape(it['title'])}", f"DESCRIPTION:{_ics_escape(it['detail'] + ' ' + base + it['path'])}",
                f"URL:{base}{it['path']}", "END:VEVENT"]
    out.append("END:VCALENDAR")
    return "\r\n".join(out) + "\r\n"
