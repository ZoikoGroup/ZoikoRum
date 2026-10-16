"""Bugs found by comparing the product documents with the code (2026-10-12): person-level engagement suspensions,
the buyer-side restriction message, expired credentials that could be hidden, capacity limits, and the dispute
challenge window that was stored but never applied."""

from __future__ import annotations

import pytest
from sqlalchemy import text

from test_proposal import P, R, buyer_org, proposal_body, request_body, tier_b
from zoikorum.domains.admin import facade as admin_facade
from zoikorum.domains.policy.schemas import SettingsIn


async def submitted_proposal(client, make_user, drain, name="cap"):
    pro_user, pro = await tier_b(client, make_user, drain, name)
    buyer, org = await buyer_org(client, make_user, drain)
    req = (await client.post(R, headers=buyer.idem(), json=request_body(org, pro))).json()[0]
    p = (await client.post(f"{R}/{req['id']}/proposals", headers=pro_user.h, json=proposal_body())).json()
    return pro_user, pro, buyer, org, p


async def test_a_person_suspended_from_engagements_cannot_accept_and_the_message_is_about_the_buyer(client, make_user, drain, monkeypatch):
    pro_user, pro, buyer, org, p = await submitted_proposal(client, make_user, drain)
    assert (await client.post(f"{P}/{p['id']}/submit", headers=pro_user.idem())).status_code == 200

    real = admin_facade.active_restrictions

    async def suspended(session, subject_type, subject_id):
        if subject_type == "IDENTITY" and str(subject_id) == str(buyer.id):
            return ["ENGAGEMENT_SUSPENSION"]  # a safety decision about the person, not their organisation
        return await real(session, subject_type, subject_id)

    monkeypatch.setattr(admin_facade, "active_restrictions", suspended)
    r = await client.post(f"{P}/{p['id']}/accept", headers=buyer.idem())
    assert r.status_code == 403, r.text
    assert "organisation is currently restricted" in r.json()["detail"]  # not "this professional is restricted"


async def test_an_expired_credential_cannot_be_hidden(client, make_user, drain, sf):
    pro_user, pro = await tier_b(client, make_user, drain, "exp")
    claim = (await client.post("/v1/professionals/me/credentials", headers=pro_user.h, json={
        "credentialType": "LICENSE", "name": "CPA", "issuingBody": "State Board", "registrationNumber": "CPA-9",
        "jurisdiction": "us"})).json()
    async with sf() as s, s.begin():
        await s.execute(text("UPDATE professional.credential_claims SET status = 'EXPIRED' WHERE id = :c"), {"c": claim["id"]})
    r = await client.delete(f"/v1/professionals/me/credentials/{claim['id']}", headers=pro_user.h)
    assert r.status_code == 409 and r.json()["code"] == "EXPIRED_CREDENTIAL_STAYS_VISIBLE"


async def test_capacity_needs_an_explicit_confirmation(client, make_user, drain):
    pro_user, pro, buyer, org, p = await submitted_proposal(client, make_user, drain, "full")
    await client.put("/v1/professionals/me/availability", headers=pro_user.h,
                     json={"availability": "NOW", "temporarilyUnavailable": True})
    refused = await client.post(f"{P}/{p['id']}/submit", headers=pro_user.idem())
    assert refused.status_code == 409 and refused.json()["code"] == "AT_CAPACITY"
    confirmed = await client.post(f"{P}/{p['id']}/submit", headers=pro_user.idem(), params={"confirmCapacity": "true"})
    assert confirmed.status_code == 200, confirmed.text
    assert (await client.post(f"{P}/{p['id']}/accept", headers=buyer.idem())).status_code == 200  # they confirmed it


async def test_a_buyer_cannot_accept_once_the_professional_is_at_capacity(client, make_user, drain):
    pro_user, pro, buyer, org, p = await submitted_proposal(client, make_user, drain, "busy")
    assert (await client.post(f"{P}/{p['id']}/submit", headers=pro_user.idem())).status_code == 200
    await client.put("/v1/professionals/me/availability", headers=pro_user.h,
                     json={"availability": "NOW", "temporarilyUnavailable": True})  # took on other work meanwhile
    r = await client.post(f"{P}/{p['id']}/accept", headers=buyer.idem())
    assert r.status_code == 409 and r.json()["code"] == "PROFESSIONAL_AT_CAPACITY"


def test_a_challenge_window_can_be_set_now_that_it_is_honoured():
    assert SettingsIn(challengeWindowDays=14).challengeWindowDays == 14  # escrow holds the payment until it ends
