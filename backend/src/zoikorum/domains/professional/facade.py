"""Professional facade - CONTRACT. Signatures and DTOs are fixed; implement bodies."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession


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


async def get_professional(session: AsyncSession, professional_id: uuid.UUID) -> ProfessionalSummary | None:
    raise NotImplementedError


async def get_professional_by_identity(session: AsyncSession, identity_id: uuid.UUID) -> ProfessionalSummary | None:
    raise NotImplementedError


async def get_professionals(session: AsyncSession, ids: list[uuid.UUID]) -> dict[uuid.UUID, ProfessionalSummary]:
    raise NotImplementedError


async def get_offering(session: AsyncSession, offering_id: uuid.UUID) -> OfferingSummary | None:
    raise NotImplementedError


async def list_offerings(session: AsyncSession, professional_id: uuid.UUID, active_only: bool = True) -> list[OfferingSummary]:
    raise NotImplementedError
