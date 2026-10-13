from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

from zoikorum.shared.money import MoneyDTO

EngagementType = Literal["ADVISORY", "PROJECT", "RETAINER", "FRACTIONAL"]
DeliveryMode = Literal["REMOTE", "ONSITE", "HYBRID"]
PricingModel = Literal["HOURLY", "FIXED", "RETAINER", "CUSTOM"]
Availability = Literal["NOW", "TWO_WEEKS", "ONE_MONTH", "NOT_SPECIFIED"]
ExperienceBand = Literal["0-2", "3-5", "6-10", "11-15", "16+"]
Country = str


class ProfilePatch(BaseModel):
    displayName: str | None = Field(default=None, min_length=1, max_length=200)
    legalName: str | None = Field(default=None, max_length=200)
    headline: str | None = Field(default=None, max_length=120)
    yearsExperienceBand: ExperienceBand | None = None
    bio: str | None = Field(default=None, max_length=3000)
    languages: list[str] | None = Field(default=None, max_length=10)
    city: str | None = Field(default=None, max_length=100)
    country: str | None = Field(default=None, pattern="^[A-Z]{2}$")
    website: str | None = Field(default=None, max_length=300, pattern=r"^(https://.+)?$")
    engagementTypes: list[EngagementType] | None = None
    deliveryModes: list[DeliveryMode] | None = None
    pricingModels: list[PricingModel] | None = None
    indicativeRate: MoneyDTO | None = None
    rateUnit: Literal["HOUR", "DAY", "MONTH", "PROJECT"] | None = None
    clearRate: bool = False


class RegisterIn(BaseModel):
    displayName: str | None = Field(default=None, min_length=1, max_length=200)  # defaults to the account name
    country: str | None = Field(default=None, pattern="^[A-Z]{2}$")  # defaults to the account country
    firmId: uuid.UUID | None = None  # practise under a firm you belong to


class SpecializationsIn(BaseModel):
    primary: str = Field(min_length=1)
    secondary: list[str] = Field(default_factory=list, max_length=5)


class JurisdictionsIn(BaseModel):
    served: list[str] = Field(default_factory=list, max_length=60)
    licensed: list[str] = Field(default_factory=list, max_length=60)
    crossBorderAcknowledged: bool = False


class AvailabilityIn(BaseModel):
    availability: Availability
    maxConcurrentEngagements: int | None = Field(default=None, ge=1, le=50)
    temporarilyUnavailable: bool = False
    weeklyHours: int | None = Field(default=None, ge=0, le=60)  # the weekly availability slider


class SpecializationOut(BaseModel):
    slug: str
    name: str
    primary: bool
    requiresCredential: bool
    regulated: bool


class PhotoIn(BaseModel):
    contentType: Literal["image/jpeg", "image/png", "image/webp"]
    dataBase64: str = Field(min_length=10, max_length=2_900_000)  # <= ~2 MB once decoded


class ProfileOut(BaseModel):
    pendingSpecializations: list[str] = []  # suggested by the professional, waiting for an admin
    id: uuid.UUID
    photoUrl: str | None
    firmId: uuid.UUID | None
    status: str
    displayName: str
    legalName: str | None
    headline: str | None
    yearsExperienceBand: str | None
    bio: str | None
    languages: list[str]
    country: str
    city: str | None
    website: str | None
    primaryCategory: str | None
    specializations: list[SpecializationOut]
    engagementTypes: list[str]
    deliveryModes: list[str]
    pricingModels: list[str]
    indicativeRate: MoneyDTO | None
    rateUnit: str | None
    availability: str
    maxConcurrentEngagements: int | None
    temporarilyUnavailable: bool
    weeklyHours: int | None = None
    servedJurisdictions: list[str]
    licensedJurisdictions: list[str]
    crossBorderAcknowledged: bool
    publishedAt: datetime | None
    version: int


class ReadinessItem(BaseModel):
    key: str
    label: str
    done: bool
    required: bool


class ReadinessOut(BaseModel):
    canPublish: bool
    items: list[ReadinessItem]


class CredentialIn(BaseModel):
    credentialType: Literal["LICENSE", "CERTIFICATION", "MEMBERSHIP", "DEGREE"]
    name: str = Field(min_length=2, max_length=150)
    issuingBody: str = Field(min_length=2, max_length=200)
    registrationNumber: str | None = Field(default=None, max_length=100)
    jurisdiction: str | None = Field(default=None, max_length=10)
    issuedOn: date | None = None
    expiresOn: date | None = None
    specialization: str | None = None  # taxonomy slug this credential supports


