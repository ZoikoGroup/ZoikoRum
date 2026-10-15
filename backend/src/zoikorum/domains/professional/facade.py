"""Professional facade - read-only interface other domains use."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from zoikorum.domains.professional.models import Offering, Professional, SavedBuyer
from zoikorum.domains.professional.service import effective_availability, photo_url, specializations_of


@dataclass(frozen=True)
class ProfessionalSummary:
    id: uuid.UUID
    identity_id: uuid.UUID
    firm_id: uuid.UUID | None
    display_name: str
    headline: str | None  # primary role title, e.g. "Fractional CFO"
    status: str  # DRAFT | PUBLISHED | UNPUBLISHED | SUSPENDED
    country: str
    primary_category: str | None  # taxonomy category slug
    primary_specialization: str | None  # specialization slug
    specializations: tuple[str, ...]  # primary + secondary slugs
    jurisdictions_served: tuple[str, ...]  # ISO-2
    licensed_jurisdictions: tuple[str, ...]
    engagement_types: tuple[str, ...]  # ADVISORY|PROJECT|RETAINER|FRACTIONAL
    delivery_modes: tuple[str, ...]  # REMOTE|ONSITE|HYBRID
    pricing_models: tuple[str, ...]  # HOURLY|FIXED|RETAINER|CUSTOM
    availability: str  # NOW|TWO_WEEKS|ONE_MONTH|NOT_SPECIFIED|AT_CAPACITY
    max_concurrent_engagements: int | None
    active_engagements: int
    years_experience_band: str | None
    languages: tuple[str, ...]
    visibility_reduced: bool  # enforcement - search must down-rank, with explanation
    industries: tuple[str, ...] = ()
    # Added for the search projection (optional, so existing callers are unaffected).
    bio: str | None = None
    city: str | None = None
    indicative_rate_minor: int | None = None
    indicative_rate_currency: str | None = None
    published_at: datetime | None = None
    photo_url: str | None = None


@dataclass(frozen=True)
class OfferingSummary:
    id: uuid.UUID
    professional_id: uuid.UUID
    title: str
    specialization: str
    engagement_types: tuple[str, ...]
    pricing_model: str
    starting_price_minor: int | None
    currency: str | None
    typical_duration: str | None
    status: str  # DRAFT | ACTIVE | PAUSED
    deliverables: tuple[str, ...]


def _summary(p: Professional) -> ProfessionalSummary:
    return ProfessionalSummary(
        id=p.id, identity_id=p.identity_id, firm_id=p.firm_id, display_name=p.display_name, headline=p.headline,
        status=p.status, country=p.country, primary_category=p.primary_category,
        primary_specialization=p.primary_specialization, specializations=tuple(specializations_of(p)),
        jurisdictions_served=tuple(p.served_jurisdictions), licensed_jurisdictions=tuple(p.licensed_jurisdictions),
        engagement_types=tuple(p.engagement_types), delivery_modes=tuple(p.delivery_modes),
        pricing_models=tuple(p.pricing_models), availability=effective_availability(p),
        max_concurrent_engagements=p.max_concurrent_engagements, active_engagements=p.active_engagements,
        years_experience_band=p.years_experience_band, languages=tuple(p.languages), industries=tuple(p.industries),
        visibility_reduced=p.visibility_reduced, bio=p.bio, city=p.city, indicative_rate_minor=p.rate_minor,
        indicative_rate_currency=p.rate_currency, published_at=p.published_at, photo_url=photo_url(p),
    )


def _offering(o: Offering) -> OfferingSummary:
    return OfferingSummary(
        id=o.id, professional_id=o.professional_id, title=o.title, specialization=o.specialization,
        engagement_types=tuple(o.engagement_types), pricing_model=o.pricing_model,
        starting_price_minor=o.starting_price_minor, currency=o.currency, typical_duration=o.typical_duration,
        status=o.status, deliverables=tuple(o.deliverables),
    )


async def get_professional(session: AsyncSession, professional_id: uuid.UUID) -> ProfessionalSummary | None:
    p = await session.get(Professional, professional_id)
    return _summary(p) if p else None


async def legal_name(session: AsyncSession, professional_id: uuid.UUID) -> str | None:
    """The name as on the professional's ID - for compliance reviewers comparing documents only; never shown publicly."""
    p = await session.get(Professional, professional_id)
    return p.legal_name if p else None


