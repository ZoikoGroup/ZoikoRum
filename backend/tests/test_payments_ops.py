"""Step 8 payment operations (Engineering Handbook 15.1/15.4, Payments & Escrow s.14/s.18): signed and idempotent provider
webhooks, chargebacks, expected payout dates with delay reasons, and daily reconciliation."""

from __future__ import annotations

import json
from datetime import timedelta

from sqlalchemy import text

from test_contract import C, signed_contract
from test_dispute import staff
from test_escrow import BANK, E, balanced, escrow_of
from zoikorum.domains.payments.providers import sign_webhook
from zoikorum.shared import clock

WH = "/v1/payments/webhooks/fake"
SECRET = "dev-webhook-secret"


def signed(event: dict, *, secret: str = SECRET, age: int = 0) -> tuple[bytes, dict]:
    body = json.dumps(event).encode()
    t = int(clock.now().timestamp()) - age
    return body, {"Webhook-Signature": sign_webhook(body, secret, t), "Content-Type": "application/json"}


async def post_event(client, event: dict, **kw):
    body, headers = signed(event, **kw)
    return await client.post(WH, content=body, headers=headers)


async def funded(client, make_user, drain, *, both=False):
    pro_user, pro, buyer, c = await signed_contract(client, make_user, drain)
    esc = await escrow_of(client, buyer, c)
    body = {"all": True, "paymentMethodToken": "tok_visa"} if both else {"milestoneIds": [c["milestones"][0]["id"]], "paymentMethodToken": "tok_visa"}
    await client.post(f"{E}/{esc['id']}/fund", headers=buyer.idem(), json=body)
    await drain()
    return pro_user, buyer, c


async def charge_ref(sf, contract_id: str) -> str:
    async with sf() as s:
        return await s.scalar(text("SELECT provider_ref FROM payments.payment_intents WHERE contract_id = :c ORDER BY created_at LIMIT 1"),
                              {"c": contract_id})


# ---- Webhooks: verified and idempotent ------------------------------------------------------------------------

async def test_webhooks_must_be_signed_fresh_and_are_processed_once(client, sf):
    event = {"id": "evt_1", "type": "something.new", "data": {}}
    body, headers = signed(event)
    assert (await client.post(WH, content=body)).json()["code"] == "INVALID_SIGNATURE"  # no signature
    bad = await post_event(client, event, secret="wrong-secret")
    assert bad.status_code == 401 and bad.json()["code"] == "INVALID_SIGNATURE"
    stale = await post_event(client, event, age=3600)  # replayed an hour later
    assert stale.json()["code"] == "INVALID_SIGNATURE"
    tampered = await client.post(WH, content=body.replace(b"something", b"different"), headers=headers)
    assert tampered.json()["code"] == "INVALID_SIGNATURE"
    assert (await client.post("/v1/payments/webhooks/other", content=body, headers=headers)).status_code == 404

    first = await client.post(WH, content=body, headers=headers)
    assert first.status_code == 200 and first.json() == {"received": True, "duplicate": False, "outcome": "ignored"}
    again = await client.post(WH, content=body, headers=headers)
    assert again.json() == {"received": True, "duplicate": True}
    async with sf() as s:
        assert await s.scalar(text("SELECT count(*) FROM payments.webhook_events")) == 1


async def test_bank_returned_payout_is_flagged_with_a_reason_and_retried(client, make_user, drain, sf):
    pro_user, buyer, c = await funded(client, make_user, drain)
    m1 = c["milestones"][0]["id"]
    await client.post(f"/v1/milestones/{m1}/submit", headers=pro_user.h, json={"note": "Delivered"})
    await client.post(f"/v1/milestones/{m1}/accept", headers=buyer.idem())
    await drain()

    earn = (await client.get("/v1/payments/earnings/me", headers=pro_user.h)).json()
    queued = earn["payouts"][0]
    assert queued["status"] == "QUEUED" and queued["delayReason"].startswith("Waiting for your payout account")
    await client.put("/v1/payout-accounts/me", headers=pro_user.h, json=BANK)
    p = (await client.get("/v1/payments/earnings/me", headers=pro_user.h)).json()["payouts"][0]
    assert p["status"] == "SETTLED" and p["expectedAt"] and p["delayReason"] is None

    async with sf() as s:
        ref = await s.scalar(text("SELECT provider_ref FROM payments.payouts"))
    r = await post_event(client, {"id": "evt_po_1", "type": "payout.failed", "data": {"ref": ref, "message": "Account closed"}})
    assert r.json()["outcome"] == "payout failed"
    p = (await client.get("/v1/payments/earnings/me", headers=pro_user.h)).json()["payouts"][0]
    assert p["status"] == "FAILED" and p["delayReason"].startswith("Account closed")
    await client.put("/v1/payout-accounts/me", headers=pro_user.h, json={**BANK, "accountNumber": "000987654321"})
    assert (await client.get("/v1/payments/earnings/me", headers=pro_user.h)).json()["payouts"][0]["status"] == "SETTLED"


# ---- Chargebacks ------------------------------------------------------------------------------------------------

