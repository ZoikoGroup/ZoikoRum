"""Policy-pinned automatic intake must freeze funded work, deduplicate and remain neutral."""
from datetime import timedelta
from test_proposal import tier_b, buyer_org, request_body, proposal_body
from test_escrow import escrow_of
from zoikorum.shared import clock


async def policy_contract(client, make_user, drain, settings):
    pro_user, pro = await tier_b(client, make_user, drain, 'automatic-pro')
    buyer, org = await buyer_org(client, make_user, drain)
    await buyer.step_up()
    response = await client.post('/v1/policy/profiles', headers=buyer.idem(), json={'orgId': org['id'], 'name': 'Automatic dispute controls', 'settings': settings, 'rules': []})
    assert response.status_code == 201, response.text
    pid = response.json()['id']
    activated = await client.post(f'/v1/policy/profiles/{pid}/activate', headers=buyer.idem())
    assert activated.status_code == 200, activated.text
    requested = await client.post('/v1/proposal-requests', headers=buyer.idem(), json=request_body(org, pro))
    assert requested.status_code == 201, requested.text
    rid = requested.json()[0]['id']
    body = proposal_body()
    body['milestones'][0]['dueDate'] = (clock.now().date() + timedelta(days=11)).isoformat()
    proposed = await client.post(f'/v1/proposal-requests/{rid}/proposals', headers=pro_user.h, json=body)
    assert proposed.status_code == 201, proposed.text
    proposal_id = proposed.json()['id']
    assert (await client.post(f'/v1/proposals/{proposal_id}/submit', headers=pro_user.idem())).status_code == 200
    accepted = await client.post(f'/v1/proposals/{proposal_id}/accept', headers=buyer.idem())
    assert accepted.status_code == 200, accepted.text
    await drain()
    c = (await client.get('/v1/contracts', headers=buyer.h)).json()['items'][0]
    await pro_user.step_up()
    for party in (buyer, pro_user):
        response = await client.post(f"/v1/contracts/{c['id']}/sign", headers=party.idem(), json={'termsHash': c['termsHash'], 'acknowledged': True})
        assert response.status_code == 200, response.text
    await drain()
    escrow = await escrow_of(client, buyer, c)
    funded = await client.post(f"/v1/escrow/{escrow['id']}/fund", headers=buyer.idem(), json={'all': True, 'paymentMethodToken': 'tok_visa'})
    assert funded.status_code == 200, funded.text
    await drain()
    return pro_user, pro, buyer, c


async def test_repeated_rejection_triggers_once_and_does_not_punish_filing(client, make_user, drain):
    pro_user, pro, buyer, c = await policy_contract(client, make_user, drain, {'autoDisputeRejectionCount': 2})
    mid = c['milestones'][0]['id']
    for attempt in range(2):
        submitted = await client.post(f'/v1/milestones/{mid}/submit', headers=pro_user.idem(), json={'note': 'Submitted the complete deliverables for review', 'files': []})
        assert submitted.status_code == 200, submitted.text
        revised = await client.post(f'/v1/milestones/{mid}/request-revision', headers=buyer.h, json={'reason': 'Please address the documented acceptance criteria.'})
        assert revised.status_code == 200, revised.text
        await drain()
    cases = (await client.get('/v1/disputes', headers=buyer.h, params={'contractId': c['id']})).json()
    assert len(cases) == 1 and cases[0]['initiatorParty'] == 'PLATFORM'
    escrow = await escrow_of(client, buyer, c)
    assert escrow['allocations'][0]['state'] == 'ON_HOLD'
    await drain()
    assert len((await client.get('/v1/disputes', headers=buyer.h, params={'contractId': c['id']})).json()) == 1
    assert (await client.get(f"/v1/trust/professionals/{pro['id']}")).json()['tier'] == 'B'


async def test_confirmed_revocation_triggers_intake_but_an_advisory_flag_does_not(client, make_user, drain, sf):
    import uuid
    from zoikorum.domains.verification import facade as verification
    from zoikorum.shared.events import record_event
    from zoikorum.shared.event_catalog import E
    pro_user, pro, buyer, c = await policy_contract(client, make_user, drain, {'autoDisputeComplianceFlag': True})
    async with sf() as session, session.begin():
        record_event(session, E.RISK_FLAG_RAISED, aggregate_type='Professional', aggregate_id=pro['id'],
            payload={'subjectType': 'PROFESSIONAL', 'subjectId': pro['id'], 'reasonCodes': ['REVIEW_NEEDED'], 'advisoryOnly': True})
    await drain()
    assert (await client.get('/v1/disputes', headers=buyer.h, params={'contractId': c['id']})).json() == []
    assert (await client.get(f"/v1/trust/professionals/{pro['id']}")).json()['tier'] == 'B'
    async with sf() as session:
        checks = await verification.get_checks(session, 'PROFESSIONAL', uuid.UUID(pro['id']))
        identity_check = next(check for check in checks if check.verification_type == 'IDENTITY' and check.status == 'VERIFIED')
    reviewer = await make_user('confirmed-compliance-reviewer', platform_roles=('COMPLIANCE_OFFICER',))
    await reviewer.step_up()
    revoked = await client.post(f'/v1/verification/cases/{identity_check.case_id}/revoke', headers=reviewer.h,
        json={'reasonCode': 'CONFIRMED_REVOCATION', 'publicReason': 'The independently reviewed identity evidence is no longer valid.'})
    assert revoked.status_code == 200, revoked.text
    await drain()
    cases = (await client.get('/v1/disputes', headers=buyer.h, params={'contractId': c['id']})).json()
    assert len(cases) == 1 and cases[0]['initiatorParty'] == 'PLATFORM' and cases[0]['category'] == 'COMPLIANCE_BREACH'
    escrow = await escrow_of(client, buyer, c)
    assert all(allocation['state'] == 'ON_HOLD' for allocation in escrow['allocations'])
    await drain()
    assert len((await client.get('/v1/disputes', headers=buyer.h, params={'contractId': c['id']})).json()) == 1
    trust = await client.get(f"/v1/trust/professionals/{pro['id']}")
    assert trust.status_code == 200 and trust.json()['tier'] == 'C'


async def test_missed_deadline_policy_is_pinned_and_uses_actual_funded_state(client, make_user, drain):
    pro_user, pro, buyer, c = await policy_contract(client, make_user, drain, {'autoDisputeMissedDeadline': True})
    current = (await client.get(f"/v1/contracts/{c['id']}", headers=buyer.h)).json()
    assert current['terms']['policySettings']['autoDisputeMissedDeadline'] is True
    clock.advance(timedelta(days=12)); await drain(); clock.set_now(None)
    cases = (await client.get('/v1/disputes', headers=buyer.h, params={'contractId': c['id']})).json()
    assert len(cases) == 1 and cases[0]['category'] == 'TIMELINE_DELAY'
    escrow = await escrow_of(client, buyer, c)
    assert escrow['allocations'][0]['state'] == 'ON_HOLD'
