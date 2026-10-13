"""Senior-review fixes (2026-10-12): who may settle disputes for a buyer, live membership for lists, policy jurisdictions,
stalled mediation, staff self-grants, buyer erasure, invitations for unconfirmed emails, and a blank environment name."""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import text

from test_contract import C
from test_dispute import D, dispute_body, funded_contract, staff
from test_organizations import enterprise_admin
from zoikorum.config import Settings
from zoikorum.domains.dispute import service as dispute_service
from zoikorum.shared import clock


async def member(sf, org_id, make_user, name, roles):
    """Another member of the contract's buyer organisation with only these roles (added directly: the test contracts
    belong to individual buyer accounts, which cannot invite a team)."""
    u = await make_user(name)
    async with sf() as s, s.begin():
        await s.execute(text("INSERT INTO buyer.members (id, organization_id, identity_id, email, display_name, roles, status, created_at) "
                             "VALUES (gen_random_uuid(), :o, :i, :e, :n, :r, 'ACTIVE', now())"),
                        {"o": org_id, "i": u.id, "e": u.email, "n": name.title(), "r": roles})
    return u


async def test_only_deciders_act_for_the_buyer_in_a_dispute_and_removed_members_lose_lists(client, make_user, drain, sf):
    pro_user, pro, buyer, c = await funded_contract(client, make_user, drain)
    reviewer = await member(sf, c["organizationId"], make_user, "rita", ["LEGAL_REVIEWER"])
    assert [k["id"] for k in (await client.get(f"{C}?role=buyer", headers=reviewer.h)).json()["items"]] == [c["id"]]

    r = await client.post(D, headers=reviewer.idem(), json=dispute_body(c))
    assert r.status_code == 403 and r.json()["code"] == "ROLE_REQUIRED"

    async with sf() as s, s.begin():  # removed from the organisation (their sign-in token still lists it for a while)
        await s.execute(text("UPDATE buyer.members SET status = 'REMOVED' WHERE identity_id = :i"), {"i": reviewer.id})
    assert (await client.get(f"{C}?role=buyer", headers=reviewer.h)).json()["items"] == []  # at once, not when the token expires
    assert (await client.get("/v1/proposal-requests?role=buyer", headers=reviewer.h)).json()["items"] == []


async def test_an_unanswered_recommendation_counts_as_declined(client, make_user, drain):
    pro_user, pro, buyer, c = await funded_contract(client, make_user, drain)
    d = (await client.post(D, headers=pro_user.idem(), json=dispute_body(c, outcome="FULL_RELEASE"))).json()
    await drain()
    clock.advance(timedelta(days=4))
    await drain()
    clock.set_now(None)
    d = (await client.post(f"{D}/{d['id']}/resolution-proposals", headers=pro_user.h, json={"outcome": "FULL_RELEASE"})).json()
    await client.post(f"/v1/resolution-proposals/{d['proposals'][0]['id']}/reject", headers=buyer.h)
    d = (await client.post(f"{D}/{d['id']}/escalate", headers=buyer.h)).json()
    mediator = await staff(make_user, "max", "MEDIATOR", "PLATFORM_ADMIN")
    await client.post(f"{D}/{d['id']}/assign-mediator", headers=mediator.h, json={"mediatorIdentityId": str(mediator.id)})
    rec = {"outcome": "REWORK", "summary": "Rework within the agreed scope is fair to both sides.", "citations": ["Agreement clause 8"]}
    d = (await client.post(f"{D}/{d['id']}/recommendation", headers=mediator.h, json=rec)).json()
    early = await client.post(f"{D}/{d['id']}/decision", headers=mediator.h, json=rec)
    assert early.json()["code"] == "RECOMMENDATION_FIRST"  # nobody has answered yet

    from zoikorum.shared.db import session_factory
    async with session_factory()() as s, s.begin():  # the answer window closes with no answer from either party
        await dispute_service.recommendation_lapsed(s, {"disputeId": d["id"], "issuedAt": d["recommendation"]["issuedAt"]})
    later = await client.post(f"{D}/{d['id']}/decision", headers=mediator.h, json=rec)
    assert later.status_code == 200 and later.json()["pendingDecision"]["outcome"] == "REWORK"


async def test_a_mediator_must_hold_the_role(client, make_user, drain):
    pro_user, pro, buyer, c = await funded_contract(client, make_user, drain)
    d = (await client.post(D, headers=pro_user.idem(), json=dispute_body(c))).json()
    await drain()
    clock.advance(timedelta(days=4))
    await drain()
    clock.set_now(None)
    d = (await client.post(f"{D}/{d['id']}/resolution-proposals", headers=pro_user.h, json={"outcome": "FULL_RELEASE"})).json()
    await client.post(f"/v1/resolution-proposals/{d['proposals'][0]['id']}/reject", headers=buyer.h)
    d = (await client.post(f"{D}/{d['id']}/escalate", headers=buyer.h)).json()
    admin = await staff(make_user, "pam", "PLATFORM_ADMIN")
    plain = await make_user("nora")
    r = await client.post(f"{D}/{d['id']}/assign-mediator", headers=admin.h, json={"mediatorIdentityId": str(plain.id)})
    assert r.status_code == 422 and r.json()["code"] == "NOT_A_MEDIATOR"


async def test_nobody_grants_staff_roles_to_themselves(client, make_user):
    admin = await staff(make_user, "ada", "PLATFORM_ADMIN")
    r = await client.post(f"/v1/admin/identities/{admin.id}/platform-roles", headers=admin.h, json={"role": "FINANCIAL_OPS"})
    assert r.status_code == 403 and r.json()["code"] == "SELF_GRANT"


async def test_unconfirmed_sign_ups_do_not_see_invitations(client, make_user, drain):
    admin, org = await enterprise_admin(make_user, drain, client)
    squatter = await make_user("sam")  # registered with the address, never confirmed it
    r = await client.post(f"/v1/organizations/{org['id']}/invitations", headers=admin.h, json={"email": squatter.email, "roles": ["REQUESTER"]})
    assert r.status_code == 201, r.text
    assert (await client.get("/v1/organizations/invitations/mine", headers=squatter.h)).json() == []
    await client.post("/v1/auth/confirm-email", json={"token": squatter.confirm_token})
    assert len((await client.get("/v1/organizations/invitations/mine", headers=squatter.h)).json()) == 1


async def test_erasure_takes_the_person_out_of_organisations(client, make_user, drain, sf):
    pro_user, pro, buyer, c = await funded_contract(client, make_user, drain)
    leaver = await member(sf, c["organizationId"], make_user, "lee", ["REQUESTER"])
    from zoikorum.domains.buyer import privacy as buyer_privacy
    async with sf() as s, s.begin():
        await s.execute(text("SELECT set_config('zoikorum.privacy_erasure', 'on', true)"))
        assert (await buyer_privacy.erase(s, leaver.id))["membershipsEnded"] == 1
    members = (await client.get(f"/v1/organizations/{c['organizationId']}/members", headers=buyer.h)).json()
    assert leaver.email not in {m["email"] for m in members}


def test_a_blank_environment_name_is_refused(monkeypatch):
    monkeypatch.setenv("ZK_ENV", " ")
    with pytest.raises(ValueError, match="ZK_ENV is set but blank"):
        Settings(_env_file=None)