async def test_chargeback_on_held_money_unfunds_the_milestone(client, make_user, drain, sf):
    pro_user, buyer, c = await funded(client, make_user, drain)
    m1 = c["milestones"][0]["id"]
    ref = await charge_ref(sf, c["id"])
    r = await post_event(client, {"id": "evt_cb_1", "type": "charge.dispute.created",
                                  "data": {"ref": ref, "amountMinor": 1_000_000, "reason": "Cardholder does not recognise the charge"}})
    assert r.json()["outcome"] == "chargeback recorded"
    await drain()

    esc = await escrow_of(client, buyer, c)
    assert esc["held"]["amountMinor"] == 0 and esc["allocations"][0]["state"] == "UNFUNDED" and esc["canFund"] is True
    k = (await client.get(f"{C}/{c['id']}", headers=pro_user.h)).json()
    assert k["milestones"][0]["status"] == "PENDING_FUNDING"  # no work without funding
    assert (await client.post(f"/v1/milestones/{m1}/submit", headers=pro_user.h, json={"note": "x"})).json()["code"] == "NOT_FUNDED"
    charges = (await client.get("/v1/payments/charges", headers=buyer.h, params={"organizationId": c["organizationId"]})).json()
    assert charges[0]["status"] == "CHARGED_BACK" and charges[0]["chargedBackAt"]
    ledger = (await client.get(f"{E}/{esc['id']}/ledger", headers=buyer.h)).json()
    assert {(x["entryType"], x["ledgerAccount"]) for x in ledger if x["entryType"] == "CHARGEBACK"} == {
        ("CHARGEBACK", "ESCROW_HELD"), ("CHARGEBACK", "CHARGEBACK_REVERSAL")}
    await balanced(sf)

    # A repeated notice changes nothing; the buyer can fund again and work resumes.
    r = await post_event(client, {"id": "evt_cb_2", "type": "charge.dispute.created", "data": {"ref": ref}})
    assert r.json()["outcome"] == "already charged back"
    await client.post(f"{E}/{esc['id']}/fund", headers=buyer.idem(), json={"milestoneIds": [m1], "paymentMethodToken": "tok_visa"})
    await drain()
    assert (await client.get(f"{C}/{c['id']}", headers=pro_user.h)).json()["milestones"][0]["status"] == "IN_PROGRESS"


async def test_chargeback_after_release_is_booked_as_a_platform_loss(client, make_user, drain, sf):
    pro_user, buyer, c = await funded(client, make_user, drain)
    m1 = c["milestones"][0]["id"]
    await client.post(f"/v1/milestones/{m1}/submit", headers=pro_user.h, json={"note": "Delivered"})
    await client.post(f"/v1/milestones/{m1}/accept", headers=buyer.idem())
    await drain()
    await post_event(client, {"id": "evt_cb_3", "type": "charge.dispute.created", "data": {"ref": await charge_ref(sf, c["id"])}})
    await drain()
    esc = await escrow_of(client, buyer, c)
    assert esc["allocations"][0]["state"] == "RELEASED"  # the professional keeps what was released
    ledger = (await client.get(f"{E}/{esc['id']}/ledger", headers=buyer.h)).json()
    loss = [x for x in ledger if x["ledgerAccount"] == "PLATFORM_CHARGEBACK_LOSS"]
    assert len(loss) == 1 and loss[0]["debit"]["amountMinor"] == 1_000_000
    await balanced(sf)


# ---- Reconciliation ---------------------------------------------------------------------------------------------

async def test_daily_reconciliation_matches_then_flags_a_mismatch(client, make_user, drain, sf):
    pro_user, buyer, c = await funded(client, make_user, drain, both=True)
    m1, m2 = (m["id"] for m in c["milestones"])
    await client.post(f"/v1/milestones/{m1}/submit", headers=pro_user.h, json={"note": "Delivered"})
    await client.post(f"/v1/milestones/{m1}/accept", headers=buyer.idem())
    await drain()
    await post_event(client, {"id": "evt_cb_4", "type": "charge.dispute.created",
                              "data": {"ref": await charge_ref(sf, c["id"]), "amountMinor": 500_000}})
    await drain()

    ops = await staff(make_user, "fin", "FINANCIAL_OPS")
    today = clock.now().date().isoformat()
    assert (await client.post("/v1/payments/reconciliations", headers=buyer.h, json={"day": today})).status_code == 403
    r = (await client.post("/v1/payments/reconciliations", headers=ops.h, json={"day": today})).json()
    assert r["status"] == "MATCHED", r["checks"]
    assert {(x["name"], x["ledger"]) for x in r["checks"]} >= {("charges", 1_500_000), ("payouts", 900_000), ("chargebacks", 500_000)}

    async with sf() as s, s.begin():  # a payout record goes missing from the payments side
        await s.execute(text("DELETE FROM payments.payouts"))
    r = (await client.post("/v1/payments/reconciliations", headers=ops.h, json={"day": today})).json()
    assert r["status"] == "MISMATCH" and r["mismatches"] == 1
    (bad,) = [x for x in r["checks"] if not x["ok"]]
    assert bad["name"] == "payouts" and bad["difference"] == 900_000
    listed = (await client.get("/v1/payments/reconciliations", headers=ops.h)).json()
    assert len(listed) == 1 and listed[0]["status"] == "MISMATCH"  # re-running a day updates its batch
    await drain()
    async with sf() as s:
        assert await s.scalar(text("SELECT count(*) FROM platform.outbox WHERE event_type LIKE '%reconciliation.mismatch%'")) == 1


async def test_reconciliation_runs_itself_every_night(client, make_user, drain, sf):
    from zoikorum.domains.payments import reconciliation

    async with sf() as s, s.begin():
        await reconciliation.bootstrap(s)
    clock.advance(timedelta(days=1, hours=2))
    await drain()
    clock.set_now(None)
    async with sf() as s:
        assert await s.scalar(text("SELECT count(*) FROM payments.reconciliation_batches WHERE status = 'MATCHED'")) == 1
        assert await s.scalar(text("SELECT count(*) FROM platform.timers WHERE kind = 'payments.daily_reconciliation' "
                                   "AND fired_at IS NULL AND cancelled_at IS NULL")) == 1  # re-armed for tomorrow