async def get_professional_by_identity(session: AsyncSession, identity_id: uuid.UUID) -> ProfessionalSummary | None:
    p = await session.scalar(select(Professional).where(Professional.identity_id == identity_id))
    return _summary(p) if p else None


async def get_professionals(session: AsyncSession, ids: list[uuid.UUID]) -> dict[uuid.UUID, ProfessionalSummary]:
    if not ids:
        return {}
    rows = (await session.scalars(select(Professional).where(Professional.id.in_(ids)))).all()
    return {p.id: _summary(p) for p in rows}


async def get_offering(session: AsyncSession, offering_id: uuid.UUID) -> OfferingSummary | None:
    o = await session.get(Offering, offering_id)
    return _offering(o) if o else None


async def list_offerings(session: AsyncSession, professional_id: uuid.UUID, active_only: bool = True) -> list[OfferingSummary]:
    stmt = select(Offering).where(Offering.professional_id == professional_id).order_by(Offering.created_at)
    if active_only:
        stmt = stmt.where(Offering.status == "ACTIVE")
    return [_offering(o) for o in (await session.scalars(stmt)).all()]


async def list_professional_ids(session: AsyncSession) -> list[uuid.UUID]:
    """Every professional (any status). Used to rebuild read models such as the search index."""
    return list((await session.scalars(select(Professional.id).order_by(Professional.created_at))).all())


async def count_profiles(session: AsyncSession) -> dict[str, int]:
    """{"total": all profiles, "published": visible to buyers}."""
    from sqlalchemy import func

    rows = dict((await session.execute(select(Professional.status, func.count()).group_by(Professional.status))).all())
    return {"total": sum(rows.values()), "published": rows.get("PUBLISHED", 0)}


async def saved_buyer_alerts(session: AsyncSession, professional_id: uuid.UUID, organization_id: uuid.UUID) -> bool:
    """Whether the professional saved this buyer organisation with alerts on (notification domain)."""
    return bool(await session.scalar(select(SavedBuyer.id).where(
        SavedBuyer.professional_id == professional_id, SavedBuyer.organization_id == organization_id, SavedBuyer.alerts.is_(True))))


async def enterprise_ready(session: AsyncSession, professional_id: uuid.UUID) -> bool:
    from zoikorum.domains.professional import enterprise

    p = await session.get(Professional, professional_id)
    return bool(p) and await enterprise.is_ready(session, p)


async def funnel(session: AsyncSession, since, until) -> dict:
    """Professional onboarding in the period: profiles started, published, and Enterprise Ready decisions."""
    from sqlalchemy import func

    started = await session.scalar(select(func.count()).select_from(Professional).where(
        Professional.created_at >= since, Professional.created_at < until)) or 0
    published = await session.scalar(select(func.count()).select_from(Professional).where(
        Professional.published_at >= since, Professional.published_at < until)) or 0
    live = await session.scalar(select(func.count()).select_from(Professional).where(Professional.status == "PUBLISHED")) or 0
    enterprise = await session.scalar(select(func.count()).select_from(Professional).where(Professional.enterprise_status == "READY")) or 0
    return {"profilesStarted": started, "profilesPublished": published, "publishedNow": live, "enterpriseReadyNow": enterprise}


async def published_rates(session: AsyncSession, specializations: list[str], currency: str) -> dict[str, list[int]]:
    """Indicative rates of published professionals in these specializations, per unit (pricing guidance)."""
    rows = (await session.execute(select(Professional.rate_minor, Professional.rate_unit).where(
        Professional.status == "PUBLISHED", Professional.rate_currency == currency, Professional.rate_minor.is_not(None),
        Professional.primary_specialization.in_(specializations)))).all()
    out: dict[str, list[int]] = {}
    for minor, unit in rows:
        out.setdefault(unit or "PROJECT", []).append(int(minor))
    return out
