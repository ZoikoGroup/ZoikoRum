from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from zoikorum.shared.money import MoneyDTO


class SpecializationIn(BaseModel):
    groupSlug: str = Field(min_length=1, max_length=120)
    name: str = Field(min_length=2, max_length=200)
    requiresCredential: bool = False
    regulated: bool = False
    requiresInsurance: bool = False
    deliverableTemplates: list[str] = Field(default_factory=list, max_length=12)
    credentialHints: list[str] = Field(default_factory=list, max_length=20)


class SpecializationPatch(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=200)
    requiresCredential: bool | None = None
    regulated: bool | None = None
    requiresInsurance: bool | None = None
    deliverableTemplates: list[str] | None = Field(default=None, max_length=12)
    credentialHints: list[str] | None = Field(default=None, max_length=20)


class SpecializationAdminOut(BaseModel):
    slug: str
    name: str
    groupSlug: str
    categorySlug: str
    requiresCredential: bool
    regulated: bool
    requiresInsurance: bool
    deliverableTemplates: list[str]
    credentialHints: list[str]
    status: str
    taxonomyVersion: int


class SaveIn(BaseModel):
    professionalId: uuid.UUID


class SavedOut(BaseModel):
    professionalId: uuid.UUID
    displayName: str
    headline: str | None
    photoUrl: str | None = None
    city: str | None = None
    country: str | None = None
    languages: list[str] = []
    yearsExperienceBand: str | None = None
    primarySpecialization: str | None
    specializations: list[str] = []  # display names, primary first
    engagementTypes: list[str] = []
    pricingModels: list[str] = []
    startingPrice: MoneyDTO | None = None
    tier: str
    dimensions: dict[str, str] = {}  # public view: screening shown only when clear
    lastVerifiedAt: datetime | None = None
    availability: str
    available: bool  # False when the profile is no longer published
    collectionIds: list[uuid.UUID] = []
    savedAt: datetime


class CollectionIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)


class CollectionOut(BaseModel):
    id: uuid.UUID
    name: str
    count: int
    updatedAt: datetime


class CollectionItemsIn(BaseModel):
    professionalIds: list[uuid.UUID] = Field(min_length=1, max_length=50)


class CompareItem(BaseModel):
    professionalId: uuid.UUID
    displayName: str
    headline: str | None
    photoUrl: str | None
    country: str
    tier: str
    dimensions: dict[str, str]
    verifiedCredentials: list[str]
    specializations: list[str]
    engagementTypes: list[str]
    deliveryModes: list[str]
    pricingModels: list[str]
    startingPrice: MoneyDTO | None
    availability: str
    yearsExperienceBand: str | None
    servedJurisdictions: list[str]
    licensedJurisdictions: list[str]
    languages: list[str]


SEARCH_KEYS = ("q", "spec", "specMatch", "tier", "verified", "engagementType", "delivery", "availability", "pricingModel",
               "credential", "jurisdiction", "experience", "sort")


class SavedSearchIn(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    params: dict[str, str] = Field(default_factory=dict)


class SavedSearchOut(BaseModel):
    id: uuid.UUID
    name: str
    params: dict[str, str]
    lastViewedAt: datetime
    createdAt: datetime
