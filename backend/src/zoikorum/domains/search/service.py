"""Search & discovery (Architecture 9.4).

The projection is rebuilt from events through other domains' facades. Queries rank with the documented
weights and every result explains itself in plain language. Ranking can never be bought: there is no
paid-placement input.
"""

from __future__ import annotations
from zoikorum.domains.admin import facade as admin_facade

import uuid
from datetime import datetime

from sqlalchemy import delete, func, literal_column, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from zoikorum.domains.marketplace import facade as marketplace_facade
from zoikorum.domains.buyer import facade as buyer_facade
from zoikorum.domains.policy import facade as policy_facade
from zoikorum.domains.professional import facade as professional_facade
from zoikorum.domains.search.models import ProfessionalDocument as Doc
from zoikorum.domains.search.schemas import FacetValue, ResultItem, SearchOut, SearchParams, SpecRef
from zoikorum.domains.trust import facade as trust_facade
from zoikorum.domains.verification import facade as verification_facade
from zoikorum.shared.auth import Actor, PlatformRole
from zoikorum.shared.errors import Forbidden, ValidationFailed
from zoikorum.shared.event_catalog import E
from zoikorum.shared.events import record_event
from zoikorum.shared.money import MoneyDTO

EN = literal_column("'english'::regconfig")
CANDIDATE_CAP = 500  # ranked in the application; ample for the current catalogue size
TIER_LABEL = {"A": "Fully Verified Professional", "B": "Verified Identity", "C": "Unverified (Discovery Only)"}
TIER_RANK = {"A": 3, "B": 2, "C": 1}
# Dimension values that count as "verified" for the `verified=` filter and policy eligibility.
GOOD = {"identity": ("VERIFIED",), "credentials": ("VALIDATED", "NOT_APPLICABLE"), "jurisdiction": ("ELIGIBLE",),
        "insurance": ("VERIFIED", "NOT_REQUIRED"), "restrictions": ("CLEAR",)}
AVAILABILITY_POINTS = {"NOW": 10, "TWO_WEEKS": 7, "ONE_MONTH": 4, "NOT_SPECIFIED": 2, "AT_CAPACITY": 0}
AVAILABILITY_TEXT = {"NOW": "Available now", "TWO_WEEKS": "Can start within 2 weeks", "ONE_MONTH": "Can start within a month"}
EXPERIENCE_RANK = {"16+": 5, "11-15": 4, "6-10": 3, "3-5": 2, "0-2": 1}
LABELS = {
    "ADVISORY": "Advisory", "PROJECT": "Project", "RETAINER": "Retainer", "FRACTIONAL": "Fractional",
    "REMOTE": "Remote", "ONSITE": "On-site", "HYBRID": "Hybrid", "HOURLY": "Hourly", "FIXED": "Fixed fee",
    "CUSTOM": "Quote on request", "NOW": "Available now", "TWO_WEEKS": "Within 2 weeks", "ONE_MONTH": "Within a month",
    "NOT_SPECIFIED": "Not specified", "AT_CAPACITY": "At capacity", "A": "Tier A", "B": "Tier B", "C": "Tier C",
}


# ---- Projection ------------------------------------------------------------------

def _weighted(text: str, weight: str):
    assert weight in "ABCD"
    # setweight() takes a "char"; a bound text parameter would not match the function signature.
    return func.setweight(func.to_tsvector(EN, text), literal_column(f"'{weight}'::\"char\""))


