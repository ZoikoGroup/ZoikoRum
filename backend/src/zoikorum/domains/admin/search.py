"""Staff console federated search (handoff: one scoped search box for the staff console).

One query across the records staff work on. Each kind is searched only when the staff member holds the capability
that lists that kind on its own console page, so the search never discloses a record (or that one exists) beyond the actor's
capabilities. Email addresses are always masked. Every search is audited (the kinds searched and the number of hits,
never the search text) and spends a per-person budget on top of the general request budget.
"""

from __future__ import annotations

import uuid
from typing import Literal

from fastapi import APIRouter, Query
from pydantic import BaseModel
from sqlalchemy import func, or_, select

from zoikorum.domains.admin.models import EnforcementCase, Incident
from zoikorum.domains.buyer import facade as buyer_facade
from zoikorum.domains.contract import facade as contract_facade
from zoikorum.domains.dispute import facade as dispute_facade
from zoikorum.domains.firm import facade as firm_facade
from zoikorum.domains.identity import facade as identity_facade
from zoikorum.domains.professional import facade as professional_facade
from zoikorum.domains.support import facade as support_facade
from zoikorum.shared.auth import CurrentActor
from zoikorum.shared.capabilities import Cap, capabilities_for, destination_route
from zoikorum.shared.db import DbSession
from zoikorum.shared.errors import Forbidden, ValidationFailed
from zoikorum.shared.events import record_audit
from zoikorum.shared.http import enforce_budget

router = APIRouter(tags=["admin"])

Kind = Literal["accounts", "organizations", "professionals", "contracts", "disputes", "support", "enforcement", "incidents"]

# Who may search each kind: the capability behind the console data the result links to.
SCOPES: dict[str, tuple[str, str]] = {
    "accounts": ("Accounts", Cap.ACCOUNTS_READ),
    "organizations": ("Organisations", Cap.ORGANIZATIONS_READ),
    "professionals": ("Professionals", Cap.PROFESSIONALS_READ),
    "contracts": ("Contracts", Cap.CONTRACTS_READ),
    "disputes": ("Disputes", Cap.DISPUTES_READ),
    "support": ("Support requests", Cap.SUPPORT_READ),
    "enforcement": ("Enforcement cases", Cap.SAFETY_READ),
    "incidents": ("Incidents", Cap.INCIDENTS_READ),
}
# Result links: platform-admin console routes (registry slugs).
ACCOUNTS, PROFESSIONALS, CONTRACTS = destination_route("D04"), destination_route("D05"), destination_route("D13")
SUPPORT, SAFETY, INCIDENTS = destination_route("D23"), destination_route("D09"), destination_route("D18")
SEARCH_BUDGET = (120, 60)  # per person: searches per minute, burst (type-ahead is debounced in the web app)


class StaffSearchHitOut(BaseModel):
    kind: Kind
    id: uuid.UUID
    title: str
    subtitle: str | None  # never an unmasked email address
    link: str  # path in the staff console


class StaffSearchGroupOut(BaseModel):
    kind: Kind
    label: str
    items: list[StaffSearchHitOut]


class StaffSearchOut(BaseModel):
    query: str
    scopes: list[Kind]  # the kinds this person may search (all of them were searched)
    groups: list[StaffSearchGroupOut]  # only kinds with at least one match


def mask_email(email: str | None) -> str | None:
    """j***@example.com: the first character of the mailbox and the domain, enough to tell two people apart."""
    if not email or "@" not in email:
        return None
    local, _, domain = email.rpartition("@")
    return f"{local[:1]}***@{domain}" if local else f"***@{domain}"


def _like(term: str) -> str:
    return "%" + term.lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def _words(value: str | None) -> str:
    return (value or "").replace("_", " ").lower()


def _join(*parts: str | None) -> str | None:
    return " · ".join(p for p in parts if p) or None


async def _accounts(session, term, exact, limit):
    rows = await identity_facade.staff_search_accounts(session, term, exact, limit)
    return [StaffSearchHitOut(kind="accounts", id=i.id, title=i.display_name, subtitle=_join(mask_email(i.email), _words(i.status)),
                              link=f"{ACCOUNTS}?selected={i.id}") for i in rows]


async def _organizations(session, term, exact, limit):
    orgs = await buyer_facade.staff_search_organizations(session, term, exact, limit)
    firms = [(f.id, f.name, f.country, f.status) for f in (await firm_facade.admin_rows(session, term, None, None, limit))[:limit]]
    if exact and (one := await firm_facade.get_firm(session, exact)):
        firms.insert(0, (one.id, one.trading_name or one.legal_name, one.hq_country, "SUSPENDED" if one.status == "SUSPENDED" else "ACTIVE"))
    hits = [StaffSearchHitOut(kind="organizations", id=o["id"], title=o["name"],
                              subtitle=_join("Enterprise" if o["kind"] == "ENTERPRISE" else "Buyer organisation", o["country"], _words(o["status"])),
                              link=f"{ACCOUNTS}?tab=orgs&selected={o['id']}") for o in orgs]
    hits += [StaffSearchHitOut(kind="organizations", id=fid, title=name, subtitle=_join("Firm", country, _words(status)),
                               link=f"{ACCOUNTS}?tab=orgs&selected={fid}") for fid, name, country, status in firms]
    return sorted(hits, key=lambda h: h.title.lower())[:limit]