class CredentialOut(BaseModel):
    id: uuid.UUID
    credentialType: str
    name: str
    issuingBody: str
    registrationNumber: str | None
    jurisdiction: str | None
    issuedOn: date | None
    expiresOn: date | None
    specialization: str | None
    status: str
    displayLabel: str  # "Self-reported" until verified (Onboarding s.17)


class OfferingIn(BaseModel):
    title: str = Field(min_length=3, max_length=150)
    specialization: str
    summary: str | None = Field(default=None, max_length=1500)
    deliverables: list[str] = Field(default_factory=list, max_length=12)
    engagementTypes: list[EngagementType] = Field(min_length=1)
    pricingModel: PricingModel
    startingPrice: MoneyDTO | None = None
    typicalDuration: str | None = Field(default=None, max_length=50)


class OfferingPatch(BaseModel):
    title: str | None = Field(default=None, min_length=3, max_length=150)
    specialization: str | None = None
    summary: str | None = Field(default=None, max_length=1500)
    deliverables: list[str] | None = Field(default=None, max_length=12)
    engagementTypes: list[EngagementType] | None = Field(default=None, min_length=1)
    pricingModel: PricingModel | None = None
    startingPrice: MoneyDTO | None = None
    clearStartingPrice: bool = False
    typicalDuration: str | None = Field(default=None, max_length=50)


class OfferingOut(BaseModel):
    id: uuid.UUID
    title: str
    specialization: str
    specializationName: str | None = None
    summary: str | None
    deliverables: list[str]
    engagementTypes: list[str]
    pricingModel: str
    startingPrice: MoneyDTO | None
    typicalDuration: str | None
    status: str
    version: int


class PublishIn(BaseModel):
    attestAccurate: Literal[True]


class PublicCredentialOut(BaseModel):
    name: str
    issuingBody: str
    jurisdiction: str | None
    status: str
    displayLabel: str


class PublicTrustOut(BaseModel):
    """Public trust snapshot: tier, dimensions and why (no raw score; screening shown only when clear)."""

    tier: str  # A | B | C
    dimensions: dict[str, str]  # identity, credentials, jurisdiction, restrictions, insurance
    explanation: list[str]
    updatedAt: datetime | None  # "last verified"


class FirmLinkIn(BaseModel):
    firmId: uuid.UUID | None = None  # None = practise independently


class HistoryOut(BaseModel):
    """Platform history (Profile doc s.12): measured on Zoikorum only, never self-reported."""

    completedEngagements: int
    onTimeRate: int | None  # % of accepted milestones delivered by their due date
    medianResponseHours: float | None
    newToPlatform: bool  # neutral caution signal (Category doc s.12)


class PublicFirmOut(BaseModel):
    id: uuid.UUID
    name: str  # trading name when set, otherwise the registered name
    verified: bool  # firm registration checked


class PublicProfileOut(BaseModel):
    """What buyers see (Professional Profile doc). Never includes legal name or registration numbers."""

    id: uuid.UUID
    photoUrl: str | None
    displayName: str
    headline: str | None
    yearsExperienceBand: str | None
    bio: str | None
    languages: list[str]
    country: str
    city: str | None
    primaryCategory: str | None
    primaryCategoryName: str | None
    specializations: list[SpecializationOut]
    engagementTypes: list[str]
    deliveryModes: list[str]
    pricingModels: list[str]
    indicativeRate: MoneyDTO | None
    rateUnit: str | None
    availability: str
    weeklyHours: int | None = None
    servedJurisdictions: list[str]
    licensedJurisdictions: list[str]
    verifiedJurisdictions: list[str]  # licensed jurisdictions backed by a verified check
    credentials: list[PublicCredentialOut]
    offerings: list[OfferingOut]
    trust: PublicTrustOut
    publishedAt: datetime | None
    isOwnProfile: bool
    firm: PublicFirmOut | None = None
    history: HistoryOut | None = None
    pendingSpecializations: list[str] = []  # shown as "Custom (under review)"


# ---- Saved buyers (Professional Dashboard s.17) ----------------------------------

class SavedBuyerIn(BaseModel):
    organizationId: uuid.UUID
    note: str | None = Field(default=None, max_length=500)
    alerts: bool = True


class SavedBuyerPatch(BaseModel):
    note: str | None = Field(default=None, max_length=500)
    alerts: bool | None = None


class BuyerCandidateOut(BaseModel):
    organizationId: uuid.UUID
    name: str
    country: str | None
    saved: bool
    requests: int
    engagements: int
    completed: int
    lastActivityAt: datetime | None


class SavedBuyerOut(BaseModel):
    id: uuid.UUID
    organizationId: uuid.UUID
    name: str
    country: str | None
    note: str | None
    alerts: bool  # their requests are always emailed and marked as from a saved buyer
    requests: int
    engagements: int
    completed: int
    lastActivityAt: datetime | None
    savedAt: datetime