async def rebuild(session: AsyncSession, professional_id: uuid.UUID, occurred_at: datetime | None = None) -> None:
    """Rebuild one professional's document from the owning domains. Idempotent."""
    pro = await professional_facade.get_professional(session, professional_id)
    if pro is None:
        await session.execute(delete(Doc).where(Doc.professional_id == professional_id))
        return
    offerings = await professional_facade.list_offerings(session, pro.id, active_only=True)
    trust = await trust_facade.get_trust(session, pro.id)
    checks = await verification_facade.get_checks(session, "PROFESSIONAL", pro.id)
    specs = await marketplace_facade.get_specializations(session, list(pro.specializations))
    names = {s: (specs[s].name if s in specs else s) for s in pro.specializations}
    verified_credentials = [c.label for c in checks if c.verification_type == "CREDENTIAL" and c.status == "VERIFIED"]
    verified_jurisdictions = sorted({c.jurisdiction[:2].upper() for c in checks if c.status == "VERIFIED" and c.jurisdiction
                                     and c.verification_type in ("JURISDICTION", "CREDENTIAL")})
    priced = [o for o in offerings if o.starting_price_minor is not None]
    cheapest = min(priced, key=lambda o: o.starting_price_minor, default=None)

    text_a = " ".join(filter(None, [pro.display_name, pro.headline]))
    text_b = " ".join(names.values())
    text_c = " ".join(filter(None, [pro.bio, *(o.title for o in offerings), *(d for o in offerings for d in o.deliverables),
                                    *verified_credentials]))
    values = dict(
        professional_id=pro.id, visible=pro.status == "PUBLISHED" and not set(await admin_facade.active_restrictions(session, "IDENTITY", pro.identity_id)).intersection({"SUSPEND_ACCOUNT", "OFFBOARD"}),
        visibility_reduced=pro.visibility_reduced or "VISIBILITY_REDUCTION" in await admin_facade.active_restrictions(session, "PROFESSIONAL", pro.id),
        display_name=pro.display_name, headline=pro.headline, country=pro.country, city=pro.city,
        years_experience_band=pro.years_experience_band, languages=list(pro.languages),
        categories=sorted({i.category_slug for i in specs.values()}), primary_specialization=pro.primary_specialization,
        specializations=list(pro.specializations), specialization_names=names,
        engagement_types=list(pro.engagement_types), delivery_modes=list(pro.delivery_modes),
        pricing_models=list(pro.pricing_models), availability=pro.availability,
        served_jurisdictions=list(pro.jurisdictions_served), licensed_jurisdictions=list(pro.licensed_jurisdictions),
        tier=trust.tier, trust_score=trust.score, dimensions=dict(trust.dimensions), verified_credentials=verified_credentials,
        verified_jurisdictions=verified_jurisdictions,
        offering_titles=[o.title for o in offerings], starting_price_minor=cheapest.starting_price_minor if cheapest else None,
        price_currency=cheapest.currency if cheapest else None, bio_excerpt=(pro.bio or "")[:300] or None, photo_url=pro.photo_url,
        published_at=pro.published_at, last_event_at=occurred_at,
        document=_weighted(text_a, "A").op("||")(_weighted(text_b, "B")).op("||")(_weighted(text_c, "C")),
    )
    stmt = pg_insert(Doc).values(id=uuid.uuid4(), **values)
    await session.execute(stmt.on_conflict_do_update(
        index_elements=[Doc.professional_id],
        set_={**{k: stmt.excluded[k] for k in values if k != "professional_id"}, "updated_at": func.now()},
    ))


async def reindex(session: AsyncSession, actor: Actor) -> dict:
    actor.require_platform_role(PlatformRole.PLATFORM_ADMIN)
    return {"reindexed": await reindex_all(session)}


async def reindex_all(session: AsyncSession) -> int:
    ids = await professional_facade.list_professional_ids(session)
    await session.execute(delete(Doc).where(Doc.professional_id.not_in(ids)) if ids else delete(Doc))
    for pid in ids:
        await rebuild(session, pid)
    return len(ids)


# ---- Query -----------------------------------------------------------------------

