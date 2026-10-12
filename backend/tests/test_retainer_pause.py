"""Pausing affects new funding, not signed terms or already funded work."""
import uuid
from sqlalchemy import update
from zoikorum.domains.contract.models import Contract
from test_contract import C, signed_contract
from test_escrow import escrow_of

async def test_pause_resume_is_authorized_and_blocks_funding(client, make_user, drain, sf):
    pro_user, pro, buyer, c = await signed_contract(client, make_user, drain)
    async with sf() as session, session.begin():
        await session.execute(update(Contract).where(Contract.id == uuid.UUID(c['id'])).values(pricing_model='RETAINER'))
    rejected = await client.post(f"{C}/{c['id']}/retainer/pause", headers=pro_user.idem(), json={'reason': 'Pause future cycles'})
    assert rejected.status_code == 403
    paused = await client.post(f"{C}/{c['id']}/retainer/pause", headers=buyer.idem(), json={'reason': 'Pause future cycles'})
    assert paused.status_code == 200, paused.text
    assert paused.json()['retainerPaused'] is True
    assert paused.json()['termsHash'] == c['termsHash']
    assert paused.json()['contractVersion'] == c['contractVersion']
    escrow = await escrow_of(client, buyer, c)
    blocked = await client.post(f"/v1/escrow/{escrow['id']}/fund", headers=buyer.idem(), json={
        'milestoneIds': [c['milestones'][0]['id']], 'paymentMethodToken': 'tok_ok'})
    assert blocked.status_code == 409, blocked.text
    assert blocked.json()['code'] == 'RETAINER_PAUSED'
    resumed = await client.post(f"{C}/{c['id']}/retainer/resume", headers=buyer.idem(), json={'reason': 'Restart future cycles'})
    assert resumed.status_code == 200, resumed.text
    assert resumed.json()['retainerPaused'] is False


async def test_cancel_preserves_a_cycle_with_payment_in_flight(client, make_user, drain, sf):
    pro_user, pro, buyer, c = await signed_contract(client, make_user, drain)
    async with sf() as session, session.begin():
        await session.execute(update(Contract).where(Contract.id == uuid.UUID(c['id'])).values(pricing_model='RETAINER'))
    escrow = await escrow_of(client, buyer, c)
    first, second = c['milestones']
    funding = await client.post(f"/v1/escrow/{escrow['id']}/fund", headers=buyer.idem(), json={
        'milestoneIds': [first['id']], 'paymentMethodToken': 'tok_visa'})
    assert funding.status_code == 200, funding.text
    cancelled = await client.post(f"{C}/{c['id']}/cancel-remaining-cycles", headers=buyer.idem(), json={'reason': 'Cancel future unfunded work'})
    assert cancelled.status_code == 200, cancelled.text
    statuses = {m['id']: m['status'] for m in cancelled.json()['milestones']}
    assert statuses[first['id']] == 'PENDING_FUNDING'
    assert statuses[second['id']] == 'CANCELLED'
    await drain()
    after = (await client.get(f"{C}/{c['id']}", headers=buyer.h)).json()
    assert after['milestones'][0]['status'] == 'IN_PROGRESS'
