from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from zoikorum.shared.money import MoneyDTO

Sort = Literal["best", "verified", "availability", "experience", "price_asc", "price_desc", "recent"]


class SearchParams(BaseModel):
    organizationId: uuid.UUID | None = None
    q: str | None = None
    category: str | None = None
    spec: list[str] = []
    specMatch: Literal["any", "all"] = "any"
    tier: list[str] = []
    verified: list[str] = []  # dimension keys that must be verified: identity, credentials, jurisdiction, insurance, restrictions
    engagementType: str | None = None
    delivery: str | None = None
    availability: str | None = None
    pricingModel: str | None = None
    credential: str | None = None
    jurisdiction: str | None = None
    experience: str | None = None  # years band, e.g. 6-10
    publishedAfter: datetime | None = None  # saved searches: "new since you last looked"
    industry: str | None = None  # industry served
    crossBorder: bool = False  # serves clients outside their own country
    budgetMaxMinor: int | None = None  # starting price at or under this (in budgetCurrency); unpriced offers still show
    budgetCurrency: str | None = None
    language: str | None = None
    sort: Sort = "best"
    limit: int = 20
    offset: int = 0


class IntentIn(BaseModel):
    text: str = Field(min_length=3, max_length=1000)  # "an ongoing fractional CFO in Germany who can start now"


class IntentFilters(BaseModel):
    """Ordinary search parameters, so the page applies them like any filter the buyer picks."""
    q: str | None = None
    spec: list[str] = []
    engagementType: str | None = None
    delivery: str | None = None
    availability: str | None = None
    jurisdiction: str | None = None
    verified: list[str] = []


class IntentOut(BaseModel):
    filters: IntentFilters
    reasons: list[str]  # one plain-language line per filter, shown so the buyer can check and change them
    source: str  # "ai:<model>@<version>" or "fallback:keyword"


class SpecRef(BaseModel):
    slug: str
    name: str
    primary: bool


class ResultItem(BaseModel):
    professionalId: uuid.UUID
    photoUrl: str | None
    displayName: str
    headline: str | None
    country: str
    city: str | None
    specializations: list[SpecRef]
    engagementTypes: list[str]
    deliveryModes: list[str]
    pricingModels: list[str]
    availability: str
    startingPrice: MoneyDTO | None
    tier: str
    tierLabel: str
    trustScore: int
    dimensions: dict[str, str] = {}  # public view: screening shown only when clear
    languages: list[str] = []
    yearsExperienceBand: str | None = None
    servedJurisdictions: list[str] = []  # where they take work (empty = unrestricted)
    licensedJurisdictions: list[str] = []
    whyThisResult: list[str]
    regulatedPreview: bool = False  # offers regulated work but is below Tier A: shown, but cannot take that work yet


class FacetValue(BaseModel):
    value: str
    label: str
    count: int


class PolicyFilterOut(BaseModel):
    """The buyer organisation's policy applied to these results, so people know why some professionals are not shown."""
    organizationId: uuid.UUID
    organizationName: str
    minTier: str
    requiredDimensions: list[str]
    jurisdictions: list[str] | None
    hidden: int  # professionals matching the search that the policy leaves out


class SearchOut(BaseModel):
    total: int
    items: list[ResultItem]
    facets: dict[str, list[FacetValue]]
    policy: PolicyFilterOut | None = None


class SuggestOut(BaseModel):
    """Autocomplete for the search box: expertise first (it becomes a filter), then matching professionals."""
    specializations: list[dict] = []  # {slug, name}
    professionals: list[dict] = []  # {id, name, headline}
