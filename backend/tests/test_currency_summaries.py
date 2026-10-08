"""Earnings summaries include all records, preserve currency and remain scoped to the professional."""
import uuid
from datetime import timedelta

from zoikorum.domains.payments.models import Payout
from zoikorum.shared import clock


async def test_earnings_all_history_and_monthly_currency_groups(client, make_user, drain, sf):
    owner = await make_user('currency-owner', account_type='PROFESSIONAL')
    pro = (await client.post('/v1/professionals', headers=owner.h, json={})).json()
    await drain()
    now = clock.now()
    start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    async with sf() as session, session.begin():
        for i in range(205):
            session.add(Payout(release_id=uuid.uuid4(), professional_id=uuid.UUID(pro['id']), contract_id=uuid.uuid4(),
                gross_minor=110, fee_minor=10, amount_minor=100, currency='USD', status='SETTLED', settled_at=start - timedelta(days=1)))
        for currency, status, amount, date in [('USD', 'SETTLED', 300, now), ('EUR', 'SETTLED', 700, now),
                                              ('EUR', 'QUEUED', 500, None), ('USD', 'FAILED', 400, None)]:
            session.add(Payout(release_id=uuid.uuid4(), professional_id=uuid.UUID(pro['id']), contract_id=uuid.uuid4(),
                gross_minor=amount + 10, fee_minor=10, amount_minor=amount, currency=currency, status=status, settled_at=date))
        session.add(Payout(release_id=uuid.uuid4(), professional_id=uuid.uuid4(), contract_id=uuid.uuid4(),
            gross_minor=9999, fee_minor=0, amount_minor=9999, currency='EUR', status='SETTLED', settled_at=now))
    response = await client.get('/v1/payments/earnings/me', headers=owner.h)
    assert response.status_code == 200, response.text
    data = response.json()
    assert len(data['payouts']) == 200
    assert data['totals'] == {}  # No misleading single-currency answer.
    groups = data['totalsByCurrency']
    assert groups['USD']['settled'] == {'currency': 'USD', 'amountMinor': 20800}
    assert groups['USD']['failed']['amountMinor'] == 400
    assert groups['EUR']['settled']['amountMinor'] == 700
    assert groups['EUR']['pending']['amountMinor'] == 500
    assert data['monthlySettledByCurrency'] == [{'currency': 'EUR', 'amountMinor': 700}, {'currency': 'USD', 'amountMinor': 300}]
