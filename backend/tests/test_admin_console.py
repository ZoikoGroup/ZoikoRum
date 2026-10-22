"""Staff admin console reads: organisations (buyers, enterprises, firms), professionals, contracts, protected funds and
the platform configuration. Each list is cursor-paged like /v1/admin/users and has a summary for the page's cards."""

from __future__ import annotations

from sqlalchemy import text

from test_contract import signed_contract
from zoikorum.config import Settings, get_settings
from zoikorum.domains.admin.service import CONFIG_GROUPS

ORGS, PROS, CONTRACTS, ESCROW, CONFIG = ("/v1/admin/organizations", "/v1/admin/professionals", "/v1/admin/contracts",
                                         "/v1/admin/escrow", "/v1/admin/config")


async def staff(make_user, *roles):
    u = await make_user("-".join(r.lower() for r in roles), platform_roles=roles)
    await u.step_up()  # staff tools need two-step verification
    return u


async def walk(client, user, url, **params) -> list[dict]:
    """Every item, one page at a time: each row exactly once, newest first."""
    items, cursor = [], None
    while True:
        r = await client.get(url, headers=user.h, params={**params, "limit": 1, **({"cursor": cursor} if cursor else {})})
        assert r.status_code == 200, r.text
        items += r.json()["items"]
        cursor = r.json()["nextCursor"]
        if not cursor:
            return items


async def audited(sf, action: str) -> int:
    async with sf() as s:
        return await s.scalar(text("SELECT count(*) FROM audit.audit_records WHERE action = :a"), {"a": action})


async def test_organisations_list_buyers_enterprises_and_firms_together(client, make_user, drain, sf):
    buyer = await make_user("bea")
    await make_user("ent", account_type="ENTERPRISE", organization="Acme Corp")
    firm_admin = await make_user("fay", account_type="FIRM", organization="Smith & Co Advisory")
    await drain()
    assert (await client.get(ORGS, headers=buyer.h)).status_code == 403  # staff only
    assert (await client.get(f"{ORGS}/summary", headers=buyer.h)).status_code == 403
    assert (await client.get(ORGS, headers=(await staff(make_user, "FINANCIAL_OPS")).h)).status_code == 403
    admin = await staff(make_user, "SUPPORT_AGENT")

    everything = (await client.get(ORGS, headers=admin.h, params={"limit": 100})).json()
    assert everything["nextCursor"] is None
    paged = await walk(client, admin, ORGS)  # one cursor pages through buyer organisations and firms alike
    assert [o["id"] for o in paged] == [o["id"] for o in everything["items"]] and len({o["id"] for o in paged}) == len(paged)
    assert [o["createdAt"] for o in paged] == sorted((o["createdAt"] for o in paged), reverse=True)

    firm = (await client.get(ORGS, headers=admin.h, params={"kind": "FIRM"})).json()["items"]
    assert [f["name"] for f in firm] == ["Smith & Co Advisory"]
    assert firm[0]["verificationStatus"] == "PENDING_VERIFICATION" and firm[0]["status"] == "ACTIVE" and firm[0]["memberCount"] == 1
    assert firm[0]["primaryContact"] == {"name": "Fay", "email": firm_admin.email} and firm[0]["contractCount"] == 0
    ent = (await client.get(ORGS, headers=admin.h, params={"kind": "ENTERPRISE"})).json()["items"]
    assert [e["name"] for e in ent] == ["Acme Corp"] and ent[0]["verificationStatus"] is None and ent[0]["primaryContact"]
    assert all(o["kind"] == "BUYER" for o in (await client.get(ORGS, headers=admin.h, params={"kind": "BUYER"})).json()["items"])
    assert [o["name"] for o in (await client.get(ORGS, headers=admin.h, params={"q": "smith &"})).json()["items"]] == ["Smith & Co Advisory"]
    assert (await client.get(ORGS, headers=admin.h, params={"q": "%"})).json()["items"] == []  # % is literal

    async with sf() as s, s.begin():
        await s.execute(text("UPDATE buyer.organizations SET status = 'SUSPENDED' WHERE name = 'Acme Corp'"))
    suspended = (await client.get(ORGS, headers=admin.h, params={"status": "SUSPENDED"})).json()["items"]
    assert [o["name"] for o in suspended] == ["Acme Corp"]

    summary = (await client.get(f"{ORGS}/summary", headers=admin.h)).json()
    assert summary == {"total": len(paged), "buyer": len(paged) - 2, "enterprise": 1, "firm": 1, "suspended": 1,
                       "newLast30Days": len(paged)}
    await drain()
    assert await audited(sf, "buyer.admin.organizations_listed") >= 5  # every staff read of the list is recorded


