"""Legal entities (Engineering Handbook 17.1): the registered company an organisation contracts and is invoiced through.
A request records it, acceptance snapshots it, and the contract and its invoices name it."""

from __future__ import annotations

from test_contract import C
from test_proposal import P, R, buyer_org, proposal_body, request_body, tier_b
from zoikorum.domains.payments.service import _billed_to

UK = {"legalName": "Acme Consulting Ltd", "registrationNumber": "12345678", "country": "gb",
      "registeredAddress": "1 King Street, London EC2V 8AU", "taxId": "GB123456789"}
US = {"legalName": "Acme Inc", "registrationNumber": "DE-7654321", "country": "US",
      "registeredAddress": "100 Market Street, Wilmington, DE 19801"}


async def test_admins_keep_one_default_entity_and_members_can_see_them(client, make_user, drain):
    buyer, org = await buyer_org(client, make_user, drain)
    E = f"/v1/organizations/{org['id']}/legal-entities"
    uk = (await client.post(E, headers=buyer.h, json=UK)).json()
    assert uk["isDefault"] is True and uk["country"] == "GB"  # the first one is the default
    us = (await client.post(E, headers=buyer.h, json={**US, "isDefault": True})).json()
    listed = (await client.get(E, headers=buyer.h)).json()
    assert [(e["legalName"], e["isDefault"]) for e in listed] == [("Acme Inc", True), ("Acme Consulting Ltd", False)]
    assert (await client.post(E, headers=buyer.h, json=UK)).json()["code"] == "DUPLICATE_NAME"

    archived = (await client.post(f"{E}/{us['id']}/archive", headers=buyer.h)).json()
    assert archived["status"] == "ARCHIVED" and archived["isDefault"] is False
    assert next(e for e in (await client.get(E, headers=buyer.h)).json() if e["id"] == uk["id"])["isDefault"] is True
    assert (await client.put(f"{E}/{us['id']}", headers=buyer.h, json=US)).json()["code"] == "ENTITY_ARCHIVED"

    stranger = await make_user("sid")
    assert (await client.get(E, headers=stranger.h)).status_code in (403, 404)
    assert (await client.post(E, headers=stranger.h, json=US)).status_code in (403, 404)


async def test_the_contract_names_the_entity_as_it_was_when_accepted(client, make_user, drain):
    pro_user, pro = await tier_b(client, make_user, drain, "ann")
    buyer, org = await buyer_org(client, make_user, drain)
    E = f"/v1/organizations/{org['id']}/legal-entities"
    await client.post(E, headers=buyer.h, json=UK)  # default
    us = (await client.post(E, headers=buyer.h, json=US)).json()

    other_buyer, other_org = await buyer_org(client, make_user, drain, "oto")
    foreign = (await client.post(f"/v1/organizations/{other_org['id']}/legal-entities", headers=other_buyer.h, json=US)).json()
    bad = await client.post(R, headers=buyer.idem(), json=request_body(org, pro, legalEntityId=foreign["id"]))
    assert bad.status_code == 422 and bad.json()["code"] == "INVALID_LEGAL_ENTITY"  # not this organisation's

    req = (await client.post(R, headers=buyer.idem(), json=request_body(org, pro, legalEntityId=us["id"]))).json()[0]
    assert req["legalEntityId"] == us["id"]
    p = (await client.post(f"{R}/{req['id']}/proposals", headers=pro_user.h, json=proposal_body())).json()
    await client.post(f"{P}/{p['id']}/submit", headers=pro_user.idem())
    assert (await client.post(f"{P}/{p['id']}/accept", headers=buyer.idem())).status_code == 200
    await drain()
    await client.put(f"{E}/{us['id']}", headers=buyer.h, json={**US, "registeredAddress": "A later address, Dover"})

    c = (await client.get(C, headers=buyer.h)).json()["items"][0]
    party = next(x for x in (await client.get(f"{C}/{c['id']}", headers=buyer.h)).json()["parties"] if x["role"] == "BUYER")
    assert party["name"] == "Acme Inc" and "Reg. no. DE-7654321" in party["detail"]
    document = (await client.get(f"{C}/{c['id']}/document", headers=buyer.h)).text
    assert "Buyer: Acme Inc (registration no. DE-7654321, 100 Market Street, Wilmington, DE 19801, US)" in document
    assert "A later address" not in document  # signed terms keep the details they were accepted with


async def test_a_request_without_a_choice_uses_the_default_and_none_is_fine(client, make_user, drain):
    pro_user, pro = await tier_b(client, make_user, drain, "ann")
    buyer, org = await buyer_org(client, make_user, drain)
    assert (await client.post(R, headers=buyer.idem(), json=request_body(org, pro))).json()[0]["legalEntityId"] is None
    uk = (await client.post(f"/v1/organizations/{org['id']}/legal-entities", headers=buyer.h, json=UK)).json()
    pro2_user, pro2 = await tier_b(client, make_user, drain, "bea")
    assert (await client.post(R, headers=buyer.idem(), json=request_body(org, pro2))).json()[0]["legalEntityId"] == uk["id"]


def test_invoices_are_billed_to_the_entity():
    class Org:
        name = "Acme Group"
    rows = dict(_billed_to(Org(), {"legalName": "Acme Consulting Ltd", "registrationNumber": "12345678", "country": "GB",
                                   "registeredAddress": "1 King Street, London", "taxId": "GB123456789"}))
    assert rows == {"Legal entity": "Acme Consulting Ltd", "Organisation": "Acme Group", "Registration no.": "12345678",
                    "Tax ID": "GB123456789", "Registered address": "1 King Street, London, GB"}
    assert _billed_to(Org(), None) == [("Organisation", "Acme Group")]