def _escape_like(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _conditions(p: SearchParams, tsquery) -> list:
    # Safety: unpublished and suspended profiles never appear. Buyer-organization policy filters
    # (minimum tier, jurisdictions) are applied here once the policy domain exists.
    conds = [Doc.visible.is_(True),
             # Never surface professionals whose screening was flagged or whose jurisdiction is restricted (Arch 9.3).
             func.coalesce(Doc.dimensions["restrictions"].astext, "") != "FLAGGED",
             func.coalesce(Doc.dimensions["jurisdiction"].astext, "") != "RESTRICTED"]
    if tsquery is not None:
        conds.append(Doc.document.op("@@")(tsquery))
    if p.category:
        conds.append(Doc.categories.contains([p.category]))
    if p.spec:
        conds.append(Doc.specializations.contains(p.spec) if p.specMatch == "all" else Doc.specializations.overlap(p.spec))
    if p.tier:
        conds.append(Doc.tier.in_([t.upper() for t in p.tier]))
    for dim in p.verified:
        if dim not in GOOD:
            raise ValidationFailed(f"Unknown verification filter {dim!r}", code="INVALID_FILTER")
        conds.append(Doc.dimensions[dim].astext.in_(GOOD[dim]))
    for value, column in ((p.engagementType, Doc.engagement_types), (p.delivery, Doc.delivery_modes),
                          (p.pricingModel, Doc.pricing_models)):
        if value:
            conds.append(column.contains([value]))
    if p.availability:
        conds.append(Doc.availability == p.availability)
    if p.credential:
        conds.append(func.array_to_string(Doc.verified_credentials, " ").ilike(f"%{_escape_like(p.credential)}%", escape="\\"))
    if p.experience:
        conds.append(Doc.years_experience_band == p.experience)
    if p.publishedAfter:
        conds.append(Doc.published_at > p.publishedAfter)
    if p.jurisdiction:
        j = p.jurisdiction.upper()
        conds.append(or_(Doc.served_jurisdictions.contains([j]), Doc.licensed_jurisdictions.contains([j])))
    return conds


def _rank_and_explain(doc: Doc, rank: float, max_rank: float, p: SearchParams) -> tuple[float, list[str]]:
    """Architecture 9.4 weights: relevance 30, trust 20, contract success 15, reviews 10, availability 10,
    response 5, pricing fit 5, policy fit 5. Contract, review, response and policy signals are 0 until
    those domains exist, so today's order comes from relevance, trust and availability."""
    why: list[str] = []
    relevance = 0.0
    if p.q:
        relevance = 30 * (rank / max_rank if max_rank else 0)
        needle = p.q.strip().lower()
        if needle in f"{doc.display_name} {doc.headline or ''}".lower():
            why.append(f"“{p.q.strip()}” matches their name or headline")
        elif any(needle in n.lower() for n in doc.specialization_names.values()):
            why.append(f"“{p.q.strip()}” matches their specializations")
        else:
            why.append(f"“{p.q.strip()}” matches their profile or services")
    if p.spec:
        matched = [s for s in doc.specializations if s in p.spec]
        relevance = max(relevance, 30 if doc.primary_specialization in p.spec else 20)
        primary = doc.primary_specialization in matched
        why.append(f"Specializes in {', '.join(doc.specialization_names.get(s, s) for s in matched)}" + (" (primary)" if primary else ""))
    trust = {"A": 12, "B": 8, "C": 2}[doc.tier] + 8 * doc.trust_score / 100  # tier and trust score (Arch 9.4)
    why.append(f"Tier {doc.tier}: {TIER_LABEL[doc.tier]}")
    if doc.verified_credentials:
        why.append(f"Verified credential: {doc.verified_credentials[0]}")
    availability = AVAILABILITY_POINTS.get(doc.availability, 0)
    if doc.availability in AVAILABILITY_TEXT:
        why.append(AVAILABILITY_TEXT[doc.availability])
    if p.jurisdiction:
        j = p.jurisdiction.upper()
        if j in doc.licensed_jurisdictions:
            why.append(f"Licensed in {j} " + ("(verified)" if j in doc.verified_jurisdictions else "(self-reported)"))
        else:
            why.append(f"Serves clients in {j}")
    pricing_fit = 5 if p.pricingModel else 0
    score = relevance + trust + availability + pricing_fit
    if doc.visibility_reduced:
        score *= 0.5  # enforcement: visibility reduction (explained to the professional, not to buyers)
    return score, why[:6]


def _sort_key(sort: str):
    def key(entry):
        doc, score = entry
        published = doc.published_at.timestamp() if doc.published_at else 0
        if sort == "verified":
            return (-TIER_RANK[doc.tier], -doc.trust_score, -score)
        if sort == "availability":
            return (-AVAILABILITY_POINTS.get(doc.availability, 0), -score)
        if sort == "experience":
            return (-EXPERIENCE_RANK.get(doc.years_experience_band or "", 0), -score)
        if sort in ("price_asc", "price_desc"):
            price = doc.starting_price_minor
            return (price is None, (price or 0) if sort == "price_asc" else -(price or 0))
        if sort == "recent":
            return (-published,)
        return (-score, -doc.trust_score, -published)
    return key


def _facets(docs: list[Doc]) -> dict[str, list[FacetValue]]:
    def count(values_of, label_of=lambda v: LABELS.get(v, v)):
        counts: dict[str, int] = {}
        for d in docs:
            for v in values_of(d):
                counts[v] = counts.get(v, 0) + 1
        return [FacetValue(value=v, label=label_of(v), count=n) for v, n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))]

    names = {s: n for d in docs for s, n in d.specialization_names.items()}
    return {
        "tier": count(lambda d: [d.tier]),
        "specialization": count(lambda d: d.specializations, lambda v: names.get(v, v)),
        "delivery": count(lambda d: d.delivery_modes),
        "pricingModel": count(lambda d: d.pricing_models),
        "engagementType": count(lambda d: d.engagement_types),
        "availability": count(lambda d: [d.availability]),
    }


