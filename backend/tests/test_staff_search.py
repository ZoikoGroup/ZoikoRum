"""Staff console federated search: one box, scoped to the kinds each staff role may see, emails always masked,
every search audited."""

from __future__ import annotations

import uuid

from sqlalchemy import text

from test_admin_console import audited, staff
from test_contract import signed_contract
from zoikorum.domains.admin.search import SCOPES, mask_email
from zoikorum.shared.capabilities import CAPABILITY_ROLES

S = "/v1/admin/search"


def kinds(body: dict) -> set[str]:
    return {g["kind"] for g in body["groups"]}


def hits(body: dict, kind: str) -> list[dict]:
    return next((g["items"] for g in body["groups"] if g["kind"] == kind), [])


def test_mask_email():
    assert mask_email("jane.doe@example.com") == "j***@example.com"
    assert mask_email("x@example.org") == "x***@example.org"
    assert mask_email(None) is None and mask_email("not-an-email") is None


async def test_search_is_scoped_to_the_actors_roles(client, make_user, drain, sf):
    pro_user, pro, buyer, contract = await signed_contract(client, make_user, drain)
    title_word = contract["title"].split()[0]
    support_agent = await staff(make_user, "SUPPORT_AGENT")
    admin = await staff(make_user, "PLATFORM_ADMIN", "TS_ANALYST")
    finance = await staff(make_user, "FINANCIAL_OPS")

    # A help request from the buyer, an incident and an enforcement case, all with one unique word.
    word = "zq" + uuid.uuid4().hex[:6]
    r = await client.post("/v1/support/requests", headers=buyer.h, json={
        "topic": "PAYMENTS", "subject": f"Payment {word} did not go through", "message": "Tried twice, still processing."})
    assert r.status_code == 201, r.text
    request_id = r.json()["id"]
    r = await client.post("/v1/admin/incidents", headers=finance.h, json={
        "title": f"Payouts {word} failing", "kind": "PAYMENTS", "severity": "SEV3", "summary": "Payouts return a provider error."})
    assert r.status_code == 201, r.text
    incident_id = r.json()["id"]

    # Support agent: support requests, organisations, professionals, cases and incidents; never contracts, disputes
    # or accounts, even when searching for a contract's exact title or id.
    body = (await client.get(S, headers=support_agent.h, params={"q": word})).json()
    assert "contracts" not in body["scopes"] and "accounts" not in body["scopes"] and "disputes" not in body["scopes"]
    assert set(body["scopes"]) == {k for k, (_, cap) in SCOPES.items() if "SUPPORT_AGENT" in CAPABILITY_ROLES[cap]}
    (req,) = hits(body, "support")
    assert req["id"] == request_id and req["link"] == f"/platform-admin/support-cases?selected={request_id}"
    assert buyer.email not in str(body) and mask_email(buyer.email) in req["subtitle"]
    assert [i["id"] for i in hits(body, "incidents")] == [incident_id]
    for q in (title_word, contract["id"], contract["reference"]):
        assert "contracts" not in kinds((await client.get(S, headers=support_agent.h, params={"q": q})).json())

    # Financial operations: contracts and incidents, but not help requests or accounts.
    body = (await client.get(S, headers=finance.h, params={"q": contract["reference"]})).json()
    (found,) = hits(body, "contracts")
    assert found["id"] == contract["id"] and found["link"] == f"/platform-admin/contracts-milestones?selected={contract['id']}"
    assert "support" not in (await client.get(S, headers=finance.h, params={"q": word})).json()["scopes"]

    # Platform admin: accounts by name or email, masked; lookup by exact id works for contracts.
    body = (await client.get(S, headers=admin.h, params={"q": buyer.email})).json()
    (acct,) = hits(body, "accounts")
    assert acct["id"] == str(buyer.id) and acct["link"] == f"/platform-admin/accounts-organizations?selected={buyer.id}"
    assert buyer.email not in str(body["groups"]) and acct["subtitle"].startswith(mask_email(buyer.email))
    body = (await client.get(S, headers=admin.h, params={"q": contract["id"]})).json()
    assert [c["id"] for c in hits(body, "contracts")] == [contract["id"]]
    body = (await client.get(S, headers=admin.h, params={"q": pro["displayName"]})).json()
    assert pro["id"] in [p["id"] for p in hits(body, "professionals")]
    assert pro_user.email not in str(body)

    # A role taken away stops scoping at once, even with an older token.
    async with sf() as s, s.begin():
        await s.execute(text("UPDATE identity.identities SET platform_roles = '{TS_ANALYST}' WHERE id = :i"), {"i": admin.id})
    body = (await client.get(S, headers=admin.h, params={"q": word})).json()
    assert "support" not in body["scopes"] and "accounts" in body["scopes"]
    async with sf() as s, s.begin():
        await s.execute(text("UPDATE identity.identities SET platform_roles = '{}' WHERE id = :i"), {"i": admin.id})
    assert (await client.get(S, headers=admin.h, params={"q": word})).status_code == 403

    await drain()
    assert await audited(sf, "admin.staff_search.performed") >= 8
    async with sf() as s:
        details = await s.scalar(text("SELECT details::text FROM audit.audit_records WHERE action = 'admin.staff_search.performed' "
                                      "ORDER BY occurred_at DESC LIMIT 1"))
    assert word not in (details or "")  # the search text itself is never recorded


async def test_non_staff_and_short_queries_are_refused(client, make_user):
    buyer = await make_user("bob")
    assert (await client.get(S, headers=buyer.h, params={"q": "anything"})).status_code == 403
    analyst = await staff(make_user, "TS_ANALYST")
    assert (await client.get(S, headers=analyst.h, params={"q": "a"})).status_code == 422
    r = await client.get(S, headers=analyst.h, params={"q": " a "})
    assert r.status_code == 422 and r.json()["code"] in ("QUERY_TOO_SHORT", "VALIDATION_FAILED")
    assert (await client.get(S, headers=analyst.h, params={"q": "ab", "limit": 50})).status_code == 422
    body = (await client.get(S, headers=analyst.h, params={"q": "%_"})).json()  # wildcards are literal
    assert body["groups"] == [] or all("%_" in str(g) for g in body["groups"])
