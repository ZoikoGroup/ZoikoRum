"""Reviewed exports enforce owner scope, encryption, redaction and actual expiry purging."""
from datetime import timedelta
from sqlalchemy import select
from zoikorum.domains.identity.models import DataRequest
from zoikorum.domains.identity.privacy_access import expire_export
from zoikorum.domains.marketplace.models import SavedSearch
from zoikorum.shared import clock
from zoikorum.shared.privacy_exports import portable

async def test_access_export_is_reviewed_scoped_encrypted_and_expired(client, make_user, sf, drain):
    owner = await make_user('privacy-owner')
    other = await make_user('privacy-other')
    staff = await make_user('privacy-reviewer', platform_roles=('COMPLIANCE_OFFICER',))
    await staff.step_up()
    async with sf() as session, session.begin():
        for user, name in [(owner, 'Owner confidential search'), (other, 'Other private search')]:
            session.add(SavedSearch(identity_id=user.id, name=name, params={'q': name}, last_viewed_at=clock.now()))
    requested = await client.post('/v1/me/data-requests', headers=owner.h, json={'requestType': 'ACCESS'})
    assert requested.status_code == 201
    request_id = requested.json()['id']
    path = '/v1/admin/privacy-requests/' + request_id + '/access'
    body = {'note': 'Reviewed account scope; internal security records require separate assessment.'}
    assert (await client.post(path, headers=other.h, json=body)).status_code == 403
    fulfilled = await client.post(path, headers=staff.h, json=body)
    assert fulfilled.status_code == 200, fulfilled.text
    assert fulfilled.json()['exportReady'] is True
    await owner.step_up()
    downloaded = await client.get('/v1/me/data-requests/'+request_id+'/reviewed-copy', headers=owner.h)
    assert downloaded.status_code == 200, downloaded.text
    exported = downloaded.json()
    assert exported['identityId'] == str(owner.id)
    assert exported['sections']['marketplace']['saved_searches'][0]['name'] == 'Owner confidential search'
    assert 'Other private search' not in downloaded.text
    assert 'password_hash' not in downloaded.text and 'refresh_token_hash' not in downloaded.text
    await other.step_up()
    assert (await client.get('/v1/me/data-requests/'+request_id+'/reviewed-copy', headers=other.h)).status_code == 404
    async with sf() as session:
        row = await session.get(DataRequest, requested.json()['id'])
        assert row.export_payload_enc and 'Owner confidential search' not in row.export_payload_enc
    await drain()
    notices = (await client.get('/v1/notifications', headers=owner.h)).json()['items']
    assert any(n['title'] == 'Your privacy request is complete' and n['url'] == '/app/settings' for n in notices)
    async with sf() as session, session.begin():
        row = await session.get(DataRequest, request_id, with_for_update=True)
        row.export_expires_at = clock.now()-timedelta(seconds=1)
        await session.flush()
        await expire_export(session, request_id)
        assert row.export_payload_enc is None
    unavailable = await client.get('/v1/me/data-requests/'+request_id+'/reviewed-copy', headers=owner.h)
    assert unavailable.status_code == 409 and unavailable.json()['code'] == 'PRIVACY_EXPORT_UNAVAILABLE'


def test_nested_exports_do_not_leak_storage_keys_or_authentication_tokens():
    assert portable({'files': [{'name': 'evidence.pdf', 'storage_key': 'private-key', 'storageKey': 'private-key'}],
        'accessToken': 'secret', 'refresh_token_hash': 'secret'}) == {'files': [{'name': 'evidence.pdf'}]}


async def test_financial_exports_do_not_disclose_the_counterparty_payouts(sf):
    import uuid
    from zoikorum.domains.payments.models import Payout
    from zoikorum.domains.payments.facade import privacy_export_contracts
    contract_id, own_pro, other_pro = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    async with sf() as session, session.begin():
        for professional_id in (own_pro, other_pro):
            session.add(Payout(release_id=uuid.uuid4(), professional_id=professional_id,
                contract_id=contract_id, gross_minor=1000, fee_minor=100, amount_minor=900,
                currency='USD', status='SETTLED', transfer_ref='private-partner-reference'))
    async with sf() as session:
        buyer = await privacy_export_contracts(session, [contract_id])
        assert buyer['payouts'] == []
        professional = await privacy_export_contracts(session, [], own_pro)
        assert len(professional['payouts']) == 1
        assert professional['payouts'][0]['professional_id'] == str(own_pro)
        assert 'private-partner-reference' not in str(professional)