def _item(doc: Doc, why: list[str]) -> ResultItem:
    price = (MoneyDTO(amountMinor=doc.starting_price_minor, currency=doc.price_currency)
             if doc.starting_price_minor is not None and doc.price_currency else None)
    return ResultItem(
        professionalId=doc.professional_id, photoUrl=doc.photo_url, displayName=doc.display_name, headline=doc.headline, country=doc.country,
        city=doc.city, specializations=[SpecRef(slug=s, name=doc.specialization_names.get(s, s), primary=s == doc.primary_specialization)
                                        for s in doc.specializations],
        engagementTypes=doc.engagement_types, deliveryModes=doc.delivery_modes, pricingModels=doc.pricing_models,
        availability=doc.availability, startingPrice=price, tier=doc.tier, tierLabel=TIER_LABEL[doc.tier],
        trustScore=doc.trust_score, whyThisResult=why, languages=doc.languages, yearsExperienceBand=doc.years_experience_band,
        dimensions={**doc.dimensions, **({"restrictions": "UNKNOWN"} if doc.dimensions.get("restrictions") not in (None, "CLEAR") else {})},
    )


async def search(session: AsyncSession, actor: Actor | None, p: SearchParams) -> SearchOut:
    q = (p.q or "").strip() or None
    p = p.model_copy(update={"q": q})
    tsquery = func.websearch_to_tsquery(EN, q) if q else None
    conds = _conditions(p, tsquery)
    org_id = p.organizationId
    if org_id:
        if actor is None or not await buyer_facade.get_member_roles(session, org_id, actor.identity_id):
            raise Forbidden("This organization search requires active membership")
    elif actor:
        organizations = await buyer_facade.list_identity_organizations(session, actor.identity_id)
        if len(organizations) == 1:
            org_id = organizations[0]
    if org_id:
        eligibility = await policy_facade.search_eligibility(session, org_id)
        conds.append(Doc.tier.in_([t for t in TIER_RANK if TIER_RANK[t] >= TIER_RANK[eligibility['minTier']]]))
        dimension_values = {**GOOD, "credentials": ("VALIDATED", "NOT_APPLICABLE"), "insurance": ("VERIFIED", "NOT_REQUIRED")}
        for dim in eligibility['requiredDimensions']:
            conds.append(Doc.dimensions[dim].astext.in_(dimension_values[dim]))
        if eligibility.get('jurisdictions'):
            conds.append(Doc.served_jurisdictions.overlap(eligibility['jurisdictions']))
    total = await session.scalar(select(func.count()).select_from(Doc).where(*conds)) or 0

    # The candidate cap keeps the strongest matches: most relevant first, then most trusted.
    order = [Doc.trust_score.desc(), Doc.published_at.desc().nulls_last()]
    if tsquery is not None:
        rank_col = func.ts_rank_cd(Doc.document, tsquery)
        order.insert(0, rank_col.desc())
    else:
        rank_col = literal_column("0.0")
    rows = (await session.execute(
        select(Doc, rank_col.label("rank")).where(*conds).order_by(*order).limit(CANDIDATE_CAP)
    )).all()
    max_rank = max((float(r) for _, r in rows), default=0.0)
    ranked = []
    whys: dict[uuid.UUID, list[str]] = {}
    for doc, r in rows:
        score, why = _rank_and_explain(doc, float(r), max_rank, p)
        ranked.append((doc, score))
        whys[doc.professional_id] = why
    ranked.sort(key=_sort_key(p.sort))
    page = ranked[p.offset:p.offset + p.limit]

    filters = {k: v for k, v in p.model_dump(exclude={"limit", "offset", "sort", "specMatch"}).items() if v}
    record_event(session, E.SEARCH_PERFORMED, aggregate_type="Search", aggregate_id=uuid.uuid4(),
                 payload={"query": q, "filters": filters, "sort": p.sort, "total": total,
                          "actorId": actor.identity_id if actor else None})
    if total == 0:
        record_event(session, E.SEARCH_ZERO_RESULT, aggregate_type="Search", aggregate_id=uuid.uuid4(),
                     payload={"query": q, "filters": filters})
    return SearchOut(total=total, items=[_item(d, whys[d.professional_id]) for d, _ in page], facets=_facets([d for d, _ in rows]))


async def count_eligible(session: AsyncSession, eligibility: dict) -> int:
    """{"minTier","requiredDimensions","jurisdictions","categories"} -> number of discoverable professionals."""
    conds = [Doc.visible.is_(True)]
    if eligibility.get("minTier"):
        allowed = [t for t, r in TIER_RANK.items() if r >= TIER_RANK[eligibility["minTier"]]]
        conds.append(Doc.tier.in_(allowed))
    for dim in eligibility.get("requiredDimensions") or []:
        if dim in GOOD:
            conds.append(Doc.dimensions[dim].astext.in_(GOOD[dim]))
    if eligibility.get("jurisdictions"):
        conds.append(Doc.served_jurisdictions.overlap(list(eligibility["jurisdictions"])))
    if eligibility.get("categories"):
        conds.append(Doc.categories.overlap(list(eligibility["categories"])))
    return await session.scalar(select(func.count()).select_from(Doc).where(*conds)) or 0
