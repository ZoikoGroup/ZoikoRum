"""Step 8: escrow and payments - open on activation, fund (capture or decline), hold, release on acceptance with the
platform fee, balanced append-only ledger, buyer invoice, professional payout (queued until a payout account exists)."""

from __future__ import annotations

import re

import pytest
from sqlalchemy import text

from test_contract import C, signed_contract
from test_search import publish

E = "/v1/escrow"
BANK = {"holderName": "Ann Example", "country": "US", "currency": "USD", "accountNumber": "000123456789"}


async def escrow_of(client, user, contract):
    r = await client.get(f"{E}/by-contract/{contract['id']}", headers=user.h)
    assert r.status_code == 200, r.text
    return r.json()


async def balanced(sf) -> None:
    async with sf() as s:
        bad = (await s.execute(text("SELECT entry_group_id FROM escrow.ledger_entries GROUP BY entry_group_id "
                                    "HAVING sum(debit_minor) <> sum(credit_minor)"))).all()
    assert bad == []


async def test_fund_hold_release_invoice_and_payout(client, make_user, drain, sf):
    pro_user, pro, buyer, c = await signed_contract(client, make_user, drain)
    esc = await escrow_of(client, buyer, c)
    assert esc["status"] == "UNFUNDED" and esc["canFund"] is True and esc["unfunded"]["amountMinor"] == 1_500_000
    m1, m2 = c["milestones"]

    key = buyer.idem()
    r = await client.post(f"{E}/{esc['id']}/fund", headers=key, json={"milestoneIds": [m1["id"]], "paymentMethodToken": "tok_visa"})
    assert r.status_code == 200 and r.json()["allocations"][0]["state"] == "FUNDING"
    replay = await client.post(f"{E}/{esc['id']}/fund", headers=key, json={"milestoneIds": [m1["id"]], "paymentMethodToken": "tok_visa"})
    assert replay.headers.get("Idempotent-Replayed") == "true"
    await drain()

    esc = await escrow_of(client, buyer, c)
    assert esc["status"] == "FUNDED" and esc["held"]["amountMinor"] == 1_000_000 and esc["allocations"][0]["state"] == "HELD"
    assert (await client.get(f"{C}/{c['id']}", headers=pro_user.h)).json()["milestones"][0]["status"] == "IN_PROGRESS"  # work may start

    await client.post(f"/v1/milestones/{m1['id']}/submit", headers=pro_user.h, json={"note": "Master file"})
    await client.post(f"/v1/milestones/{m1['id']}/accept", headers=buyer.idem())
    await drain()

    esc = await escrow_of(client, buyer, c)
    a1 = esc["allocations"][0]
    assert a1["state"] == "RELEASED" and a1["fee"]["amountMinor"] == 100_000 and a1["released"]["amountMinor"] == 900_000  # 10% fee
    assert esc["status"] == "PARTIALLY_RELEASED" and esc["held"]["amountMinor"] == 0 and esc["fees"]["amountMinor"] == 100_000
    ledger = (await client.get(f"{E}/{esc['id']}/ledger", headers=pro_user.h)).json()
    assert {(x["entryType"], x["ledgerAccount"]) for x in ledger} == {
        ("BUYER_FUNDING", "BUYER_CLEARING"), ("ESCROW_HOLD", "ESCROW_HELD"), ("ESCROW_RELEASE", "ESCROW_HELD"),
        ("ESCROW_RELEASE", "PRO_PAYABLE"), ("PLATFORM_FEE", "PLATFORM_REVENUE")}
    await balanced(sf)

    org_id = c["organizationId"]
    invoices = (await client.get("/v1/payments/invoices", headers=buyer.h, params={"organizationId": org_id})).json()
    # Numbers come from a database sequence shared across tests, so check the format rather than a fixed value.
    assert len(invoices) == 1 and invoices[0]["total"]["amountMinor"] == 1_000_000
    assert re.fullmatch(r"ZK-INV-\d{6}", invoices[0]["number"])
    assert invoices[0]["lines"][0]["description"].startswith("M1 ")
    charges = (await client.get("/v1/payments/charges", headers=buyer.h, params={"organizationId": org_id})).json()
    assert charges[0]["status"] == "CAPTURED" and "4242" in charges[0]["methodLabel"]

    # No payout account yet: the payout waits, then settles once an account is added (two-step confirmation).
    earn = (await client.get("/v1/payments/earnings/me", headers=pro_user.h)).json()
    assert earn["payoutAccount"] is None and earn["payouts"][0]["status"] == "QUEUED" and earn["totals"]["pending"]["amountMinor"] == 900_000
    r = await client.put("/v1/payout-accounts/me", headers=pro_user.h, json=BANK)  # confirmed two-step when countersigning
    assert r.status_code == 200 and r.json()["label"] == "Bank account •••• 6789"
    earn = (await client.get("/v1/payments/earnings/me", headers=pro_user.h)).json()
    assert earn["payouts"][0]["status"] == "SETTLED" and earn["totals"]["settled"]["amountMinor"] == 900_000
    async with sf() as s:
        stored = await s.scalar(text("SELECT count(*) FROM payments.payout_accounts WHERE provider_account_ref LIKE '%123456789%'"))
    assert stored == 0  # the full account number is never stored

    # Second milestone: fund everything left, deliver, accept -> fully released, contract completed.
    await client.post(f"{E}/{esc['id']}/fund", headers=buyer.idem(), json={"all": True, "paymentMethodToken": "tok_visa"})
    await drain()
    await client.post(f"/v1/milestones/{m2['id']}/submit", headers=pro_user.h, json={"note": "Local files"})
    await client.post(f"/v1/milestones/{m2['id']}/accept", headers=buyer.idem())
    await drain()
    esc = await escrow_of(client, buyer, c)
    assert esc["status"] == "FULLY_RELEASED" and esc["released"]["amountMinor"] == 1_350_000 and esc["fees"]["amountMinor"] == 150_000
    assert (await client.get(f"{C}/{c['id']}", headers=buyer.h)).json()["status"] == "COMPLETED"
    await balanced(sf)


