"""Staff capability catalogue (Admin Navigation Registry ZKR-ADMIN-ENG-001, NAV-03).

One resolver decides what a staff member may see and do in the platform-admin console: the sidebar, the page routes,
the APIs behind them, exports and row actions all ask for a *capability*, never for a list of roles. Roles stay the
unit that is granted (identity domain, maker-checker); ``CAPABILITY_ROLES`` says which roles carry each capability and
``ROLE_CAPABILITIES`` is the same table read the other way.

The table was derived from the role checks in force before capabilities existed, so nobody gained or lost access
when they were introduced. Where a page and the API behind it disagreed (for example a page every staff member sees
whose records only some roles may read), both rules are kept as separate capabilities: the destination's read
capability (``*.read`` in ``DESTINATIONS``) is the old sidebar rule, the finer ones are the old API rules.

Capabilities take effect only in a staff (admin audience) session and only for roles in force now: the session
validator (identity facade ``validate_session_actor``) fills ``Actor.platform_roles`` with the live, unexpired roles
of a staff sign-in and with nothing otherwise. Four-eyes rules (who may approve whose request, which role an approval
counts as) stay role-based: they are separation-of-duties rules about people, recorded on the requests themselves.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from zoikorum.shared.auth import PlatformRole as R


class Cap:
    """Capability names. ``*.read`` without a further dot are destination (page) capabilities."""

    # ---- Destination reads (registry D01-D24, plus Approvals and AI Governance) ----------------------------------------
    DASHBOARD_READ = "dashboard.read"
    WORK_READ = "work.read"
    ANALYTICS_READ = "analytics.read"
    ACCOUNTS_READ = "accounts.read"
    PROFESSIONALS_READ = "professionals.read"
    ENTERPRISE_READ = "enterprise.read"
    IDENTITY_CASES_READ = "identity_cases.read"
    VERIFICATION_READ = "verification.read"
    SAFETY_READ = "safety.read"
    DISPUTES_READ = "disputes.read"
    AUDIT_READ = "audit.read"
    ENGAGEMENTS_READ = "engagements.read"
    CONTRACTS_READ = "contracts.read"
    TAXONOMY_READ = "taxonomy.read"
    PAYMENTS_READ = "payments.read"
    RECON_READ = "recon.read"
    FINEXCEPTIONS_READ = "finexceptions.read"
    INCIDENTS_READ = "incidents.read"
    HEALTH_READ = "health.read"
    SWITCHES_READ = "switches.read"
    DLQ_READ = "dlq.read"
    IAM_READ = "iam.read"
    SUPPORT_READ = "support.read"
    CONFIGURATION_READ = "configuration.read"
    APPROVALS_READ = "approvals.read"
    AI_READ = "ai.read"

    # ---- Finer reads (API rules narrower or wider than the page that uses them) ----------------------------------------
    ANALYTICS_KPIS_READ = "analytics.kpis.read"
    ORGANIZATIONS_READ = "organizations.read"
    VERIFICATION_SUBJECT_READ = "verification.subject.read"
    TRUST_RECORDS_READ = "trust.records.read"
    CONTRACTS_DETAIL_READ = "contracts.detail.read"
    SAFETY_REPORTS_READ = "safety.reports.read"
    SAFETY_REPORTS_CONFIDENTIAL = "safety.reports.confidential"
    SAFETY_RISK_READ = "safety.risk.read"
    AUDIT_RECORDS_READ = "audit.records.read"
    AUDIT_ARCHIVES_READ = "audit.archives.read"
    DISPUTES_RETENTION_READ = "disputes.retention.read"
    STAFF_SEARCH = "search.staff"

    # ---- Actions ---------------------------------------------------------------------------------------------------------
    ACCOUNTS_RESET_MFA = "accounts.reset_mfa"
    IDENTITY_CASES_RESOLVE = "identity_cases.resolve"
    ENTERPRISE_DECIDE = "enterprise.decide"
    VERIFICATION_DECIDE = "verification.decide"
    SAFETY_OPEN = "safety.open"
    SAFETY_ACT = "safety.act"
    SAFETY_ASSESS = "safety.assess"
    SAFETY_APPROVE = "safety.approve"
    SAFETY_APPROVE_SEVERE = "safety.approve_severe"
    SAFETY_REVERSE = "safety.reverse"
    SAFETY_APPEALS_DECIDE = "safety.appeals.decide"
    SAFETY_OVERRIDE = "safety.override"
    DISPUTES_ASSIGN = "disputes.assign"
    DISPUTES_MEDIATE = "disputes.mediate"
    DISPUTES_ADJUDICATE = "disputes.adjudicate"
    AUDIT_EXPORT = "audit.export"
    AUDIT_CHAIN_VERIFY = "audit.chain.verify"
    TAXONOMY_EDIT = "taxonomy.edit"
    PAYMENTS_OPS = "payments.ops"
    RECON_OPERATE = "recon.operate"
    INCIDENTS_OPERATE = "incidents.operate"
    INCIDENTS_LEAD = "incidents.lead"
    SWITCHES_REQUEST = "switches.request"
    SWITCHES_REQUEST_MONEY = "switches.request_money"
    DLQ_REPLAY = "dlq.replay"
    DLQ_REPLAY_FINANCIAL = "dlq.replay_financial"
    IAM_REQUEST = "iam.request"
    SUPPORT_REPLY = "support.reply"
    ASSIGNMENTS_MANAGE = "assignments.manage"
    FLAGS_MANAGE = "flags.manage"
    API_KEYS_MANAGE = "api_keys.manage"
    ANALYTICS_REBUILD = "analytics.rebuild"
    SEARCH_REINDEX = "search.reindex"
    AI_PROMPTS_MANAGE = "ai.prompts.manage"


PA, TS, CO, RISK, LEGAL = R.PLATFORM_ADMIN, R.TS_ANALYST, R.COMPLIANCE_OFFICER, R.RISK_LEAD, R.LEGAL
MED, FO, EXEC, AI, SUP = R.MEDIATOR, R.FINANCIAL_OPS, R.EXECUTIVE, R.AI_SAFETY_REVIEWER, R.SUPPORT_AGENT
FIN = frozenset({FO, PA})
CONTRACT_STAFF = frozenset({PA, CO, LEGAL, MED, FO})

# Which roles carry each capability. The single source of truth; ROLE_CAPABILITIES below is derived from it.
CAPABILITY_ROLES: dict[str, frozenset[str]] = {
    Cap.DASHBOARD_READ: R.ALL,
    Cap.WORK_READ: R.ALL,
    Cap.ANALYTICS_READ: R.ALL,
    Cap.ACCOUNTS_READ: frozenset({PA, TS}),
    Cap.PROFESSIONALS_READ: frozenset({PA, TS, CO, SUP}),
    Cap.ENTERPRISE_READ: frozenset({CO}),
    Cap.IDENTITY_CASES_READ: frozenset({PA, TS}),
    Cap.VERIFICATION_READ: frozenset({CO}),
    Cap.SAFETY_READ: R.ALL,
    Cap.DISPUTES_READ: frozenset({MED, LEGAL, PA}),
    Cap.AUDIT_READ: R.ALL,
    Cap.ENGAGEMENTS_READ: CONTRACT_STAFF,
    Cap.CONTRACTS_READ: CONTRACT_STAFF,
    Cap.TAXONOMY_READ: frozenset({PA}),
    Cap.PAYMENTS_READ: FIN,
    Cap.RECON_READ: FIN,
    Cap.FINEXCEPTIONS_READ: FIN,
    Cap.INCIDENTS_READ: R.ALL,
    Cap.HEALTH_READ: FIN,
    Cap.SWITCHES_READ: FIN,
    Cap.DLQ_READ: FIN,
    Cap.IAM_READ: frozenset({PA}),
    Cap.SUPPORT_READ: frozenset({SUP, PA}),
    Cap.CONFIGURATION_READ: frozenset({PA}),
    Cap.APPROVALS_READ: R.ALL,
    Cap.AI_READ: frozenset({AI}),

    Cap.ANALYTICS_KPIS_READ: frozenset({PA, TS, FO, RISK, LEGAL, CO}),
    Cap.ORGANIZATIONS_READ: frozenset({PA, TS, CO, SUP}),
    Cap.VERIFICATION_SUBJECT_READ: frozenset({CO, PA, TS}),
    Cap.TRUST_RECORDS_READ: frozenset({TS, CO, RISK, PA}),
    Cap.CONTRACTS_DETAIL_READ: frozenset({PA, CO, LEGAL, MED}),
    Cap.SAFETY_REPORTS_READ: frozenset({TS, RISK, LEGAL}),
    Cap.SAFETY_REPORTS_CONFIDENTIAL: frozenset({RISK, LEGAL}),
    Cap.SAFETY_RISK_READ: frozenset({TS, RISK, PA}),
    Cap.AUDIT_RECORDS_READ: frozenset({CO, LEGAL, PA}),
    Cap.AUDIT_ARCHIVES_READ: frozenset({PA, LEGAL, RISK}),
    Cap.DISPUTES_RETENTION_READ: frozenset({LEGAL, PA}),
    Cap.STAFF_SEARCH: R.ALL,

    Cap.ACCOUNTS_RESET_MFA: frozenset({PA}),
    Cap.IDENTITY_CASES_RESOLVE: frozenset({PA, TS}),
    Cap.ENTERPRISE_DECIDE: frozenset({CO}),
    Cap.VERIFICATION_DECIDE: frozenset({CO}),
    Cap.SAFETY_OPEN: frozenset({TS}),
    Cap.SAFETY_ACT: frozenset({TS, RISK}),  # close without action, propose an action, confirm remediation
    Cap.SAFETY_ASSESS: frozenset({RISK}),
    Cap.SAFETY_APPROVE: frozenset({RISK, LEGAL}),  # levels 1-3; which role a vote counts as stays role-based (four eyes)
    Cap.SAFETY_APPROVE_SEVERE: frozenset({EXEC, LEGAL}),  # level 4
    Cap.SAFETY_REVERSE: frozenset({RISK, LEGAL}),
    Cap.SAFETY_APPEALS_DECIDE: frozenset({LEGAL}),
    Cap.SAFETY_OVERRIDE: frozenset({EXEC}),
    Cap.DISPUTES_ASSIGN: frozenset({PA, MED}),
    Cap.DISPUTES_MEDIATE: frozenset({MED}),
    Cap.DISPUTES_ADJUDICATE: frozenset({LEGAL}),  # approve platform decisions, appeals, arbitration awards, legal holds
    Cap.AUDIT_EXPORT: frozenset({CO, LEGAL, PA}),
    Cap.AUDIT_CHAIN_VERIFY: frozenset({CO, PA}),
    Cap.TAXONOMY_EDIT: frozenset({PA}),
    Cap.PAYMENTS_OPS: FIN,  # retry and ask to close financial exceptions
    Cap.RECON_OPERATE: FIN,
    Cap.INCIDENTS_OPERATE: R.ALL,
    Cap.INCIDENTS_LEAD: frozenset({PA, RISK, LEGAL, EXEC}),
    Cap.SWITCHES_REQUEST: frozenset({PA}),
    Cap.SWITCHES_REQUEST_MONEY: FIN,
    Cap.DLQ_REPLAY: FIN,
    Cap.DLQ_REPLAY_FINANCIAL: frozenset({FO}),  # only Financial Operations may replay a money event
    Cap.IAM_REQUEST: frozenset({PA}),
    Cap.SUPPORT_REPLY: frozenset({SUP, PA}),
    Cap.ASSIGNMENTS_MANAGE: frozenset({TS, RISK, PA}),  # assign or release someone else's trust & safety case
    Cap.FLAGS_MANAGE: frozenset({PA}),
    Cap.API_KEYS_MANAGE: frozenset({PA}),
    Cap.ANALYTICS_REBUILD: frozenset({PA}),
    Cap.SEARCH_REINDEX: frozenset({PA}),
    Cap.AI_PROMPTS_MANAGE: frozenset({AI}),
}

ALL_CAPABILITIES: frozenset[str] = frozenset(CAPABILITY_ROLES)

# The same table, per role.
ROLE_CAPABILITIES: dict[str, frozenset[str]] = {
    role: frozenset(c for c, roles in CAPABILITY_ROLES.items() if role in roles) for role in sorted(R.ALL)
}


# ---- Navigation registry -----------------------------------------------------------------------------------------------

ROUTE_PREFIX = "/platform-admin"


@dataclass(frozen=True)
class Destination:
    id: str
    slug: str
    title: str
    group: str
    read_capability: str

    @property
    def route(self) -> str:
        return f"{ROUTE_PREFIX}/{self.slug}"


# Registry order (D01-D24). Approvals and AI Governance are console pages outside the registry; they keep their place
# in the sidebar (Administration & Support).
DESTINATIONS: tuple[Destination, ...] = (
    Destination("D01", "command-center", "Command Center", "Overview", Cap.DASHBOARD_READ),
    Destination("D02", "my-work-queue", "My Work Queue", "Overview", Cap.WORK_READ),
    Destination("D03", "analytics-insights", "Analytics & Insights", "Overview", Cap.ANALYTICS_READ),
    Destination("D04", "accounts-organizations", "Accounts & Organizations", "People & Organizations", Cap.ACCOUNTS_READ),
    Destination("D05", "professional-directory", "Professional Directory", "People & Organizations", Cap.PROFESSIONALS_READ),
    Destination("D06", "enterprise-readiness", "Enterprise Readiness", "People & Organizations", Cap.ENTERPRISE_READ),
    Destination("D07", "duplicate-identity-cases", "Duplicate Identity Cases", "People & Organizations", Cap.IDENTITY_CASES_READ),
    Destination("D08", "verification-center", "Verification Center", "Trust, Risk & Compliance", Cap.VERIFICATION_READ),
    Destination("D09", "trust-safety", "Trust & Safety", "Trust, Risk & Compliance", Cap.SAFETY_READ),
    Destination("D10", "dispute-resolution", "Dispute Resolution", "Trust, Risk & Compliance", Cap.DISPUTES_READ),
    Destination("D11", "audit-evidence", "Audit & Evidence", "Trust, Risk & Compliance", Cap.AUDIT_READ),
    Destination("D12", "engagement-oversight", "Engagement Oversight", "Engagement Operations", Cap.ENGAGEMENTS_READ),
    Destination("D13", "contracts-milestones", "Contracts & Milestones", "Engagement Operations", Cap.CONTRACTS_READ),
    Destination("D14", "taxonomy-standards", "Taxonomy & Standards", "Engagement Operations", Cap.TAXONOMY_READ),
    Destination("D15", "protected-payments", "Protected Payments", "Financial Operations", Cap.PAYMENTS_READ),
    Destination("D16", "reconciliation", "Reconciliation", "Financial Operations", Cap.RECON_READ),
    Destination("D17", "financial-exceptions", "Financial Exceptions", "Financial Operations", Cap.FINEXCEPTIONS_READ),
    Destination("D18", "incident-command", "Incident Command", "Platform Reliability", Cap.INCIDENTS_READ),
    Destination("D19", "service-health-workers", "Service Health & Workers", "Platform Reliability", Cap.HEALTH_READ),
    Destination("D20", "feature-controls", "Feature Controls", "Platform Reliability", Cap.SWITCHES_READ),
    Destination("D21", "failed-event-deliveries", "Failed Event Deliveries", "Platform Reliability", Cap.DLQ_READ),
    Destination("APPROVALS", "approvals", "Approvals", "Administration & Support", Cap.APPROVALS_READ),
    Destination("D22", "staff-access-control", "Staff & Access Control", "Administration & Support", Cap.IAM_READ),
    Destination("D23", "support-cases", "Support Cases", "Administration & Support", Cap.SUPPORT_READ),
    Destination("D24", "platform-configuration", "Platform Configuration", "Administration & Support", Cap.CONFIGURATION_READ),
    Destination("AI_GOVERNANCE", "ai-governance", "AI Governance", "Administration & Support", Cap.AI_READ),
)


# ---- Resolution --------------------------------------------------------------------------------------------------------

def capabilities_for(roles: Iterable[str]) -> frozenset[str]:
    """Every capability the given roles carry together."""
    return frozenset().union(*(ROLE_CAPABILITIES.get(r, frozenset()) for r in roles))


def roles_with(*caps: str) -> frozenset[str]:
    """The roles carrying at least one of ``caps`` (to find people who can act, e.g. eligible case owners)."""
    return frozenset().union(*(CAPABILITY_ROLES[c] for c in caps))


def actor_capabilities(actor) -> frozenset[str]:
    """The capabilities in force for this request: live roles of a staff (admin audience) session, none otherwise."""
    return capabilities_for(actor.platform_roles) if actor.admin_session else frozenset()


def has_capability(actor, *caps: str) -> bool:
    """True when the actor holds at least one of ``caps`` now."""
    unknown = set(caps) - ALL_CAPABILITIES
    if unknown:
        raise KeyError(f"Unknown capability: {', '.join(sorted(unknown))}")
    return bool(actor_capabilities(actor).intersection(caps))


def destination_route(dest_id: str) -> str:
    """The console route of a destination (links in search results and notifications)."""
    return next(d.route for d in DESTINATIONS if d.id == dest_id)


def destinations_for(caps: Iterable[str]) -> list[Destination]:
    held = set(caps)
    return [d for d in DESTINATIONS if d.read_capability in held]
