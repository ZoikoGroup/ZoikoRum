"""Authentic signed receipts, late-event handling, scope and bounce suppression."""
import base64
import json
import uuid
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from sqlalchemy import select
from zoikorum.config import get_settings
from zoikorum.domains.notification.models import Notification, EmailReceipt
from zoikorum.domains.notification import service
from zoikorum.shared import clock
from zoikorum.shared.event_catalog import E

async def test_signed_receipts_are_deduplicated_scoped_and_suppress_bounced_addresses(client, make_user, sf, monkeypatch):
    user = await make_user('email-recipient')
    other = await make_user('email-other')
    key = ec.generate_private_key(ec.SECP256R1())
    public = key.public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
    monkeypatch.setattr(get_settings(), 'sendgrid_webhook_public_key', base64.b64encode(public).decode())
    async def notification():
        async with sf() as session, session.begin():
            row = Notification(identity_id=user.id, source_event_id=uuid.uuid4(), event_type=E.PROPOSAL_REQUESTED,
                title='New request', body='Open your request', url='/app/requests', in_app=True, mandatory=True,
                email_status='ACCEPTED', email_attempts=1)
            session.add(row)
            await session.flush()
            return row.id
    row_id = await notification()
    def payload(kind, identifier):
        return {'sg_event_id': identifier, 'event': kind, 'zoikorum_notification_id': str(row_id),
                'email': user.email, 'timestamp': int(clock.now().timestamp())}
    async def send(events, invalid=False):
        raw = json.dumps(events).encode()
        timestamp = str(int(clock.now().timestamp()))
        signature = key.sign(timestamp.encode()+raw, ec.ECDSA(hashes.SHA256()))
        return await client.post('/v1/webhooks/sendgrid', content=raw+b' ' if invalid else raw,
            headers={'X-Twilio-Email-Event-Webhook-Signature': base64.b64encode(signature).decode(),
                     'X-Twilio-Email-Event-Webhook-Timestamp': timestamp, 'Content-Type': 'application/json'})
    event = payload('delivered', 'delivered-receipt')
    assert (await send([event], invalid=True)).status_code == 401
    receipt = await send([event])
    assert receipt.status_code == 200 and receipt.json()['processed'] == 1, receipt.text
    assert (await send([event])).json()['processed'] == 0
    owner = await client.get(f'/v1/notifications/{row_id}/email-status', headers=user.h)
    assert owner.json()['status'] == 'DELIVERED'
    assert (await client.get(f'/v1/notifications/{row_id}/email-status', headers=other.h)).status_code == 404
    assert (await send([payload('bounce', 'bounce-receipt')])).status_code == 200
    assert (await send([payload('processed', 'late-processed'), payload('delivered', 'late-delivered')])).status_code == 200
    assert (await client.get(f'/v1/notifications/{row_id}/email-status', headers=user.h)).json()['status'] == 'BOUNCED'
    next_id = await notification()
    async with sf() as session, session.begin():
        row = await session.get(Notification, next_id)
        row.email_status = 'PENDING'
        await session.flush()
        await service.deliver_email(session, str(next_id))
        assert row.email_status == 'SUPPRESSED' and row.in_app is True
    async with sf() as session:
        rows = (await session.scalars(select(EmailReceipt).where(EmailReceipt.notification_id == row_id))).all()
        assert len(rows) == 4