async def test_declined_card_leaves_milestone_unfunded(client, make_user, drain):
    pro_user, pro, buyer, c = await signed_contract(client, make_user, drain)
    esc = await escrow_of(client, buyer, c)
    await client.post(f"{E}/{esc['id']}/fund", headers=buyer.idem(), json={"all": True, "paymentMethodToken": "tok_fail"})
    await drain()
    esc = await escrow_of(client, buyer, c)
    assert esc["status"] == "UNFUNDED" and {a["state"] for a in esc["allocations"]} == {"UNFUNDED"}
    assert esc["fundings"][0]["status"] == "FAILED" and "declined" in esc["fundings"][0]["failureMessage"]
    assert {m["status"] for m in (await client.get(f"{C}/{c['id']}", headers=buyer.h)).json()["milestones"]} == {"PENDING_FUNDING"}


async def test_funding_rules_and_access(client, make_user, drain, sf):
    pro_user, pro, buyer, c = await signed_contract(client, make_user, drain)
    esc = await escrow_of(client, buyer, c)
    url, m1 = f"{E}/{esc['id']}/fund", c["milestones"][0]["id"]
    assert (await client.post(url, headers=pro_user.idem(), json={"all": True, "paymentMethodToken": "tok_visa"})).status_code == 403
    stranger = await make_user("sam")
    assert (await client.get(f"{E}/{esc['id']}", headers=stranger.h)).status_code == 404
    assert (await client.post(url, headers=buyer.h, json={"all": True, "paymentMethodToken": "tok_visa"})).json()["code"] == "IDEMPOTENCY_KEY_REQUIRED"

    async with sf() as s, s.begin():
        await s.execute(text("UPDATE buyer.members SET spend_limit_minor = 100, spend_limit_currency = 'USD' WHERE identity_id = :i"), {"i": buyer.id})
    r = await client.post(url, headers=buyer.idem(), json={"milestoneIds": [m1], "paymentMethodToken": "tok_visa"})
    assert r.status_code == 403 and r.json()["code"] == "SPEND_LIMIT_EXCEEDED"
    async with sf() as s, s.begin():
        await s.execute(text("UPDATE buyer.members SET spend_limit_minor = NULL, spend_limit_currency = NULL WHERE identity_id = :i"), {"i": buyer.id})

    await client.post(url, headers=buyer.idem(), json={"milestoneIds": [m1], "paymentMethodToken": "tok_visa"})
    r = await client.post(url, headers=buyer.idem(), json={"milestoneIds": [m1], "paymentMethodToken": "tok_visa"})
    assert r.status_code == 409 and r.json()["code"] == "ALREADY_FUNDED"
    await drain()

    # Releasing twice is impossible, and the ledger can never be edited.
    from zoikorum.domains.escrow import service
    async with sf() as s, s.begin():
        await service.milestone_accepted(s, {"milestoneId": m1})  # not accepted yet in contract terms, but allocation is HELD
    async with sf() as s, s.begin():
        await service.milestone_accepted(s, {"milestoneId": m1})
    async with sf() as s:
        releases = await s.scalar(text("SELECT count(*) FROM escrow.releases"))
    assert releases == 1
    await balanced(sf)
    with pytest.raises(Exception, match="append-only"):
        async with sf() as s, s.begin():
            await s.execute(text("UPDATE escrow.ledger_entries SET credit_minor = 0"))


async def test_payout_account_needs_two_step_and_verified_identity(client, make_user, drain):
    from test_proposal import tier_b
    b_user, _ = await tier_b(client, make_user, drain, "ann")
    assert (await client.put("/v1/payout-accounts/me", headers=b_user.h, json=BANK)).json()["code"] == "STEP_UP_REQUIRED"
    u, pro = await publish(client, make_user, drain, "cara", headline="Bookkeeper", primary="transfer-pricing")  # Tier C
    await u.step_up()
    r = await client.put("/v1/payout-accounts/me", headers=u.h, json=BANK)
    assert r.status_code == 403 and r.json()["code"] == "PAYOUT_COMPLIANCE_REQUIRED"
