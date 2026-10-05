"""Step 3 - capability taxonomy: public tree, facade validation, admin changes."""

from __future__ import annotations

import base64
import uuid

import pytest
from sqlalchemy import text

from zoikorum.domains.marketplace import facade
from zoikorum.domains.marketplace.taxonomy_data import default_taxonomy_rows
from zoikorum.shared.auth import PlatformRole
from zoikorum.shared.errors import ValidationFailed


async def test_public_taxonomy_has_finance_and_accounting(client):
    r = await client.get("/v1/taxonomy")
    assert r.status_code == 200
    (cat,) = r.json()["categories"]
    assert cat["slug"] == "finance-and-accounting" and len(cat["groups"]) == 7
    leadership = next(g for g in cat["groups"] if g["slug"] == "finance-leadership")
    assert leadership["specializations"][0]["slug"] == "fractional-cfo"
    tax = next(g for g in cat["groups"] if g["slug"] == "taxation")
    filings = next(s for s in tax["specializations"] if s["slug"] == "tax-compliance-and-filings")
    assert filings["requiresCredential"] and filings["regulated"] and "CPA" in filings["credentialHints"]

    assert (await client.get("/v1/taxonomy/finance-and-accounting")).json()["slug"] == "finance-and-accounting"
    assert (await client.get("/v1/taxonomy/plumbing")).status_code == 404


async def test_seed_is_idempotent(sf):
    from zoikorum.domains.marketplace.service import seed_default_taxonomy

    async with sf() as s, s.begin():
        await seed_default_taxonomy(s)
        await seed_default_taxonomy(s)
        count = await s.scalar(text("SELECT count(*) FROM marketplace.taxonomy_nodes"))
    assert count == len(default_taxonomy_rows())


async def test_facade_validates_specializations(sf):
    async with sf() as s:
        info = await facade.get_specializations(s, ["fractional-cfo", "sox-compliance-and-testing"])
        assert info["fractional-cfo"].group_slug == "finance-leadership"
        assert info["sox-compliance-and-testing"].requires_credential is True
        await facade.validate_specializations(s, ["fractional-cfo"])
        with pytest.raises(ValidationFailed) as exc:
            await facade.validate_specializations(s, ["fractional-cfo", "astrology"])
        assert exc.value.code == "UNKNOWN_SPECIALIZATION"
        assert (await facade.get_category(s, "finance-and-accounting")).taxonomy_version == 1


async def test_admin_adds_updates_and_deprecates_specializations(client, make_user, drain, sf):
    admin = await make_user("admin", platform_roles=(PlatformRole.PLATFORM_ADMIN,))
    await admin.step_up()
    base = "/v1/admin/taxonomy/specializations"

    r = await client.post(base, headers=admin.h, json={"groupSlug": "taxation", "name": "Crypto Asset Taxation",
                                                       "requiresCredential": True})
    assert r.status_code == 201, r.text
    assert r.json()["slug"] == "crypto-asset-taxation" and r.json()["taxonomyVersion"] == 2
    dup = await client.post(base, headers=admin.h, json={"groupSlug": "taxation", "name": "Crypto Asset Taxation"})
    assert dup.status_code == 409

    r = await client.patch(f"{base}/crypto-asset-taxation", headers=admin.h, json={"regulated": True})
    assert r.json()["regulated"] is True and r.json()["taxonomyVersion"] == 3

    r = await client.post(f"{base}/crypto-asset-taxation/deprecate", headers=admin.h)
    assert r.status_code == 200 and r.json()["status"] == "DEPRECATED"
    async with sf() as s:
        with pytest.raises(ValidationFailed):
            await facade.validate_specializations(s, ["crypto-asset-taxation"])
    tree = (await client.get("/v1/taxonomy")).json()["categories"][0]
    assert tree["version"] == 4
    assert all(sp["slug"] != "crypto-asset-taxation" for g in tree["groups"] for sp in g["specializations"])

    await drain()
    async with sf() as s:
        n = await s.scalar(text("SELECT count(*) FROM audit.audit_records WHERE action = 'zoikorum.marketplace.taxonomy.updated.v1'"))
    assert n == 3


async def test_only_platform_admins_change_the_taxonomy(client, make_user):
    user = await make_user("buyer")
    r = await client.post("/v1/admin/taxonomy/specializations", headers=user.h,
                          json={"groupSlug": "taxation", "name": "Something New"})
    assert r.status_code == 403
    assert (await client.post("/v1/admin/taxonomy/seed", headers=user.h)).status_code == 403


async def _published_pro(client, make_user, drain, name="pia"):
    u = await make_user(name, account_type="PROFESSIONAL")
    pro = (await client.post("/v1/professionals", headers=u.h, json={})).json()
    await client.post("/v1/auth/confirm-email", json={"token": u.confirm_token})
    await client.put("/v1/professionals/me/photo", headers=u.h, json={
        "contentType": "image/png", "dataBase64": base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"0" * 64).decode()})
    await client.patch("/v1/professionals/me", headers=u.h, json={
        "headline": "Fractional CFO", "legalName": "Pia Example", "yearsExperienceBand": "3-5",
        "engagementTypes": ["PROJECT"], "deliveryModes": ["REMOTE"], "pricingModels": ["CUSTOM"],
        "bio": "Month-end close, board reporting and cash forecasting for growing companies and their investors."})
    await client.put("/v1/professionals/me/specializations", headers=u.h, json={"primary": "fractional-cfo"})
    await client.put("/v1/professionals/me/jurisdictions", headers=u.h, json={"served": ["US"]})
    assert (await client.post("/v1/professionals/me/publish", headers=u.h, json={"attestAccurate": True})).status_code == 200
    await drain()
    return u, pro


async def test_buyers_save_and_unsave_professionals(client, make_user, drain, sf):
    u, pro = await _published_pro(client, make_user, drain)
    buyer = await make_user("bea")
    url = "/v1/saved/professionals"
    assert (await client.post(url, headers=buyer.h, json={"professionalId": pro["id"]})).status_code == 204
    assert (await client.post(url, headers=buyer.h, json={"professionalId": pro["id"]})).status_code == 204  # idempotent
    (saved,) = (await client.get(url, headers=buyer.h)).json()
    assert saved["displayName"] == "Pia" and saved["primarySpecialization"] == "Fractional CFO"
    assert saved["tier"] == "C" and saved["available"] is True
    async with sf() as s:
        assert await facade.saved_by(s, uuid.UUID(pro["id"])) == [buyer.id]

    await client.post("/v1/professionals/me/unpublish", headers=u.h)
    assert (await client.get(url, headers=buyer.h)).json()[0]["available"] is False  # kept, marked unavailable
    other = await make_user("oli")
    assert (await client.post(url, headers=other.h, json={"professionalId": pro["id"]})).status_code == 404  # unpublished
    assert (await client.delete(f"{url}/{pro['id']}", headers=buyer.h)).status_code == 204
    assert (await client.get(url, headers=buyer.h)).json() == []
    assert (await client.get(url)).status_code == 401
