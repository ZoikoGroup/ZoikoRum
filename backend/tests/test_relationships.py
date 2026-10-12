"""Private bookmarks and preferences never grant access to another professional's requests."""
import uuid
from sqlalchemy import select
from test_contract import signed_contract
from zoikorum.domains.notification.models import Notification
from zoikorum.shared.events import record_event
from zoikorum.shared.event_catalog import E

R = '/v1/professionals/me/relationships'

async def test_relationships_are_scoped_and_preferences_control_delivered_alerts(client, make_user, drain, sf):
    pro_user, pro, buyer, c = await signed_contract(client, make_user, drain)
    saved = await client.post(R, headers=pro_user.h, json={'requestId': c['requestId'], 'kind': 'BUYER'})
    assert saved.status_code == 201, saved.text
    row = saved.json()
    assert row['name'] == buyer.user['displayName']
    repeated = await client.post(R, headers=pro_user.h, json={'requestId': c['requestId'], 'kind': 'BUYER'})
    assert repeated.json()['id'] == row['id']
    followed = await client.post(R, headers=pro_user.h, json={'requestId': c['requestId'], 'kind': 'ORGANIZATION'})
    assert followed.status_code == 201, followed.text
    other = await make_user('unrelated-relationship')
    forbidden = await client.patch(f"{R}/{row['id']}", headers=other.h, json={'emailAlerts': False, 'inAppAlerts': False})
    assert forbidden.status_code in (403, 404)
    unknown = await client.post(R, headers=pro_user.h, json={'requestId': str(uuid.uuid4()), 'kind': 'BUYER'})
    assert unknown.status_code == 404
    changed = await client.patch(f"{R}/{row['id']}", headers=pro_user.h, json={'emailAlerts': False, 'inAppAlerts': False})
    assert changed.status_code == 200
    async def requested():
        async with sf() as session, session.begin():
            event = record_event(session, E.PROPOSAL_REQUESTED, aggregate_type='ProposalRequest', aggregate_id=c['requestId'],
                tenant_id=c['organizationId'], payload={'requestId': c['requestId'], 'professionalId': c['professionalId'],
                'buyerIdentityId': buyer.id, 'organizationId': c['organizationId']})
        await drain()
        async with sf() as session:
            return (await session.scalars(select(Notification).where(Notification.source_event_id == event.eventId,
                Notification.identity_id == pro_user.id))).all()
    assert await requested() == []
    await client.patch(f"{R}/{row['id']}", headers=pro_user.h, json={'emailAlerts': False, 'inAppAlerts': True})
    notices = await requested()
    assert len(notices) == 1
    assert notices[0].in_app is True and notices[0].email_status == 'DISABLED'
    assert (await client.delete(f"{R}/{row['id']}", headers=pro_user.h)).status_code == 204
    listing = (await client.get(R, headers=pro_user.h)).json()
    assert len(listing) == 1 and listing[0]['kind'] == 'ORGANIZATION'
