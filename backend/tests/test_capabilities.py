"""Staff capability catalogue (shared/capabilities.py, Admin Navigation Registry NAV-03): one resolver for the sidebar,
the routes and the APIs. Capabilities replaced role lists without anyone gaining or losing access."""

from __future__ import annotations

from sqlalchemy import text

from zoikorum.shared.auth import PlatformRole
from zoikorum.shared.capabilities import (
    CAPABILITY_ROLES, DESTINATIONS, ROLE_CAPABILITIES, Cap, capabilities_for, destinations_for, roles_with,
)

ALL = None  # every staff role
# The staff sidebar before capabilities (AppShell STAFF_NAV role lists), by registry destination.
OLD_SIDEBAR: dict[str, set[str] | None] = {
    "D01": ALL, "D02": ALL, "D03": ALL,
    "D04": {"PLATFORM_ADMIN", "TS_ANALYST"},
    "D05": {"PLATFORM_ADMIN", "TS_ANALYST", "COMPLIANCE_OFFICER", "SUPPORT_AGENT"},
    "D06": {"COMPLIANCE_OFFICER"},
    "D07": {"TS_ANALYST", "PLATFORM_ADMIN"},
    "D08": {"COMPLIANCE_OFFICER"},
    "D09": ALL,
    "D10": {"MEDIATOR", "LEGAL", "PLATFORM_ADMIN"},
    "D11": ALL,
    "D12": {"PLATFORM_ADMIN", "COMPLIANCE_OFFICER", "LEGAL", "MEDIATOR", "FINANCIAL_OPS"},
    "D13": {"PLATFORM_ADMIN", "COMPLIANCE_OFFICER", "LEGAL", "MEDIATOR", "FINANCIAL_OPS"},
    "D14": {"PLATFORM_ADMIN"},
    "D15": {"FINANCIAL_OPS", "PLATFORM_ADMIN"}, "D16": {"FINANCIAL_OPS", "PLATFORM_ADMIN"},
    "D17": {"FINANCIAL_OPS", "PLATFORM_ADMIN"},
    "D18": ALL,
    "D19": {"FINANCIAL_OPS", "PLATFORM_ADMIN"}, "D20": {"FINANCIAL_OPS", "PLATFORM_ADMIN"},
    "D21": {"FINANCIAL_OPS", "PLATFORM_ADMIN"},
    "APPROVALS": ALL,
    "D22": {"PLATFORM_ADMIN"},
    "D23": {"SUPPORT_AGENT", "PLATFORM_ADMIN"},
    "D24": {"PLATFORM_ADMIN"},
    "AI_GOVERNANCE": {"AI_SAFETY_REVIEWER"},
}

