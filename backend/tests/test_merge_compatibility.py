"""Dev's privacy lifecycle also handles maruthi's new credential and delivery records."""
import uuid
from sqlalchemy import select, func
from zoikorum.domains.identity import privacy as identity_privacy
from zoikorum.domains.notification import privacy as notification_privacy
from zoikorum.domains.identity.models import Passkey, AuthChallenge, FederationAccount, DataRequest
from zoikorum.domains.notification.models import Notification, EmailReceipt
from zoikorum.shared import clock

async def test_erasure_removes_new_authentication_records_and_notification_receipts(make_user, sf):
    user = await make_user('merged-erasure')
    async with sf() as session, session.begin():
        session.add(Passkey(identity_id=user.id, credential_id=b'credential', public_key=b'public-key', sign_count=0, label='Laptop'))
        session.add(AuthChallenge(identity_id=user.id, purpose='REGISTER', challenge=b'challenge', expires_at=clock.now()))
        session.add(FederationAccount(identity_id=user.id, organization_id=uuid.uuid4(), subject=str(uuid.uuid4()), active=True))
        session.add(DataRequest(identity_id=user.id, request_type='ACCESS', status='COMPLETED', export_payload_enc='encrypted-private-copy'))
        notice = Notification(identity_id=user.id, source_event_id=uuid.uuid4(), event_type='example.event.v1', title='Receipt', body='Message', url='/app', in_app=True, mandatory=False, email_status='DELIVERED')
        session.add(notice)
        await session.flush()
        session.add(EmailReceipt(notification_id=notice.id, provider_event_id='provider-event', event_type='delivered', occurred_at=clock.now(), payload_sha256='a'*64))
    async with sf() as session, session.begin():
        exported = await identity_privacy.export(session, user.id)
        assert 'encrypted-private-copy' not in str(exported)
        await notification_privacy.erase(session, user.id)
        await identity_privacy.erase(session, user.id)
        await session.flush()
        for model in (Passkey, AuthChallenge, FederationAccount, EmailReceipt):
            assert await session.scalar(select(func.count()).select_from(model)) == 0
        row = await session.scalar(select(DataRequest).where(DataRequest.identity_id == user.id))
        assert row.export_payload_enc is None
