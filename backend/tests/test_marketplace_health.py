"""Platform Analytics: windowed marketplace health, the daily series and who may rebuild projections."""
from datetime import datetime, timedelta, timezone

from zoikorum.shared import clock


async def test_marketplace_health_window_and_daily_series(client, make_user, drain):
    from test_dispute import funded_contract
    pro_user, _, buyer, c = await funded_contract(client, make_user, drain, both=True)
    for m in c['milestones']:
        assert (await client.post(f"/v1/milestones/{m['id']}/submit", headers=pro_user.idem(), json={'note': 'Completed agreed deliverables', 'files': []})).status_code == 200
        assert (await client.post(f"/v1/milestones/{m['id']}/accept", headers=buyer.idem())).status_code == 200
        await drain()
    analyst = await make_user('health-analyst', platform_roles=('TS_ANALYST',))
    await analyst.step_up()
    await drain()

    everything = await client.get('/v1/analytics/marketplace-health', headers=analyst.h)
    assert everything.status_code == 200, everything.text
    body = everything.json()
    assert body['activations'] >= 1 and body['medianReleaseLatencySeconds'] >= 0
    assert body['searches'] == body['eventCounts'].get('zoikorum.search.query.performed.v1', 0)
    assert body['activations'] == sum(day['activations'] for day in body['daily'])
    assert [day['date'] for day in body['daily']] == sorted(day['date'] for day in body['daily'])

    today = datetime.combine(clock.now().astimezone(timezone.utc).date(), datetime.min.time(), tzinfo=timezone.utc)
    window = await client.get('/v1/analytics/marketplace-health', headers=analyst.h,
                              params={'from': today.isoformat(), 'to': (today + timedelta(days=1)).isoformat()})
    assert window.status_code == 200, window.text
    day = window.json()
    assert [d['date'] for d in day['daily']] == [today.date().isoformat()]
    assert day['daily'][0]['activations'] == day['activations'] >= 1
    assert day['daily'][0]['releases'] == day['eventCounts']['zoikorum.escrow.account.released.v1'] >= 1

    future = (await client.get('/v1/analytics/marketplace-health', headers=analyst.h,
                               params={'from': (today + timedelta(days=2)).isoformat()})).json()
    assert future['eventCounts'] == {} and future['daily'] == [] and future['lastEventAt'] is None
    assert future['medianReleaseLatencySeconds'] is None and future['proposalContractConversionBps'] is None
    assert future['trustTierDistribution'] == body['trustTierDistribution']  # a current snapshot, not windowed

    assert (await client.get('/v1/analytics/marketplace-health', headers=buyer.h)).status_code == 403
    assert (await client.post('/v1/admin/analytics/rebuild', headers=analyst.h)).status_code == 403


async def test_rebuild_reproduces_marketplace_health(client, make_user, drain):
    from test_dispute import funded_contract
    pro_user, _, buyer, c = await funded_contract(client, make_user, drain, both=True)
    for m in c['milestones']:
        assert (await client.post(f"/v1/milestones/{m['id']}/submit", headers=pro_user.idem(), json={'note': 'Completed agreed deliverables', 'files': []})).status_code == 200
        assert (await client.post(f"/v1/milestones/{m['id']}/accept", headers=buyer.idem())).status_code == 200
        await drain()
    admin = await make_user('health-admin', platform_roles=('PLATFORM_ADMIN',))
    await admin.step_up()
    await drain()

    before = (await client.get('/v1/analytics/marketplace-health', headers=admin.h)).json()
    rebuilt = await client.post('/v1/admin/analytics/rebuild', headers=admin.h)
    assert rebuilt.status_code == 200, rebuilt.text
    assert rebuilt.json()['projectedEvents'] == sum(before['eventCounts'].values())
    after = (await client.get('/v1/analytics/marketplace-health', headers=admin.h)).json()
    assert after == before
    assert after['activations'] >= 1 and after['medianReleaseLatencySeconds'] is not None