# Snapshot of the role -> capability table. A change here is an access change: review it as one.
SNAPSHOT: dict[str, list[str]] = {
    "AI_SAFETY_REVIEWER": ['ai.prompts.manage', 'ai.read', 'analytics.read', 'approvals.read', 'audit.read', 'dashboard.read', 'incidents.operate', 'incidents.read', 'safety.read', 'search.staff', 'work.read'],
    "COMPLIANCE_OFFICER": ['analytics.kpis.read', 'analytics.read', 'approvals.read', 'audit.chain.verify', 'audit.export', 'audit.read', 'audit.records.read', 'contracts.detail.read', 'contracts.read', 'dashboard.read', 'engagements.read', 'enterprise.decide', 'enterprise.read', 'incidents.operate', 'incidents.read', 'organizations.read', 'professionals.read', 'safety.read', 'search.staff', 'trust.records.read', 'verification.decide', 'verification.read', 'verification.subject.read', 'work.read'],
    "EXECUTIVE": ['analytics.read', 'approvals.read', 'audit.read', 'dashboard.read', 'incidents.lead', 'incidents.operate', 'incidents.read', 'safety.approve_severe', 'safety.override', 'safety.read', 'search.staff', 'work.read'],
    "FINANCIAL_OPS": ['analytics.kpis.read', 'analytics.read', 'approvals.read', 'audit.read', 'contracts.read', 'dashboard.read', 'dlq.read', 'dlq.replay', 'dlq.replay_financial', 'engagements.read', 'finexceptions.read', 'health.read', 'incidents.operate', 'incidents.read', 'payments.ops', 'payments.read', 'recon.operate', 'recon.read', 'safety.read', 'search.staff', 'switches.read', 'switches.request_money', 'work.read'],
    "LEGAL": ['analytics.kpis.read', 'analytics.read', 'approvals.read', 'audit.archives.read', 'audit.export', 'audit.read', 'audit.records.read', 'contracts.detail.read', 'contracts.read', 'dashboard.read', 'disputes.adjudicate', 'disputes.read', 'disputes.retention.read', 'engagements.read', 'incidents.lead', 'incidents.operate', 'incidents.read', 'safety.appeals.decide', 'safety.approve', 'safety.approve_severe', 'safety.read', 'safety.reports.confidential', 'safety.reports.read', 'safety.reverse', 'search.staff', 'work.read'],
    "MEDIATOR": ['analytics.read', 'approvals.read', 'audit.read', 'contracts.detail.read', 'contracts.read', 'dashboard.read', 'disputes.assign', 'disputes.mediate', 'disputes.read', 'engagements.read', 'incidents.operate', 'incidents.read', 'safety.read', 'search.staff', 'work.read'],
    "PLATFORM_ADMIN": ['accounts.read', 'accounts.reset_mfa', 'analytics.kpis.read', 'analytics.read', 'analytics.rebuild', 'api_keys.manage', 'approvals.read', 'assignments.manage', 'audit.archives.read', 'audit.chain.verify', 'audit.export', 'audit.read', 'audit.records.read', 'configuration.read', 'contracts.detail.read', 'contracts.read', 'dashboard.read', 'disputes.assign', 'disputes.read', 'disputes.retention.read', 'dlq.read', 'dlq.replay', 'engagements.read', 'finexceptions.read', 'flags.manage', 'health.read', 'iam.read', 'iam.request', 'identity_cases.read', 'identity_cases.resolve', 'incidents.lead', 'incidents.operate', 'incidents.read', 'organizations.read', 'payments.ops', 'payments.read', 'professionals.read', 'recon.operate', 'recon.read', 'safety.read', 'safety.risk.read', 'search.reindex', 'search.staff', 'support.read', 'support.reply', 'switches.read', 'switches.request', 'switches.request_money', 'taxonomy.edit', 'taxonomy.read', 'trust.records.read', 'verification.subject.read', 'work.read'],
    "RISK_LEAD": ['analytics.kpis.read', 'analytics.read', 'approvals.read', 'assignments.manage', 'audit.archives.read', 'audit.read', 'dashboard.read', 'incidents.lead', 'incidents.operate', 'incidents.read', 'safety.act', 'safety.approve', 'safety.assess', 'safety.read', 'safety.reports.confidential', 'safety.reports.read', 'safety.reverse', 'safety.risk.read', 'search.staff', 'trust.records.read', 'work.read'],
    "SUPPORT_AGENT": ['analytics.read', 'approvals.read', 'audit.read', 'dashboard.read', 'incidents.operate', 'incidents.read', 'organizations.read', 'professionals.read', 'safety.read', 'search.staff', 'support.read', 'support.reply', 'work.read'],
    "TS_ANALYST": ['accounts.read', 'analytics.kpis.read', 'analytics.read', 'approvals.read', 'assignments.manage', 'audit.read', 'dashboard.read', 'identity_cases.read', 'identity_cases.resolve', 'incidents.operate', 'incidents.read', 'organizations.read', 'professionals.read', 'safety.act', 'safety.open', 'safety.read', 'safety.reports.read', 'safety.risk.read', 'search.staff', 'trust.records.read', 'verification.subject.read', 'work.read'],
}

# One endpoint enforcing each destination read capability (method GET, with query parameters).
READ_ENDPOINTS: dict[str, tuple[str, dict]] = {
    Cap.DASHBOARD_READ: ("/v1/admin/overview", {}),
    Cap.WORK_READ: ("/v1/admin/assignments", {}),
    Cap.ANALYTICS_READ: ("/v1/analytics/marketplace-health", {}),
    Cap.ACCOUNTS_READ: ("/v1/admin/users", {}),
    Cap.PROFESSIONALS_READ: ("/v1/admin/professionals", {}),
    Cap.ENTERPRISE_READ: ("/v1/professionals/admin/enterprise-applications", {}),
    Cap.IDENTITY_CASES_READ: ("/v1/admin/duplicate-accounts", {}),
    Cap.VERIFICATION_READ: ("/v1/verification/review-queue", {"status": "ALL"}),
    Cap.SAFETY_READ: ("/v1/admin/enforcement-cases", {}),
    Cap.DISPUTES_READ: ("/v1/disputes", {"role": "operator"}),
    Cap.AUDIT_READ: ("/v1/admin/audit/archives", {}),
    Cap.ENGAGEMENTS_READ: ("/v1/admin/contracts", {}),
    Cap.CONTRACTS_READ: ("/v1/admin/contracts/summary", {}),
    Cap.TAXONOMY_READ: ("/v1/admin/taxonomy/suggestions", {}),
    Cap.PAYMENTS_READ: ("/v1/admin/escrow", {}),
    Cap.RECON_READ: ("/v1/payments/reconciliations", {}),
    Cap.FINEXCEPTIONS_READ: ("/v1/payments/ops/worklist", {}),
    Cap.INCIDENTS_READ: ("/v1/admin/incidents", {}),
    Cap.HEALTH_READ: ("/v1/admin/worker", {}),
    Cap.SWITCHES_READ: ("/v1/admin/switches", {}),
    Cap.DLQ_READ: ("/v1/admin/dead-letters", {}),
    Cap.IAM_READ: ("/v1/admin/staff", {}),
    Cap.SUPPORT_READ: ("/v1/admin/support/requests", {}),
    Cap.CONFIGURATION_READ: ("/v1/admin/config", {}),
    Cap.APPROVALS_READ: ("/v1/admin/approval-requests", {}),
    Cap.AI_READ: ("/v1/ai/prompts", {}),
}


