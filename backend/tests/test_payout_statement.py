"""The professional's payout statement page (GET /v1/payments/payouts/{id}): amounts, engagement, buyer organisation,
steps, related transactions and the masked destination. Owner only (plus Financial Operations staff, audited)."""

from __future__ import annotations

from sqlalchemy import text

from test_contract import signed_contract
from test_dispute import staff
from test_escrow import BANK, E, escrow_of
from test_proposal import tier_b


async def paid_payout(client, make_user, drain):
    pro_user, pro, buyer, c = await signed_contract(client, make_user, drain)
    esc = await escrow_of(client, buyer, c)
    m1 = c["milestones"][0]
    await client.post(f"{E}/{esc['id']}/fund", headers=buyer.idem(), json={"milestoneIds": [m1["id"]], "paymentMethodToken": "tok_visa"})
    await drain()
    await client.post(f"/v1/milestones/{m1['id']}/submit", headers=pro_user.h, json={"note": "Master file"})
    await client.post(f"/v1/milestones/{m1['id']}/accept", headers=buyer.idem())
    await drain()
    assert (await client.put("/v1/payout-accounts/me", headers=pro_user.h, json=BANK)).status_code == 200
    (payout,) = (await client.get("/v1/payments/earnings/me", headers=pro_user.h)).json()["payouts"]
    return pro_user, buyer, c, payout


async def test_owner_reads_the_statement_and_the_amounts_add_up(client, make_user, drain):
    pro_user, buyer, c, payout = await paid_payout(client, make_user, drain)
    r = await client.get(f"/v1/payments/payouts/{payout['id']}", headers=pro_user.h)
    assert r.status_code == 200, r.text
    s = r.json()
    assert s["reference"] == f"ZK-PAY-{payout['id'][:8].upper()}"
    assert s["status"] == "SETTLED" and s["statusLabel"] == "Paid" and s["settledAt"]
    gross, fee, net = s["gross"], s["fee"], s["net"]
    assert gross["currency"] == fee["currency"] == net["currency"] == c["total"]["currency"]  # never mixed
    assert gross["amountMinor"] - fee["amountMinor"] == net["amountMinor"] and fee["amountMinor"] > 0
    assert s["feeBps"] == round(fee["amountMinor"] * 10000 / gross["amountMinor"])
    assert s["transferReference"]

    e = s["engagement"]
    assert e["contractId"] == c["id"] and e["reference"] == c["reference"] and e["reference"].startswith("ZK-ENG-")
    assert e["milestoneTitle"] == c["milestones"][0]["title"] and e["acceptedAt"]
    assert e["clientInvoiceNumber"].startswith("ZK-INV-")
    assert s["client"]["name"] and set(s["client"]) == {"name", "country"}

    assert [st["key"] for st in s["steps"]] == ["FUNDED", "ACCEPTED", "INITIATED", "IN_TRANSIT", "COMPLETED"]
    assert all(st["state"] == "DONE" for st in s["steps"]) and s["steps"][0]["at"] and s["steps"][-1]["at"]
    kinds = [t["kind"] for t in s["transactions"]]
    assert set(kinds) == {"ESCROW_FUNDED", "MILESTONE_INVOICE", "ESCROW_RELEASE", "PAYOUT"} and kinds[0] == "ESCROW_FUNDED"
    assert {t["amount"]["currency"] for t in s["transactions"]} == {c["total"]["currency"]}
    release = next(t for t in s["transactions"] if t["kind"] == "ESCROW_RELEASE")
    assert release["amount"] == gross

    d = s["destination"]
    assert d["last4"] == BANK["accountNumber"][-4:] and d["currency"] == "USD" and d["label"].endswith(d["last4"])
    assert BANK["accountNumber"] not in r.text  # never the full number


async def test_no_client_contact_details(client, make_user, drain):
    pro_user, buyer, c, payout = await paid_payout(client, make_user, drain)
    r = await client.get(f"/v1/payments/payouts/{payout['id']}", headers=pro_user.h)
    assert r.status_code == 200
    assert buyer.email.lower() not in r.text.lower() and "@" not in r.text  # no email anywhere in the statement
    assert "phone" not in r.text.lower()


async def test_other_people_get_404_and_staff_reads_are_audited(client, make_user, drain, sf):
    pro_user, buyer, c, payout = await paid_payout(client, make_user, drain)
    url = f"/v1/payments/payouts/{payout['id']}"
    other, _ = await tier_b(client, make_user, drain, "olga")  # another professional
    assert (await client.get(url, headers=other.h)).status_code == 404
    assert (await client.get(url, headers=buyer.h)).status_code == 404
    assert (await client.get("/v1/payments/payouts/00000000-0000-0000-0000-000000000000", headers=pro_user.h)).status_code == 404

    ops = await staff(make_user, "fin", "FINANCIAL_OPS")
    r = await client.get(url, headers=ops.h)
    assert r.status_code == 200 and r.json()["id"] == payout["id"]
    await drain()
    async with sf() as s:
        assert await s.scalar(text("SELECT count(*) FROM audit.audit_records WHERE action = 'payments.payout.statement_viewed'")) == 1


async def test_queued_payout_is_processing_without_transfer_reference(client, make_user, drain):
    pro_user, pro, buyer, c = await signed_contract(client, make_user, drain)
    esc = await escrow_of(client, buyer, c)
    m1 = c["milestones"][0]
    await client.post(f"{E}/{esc['id']}/fund", headers=buyer.idem(), json={"milestoneIds": [m1["id"]], "paymentMethodToken": "tok_visa"})
    await drain()
    await client.post(f"/v1/milestones/{m1['id']}/submit", headers=pro_user.h, json={"note": "Master file"})
    await client.post(f"/v1/milestones/{m1['id']}/accept", headers=buyer.idem())
    await drain()
    (payout,) = (await client.get("/v1/payments/earnings/me", headers=pro_user.h)).json()["payouts"]
    s = (await client.get(f"/v1/payments/payouts/{payout['id']}", headers=pro_user.h)).json()
    assert s["status"] == "QUEUED" and s["statusLabel"] == "Processing"
    assert s["transferReference"] is None and s["destination"] is None and s["initiatedAt"] is None
    states = {st["key"]: st["state"] for st in s["steps"]}
    assert states == {"FUNDED": "DONE", "ACCEPTED": "DONE", "INITIATED": "CURRENT", "IN_TRANSIT": "UPCOMING", "COMPLETED": "UPCOMING"}
    assert s["steps"][2]["note"]  # why it is waiting