async def test_professionals_show_publication_tier_verification_and_engagements(client, make_user, drain, sf):
    pro_user, pro, buyer, contract = await signed_contract(client, make_user, drain)
    newcomer = await make_user("nia", account_type="PROFESSIONAL")
    draft = (await client.post("/v1/professionals", headers=newcomer.h, json={})).json()
    await drain()
    assert (await client.get(PROS, headers=buyer.h)).status_code == 403
    assert (await client.get(PROS, headers=(await staff(make_user, "MEDIATOR")).h)).status_code == 403
    officer = await staff(make_user, "COMPLIANCE_OFFICER")

    rows = {p["id"]: p for p in await walk(client, officer, PROS)}
    assert set(rows) == {pro["id"], draft["id"]}
    p = rows[pro["id"]]
    assert p["publication"] == "PUBLISHED" and p["tier"] == "B" and p["verification"]["identity"] == "VERIFIED"
    assert p["identityId"] == str(pro_user.id) and p["specialization"] == "transfer-pricing" and p["country"] == "US"
    assert p["activeEngagements"] == 1 and p["lifetimeEngagements"] == 1
    d = rows[draft["id"]]
    assert d["publication"] == "DRAFT" and d["tier"] == "C" and d["verification"]["identity"] == "NONE"
    assert set(d["verification"]) == {"identity", "credentials", "jurisdiction"} and d["lifetimeEngagements"] == 0

    # A draft with a verification check waiting for a decision is in review.
    await client.post("/v1/verification/cases", headers=newcomer.h, json={
        "verificationType": "IDENTITY", "subjectType": "PROFESSIONAL", "subjectId": draft["id"]})
    ids = lambda r: [x["id"] for x in r.json()["items"]]  # noqa: E731
    assert ids(await client.get(PROS, headers=officer.h, params={"publication": "IN_REVIEW"})) == [draft["id"]]
    assert ids(await client.get(PROS, headers=officer.h, params={"tier": "B"})) == [pro["id"]]
    assert ids(await client.get(PROS, headers=officer.h, params={"tier": "C"})) == [draft["id"]]
    assert ids(await client.get(PROS, headers=officer.h, params={"q": pro["displayName"].upper()})) == [pro["id"]]
    assert ids(await client.get(PROS, headers=officer.h, params={"country": "GB"})) == []

    async with sf() as s, s.begin():  # enforcement reduced the profile's visibility
        await s.execute(text("UPDATE professional.professionals SET visibility_reduced = true WHERE id = :i"), {"i": pro["id"]})
    assert ids(await client.get(PROS, headers=officer.h, params={"publication": "RESTRICTED"})) == [pro["id"]]
    summary = (await client.get(f"{PROS}/summary", headers=officer.h)).json()
    assert summary == {"total": 2, "published": 0, "inReview": 1, "draft": 0, "restricted": 1, "identityVerified": 1,
                       "tiers": {"A": 0, "B": 1, "C": 1}}


async def test_contracts_with_milestones_escrow_money_and_disputes(client, make_user, drain):
    pro_user, pro, buyer, c = await signed_contract(client, make_user, drain)
    assert (await client.get(CONTRACTS, headers=buyer.h)).status_code == 403
    assert (await client.get(CONTRACTS, headers=(await staff(make_user, "SUPPORT_AGENT")).h)).status_code == 403
    mediator = await staff(make_user, "MEDIATOR")

    esc = (await client.get(f"/v1/escrow/by-contract/{c['id']}", headers=buyer.h)).json()
    r = await client.post(f"/v1/escrow/{esc['id']}/fund", headers=buyer.idem(),
                          json={"milestoneIds": [c["milestones"][0]["id"]], "paymentMethodToken": "tok_visa"})
    assert r.status_code == 200, r.text
    await drain()

    items = (await client.get(CONTRACTS, headers=mediator.h)).json()["items"]
    assert len(items) == 1
    row = items[0]
    assert row["id"] == c["id"] and row["status"] == "ACTIVE" and row["signedAt"] and row["version"] == 1
    assert row["currency"] == "USD" and row["totalMinor"] == 1_500_000
    assert row["buyer"]["organizationId"] == c["organizationId"] and row["buyer"]["name"]
    assert row["professional"] == {"id": pro["id"], "name": pro["displayName"], "country": "US"}
    assert [(m["sequence"], m["amountMinor"]) for m in row["milestones"]] == [(1, 1_000_000), (2, 500_000)]
    assert row["fundedMinor"] == 1_000_000 and row["releasedMinor"] == 0 and row["hasOpenDispute"] is False
    assert (await client.get(CONTRACTS, headers=mediator.h, params={"status": "COMPLETED"})).json()["items"] == []
    assert len((await client.get(CONTRACTS, headers=mediator.h, params={"q": row["title"][:6].lower()})).json()["items"]) == 1

    summary = (await client.get(f"{CONTRACTS}/summary", headers=mediator.h)).json()
    assert summary["total"] == 1 and summary["byStatus"] == {"ACTIVE": 1} and summary["openDisputes"] == 0
    assert sum(summary["milestonesByStatus"].values()) == 2 and summary["milestonesByStatus"].get("IN_PROGRESS") == 1