def test_every_roles_destinations_equal_the_old_sidebar():
    for role in sorted(PlatformRole.ALL):
        mine = {d.id for d in destinations_for(ROLE_CAPABILITIES[role])}
        old = {d for d, roles in OLD_SIDEBAR.items() if roles is None or role in roles}
        assert mine == old, role


def test_registry_order_routes_and_read_capabilities():
    assert [d.id for d in DESTINATIONS if d.id.startswith("D")] == [f"D{i:02d}" for i in range(1, 25)]
    assert all(d.route == f"/platform-admin/{d.slug}" for d in DESTINATIONS)
    assert {d.read_capability for d in DESTINATIONS} == set(READ_ENDPOINTS)
    assert DESTINATIONS[0].route == "/platform-admin/command-center"
    assert DESTINATIONS[-2].route == "/platform-admin/platform-configuration"


def test_role_capability_table_snapshot():
    assert {r: sorted(c) for r, c in ROLE_CAPABILITIES.items()} == SNAPSHOT
    assert set(ROLE_CAPABILITIES) == set(PlatformRole.ALL)
    for cap, roles in CAPABILITY_ROLES.items():
        assert roles_with(cap) == roles and roles <= PlatformRole.ALL
    assert capabilities_for([]) == frozenset()


async def _staff(make_user, role):
    u = await make_user(role.lower(), platform_roles=(role,))
    await u.step_up()
    return u


async def test_every_read_capability_is_enforced_on_an_endpoint(client, make_user):
    buyer = await make_user("buyer")
    staff = {r: await _staff(make_user, r) for r in sorted(PlatformRole.ALL)}
    for cap, (path, params) in READ_ENDPOINTS.items():
        holders = CAPABILITY_ROLES[cap]
        with_ = staff[PlatformRole.PLATFORM_ADMIN] if PlatformRole.PLATFORM_ADMIN in holders else staff[sorted(holders)[0]]
        lacking = sorted(PlatformRole.ALL - holders)
        without = staff[lacking[0]] if lacking else buyer
        ok = await client.get(path, headers=with_.h, params=params)
        assert ok.status_code == 200, (cap, path, ok.text)
        refused = await client.get(path, headers=without.h, params=params)
        assert refused.status_code == 403, (cap, path, refused.text)
        if lacking:  # a customer account never has one either
            assert (await client.get(path, headers=buyer.h, params=params)).status_code == 403, (cap, path)


async def test_my_capabilities_lists_capabilities_and_destinations_in_registry_order(client, make_user):
    fin = await _staff(make_user, "FINANCIAL_OPS")
    r = await client.get("/v1/admin/me/capabilities", headers=fin.h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["capabilities"] == SNAPSHOT["FINANCIAL_OPS"]
    assert [d["id"] for d in body["destinations"]] == ["D01", "D02", "D03", "D09", "D11", "D12", "D13", "D15", "D16", "D17",
                                                       "D18", "D19", "D20", "D21", "APPROVALS"]
    assert body["destinations"][0] == {"id": "D01", "slug": "command-center", "route": "/platform-admin/command-center",
                                       "title": "Command Center", "group": "Overview"}
    ai = await _staff(make_user, "AI_SAFETY_REVIEWER")
    routes = [d["route"] for d in (await client.get("/v1/admin/me/capabilities", headers=ai.h)).json()["destinations"]]
    assert routes[-1] == "/platform-admin/ai-governance" and "/platform-admin/protected-payments" not in routes


async def test_my_capabilities_needs_a_staff_session(client, make_user, sf):
    buyer = await make_user("customer")
    refused = await client.get("/v1/admin/me/capabilities", headers=buyer.h)
    assert refused.status_code == 403 and refused.json()["code"] == "ADMIN_SESSION_REQUIRED"
    # A staff member signed in on the customer sign-in (not an ADMIN audience session): no capabilities at all.
    person = await make_user("staffer")
    async with sf() as s, s.begin():
        await s.execute(text("UPDATE identity.identities SET platform_roles = :r WHERE id = :i"),
                        {"r": ["PLATFORM_ADMIN"], "i": person.id})
    await person.refresh()
    refused = await client.get("/v1/admin/me/capabilities", headers=person.h)
    assert refused.status_code == 403 and refused.json()["code"] == "ADMIN_SESSION_REQUIRED"
    assert (await client.get("/v1/payments/reconciliations", headers=person.h)).status_code == 403
