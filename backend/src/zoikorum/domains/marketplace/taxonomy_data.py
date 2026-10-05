"""Default capability taxonomy (reference data), from the Finance & Accounting category doc.

Pure data + a deterministic row builder, shared by the Alembic seed migration and tests.
Node ids are uuid5(slug) so seeding is idempotent and ids are stable across environments.
"""

from __future__ import annotations

import re
import uuid

TAXONOMY_VERSION = 1
_NS = uuid.UUID("5b1f0f6e-6a52-4e83-9d6f-2f6e7c1a9a01")

# Specializations flagged (Onboarding s.12, Policy "Regulated Engagement Profile"):
#   C = requires a validated credential before the claim is displayed as verified work
#   R = regulated work (enterprise policies typically require Tier A); professional indemnity insurance required
FINANCE_ACCOUNTING = {
    "name": "Finance & Accounting",
    "credential_hints": ["CPA", "CA", "ACCA", "CMA", "CFA", "CIA", "CGMA", "CFE"],
    "groups": [
        ("Accounting & Reporting", [
            ("Financial Accounting", ""), ("Management Accounting", ""), ("Bookkeeping & Accounting Services", ""),
            ("Month-End / Quarter-End Close", ""), ("Group Consolidation & Reporting", ""),
            ("Technical Accounting Advisory", "C"), ("IFRS Reporting", "C"), ("US GAAP Reporting", "C"),
        ]),
        ("Taxation", [
            ("Corporate Tax Advisory", "C"), ("Personal Tax Planning", ""), ("International Tax Strategy", "C"),
            ("Transfer Pricing", "C"), ("VAT / GST / Sales Tax", ""), ("Tax Compliance & Filings", "CR"),
            ("R&D Credits & Incentives", ""),
        ]),
        ("Finance Leadership", [
            ("Fractional CFO", ""), ("Fractional Controller", ""), ("Virtual Finance Director", ""),
            ("FP&A & Financial Planning", ""), ("Budgeting & Forecasting", ""), ("Treasury & Cash Management", ""),
            ("Capital Strategy & Structuring", ""),
        ]),
        ("Audit & Assurance", [
            ("Internal Audit", ""), ("External Audit Support", "CR"), ("Audit Readiness & Preparation", ""),
            ("SOX Compliance & Testing", "CR"), ("Internal Controls Design & Testing", ""), ("Risk & Controls Assessment", ""),
        ]),
        ("Transaction & Advisory", [
            ("M&A Financial Due Diligence", ""), ("Valuation Services", "C"), ("Restructuring & Turnaround", ""),
            ("Investment Analysis & Modeling", ""), ("Carve-Out & Integration Support", ""),
        ]),
        ("Regulatory & Compliance Finance", [
            ("Regulatory Reporting", "CR"), ("Financial Risk Management", ""), ("AML / Financial Crime Controls", "CR"),
            ("Compliance Documentation & Testing", ""), ("IFRS 9 / IFRS 17 Implementation", "C"),
        ]),
        ("Finance Systems & Technology", [
            ("Accounting Systems Implementation", ""), ("ERP Finance Modules", ""), ("Finance Process Automation", ""),
            ("Financial Reporting & BI Tools", ""), ("Finance Data Integration", ""),
        ]),
    ],
}

# Typical deliverables per group (Onboarding s.8 "deliverables templates"); specific overrides below.
GROUP_DELIVERABLES = {
    "Accounting & Reporting": ["Monthly management accounts", "Reconciliations pack", "Close checklist and timetable"],
    "Taxation": ["Tax computation and return", "Advisory memo", "Filing calendar"],
    "Finance Leadership": ["13-week cash flow forecast", "Board reporting pack", "Annual budget and KPI dashboard"],
    "Audit & Assurance": ["Audit plan", "Controls testing workpapers", "Findings report with remediation plan"],
    "Transaction & Advisory": ["Due diligence report", "Financial model", "Valuation summary"],
    "Regulatory & Compliance Finance": ["Regulatory return", "Compliance testing report", "Policy and procedure documentation"],
    "Finance Systems & Technology": ["Requirements and design document", "Configured system with test evidence", "User training and handover"],
}
SPECIALIZATION_DELIVERABLES = {
    "Fractional CFO": ["Financial strategy and operating plan", "Investor and board reporting", "Fundraising support materials"],
    "Bookkeeping & Accounting Services": ["Monthly bookkeeping", "Bank and card reconciliations", "Year-end pack for accountant"],
    "SOX Compliance & Testing": ["Risk and control matrix", "Walkthrough documentation", "Testing results and deficiency log"],
}


def slugify(text: str) -> str:
    # Spaced so abbreviations stay readable: "FP&A" -> "fp-and-a", "M&A" -> "m-and-a".
    s = text.lower().replace("&", " and ").replace("/", " ").replace("+", " plus ")
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")


def node_id(slug: str) -> uuid.UUID:
    return uuid.uuid5(_NS, slug)


def default_taxonomy_rows() -> list[dict]:
    """Flat rows for marketplace.taxonomy_nodes (parents before children)."""
    cat = FINANCE_ACCOUNTING
    cat_slug = slugify(cat["name"])
    rows = [dict(id=node_id(cat_slug), slug=cat_slug, name=cat["name"], level="CATEGORY", parent_id=None,
                 category_slug=cat_slug, sort_order=1, requires_credential=False, regulated=False, requires_insurance=False,
                 deliverable_templates=[], credential_hints=cat["credential_hints"], status="ACTIVE",
                 taxonomy_version=TAXONOMY_VERSION)]
    for gi, (group, specs) in enumerate(cat["groups"], start=1):
        g_slug = slugify(group)
        rows.append(dict(id=node_id(g_slug), slug=g_slug, name=group, level="GROUP", parent_id=node_id(cat_slug),
                         category_slug=cat_slug, sort_order=gi, requires_credential=False, regulated=False, requires_insurance=False,
                         deliverable_templates=GROUP_DELIVERABLES.get(group, []), credential_hints=[],
                         status="ACTIVE", taxonomy_version=TAXONOMY_VERSION))
        for si, (spec, flags) in enumerate(specs, start=1):
            s_slug = slugify(spec)
            rows.append(dict(id=node_id(s_slug), slug=s_slug, name=spec, level="SPECIALIZATION", parent_id=node_id(g_slug),
                             category_slug=cat_slug, sort_order=si, requires_credential="C" in flags, regulated="R" in flags,
                             requires_insurance="R" in flags,
                             deliverable_templates=SPECIALIZATION_DELIVERABLES.get(spec, GROUP_DELIVERABLES.get(group, [])),
                             credential_hints=cat["credential_hints"] if "C" in flags else [],
                             status="ACTIVE", taxonomy_version=TAXONOMY_VERSION))
    return rows
