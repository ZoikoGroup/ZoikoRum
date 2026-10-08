from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from zoikorum.shared.money import MoneyDTO

Sort = Literal["best", "verified", "availability", "experience", "price_asc", "price_desc", "recent"]


class SearchParams(BaseModel):
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
    sort: Sort = "best"
    limit: int = 20
    offset: int = 0


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


class FacetValue(BaseModel):
    value: str
    label: str
    count: int


class SearchOut(BaseModel):
    total: int
    items: list[ResultItem]
    facets: dict[str, list[FacetValue]]
