"""Server-generated PDFs: the engagement agreement, invoices and payout statements (shared/pdf.py)."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import text

from test_contract import C, signed_contract
from test_escrow import BANK, E, escrow_of
from zoikorum.shared import pdf


@pytest.mark.unit
def test_rendering_is_reproducible_and_unicode_safe():
    doc = pdf.PdfDocument(title="Invoice", reference="ZK-INV-000001", issued=datetime(2026, 10, 9, tzinfo=timezone.utc),
                          fingerprint="ab" * 32,
                          sections=[pdf.Section("Billed to", rows=[("Organisation", "Zürich Ltd — José, ₹")]),
                                    pdf.Section("Items", table=[("Long description " * 20, pdf.money(150000, "INR"))],
                                                total=("Total", pdf.money(150000, "INR")))])
    first = pdf.render(doc)
    assert first.startswith(b"%PDF-") and first == pdf.render(doc)  # the same record always gives the same file
    assert pdf.money(-15000, "USD") == "USD -150.00" and pdf.money(123456789, "EUR") == "EUR 1,234,567.89"


async def test_agreement_pdf_for_the_parties_only(client, make_user, drain, sf):
    pro_user, pro, buyer, c = await signed_contract(client, make_user, drain)
    url = f"{C}/{c['id']}/document.pdf"
    r = await client.get(url, headers=buyer.h)
    assert r.status_code == 200 and r.headers["content-type"] == "application/pdf"
    assert r.content.startswith(b"%PDF-") and f'{c["reference"]}-v1.pdf' in r.headers["content-disposition"]
    assert r.headers["cache-control"] == "no-store"
    assert (await client.get(url, headers=pro_user.h)).content == r.content  # both parties get the identical document
    assert (await client.get(f"{C}/{c['id']}/versions/1/document.pdf", headers=buyer.h)).content == r.content
    assert (await client.get(f"{C}/{c['id']}/versions/9/document.pdf", headers=buyer.h)).status_code == 404
    stranger = await make_user("sam")
    assert (await client.get(url, headers=stranger.h)).status_code in (403, 404)
    await drain()
    async with sf() as s:
        # three successful downloads (buyer, professional, buyer for version 1); refused and missing ones record nothing
        assert await s.scalar(text("SELECT count(*) FROM audit.audit_records WHERE action LIKE '%document.pdf_downloaded%'")) == 3


async def test_invoice_pdf(client, make_user, drain, sf):
    pro_user, pro, buyer, c = await signed_contract(client, make_user, drain)
    esc = await escrow_of(client, buyer, c)
    m1 = c["milestones"][0]
    await client.post(f"{E}/{esc['id']}/fund", headers=buyer.idem(), json={"milestoneIds": [m1["id"]], "paymentMethodToken": "tok_visa"})
    await drain()
    await client.post(f"/v1/milestones/{m1['id']}/submit", headers=pro_user.h, json={"note": "Master file"})
    await client.post(f"/v1/milestones/{m1['id']}/accept", headers=buyer.idem())
    await drain()
    (invoice,) = (await client.get("/v1/payments/invoices", headers=buyer.h, params={"organizationId": c["organizationId"]})).json()["items"]

    url = f"/v1/payments/invoices/{invoice['id']}/pdf"
    r = await client.get(url, headers=buyer.h)
    assert r.status_code == 200 and r.content.startswith(b"%PDF-") and f'{invoice["number"]}.pdf' in r.headers["content-disposition"]
    assert (await client.get(url, headers=buyer.h)).content == r.content
    assert (await client.get(url, headers=pro_user.h)).status_code in (403, 404)  # invoices belong to the buyer organisation
    assert (await client.get("/v1/payments/invoices/00000000-0000-0000-0000-000000000000/pdf", headers=buyer.h)).status_code == 404
    await drain()
    async with sf() as s:
        recorded = await s.scalar(text("SELECT evidence_hash FROM audit.audit_records WHERE action LIKE '%invoice.pdf_downloaded%' LIMIT 1"))
    assert recorded and len(recorded) == 64  # the invoice content's SHA-256, also printed in the PDF footer


async def test_payout_statement_pdf_for_the_professional_only(client, make_user, drain, sf):
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
    assert payout["status"] == "SETTLED"

    url = f"/v1/payments/payouts/{payout['id']}/pdf"
    r = await client.get(url, headers=pro_user.h)
    assert r.status_code == 200 and r.content.startswith(b"%PDF-") and r.headers["cache-control"] == "no-store"
    assert f'ZK-PAY-{payout["id"][:8].upper()}.pdf' in r.headers["content-disposition"]
    assert (await client.get(url, headers=pro_user.h)).content == r.content  # same payout, same file
    assert (await client.get(url, headers=buyer.h)).status_code == 404  # only the professional who was paid
    assert (await client.get("/v1/payments/payouts/00000000-0000-0000-0000-000000000000/pdf", headers=pro_user.h)).status_code == 404
    await drain()
    async with sf() as s:
        hashes = (await s.scalars(text("SELECT evidence_hash FROM audit.audit_records WHERE action LIKE '%payout.statement_downloaded%'"))).all()
    assert len(hashes) == 2 and len(hashes[0]) == 64  # refused and missing downloads record nothing


async def test_invoice_shows_the_tax_included_in_the_amount(client, make_user, drain, sf, monkeypatch):
    from zoikorum.config import get_settings

    monkeypatch.setattr(get_settings(), "tax_rules", {"US": {"label": "Sales tax", "rateBps": 1000, "basis": "FEE"}})
    pro_user, pro, buyer, c = await signed_contract(client, make_user, drain)
    esc = await escrow_of(client, buyer, c)
    m1 = c["milestones"][0]
    await client.post(f"{E}/{esc['id']}/fund", headers=buyer.idem(), json={"milestoneIds": [m1["id"]], "paymentMethodToken": "tok_visa"})
    await drain()
    await client.post(f"/v1/milestones/{m1['id']}/submit", headers=pro_user.h, json={"note": "Master file"})
    await client.post(f"/v1/milestones/{m1['id']}/accept", headers=buyer.idem())
    await drain()
    (invoice,) = (await client.get("/v1/payments/invoices", headers=buyer.h, params={"organizationId": c["organizationId"]})).json()["items"]
    gross = m1["amount"]["amountMinor"]
    fee = gross // 10  # the 10% platform fee
    assert invoice["total"]["amountMinor"] == gross  # tax-inclusive: what was paid does not change
    assert invoice["tax"]["amountMinor"] == round(fee * 1000 / 11000)
    assert invoice["lines"][1]["description"] == "Of which Sales tax 10% on the Zoikorum platform fee (included)"
    r = await client.get(f"/v1/payments/invoices/{invoice['id']}/pdf", headers=buyer.h)
    assert r.status_code == 200 and r.content.startswith(b"%PDF-")


@pytest.mark.unit
def test_audit_export_pdf_renders_records_and_empty_case():
    import json
    from types import SimpleNamespace
    from zoikorum.domains.audit.service import render_export_pdf

    records = [{"seq": i, "occurredAt": "2026-10-09T10:00:00+00:00", "action": "policy.dashboard.exported " * 4,
                "actorId": "11111111-2222", "objectType": "Organization", "objectId": "abcdef0123456789", "hash": "f" * 64}
               for i in range(120)]
    job = SimpleNamespace(content=json.dumps({"records": records}), content_sha256="ab" * 32, chain_head_hash="cd" * 32)
    assert render_export_pdf(job).startswith(b"%PDF-")
    assert render_export_pdf(SimpleNamespace(content=json.dumps({"records": []}), content_sha256=None, chain_head_hash=None)).startswith(b"%PDF-")
