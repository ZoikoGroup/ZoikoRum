"""Money-flow gaps closed on 2026-10-12: funding only on an active contract, payments that finish after the work closed,
provider errors, refund failures, never-signed contracts, the fee fixed at activation, and spend limits."""

from __future__ import annotations


from sqlalchemy import text

from test_contract import C, accepted_contract, signed_contract
from test_dispute import D, dispute_body
from test_escrow import E, balanced, escrow_of
from zoikorum.domains.contract import service as contract_service
from zoikorum.domains.escrow import service as escrow_service
from zoikorum.domains.notification.service import EVENT_TITLES
from zoikorum.domains.payments import providers
from zoikorum.domains.payments import service as payments_service
from zoikorum.shared.errors import ServiceUnavailable, ValidationFailed
from zoikorum.shared.event_catalog import E as EV


async def fund(client, buyer, esc, ids):
    return await client.post(f"{E}/{esc['id']}/fund", headers=buyer.idem(), json={"milestoneIds": ids, "paymentMethodToken": "tok_visa"})


async def states(sf, contract_id) -> dict[int, str]:
    async with sf() as s:
        rows = (await s.execute(text("SELECT a.sequence, a.state FROM escrow.allocations a JOIN escrow.accounts x ON x.id = a.account_id "
                                     "WHERE x.contract_id = :c"), {"c": contract_id})).all()
    return dict(rows)


async def events(sf, kind: str) -> int:
    async with sf() as s:
        return await s.scalar(text("SELECT count(*) FROM platform.outbox WHERE event_type = :t"), {"t": kind})


async def test_no_funding_while_a_dispute_is_open(client, make_user, drain, sf):
    pro_user, pro, buyer, c = await signed_contract(client, make_user, drain)
    esc = await escrow_of(client, buyer, c)
    m1, m2 = c["milestones"]
    await fund(client, buyer, esc, [m1["id"]])
    await drain()
    assert (await client.post(D, headers=buyer.idem(), json=dispute_body(c))).status_code == 201
    await drain()
    blocked = await fund(client, buyer, esc, [m2["id"]])
    assert blocked.status_code == 409 and blocked.json()["code"] == "CONTRACT_NOT_ACTIVE"
    assert "dispute" in blocked.json()["detail"]
    assert (await escrow_of(client, buyer, c))["canFund"] is False  # the page does not offer it either
    assert (await states(sf, c["id"]))[2] == "UNFUNDED"


async def test_payment_finishing_after_the_work_closed_is_refunded(client, make_user, drain, sf, monkeypatch):
    """Checkout still open when the milestone is cancelled: the captured money goes straight back to the buyer. A refund the
    provider cannot make is announced and retried daily."""
    pro_user, pro, buyer, c = await signed_contract(client, make_user, drain)
    esc = await escrow_of(client, buyer, c)
    m2 = c["milestones"][1]
    assert (await fund(client, buyer, esc, [m2["id"]])).status_code == 200  # request recorded; the charge runs in the worker
    async with sf() as s, s.begin():  # meanwhile the milestone closes (e.g. a dispute decision ended the engagement)
        await s.execute(text("UPDATE contract.milestones SET status = 'CANCELLED' WHERE id = :m"), {"m": m2["id"]})
    failing = providers.FakeProvider()
    monkeypatch.setattr(failing, "refund", lambda *a, **k: providers.PayoutResult(False, failure_message="Card account closed"))
    monkeypatch.setattr(payments_service, "get_provider", lambda: failing)
    await drain()
    assert (await states(sf, c["id"]))[2] == "REFUNDED"
    assert await events(sf, EV.REFUND_FAILED) == 1
    monkeypatch.setattr(payments_service, "get_provider", providers.get_provider)
    async with sf() as s, s.begin():
        assert await payments_service.retry_failed_refunds(s) == 1
    async with sf() as s:
        assert await s.scalar(text("SELECT status FROM payments.refunds WHERE contract_id = :c"), {"c": c["id"]}) == "SETTLED"
    await balanced(sf)


async def test_provider_refusing_a_charge_is_a_failed_payment_not_a_stuck_one(client, make_user, drain, sf, monkeypatch):
    pro_user, pro, buyer, c = await signed_contract(client, make_user, drain)
    esc = await escrow_of(client, buyer, c)

    def refuse(*a, **k):
        raise ValidationFailed("Amount below the provider minimum", code="AMOUNT_TOO_SMALL")

    refusing = providers.FakeProvider()
    monkeypatch.setattr(refusing, "charge", refuse)
    monkeypatch.setattr(payments_service, "get_provider", lambda: refusing)
    await fund(client, buyer, esc, [c["milestones"][0]["id"]])
    await drain()
    assert (await states(sf, c["id"]))[1] == "UNFUNDED"
    funding = (await escrow_of(client, buyer, c))["fundings"][0]
    assert funding["status"] == "FAILED" and "minimum" in funding["failureMessage"]


