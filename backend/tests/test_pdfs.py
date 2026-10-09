"""Server-generated PDFs: the engagement agreement and invoices (shared/pdf.py)."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import text

from test_contract import C, signed_contract
from test_escrow import E, escrow_of
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
    (invoice,) = (await client.get("/v1/payments/invoices", headers=buyer.h, params={"organizationId": c["organizationId"]})).json()

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
