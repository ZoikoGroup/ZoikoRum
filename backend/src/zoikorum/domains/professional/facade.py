"""Professional facade - read-only interface other domains use."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from zoikorum.domains.professional.models import Offering, Professional
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
        years_experience_band=p.years_experience_band, languages=tuple(p.languages),
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