async def _professionals(session, term, exact, limit):
    pros = await professional_facade.staff_search_professionals(session, term, exact, limit)
    people = await identity_facade.get_identities(session, [p["identityId"] for p in pros])
    return [StaffSearchHitOut(kind="professionals", id=p["id"], title=p["displayName"],
                              subtitle=_join(p["headline"], mask_email(people[p["identityId"]].email) if p["identityId"] in people else None),
                              link=f"{PROFESSIONALS}?selected={p['id']}") for p in pros]


async def _contracts(session, term, exact, limit):
    rows = await contract_facade.staff_search_contracts(session, term, exact, limit)
    return [StaffSearchHitOut(kind="contracts", id=c["id"], title=c["title"], subtitle=_join(c["reference"], _words(c["status"])),
                              link=f"{CONTRACTS}?selected={c['id']}") for c in rows]


async def _disputes(session, term, exact, limit):
    rows = await dispute_facade.staff_search_disputes(session, term, exact, limit)
    return [StaffSearchHitOut(kind="disputes", id=d["id"], title=f"{d['reference']}: {d['summary']}"[:200],
                              subtitle=_join(d["contractReference"], _words(d["category"]), _words(d["status"])),
                              link=f"/app/disputes/{d['id']}") for d in rows]


async def _support(session, term, exact, limit):
    rows = await support_facade.staff_search_requests(session, term, exact, limit)
    people = await identity_facade.get_identities(session, [r["requesterIdentityId"] for r in rows])
    return [StaffSearchHitOut(kind="support", id=r["id"], title=r["subject"], subtitle=_join(
        r["reference"], _words(r["status"]),
        mask_email(people[r["requesterIdentityId"]].email) if r["requesterIdentityId"] in people else None),
        link=f"{SUPPORT}?selected={r['id']}") for r in rows]


async def _enforcement(session, term, exact, limit):
    match = [func.lower(EnforcementCase.summary).like(_like(term), escape="\\")]
    if exact:
        match.append(EnforcementCase.id == exact)
    rows = (await session.scalars(select(EnforcementCase).where(or_(*match))
                                  .order_by(EnforcementCase.created_at.desc(), EnforcementCase.id).limit(limit))).all()
    return [StaffSearchHitOut(kind="enforcement", id=c.id, title=c.summary[:200],
                              subtitle=_join(f"Level {c.level}", _words(c.status), _words(c.subject_type)),
                              link=f"{SAFETY}?selected={c.id}") for c in rows]


async def _incidents(session, term, exact, limit):
    like = _like(term)
    match = [func.lower(Incident.title).like(like, escape="\\"), func.lower(Incident.reference).like(like, escape="\\")]
    if exact:
        match.append(Incident.id == exact)
    rows = (await session.scalars(select(Incident).where(or_(*match))
                                  .order_by(Incident.detected_at.desc(), Incident.id).limit(limit))).all()
    return [StaffSearchHitOut(kind="incidents", id=i.id, title=i.title, subtitle=_join(i.reference, i.severity, _words(i.status)),
                              link=f"{INCIDENTS}?selected={i.id}") for i in rows]


SEARCHES = {"accounts": _accounts, "organizations": _organizations, "professionals": _professionals, "contracts": _contracts,
            "disputes": _disputes, "support": _support, "enforcement": _enforcement, "incidents": _incidents}


async def search(session, actor, q: str, limit: int) -> StaffSearchOut:
    actor.require_capability(Cap.STAFF_SEARCH)  # staff only, from a two-step session
    # Scope by the roles the person holds now, not only the ones in the token: a revoked role stops searching at once.
    caps = capabilities_for(set(actor.platform_roles) & set(await identity_facade.live_platform_roles(session, actor.identity_id)))
    if Cap.STAFF_SEARCH not in caps:
        raise Forbidden("Your staff authority has changed")
    term = " ".join(q.split())
    if len(term) < 2:
        raise ValidationFailed("Type at least two characters to search", code="QUERY_TOO_SHORT")
    await enforce_budget("staff_search", str(actor.identity_id), *SEARCH_BUDGET, "Too many searches; wait a moment and try again")
    try:
        exact = uuid.UUID(term)
    except ValueError:
        exact = None
    scopes = [k for k, (_, cap) in SCOPES.items() if cap in caps]
    groups = []
    for kind in scopes:
        items = await SEARCHES[kind](session, term, exact, limit)
        if items:
            groups.append(StaffSearchGroupOut(kind=kind, label=SCOPES[kind][0], items=items))
    record_audit(session, "admin.staff_search.performed", object_type="Identity", object_id=actor.identity_id,
                 details={"length": len(term), "byId": exact is not None, "scopes": scopes,
                          "hits": {g.kind: len(g.items) for g in groups}})
    return StaffSearchOut(query=term, scopes=scopes, groups=groups)


@router.get("/v1/admin/search", response_model=StaffSearchOut)
async def staff_search(actor: CurrentActor, session: DbSession, q: str = Query(min_length=2, max_length=100),
                       limit: int = Query(5, ge=1, le=10)) -> StaffSearchOut:
    """Staff: one search across accounts, organisations, professionals, contracts, disputes, support requests,
    enforcement cases and incidents. Only the kinds the person's roles may see are searched; emails are masked; each
    kind returns at most ``limit`` matches. Audited."""
    return await search(session, actor, q, limit)