async def test_protected_funds_per_allocation_and_currency_buckets(client, make_user, drain):
    pro_user, pro, buyer, c = await signed_contract(client, make_user, drain)
    m1, m2 = c["milestones"]
    esc = (await client.get(f"/v1/escrow/by-contract/{c['id']}", headers=buyer.h)).json()
    await client.post(f"/v1/escrow/{esc['id']}/fund", headers=buyer.idem(), json={"milestoneIds": [m1["id"]], "paymentMethodToken": "tok_visa"})
    await drain()
    assert (await client.get(ESCROW, headers=buyer.h)).status_code == 403
    assert (await client.get(ESCROW, headers=(await staff(make_user, "COMPLIANCE_OFFICER")).h)).status_code == 403
    ops = await staff(make_user, "FINANCIAL_OPS")

    rows = {r["milestoneId"]: r for r in await walk(client, ops, ESCROW)}
    assert set(rows) == {m1["id"], m2["id"]}
    held, unfunded = rows[m1["id"]], rows[m2["id"]]
    assert held["status"] == "HELD" and held["amountMinor"] == 1_000_000 and held["milestoneSequence"] == 1
    assert held["provider"] and held["providerReference"] and held["contractId"] == c["id"] and held["contractTitle"]
    assert held["buyerName"] and held["professionalName"] == pro["displayName"] and held["currency"] == "USD"
    assert unfunded["status"] == "UNFUNDED" and unfunded["provider"] is None
    assert [r["milestoneId"] for r in (await client.get(ESCROW, headers=ops.h, params={"status": "HELD"})).json()["items"]] == [m1["id"]]
    assert (await client.get(ESCROW, headers=ops.h, params={"currency": "EUR"})).json()["items"] == []

    summary = (await client.get(f"{ESCROW}/summary", headers=ops.h)).json()
    assert summary == {"buckets": [{"status": "HELD", "currency": "USD", "count": 1, "amountMinor": 1_000_000},
                                   {"status": "UNFUNDED", "currency": "USD", "count": 1, "amountMinor": 500_000}]}


SECRET_LOOKING = ("secret", "password", "key", "token", "dsn", "credential", "url", "endpoint", "username", "bucket", "host")
# Which providers, models and infrastructure the platform runs on is not shown either.
INFRASTRUCTURE = ("provider", "model", "scanner", "event_bus", "log_level", "tracing", "breaker")


def test_the_configuration_allowlist_names_real_settings_and_nothing_secret():
    fields = Settings.model_fields
    for _, settings in CONFIG_GROUPS:
        for name, description in settings:
            assert name in fields, f"{name} is not a setting"
            assert not any(word in name.lower() for word in SECRET_LOOKING), f"{name} looks secret"
            assert not any(word in name.lower() for word in INFRASTRUCTURE), f"{name} describes infrastructure"
            assert description


async def test_configuration_is_platform_admin_only_and_never_shows_secrets(client, make_user):
    buyer = await make_user("bea")
    assert (await client.get(CONFIG, headers=buyer.h)).status_code == 403
    assert (await client.get(CONFIG, headers=(await staff(make_user, "FINANCIAL_OPS")).h)).status_code == 403
    admin = await staff(make_user, "PLATFORM_ADMIN")
    r = await client.get(CONFIG, headers=admin.h)
    assert r.status_code == 200, r.text
    body = r.json()
    s = get_settings()
    assert body["environment"] == s.env and body["groups"]
    settings = {x["key"]: x for g in body["groups"] for x in g["settings"]}
    assert settings["ZK_PLATFORM_FEE_BPS"]["value"] == str(s.platform_fee_bps)
    assert settings["ZK_RELEASE_BLOCK_ESCALATION_DAYS"]["value"] == str(s.release_block_escalation_days)
    assert not [k for k in settings if any(word in k.lower() for word in SECRET_LOOKING)]
    secrets = [v for v in (s.jwt_secret, s.field_encryption_key, s.webhook_secret, s.database_url, s.smtp_password,
                           s.stripe_secret_key, s.anthropic_api_key, s.redis_url) if v]
    assert not [v for v in secrets if v in r.text]  # no secret value appears anywhere in the response