async def test_funding_reverts_if_the_provider_never_starts_the_charge(client, make_user, drain, sf, monkeypatch):
    pro_user, pro, buyer, c = await signed_contract(client, make_user, drain)
    esc = await escrow_of(client, buyer, c)

    def down(*a, **k):
        raise ServiceUnavailable("Payment provider unavailable")

    unavailable = providers.FakeProvider()
    monkeypatch.setattr(unavailable, "charge", down)
    monkeypatch.setattr(payments_service, "get_provider", lambda: unavailable)
    await fund(client, buyer, esc, [c["milestones"][0]["id"]])
    await drain()
    assert (await states(sf, c["id"]))[1] == "FUNDING"  # retried in the background...
    async with sf() as s:
        funding_id = await s.scalar(text("SELECT id FROM escrow.fundings WHERE status = 'REQUESTED'"))
    async with sf() as s, s.begin():  # ...and after an hour of no charge at all, the buyer can try again
        await escrow_service.funding_check(s, {"fundingId": str(funding_id)})
    assert (await states(sf, c["id"]))[1] == "UNFUNDED"
    monkeypatch.setattr(payments_service, "get_provider", providers.get_provider)
    async with sf() as s, s.begin():  # a late retry does not charge a funding the buyer no longer has open
        await payments_service.charge_for_funding(s, {"fundingId": str(funding_id), "escrowAccountId": esc["id"], "contractId": c["id"],
                                                      "organizationId": c["organizationId"], "amountMinor": 1, "currency": "USD",
                                                      "paymentMethodToken": "tok_visa"})
        assert await s.scalar(text("SELECT count(*) FROM payments.payment_intents WHERE funding_id = :f"), {"f": funding_id}) == 0


async def test_an_agreement_nobody_signs_lapses(client, make_user, drain, sf):
    pro_user, pro, buyer, org, accepted, c = await accepted_contract(client, make_user, drain)
    async with sf() as s, s.begin():
        await contract_service.signature_deadline_passed(s, {"contractId": c["id"]})
        await contract_service.signature_expired(s, {"contractId": c["id"]})
    after = (await client.get(f"{C}/{c['id']}", headers=buyer.h)).json()
    assert after["status"] == "TERMINATED" and {m["status"] for m in after["milestones"]} == {"CANCELLED"}


async def test_the_fee_agreed_at_activation_is_the_one_charged(client, make_user, drain, sf):
    pro_user, pro, buyer, c = await signed_contract(client, make_user, drain)
    esc = await escrow_of(client, buyer, c)
    assert esc["feeBps"] == 1000
    async with sf() as s, s.begin():  # as if the platform fee had been 5% when this engagement started
        await s.execute(text("UPDATE escrow.accounts SET fee_bps = 500 WHERE id = :a"), {"a": esc["id"]})
    m1 = c["milestones"][0]
    await fund(client, buyer, esc, [m1["id"]])
    await drain()
    await client.post(f"/v1/milestones/{m1['id']}/submit", headers=pro_user.h, json={"note": "Delivered"})
    await client.post(f"/v1/milestones/{m1['id']}/accept", headers=buyer.idem())
    await drain()
    async with sf() as s:
        fee_bps, gross, fee = (await s.execute(text("SELECT fee_bps, gross_minor, fee_minor FROM escrow.releases WHERE milestone_id = :m"),
                                               {"m": m1["id"]})).one()
    assert fee_bps == 500 and fee == gross * 5 // 100
    await balanced(sf)


async def test_people_hear_about_money_events():
    for kind in (EV.MILESTONE_FUNDING_REMINDER, EV.MILESTONE_FUNDING_REVERSED, EV.MILESTONE_PARTIAL_ACCEPTANCE_OFFERED,
                 EV.ESCROW_RELEASE_BLOCKED, EV.REFUND_FAILED, EV.REFUND_SETTLED):
        assert kind in EVENT_TITLES


async def test_release_not_approved_is_announced(client, make_user, drain, sf):
    pro_user, pro, buyer, c = await signed_contract(client, make_user, drain)
    esc = await escrow_of(client, buyer, c)
    m1 = c["milestones"][0]
    await fund(client, buyer, esc, [m1["id"]])
    await drain()
    async with sf() as s, s.begin():
        await s.execute(text("UPDATE escrow.allocations SET state = 'RELEASE_PENDING_APPROVAL' WHERE milestone_id = :m"), {"m": m1["id"]})
        await escrow_service.release_not_approved(s, {"subjectId": m1["id"], "subjectType": "Milestone", "action": "ESCROW_RELEASE"},
                                                  EV.APPROVAL_DENIED)
    assert await events(sf, EV.ESCROW_RELEASE_BLOCKED) == 1
    assert (await states(sf, c["id"]))[1] == "RELEASE_PENDING_APPROVAL"  # neither paid nor refunded on one side's word
