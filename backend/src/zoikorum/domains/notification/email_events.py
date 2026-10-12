"""Verify SendGrid's signature over raw bytes; apply durable, monotonic receipts."""
import base64
import hashlib
import json
import uuid
from datetime import datetime, timezone
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from zoikorum.config import get_settings
from zoikorum.domains.notification.models import EmailReceipt, EmailSuppression, Notification
from zoikorum.domains.identity import facade as identity
from zoikorum.shared import clock
from zoikorum.shared.crypto import sha256_hex
from zoikorum.shared.errors import Unauthenticated, ValidationFailed, ServiceUnavailable, Conflict
from zoikorum.shared.events import record_event
from zoikorum.shared.event_catalog import E

STATES = {'processed': 'ACCEPTED', 'deferred': 'DEFERRED', 'delivered': 'DELIVERED',
          'bounce': 'BOUNCED', 'dropped': 'FAILED', 'spamreport': 'SUPPRESSED', 'unsubscribe': 'SUPPRESSED'}
RANK = {'PENDING': 0, 'ACCEPTED': 1, 'DEFERRED': 2, 'DELIVERED': 3, 'FAILED': 4, 'BOUNCED': 5, 'SUPPRESSED': 6}

def verify(raw, signature, timestamp):
    settings = get_settings()
    if not settings.sendgrid_webhook_public_key:
        raise ServiceUnavailable('Signed email webhook is not configured', code='INTEGRATION_NOT_CONFIGURED')
    try:
        instant = int(timestamp)
        if abs(clock.now().timestamp() - instant) > settings.webhook_tolerance_seconds:
            raise ValueError('Expired signature')
        key = serialization.load_der_public_key(base64.b64decode(settings.sendgrid_webhook_public_key, validate=True))
        if not isinstance(key, ec.EllipticCurvePublicKey):
            raise ValueError('Invalid signing key')
        key.verify(base64.b64decode(signature, validate=True), timestamp.encode('ascii') + raw, ec.ECDSA(hashes.SHA256()))
    except (InvalidSignature, ValueError, TypeError, UnicodeError) as error:
        raise Unauthenticated('Invalid email webhook signature') from error

async def receive(session, raw, signature, timestamp):
    if len(raw) > 1024 * 1024:
        raise ValidationFailed('Email webhook exceeds the allowed size')
    verify(raw, signature, timestamp)
    try:
        events = json.loads(raw)
    except (ValueError, UnicodeError) as error:
        raise ValidationFailed('Invalid email event payload') from error
    if not isinstance(events, list) or len(events) > 1000:
        raise ValidationFailed('Expected a bounded email event batch')
    processed = 0
    for event in events:
        if not isinstance(event, dict):
            raise ValidationFailed('Invalid email event')
        kind = event.get('event')
        if not isinstance(kind, str):
            raise ValidationFailed('Invalid email event type')
        if kind not in STATES or not event.get('zoikorum_notification_id'):
            continue
        try:
            if not isinstance(event['zoikorum_notification_id'], str):
                raise ValueError('Invalid notification id')
            notification_id = uuid.UUID(event['zoikorum_notification_id'])
            provider_id = event['sg_event_id']
            if not isinstance(provider_id, str) or not 1 <= len(provider_id) <= 200:
                raise ValueError('Invalid event id')
            occurred_at = datetime.fromtimestamp(int(event['timestamp']), timezone.utc)
        except (KeyError, ValueError, TypeError, OverflowError, OSError) as error:
            raise ValidationFailed('Invalid email event reference') from error
        row = await session.scalar(select(Notification).where(Notification.id == notification_id).with_for_update())
        if not row:
            continue
        recipient = await identity.get_identity(session, row.identity_id)
        if not recipient or str(event.get('email', '')).strip().lower() != recipient.email.strip().lower():
            continue
        digest = hashlib.sha256(json.dumps(event, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        existing = await session.scalar(select(EmailReceipt).where(EmailReceipt.provider_event_id == provider_id))
        if existing:
            if existing.payload_sha256 != digest:
                raise Conflict('Email event identifier was reused with different content')
            continue
        inserted = await session.scalar(insert(EmailReceipt).values(id=uuid.uuid4(), provider_event_id=provider_id,
            notification_id=row.id, event_type=kind, occurred_at=occurred_at, payload_sha256=digest)
            .on_conflict_do_nothing(index_elements=['provider_event_id']).returning(EmailReceipt.id))
        if not inserted:
            continue
        processed += 1
        state = STATES[kind]
        if RANK.get(state, 0) >= RANK.get(row.email_status, 0):
            row.email_status = state
            row.delivered_at = occurred_at if state == 'DELIVERED' else None
            row.last_error = None if state == 'DELIVERED' else ('Email provider reported ' + state.lower() if state in ('FAILED', 'BOUNCED', 'SUPPRESSED') else None)
            if state not in ('ACCEPTED', 'DEFERRED'):
                record_event(session, E.NOTIFICATION_DELIVERED if state == 'DELIVERED' else E.NOTIFICATION_FAILED,
                aggregate_type='Notification', aggregate_id=row.id,
                payload={'notificationId': row.id, 'identityId': row.identity_id, 'channel': 'EMAIL', 'status': state})
        if kind in ('spamreport', 'unsubscribe') or (kind == 'bounce' and event.get('type') != 'blocked'):
            await session.execute(insert(EmailSuppression).values(id=uuid.uuid4(),
                address_sha256=sha256_hex(recipient.email.strip().lower()), reason=kind)
                .on_conflict_do_nothing(index_elements=['address_sha256']))
    return {'processed': processed}
