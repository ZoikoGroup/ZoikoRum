"""Professional domain commands: onboarding, profile, specializations, jurisdictions,
availability, credential claims, offerings and publishing (Professional Onboarding doc)."""

from __future__ import annotations

import base64
import hashlib
import re
import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from zoikorum.domains.contract import facade as contract_facade
from zoikorum.domains.firm import facade as firm_facade
from zoikorum.domains.identity import facade as identity_facade
from zoikorum.domains.marketplace import facade as marketplace_facade
from zoikorum.domains.proposal import facade as proposal_facade
from zoikorum.domains.trust import facade as trust_facade
from zoikorum.domains.verification import facade as verification_facade
from zoikorum.domains.professional.models import CredentialClaim, Offering, Professional
from zoikorum.domains.professional.schemas import (
    AvailabilityIn,
    CredentialIn,
    CredentialOut,
    FirmLinkIn,
    JurisdictionsIn,
    OfferingIn,
    OfferingOut,
    OfferingPatch,
    ProfileOut,
    ProfilePatch,
    PublicCredentialOut,
    HistoryOut,
    PublicFirmOut,
    PublicProfileOut,
    PublicTrustOut,
    PhotoIn,
    ReadinessItem,
    ReadinessOut,
    RegisterIn,
    SpecializationOut,
    SpecializationsIn,
)
from zoikorum.shared import clock
from zoikorum.shared.auth import Actor, Persona
from zoikorum.shared.errors import Conflict, Forbidden, NotFound, ValidationFailed, VersionConflict
from zoikorum.shared.event_catalog import E
from zoikorum.shared.events import record_audit, record_event
from zoikorum.shared.money import MoneyDTO
from zoikorum.shared.state_machine import StateMachine
from zoikorum.shared.storage import get_storage

PROFILE_STATES = StateMachine("Professional", {
    "DRAFT": {"PUBLISHED", "SUSPENDED"},
    "PUBLISHED": {"UNPUBLISHED", "SUSPENDED"},
    "UNPUBLISHED": {"PUBLISHED", "SUSPENDED"},
    "SUSPENDED": {"DRAFT", "PUBLISHED", "UNPUBLISHED"},  # reinstatement (enforcement reversal)
})
OFFERING_STATES = StateMachine("Offering", {
    "DRAFT": {"ACTIVE"},
    "ACTIVE": {"PAUSED"},
    "PAUSED": {"ACTIVE"},  # paused != deleted
})

MAX_OFFERINGS = 20
MAX_CREDENTIALS = 20
MAX_BIO_WORDS = 300  # Onboarding s.7 (150-250 words recommended on the public profile)
# Copy rules (Ethics Code, Onboarding s.17): no unverifiable superlatives or promises of outcome.
# "top-line"/"top-down" are finance terms, not claims; "top-rated", "top-tier", "top 1%" are claims.
_SUPERLATIVES = re.compile(r"#\s?1\b|\bno\.\s?1\b|\bnumber one\b|\b(best|leading|guarantee[sd]?|top(?!-(?:line|down)\b))\b",
                           re.IGNORECASE)
# Claim states the owner sees; FAILED/REVOKED/EXPIRED/WITHDRAWN are hidden from buyers.
# Owner labels follow Onboarding s.12 (Validated / Pending / Not validated); buyers see "Self-reported" until validated (s.17).
_LABELS = {"SELF_REPORTED": "Self-reported", "PENDING": "Pending", "VERIFIED": "Validated",
           "FAILED": "Not validated", "EXPIRED": "Expired", "REVOKED": "Revoked", "WITHDRAWN": "Withdrawn"}
# Expired credentials stay visible as "Expired" (Trust & Safety Charter s.7.2: expired credentials cannot be hidden);
# failed or revoked claims are removed from public display (Onboarding s.17).
_PUBLIC_CLAIM_STATES = ("SELF_REPORTED", "PENDING", "VERIFIED", "EXPIRED")


def _evt(session: AsyncSession, event_type: str, pro: Professional, *, aggregate_type: str = "Professional",
         aggregate_id: uuid.UUID | None = None, **payload) -> None:
    record_event(session, event_type, aggregate_type=aggregate_type, aggregate_id=aggregate_id or pro.id,
                 tenant_id=pro.id, payload={"professionalId": pro.id, **payload})


def public_dimensions(dimensions: dict[str, str]) -> dict[str, str]:
    """Buyers never see a screening problem, only whether it is clear (a flag stays between the professional and Trust & Safety)."""
    out = dict(dimensions)
    if out.get("restrictions") not in (None, "CLEAR"):
        out["restrictions"] = "UNKNOWN"
    return out


def public_explanation(lines) -> list[str]:
    return [line for line in lines if "screening" not in line and "suspended" not in line]


def check_copy(field: str, text: str | None) -> None:
    if text and (m := _SUPERLATIVES.search(text)):
        raise ValidationFailed(
            f"Your {field} uses {m.group(0)!r}. Describe what you do and let verified facts speak instead "
            "of superlatives or guarantees.", code="COPY_RULES")


def effective_availability(pro: Professional) -> str:
    """What buyers see. At capacity overrides whatever the professional picked."""
    if pro.temporarily_unavailable:
        return "AT_CAPACITY"
    if pro.max_concurrent_engagements is not None and pro.active_engagements >= pro.max_concurrent_engagements:
        return "AT_CAPACITY"
    return pro.availability


def specializations_of(pro: Professional) -> list[str]:
    return ([pro.primary_specialization] if pro.primary_specialization else []) + list(pro.secondary_specializations)


def _if_match(version: int | None, current: int, what: str) -> None:
    if version is not None and version != current:
        raise VersionConflict(f"Your {what} was changed somewhere else. Reload and try again.")


# ---- Loading -------------------------------------------------------------------

async def _mine(session: AsyncSession, actor: Actor, lock: bool = False) -> Professional:
    # Looked up by identity, not the token's `pro` claim: that claim only appears after a token refresh.
    stmt = select(Professional).where(Professional.identity_id == actor.identity_id)
    pro = await session.scalar(stmt.with_for_update() if lock else stmt)
    if pro is None:
        raise NotFound("You have not created a professional profile yet", code="PROFILE_NOT_FOUND")
    return pro


async def _offering(session: AsyncSession, pro: Professional, offering_id: uuid.UUID, lock: bool = False) -> Offering:
    o = await session.get(Offering, offering_id, with_for_update=lock)
    if o is None or o.professional_id != pro.id:
        raise NotFound("Offering not found")
    return o


# ---- Output --------------------------------------------------------------------

async def _spec_out(session: AsyncSession, pro: Professional) -> list[SpecializationOut]:
    slugs = specializations_of(pro)
    info = await marketplace_facade.get_specializations(session, slugs)
    out = []
    for slug in slugs:
        i = info.get(slug)  # missing => deprecated since it was chosen; keep showing it
        out.append(SpecializationOut(slug=slug, name=i.name if i else slug, primary=slug == pro.primary_specialization,
                                     requiresCredential=bool(i and i.requires_credential), regulated=bool(i and i.regulated)))
    return out


def photo_url(pro: Professional) -> str | None:
    # The hash in the URL busts browser caches when the photo changes.
    return f"/v1/professionals/{pro.id}/photo?v={pro.photo_sha256[:12]}" if pro.photo_key else None


def _rate(pro: Professional) -> MoneyDTO | None:
    return MoneyDTO(amountMinor=pro.rate_minor, currency=pro.rate_currency) if pro.rate_minor is not None else None


async def _profile_out(session: AsyncSession, pro: Professional) -> ProfileOut:
    return ProfileOut(
        id=pro.id, photoUrl=photo_url(pro), firmId=pro.firm_id, status=pro.status, displayName=pro.display_name, legalName=pro.legal_name,
        headline=pro.headline, yearsExperienceBand=pro.years_experience_band, bio=pro.bio, languages=list(pro.languages),
        country=pro.country, city=pro.city, website=pro.website, primaryCategory=pro.primary_category,
        specializations=await _spec_out(session, pro), engagementTypes=list(pro.engagement_types),
        deliveryModes=list(pro.delivery_modes), pricingModels=list(pro.pricing_models), indicativeRate=_rate(pro),
        rateUnit=pro.rate_unit, availability=pro.availability, maxConcurrentEngagements=pro.max_concurrent_engagements,
        temporarilyUnavailable=pro.temporarily_unavailable, servedJurisdictions=list(pro.served_jurisdictions),
        licensedJurisdictions=list(pro.licensed_jurisdictions),
        crossBorderAcknowledged=pro.cross_border_acknowledged_at is not None, publishedAt=pro.published_at,
        version=pro.version,
    )


def _credential_out(c: CredentialClaim) -> CredentialOut:
    return CredentialOut(
        id=c.id, credentialType=c.credential_type, name=c.name, issuingBody=c.issuing_body,
        registrationNumber=c.registration_number, jurisdiction=c.jurisdiction, issuedOn=c.issued_on,
        expiresOn=c.expires_on, specialization=c.specialization, status=c.status, displayLabel=_LABELS[c.status],
    )


def _offering_out(o: Offering, names: dict[str, str] | None = None) -> OfferingOut:
    price = MoneyDTO(amountMinor=o.starting_price_minor, currency=o.currency) if o.starting_price_minor is not None else None
    return OfferingOut(
        id=o.id, title=o.title, specialization=o.specialization, specializationName=(names or {}).get(o.specialization),
        summary=o.summary, deliverables=list(o.deliverables), engagementTypes=list(o.engagement_types),
        pricingModel=o.pricing_model, startingPrice=price, typicalDuration=o.typical_duration, status=o.status,
        version=o.version,
    )


async def _spec_names(session: AsyncSession, slugs: list[str]) -> dict[str, str]:
    return {s: i.name for s, i in (await marketplace_facade.get_specializations(session, slugs)).items()}


# ---- Registration & profile ----------------------------------------------------

async def register(session: AsyncSession, actor: Actor, body: RegisterIn) -> ProfileOut:
    """One professional profile per ZoikoID. Starts as an unpublished DRAFT."""
    actor.require_persona(Persona.PROFESSIONAL)
    if await session.scalar(select(Professional.id).where(Professional.identity_id == actor.identity_id)):
        raise Conflict("You already have a professional profile", code="PROFILE_EXISTS")
    if body.firmId and not await firm_facade.member_roles(session, body.firmId, actor.identity_id):
        raise Forbidden("You can only practise under a firm you are a member of", code="NOT_FIRM_MEMBER")
    who = await identity_facade.get_identity(session, actor.identity_id)
    if who is None:
        raise NotFound("Account not found")
    pro = Professional(identity_id=actor.identity_id, firm_id=body.firmId,
                       display_name=(body.displayName or who.display_name).strip(), country=body.country or who.country)
    session.add(pro)
    await session.flush()
    _evt(session, E.PROFESSIONAL_REGISTERED, pro, identityId=actor.identity_id, firmId=pro.firm_id, country=pro.country)
    return await _profile_out(session, pro)


async def get_me(session: AsyncSession, actor: Actor) -> ProfileOut:
    return await _profile_out(session, await _mine(session, actor))


async def update_me(session: AsyncSession, actor: Actor, patch: ProfilePatch, if_match: int | None) -> ProfileOut:
    pro = await _mine(session, actor, lock=True)
    _if_match(if_match, pro.version, "profile")
    check_copy("display name", patch.displayName)
    check_copy("headline", patch.headline)
    check_copy("bio", patch.bio)
    if patch.bio and len(patch.bio.split()) > MAX_BIO_WORDS:
        raise ValidationFailed(f"Keep your bio to {MAX_BIO_WORDS} words or fewer (150-250 reads best)", code="BIO_TOO_LONG")
    fields = {"displayName": "display_name", "legalName": "legal_name", "headline": "headline",
              "yearsExperienceBand": "years_experience_band", "bio": "bio", "city": "city", "country": "country",
              "website": "website", "engagementTypes": "engagement_types", "deliveryModes": "delivery_modes",
              "pricingModels": "pricing_models", "rateUnit": "rate_unit"}
    changed: list[str] = []
    for api_name, col in fields.items():
        value = getattr(patch, api_name)
        if value is None:
            continue
        if isinstance(value, str):
            value = value.strip() or None
            if value is None and col in ("display_name", "country"):
                continue  # required fields cannot be blanked
        elif isinstance(value, list):
            value = sorted(set(value))
        if value != getattr(pro, col):
            setattr(pro, col, value)
            changed.append(api_name)
    if patch.languages is not None:
        langs = list(dict.fromkeys(v.strip() for v in patch.languages if v.strip()))
        if langs != list(pro.languages):
            pro.languages = langs
            changed.append("languages")
    if patch.clearRate:
        if pro.rate_minor is not None:
            pro.rate_minor = pro.rate_currency = pro.rate_unit = None
            changed.append("indicativeRate")
    elif patch.indicativeRate is not None:
        if not (patch.rateUnit or pro.rate_unit):
            raise ValidationFailed("Say what the indicative rate is per (hour, day, month or project)", code="RATE_UNIT_REQUIRED")
        if (patch.indicativeRate.amountMinor, patch.indicativeRate.currency) != (pro.rate_minor, pro.rate_currency):
            pro.rate_minor, pro.rate_currency = patch.indicativeRate.amountMinor, patch.indicativeRate.currency
            changed.append("indicativeRate")
    if changed:
        # Field names only: values (legal name, bio) stay out of the event stream and audit ledger.
        _evt(session, E.PROFILE_UPDATED, pro, changes=sorted(changed))
        await session.flush()
    return await _profile_out(session, pro)


async def set_specializations(session: AsyncSession, actor: Actor, body: SpecializationsIn) -> ProfileOut:
    """1 primary + up to 5 secondary, taxonomy specializations only (Onboarding s.8)."""
    pro = await _mine(session, actor, lock=True)
    secondary = list(dict.fromkeys(body.secondary))
    if body.primary in secondary:
        raise ValidationFailed("Your primary specialization cannot also be a secondary one", code="DUPLICATE_SPECIALIZATION")
    await marketplace_facade.validate_specializations(session, [body.primary, *secondary])
    primary = (await marketplace_facade.get_specializations(session, [body.primary]))[body.primary]
    if [body.primary, *secondary] != specializations_of(pro):
        pro.primary_specialization, pro.secondary_specializations = body.primary, secondary
        pro.primary_category = primary.category_slug
        _evt(session, E.PROFILE_UPDATED, pro, changes=["specializations"], specializations=specializations_of(pro))
        await session.flush()
    return await _profile_out(session, pro)


async def set_jurisdictions(session: AsyncSession, actor: Actor, body: JurisdictionsIn) -> ProfileOut:
    """Where you serve clients and where you hold licences (Onboarding s.13)."""
    pro = await _mine(session, actor, lock=True)
    served = sorted({c.strip().upper() for c in body.served if c.strip()})
    licensed = sorted({c.strip().upper() for c in body.licensed if c.strip()})
    bad = [c for c in served + licensed if not re.fullmatch(r"[A-Z]{2}", c)]
    if bad:
        raise ValidationFailed(f"Use two-letter country codes (e.g. US, GB): {', '.join(bad)}", code="INVALID_JURISDICTION")
    cross_border = [c for c in served if c != pro.country]
    if cross_border and not body.crossBorderAcknowledged and pro.cross_border_acknowledged_at is None:
        raise ValidationFailed(
            "Serving clients outside your home country needs your acknowledgement that local rules may apply "
            f"({', '.join(cross_border)})", code="CROSS_BORDER_ACK_REQUIRED")
    if cross_border and pro.cross_border_acknowledged_at is None:
        pro.cross_border_acknowledged_at = clock.now()
    if (served, licensed) != (sorted(pro.served_jurisdictions), sorted(pro.licensed_jurisdictions)):
        pro.served_jurisdictions, pro.licensed_jurisdictions = served, licensed
        _evt(session, E.JURISDICTIONS_UPDATED, pro, served=served, licensed=licensed)
    await session.flush()
    return await _profile_out(session, pro)


async def _set_firm_link(session: AsyncSession, pro: Professional, firm_id: uuid.UUID | None) -> None:
    pro.firm_id = firm_id
    _evt(session, E.PROFILE_UPDATED, pro, changes=["firm"], firmId=firm_id)
    await session.flush()


async def set_firm(session: AsyncSession, actor: Actor, body: FirmLinkIn) -> ProfileOut:
    """Practise under a firm you are an active member of, or independently (firmId null)."""
    pro = await _mine(session, actor, lock=True)
    if body.firmId and not await firm_facade.member_roles(session, body.firmId, actor.identity_id):
        raise Forbidden("You can only practise under a firm you are a member of", code="NOT_FIRM_MEMBER")
    if body.firmId != pro.firm_id:
        await _set_firm_link(session, pro, body.firmId)
    return await _profile_out(session, pro)


async def firm_member_joined(session: AsyncSession, firm_id: uuid.UUID, identity_id: uuid.UUID) -> None:
    """Consumer of FIRM_MEMBER_JOINED: a profile with no firm starts practising under the firm just joined.
    A profile already linked to another firm keeps its link; the professional can switch in their profile."""
    pro = await session.scalar(select(Professional).where(Professional.identity_id == identity_id).with_for_update())
    if pro is not None and pro.firm_id is None:
        await _set_firm_link(session, pro, firm_id)


async def firm_member_removed(session: AsyncSession, firm_id: uuid.UUID, identity_id: uuid.UUID) -> None:
    """Consumer of FIRM_MEMBER_REMOVED: leaving a firm ends practising under it."""
    pro = await session.scalar(select(Professional).where(Professional.identity_id == identity_id).with_for_update())
    if pro is not None and pro.firm_id == firm_id:
        await _set_firm_link(session, pro, None)


async def engagement_count_changed(session: AsyncSession, professional_id: uuid.UUID, delta: int) -> None:
    """Consumer of CONTRACT_ACTIVATED (+1) and CONTRACT_COMPLETED / TERMINATED (-1). Reaching the professional's
    maximum shows them as At capacity in search (Onboarding s.12)."""
    pro = await session.get(Professional, professional_id, with_for_update=True)
    if pro is None:
        return
    before = effective_availability(pro)
    pro.active_engagements = max(0, pro.active_engagements + delta)
    _evt(session, E.CAPACITY_CHANGED, pro, activeEngagements=pro.active_engagements, maxConcurrent=pro.max_concurrent_engagements,
         availability=effective_availability(pro), availabilityChanged=before != effective_availability(pro))
    await session.flush()


async def set_availability(session: AsyncSession, actor: Actor, body: AvailabilityIn) -> ProfileOut:
    pro = await _mine(session, actor, lock=True)
    new = (body.availability, body.maxConcurrentEngagements, body.temporarilyUnavailable)
    if new != (pro.availability, pro.max_concurrent_engagements, pro.temporarily_unavailable):
        pro.availability, pro.max_concurrent_engagements, pro.temporarily_unavailable = new
        _evt(session, E.AVAILABILITY_UPDATED, pro, availability=effective_availability(pro),
             activeEngagements=pro.active_engagements, maxConcurrent=pro.max_concurrent_engagements)
        await session.flush()
    return await _profile_out(session, pro)


# ---- Profile photo -----------------------------------------------------------------

_MAGIC = {"image/jpeg": (b"\xff\xd8\xff",), "image/png": (b"\x89PNG\r\n\x1a\n",), "image/webp": (b"RIFF",)}
MAX_PHOTO_BYTES = 2 * 1024 * 1024


async def set_photo(session: AsyncSession, actor: Actor, body: PhotoIn) -> ProfileOut:
    """Stores the photo in blob storage. The declared type must match the file's own bytes."""
    pro = await _mine(session, actor, lock=True)
    try:
        data = base64.b64decode(body.dataBase64, validate=True)
    except ValueError as exc:
        raise ValidationFailed("The photo could not be read", code="INVALID_PHOTO") from exc
    if len(data) > MAX_PHOTO_BYTES:
        raise ValidationFailed("Use a photo under 2 MB", code="PHOTO_TOO_LARGE")
    ok = any(data.startswith(m) for m in _MAGIC[body.contentType])
    if body.contentType == "image/webp":
        ok = ok and data[8:12] == b"WEBP"
    if not ok:
        raise ValidationFailed("Upload a JPEG, PNG or WebP image", code="INVALID_PHOTO")
    old = pro.photo_key
    digest = sha256_hex_bytes(data)
    key = f"professionals/{pro.id}/photo-{digest[:16]}"
    get_storage().put(key, data)
    pro.photo_key, pro.photo_content_type, pro.photo_sha256 = key, body.contentType, digest
    if old and old != key:
        get_storage().delete(old)
    _evt(session, E.PROFILE_UPDATED, pro, changes=["photo"])
    await session.flush()
    return await _profile_out(session, pro)


async def remove_photo(session: AsyncSession, actor: Actor) -> ProfileOut:
    pro = await _mine(session, actor, lock=True)
    if pro.photo_key:
        get_storage().delete(pro.photo_key)
        pro.photo_key = pro.photo_content_type = pro.photo_sha256 = None
        _evt(session, E.PROFILE_UPDATED, pro, changes=["photo"])
        await session.flush()
    return await _profile_out(session, pro)


async def photo(session: AsyncSession, actor: Actor | None, professional_id: uuid.UUID) -> tuple[bytes, str]:
    """Same visibility as the public profile: published, or the owner / operators."""
    pro = await session.get(Professional, professional_id)
    own = bool(actor and pro and pro.identity_id == actor.identity_id)
    if pro is None or not pro.photo_key or (pro.status != "PUBLISHED" and not own and not (actor and actor.is_operator)):
        raise NotFound("Photo not found")
    data = get_storage().get(pro.photo_key)
    if data is None:
        raise NotFound("Photo not found")
    return data, pro.photo_content_type or "application/octet-stream"


def sha256_hex_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ---- Credential claims -----------------------------------------------------------

async def add_credential(session: AsyncSession, actor: Actor, body: CredentialIn) -> CredentialOut:
    """A claim stays 'Self-reported' until verification confirms it (Onboarding s.12)."""
    pro = await _mine(session, actor, lock=True)
    today = clock.now().date()
    if body.issuedOn and body.issuedOn > today:
        raise ValidationFailed("The issue date cannot be in the future", code="INVALID_DATES")
    if body.expiresOn and body.expiresOn <= today:
        raise ValidationFailed("This credential has already expired", code="CREDENTIAL_EXPIRED")
    if body.issuedOn and body.expiresOn and body.issuedOn >= body.expiresOn:
        raise ValidationFailed("The expiry date must be after the issue date", code="INVALID_DATES")
    if body.specialization:
        await marketplace_facade.validate_specializations(session, [body.specialization])
    active = await session.scalar(select(func.count()).select_from(CredentialClaim).where(
        CredentialClaim.professional_id == pro.id, CredentialClaim.status != "WITHDRAWN"))
    if active >= MAX_CREDENTIALS:
        raise Conflict(f"You can list up to {MAX_CREDENTIALS} credentials", code="TOO_MANY_CREDENTIALS")
    c = CredentialClaim(
        professional_id=pro.id, credential_type=body.credentialType, name=body.name.strip(),
        issuing_body=body.issuingBody.strip(), registration_number=(body.registrationNumber or "").strip() or None,
        jurisdiction=(body.jurisdiction or "").strip().upper() or None, issued_on=body.issuedOn,
        expires_on=body.expiresOn, specialization=body.specialization, status="PENDING",
    )
    session.add(c)
    await session.flush()
    _evt(session, E.CREDENTIAL_SUBMITTED, pro, aggregate_type="CredentialClaim", aggregate_id=c.id,
         credentialClaimId=c.id, credentialName=c.name, issuingBody=c.issuing_body,
         registrationNumber=c.registration_number, jurisdiction=c.jurisdiction,
         issuedOn=c.issued_on.isoformat() if c.issued_on else None,
         expiresOn=c.expires_on.isoformat() if c.expires_on else None, specialization=c.specialization)
    return _credential_out(c)


async def list_credentials(session: AsyncSession, actor: Actor) -> list[CredentialOut]:
    pro = await _mine(session, actor)
    rows = (await session.scalars(select(CredentialClaim).where(
        CredentialClaim.professional_id == pro.id, CredentialClaim.status != "WITHDRAWN").order_by(CredentialClaim.created_at))).all()
    return [_credential_out(c) for c in rows]


async def withdraw_credential(session: AsyncSession, actor: Actor, claim_id: uuid.UUID) -> None:
    pro = await _mine(session, actor)
    c = await session.get(CredentialClaim, claim_id, with_for_update=True)
    if c is None or c.professional_id != pro.id or c.status == "WITHDRAWN":
        raise NotFound("Credential not found")
    previous, c.status = c.status, "WITHDRAWN"
    record_audit(session, "CREDENTIAL_WITHDRAWN", object_type="CredentialClaim", object_id=c.id, tenant_id=pro.id,
                 details={"professionalId": str(pro.id), "previousStatus": previous})


async def set_claim_status(session: AsyncSession, claim_id: uuid.UUID, status: str) -> None:
    """Consumer of verification outcomes. Idempotent; withdrawn claims stay withdrawn."""
    c = await session.get(CredentialClaim, claim_id, with_for_update=True)
    if c is not None and c.status != "WITHDRAWN":
        c.status = status


# ---- Offerings -------------------------------------------------------------------

def _offering_evt(session: AsyncSession, event_type: str, pro: Professional, o: Offering, **extra) -> None:
    _evt(session, event_type, pro, aggregate_type="Offering", aggregate_id=o.id, offeringId=o.id, status=o.status, **extra)


def _check_offering_specialization(pro: Professional, slug: str) -> None:
    if slug not in specializations_of(pro):
        raise ValidationFailed("An offering must use one of the specializations on your profile",
                               code="SPECIALIZATION_NOT_ON_PROFILE")


def _apply_price(o: Offering, price: MoneyDTO | None) -> None:
    o.starting_price_minor = price.amountMinor if price else None
    o.currency = price.currency if price else None


async def create_offering(session: AsyncSession, actor: Actor, body: OfferingIn) -> OfferingOut:
    pro = await _mine(session, actor, lock=True)
    _check_offering_specialization(pro, body.specialization)
    check_copy("offering title", body.title)
    check_copy("offering summary", body.summary)
    for d in body.deliverables:
        check_copy("deliverable", d)
    count = await session.scalar(select(func.count()).select_from(Offering).where(Offering.professional_id == pro.id))
    if count >= MAX_OFFERINGS:
        raise Conflict(f"You can have up to {MAX_OFFERINGS} offerings. Pause or edit an existing one.", code="TOO_MANY_OFFERINGS")
    o = Offering(professional_id=pro.id, title=body.title.strip(), specialization=body.specialization,
                 summary=(body.summary or "").strip() or None, deliverables=[d.strip() for d in body.deliverables if d.strip()],
                 engagement_types=sorted(set(body.engagementTypes)), pricing_model=body.pricingModel,
                 typical_duration=(body.typicalDuration or "").strip() or None, status="DRAFT")
    _apply_price(o, body.startingPrice)
    session.add(o)
    await session.flush()
    _offering_evt(session, E.SERVICE_OFFERING_CREATED, pro, o)
    return _offering_out(o, await _spec_names(session, [o.specialization]))


async def list_offerings(session: AsyncSession, actor: Actor) -> list[OfferingOut]:
    pro = await _mine(session, actor)
    rows = (await session.scalars(select(Offering).where(Offering.professional_id == pro.id).order_by(Offering.created_at))).all()
    names = await _spec_names(session, sorted({o.specialization for o in rows}))
    return [_offering_out(o, names) for o in rows]


async def get_offering(session: AsyncSession, actor: Actor, offering_id: uuid.UUID) -> OfferingOut:
    o = await _offering(session, await _mine(session, actor), offering_id)
    return _offering_out(o, await _spec_names(session, [o.specialization]))


async def update_offering(session: AsyncSession, actor: Actor, offering_id: uuid.UUID, patch: OfferingPatch,
                          if_match: int | None) -> OfferingOut:
    pro = await _mine(session, actor)
    o = await _offering(session, pro, offering_id, lock=True)
    _if_match(if_match, o.version, "offering")
    if patch.specialization is not None:
        _check_offering_specialization(pro, patch.specialization)
    check_copy("offering title", patch.title)
    check_copy("offering summary", patch.summary)
    for d in patch.deliverables or []:
        check_copy("deliverable", d)
    fields = {"title": "title", "specialization": "specialization", "summary": "summary",
              "typicalDuration": "typical_duration", "pricingModel": "pricing_model"}
    changed = []
    for api_name, col in fields.items():
        value = getattr(patch, api_name)
        if value is not None:
            value = (value.strip() or None) if isinstance(value, str) else value
            if value is None and col in ("title", "specialization", "pricing_model"):
                continue
            if value != getattr(o, col):
                setattr(o, col, value)
                changed.append(api_name)
    if patch.deliverables is not None:
        o.deliverables = [d.strip() for d in patch.deliverables if d.strip()]
        changed.append("deliverables")
    if patch.engagementTypes is not None:
        o.engagement_types = sorted(set(patch.engagementTypes))
        changed.append("engagementTypes")
    if patch.clearStartingPrice or patch.startingPrice is not None:
        _apply_price(o, None if patch.clearStartingPrice else patch.startingPrice)
        changed.append("startingPrice")
    if o.status == "ACTIVE":
        _check_offering_complete(o)  # a live offering must stay contract-ready
    if changed:
        _offering_evt(session, E.SERVICE_OFFERING_UPDATED, pro, o, changes=sorted(set(changed)))
        await session.flush()
    return _offering_out(o, await _spec_names(session, [o.specialization]))


def _check_offering_complete(o: Offering) -> None:
    if not o.deliverables:
        raise ValidationFailed("List at least one deliverable before activating this offering", code="OFFERING_INCOMPLETE")
    if o.pricing_model != "CUSTOM" and o.starting_price_minor is None:
        raise ValidationFailed("Add a starting price, or choose 'Quote on request' pricing", code="OFFERING_INCOMPLETE")


async def set_offering_status(session: AsyncSession, actor: Actor, offering_id: uuid.UUID, target: str) -> OfferingOut:
    pro = await _mine(session, actor)
    o = await _offering(session, pro, offering_id, lock=True)
    OFFERING_STATES.assert_can(o.status, target)
    if target == "ACTIVE":
        _check_offering_specialization(pro, o.specialization)
        _check_offering_complete(o)
    o.status = target
    _offering_evt(session, E.SERVICE_OFFERING_STATUS_CHANGED, pro, o)
    await session.flush()
    return _offering_out(o, await _spec_names(session, [o.specialization]))


# ---- Readiness & publishing ------------------------------------------------------

async def _readiness(session: AsyncSession, pro: Professional) -> ReadinessOut:
    who = await identity_facade.get_identity(session, pro.identity_id)
    claims = (await session.scalars(select(CredentialClaim.status).where(
        CredentialClaim.professional_id == pro.id, CredentialClaim.status.in_(_PUBLIC_CLAIM_STATES)))).all()
    active_offerings = await session.scalar(select(func.count()).select_from(Offering).where(
        Offering.professional_id == pro.id, Offering.status == "ACTIVE"))
    specs = await marketplace_facade.get_specializations(session, specializations_of(pro))
    needs_credential = any(i.requires_credential for i in specs.values())
    copy_ok = not any(_SUPERLATIVES.search(t or "") for t in (pro.display_name, pro.headline, pro.bio))
    items = [
        ReadinessItem(key="email", label="Confirm your email address", done=bool(who and who.email_confirmed), required=True),
        ReadinessItem(key="basics", label="Add your legal name (private), primary role title and years of experience",
                      done=bool(pro.legal_name and pro.headline and pro.years_experience_band), required=True),
        ReadinessItem(key="photo", label="Add a professional photo", done=pro.photo_key is not None, required=True),
        ReadinessItem(key="copy", label="Name, headline and bio avoid superlatives and guarantees", done=copy_ok, required=True),
        ReadinessItem(key="bio", label="Add a short bio (150-250 words reads best)", done=bool(pro.bio), required=False),
        ReadinessItem(key="specializations", label="Choose your primary specialization",
                      done=pro.primary_specialization is not None, required=True),
        ReadinessItem(key="engagement", label="Choose engagement types and delivery modes",
                      done=bool(pro.engagement_types and pro.delivery_modes), required=True),
        ReadinessItem(key="pricing", label="Choose how you price your work (quote on request is fine)",
                      done=bool(pro.pricing_models), required=True),
        ReadinessItem(key="jurisdictions", label="Add the countries where you serve clients",
                      done=bool(pro.served_jurisdictions), required=True),
        ReadinessItem(key="availability", label="Set your availability", done=pro.availability != "NOT_SPECIFIED", required=False),
        ReadinessItem(key="credentials",
                      label="Add the credentials your specializations require" if needs_credential else "Add your credentials",
                      done=bool(claims), required=False),
        ReadinessItem(key="offering", label="Activate at least one service offering", done=bool(active_offerings), required=False),
    ]
    return ReadinessOut(canPublish=all(i.done for i in items if i.required), items=items)


async def readiness(session: AsyncSession, actor: Actor) -> ReadinessOut:
    return await _readiness(session, await _mine(session, actor))


async def publish(session: AsyncSession, actor: Actor) -> ProfileOut:
    """Go live in discovery. Tier C (unverified) profiles may publish; credentials show as self-reported."""
    pro = await _mine(session, actor, lock=True)
    PROFILE_STATES.assert_can(pro.status, "PUBLISHED")
    ready = await _readiness(session, pro)
    missing = [i.label for i in ready.items if i.required and not i.done]
    if missing:
        raise ValidationFailed("Your profile is not ready to publish yet", code="PROFILE_NOT_READY", extra={"missing": missing})
    now = clock.now()
    pro.status, pro.accuracy_attested_at, pro.published_at = "PUBLISHED", now, now
    _evt(session, E.PROFILE_PUBLISHED, pro)
    await session.flush()
    return await _profile_out(session, pro)


async def unpublish(session: AsyncSession, actor: Actor) -> ProfileOut:
    pro = await _mine(session, actor, lock=True)
    PROFILE_STATES.assert_can(pro.status, "UNPUBLISHED")
    pro.status = "UNPUBLISHED"
    _evt(session, E.PROFILE_UNPUBLISHED, pro)
    await session.flush()
    return await _profile_out(session, pro)


# ---- Public profile --------------------------------------------------------------

async def public_profile(session: AsyncSession, actor: Actor | None, professional_id: uuid.UUID) -> PublicProfileOut:
    """What buyers see. Unpublished or suspended profiles do not exist for the public;
    the owner (preview) and operators can still open them."""
    pro = await session.get(Professional, professional_id)
    own = bool(actor and pro and pro.identity_id == actor.identity_id)
    if pro is None or (pro.status != "PUBLISHED" and not own and not (actor and actor.is_operator)):
        raise NotFound("Professional not found")
    claims = (await session.scalars(select(CredentialClaim).where(
        CredentialClaim.professional_id == pro.id, CredentialClaim.status.in_(_PUBLIC_CLAIM_STATES))
        .order_by(CredentialClaim.created_at))).all()
    offerings = (await session.scalars(select(Offering).where(
        Offering.professional_id == pro.id, Offering.status == "ACTIVE").order_by(Offering.created_at))).all()
    names = await _spec_names(session, sorted({o.specialization for o in offerings}))
    category = await marketplace_facade.get_category(session, pro.primary_category) if pro.primary_category else None
    trust = await trust_facade.get_trust(session, pro.id)
    checks = await verification_facade.get_checks(session, "PROFESSIONAL", pro.id)
    verified_jurisdictions = sorted({c.jurisdiction[:2].upper() for c in checks if c.status == "VERIFIED" and c.jurisdiction
                                     and c.verification_type in ("JURISDICTION", "CREDENTIAL")})
    firm = await firm_facade.get_firm(session, pro.firm_id) if pro.firm_id else None
    delivery = await contract_facade.delivery_stats(session, pro.id)
    response = await proposal_facade.response_stats(session, pro.id)
    history = HistoryOut(
        completedEngagements=delivery["completed"],
        onTimeRate=round(100 * delivery["onTime"] / delivery["milestonesWithDueDate"]) if delivery["milestonesWithDueDate"] else None,
        medianResponseHours=response["medianHours"],
        newToPlatform=delivery["completed"] == 0 and (pro.published_at is None or (clock.now() - pro.published_at).days < 30))
    return PublicProfileOut(
        history=history,
        firm=PublicFirmOut(id=firm.id, name=firm.trading_name or firm.legal_name, verified=firm.status == "VERIFIED")
        if firm and firm.status != "SUSPENDED" else None,
        id=pro.id, photoUrl=photo_url(pro), displayName=pro.display_name, headline=pro.headline,
        yearsExperienceBand=pro.years_experience_band,
        bio=pro.bio, languages=list(pro.languages), country=pro.country, city=pro.city,
        primaryCategory=pro.primary_category, primaryCategoryName=category.name if category else None,
        specializations=await _spec_out(session, pro), engagementTypes=list(pro.engagement_types),
        deliveryModes=list(pro.delivery_modes), pricingModels=list(pro.pricing_models), indicativeRate=_rate(pro),
        rateUnit=pro.rate_unit, availability=effective_availability(pro),
        servedJurisdictions=list(pro.served_jurisdictions), licensedJurisdictions=list(pro.licensed_jurisdictions),
        verifiedJurisdictions=verified_jurisdictions,
        credentials=[PublicCredentialOut(name=c.name, issuingBody=c.issuing_body, jurisdiction=c.jurisdiction,
                                         status=c.status if c.status in ("VERIFIED", "EXPIRED") else "SELF_REPORTED",
                                         displayLabel={"VERIFIED": "Validated", "EXPIRED": "Expired"}.get(c.status, "Self-reported"))
                     for c in claims],
        offerings=[_offering_out(o, names) for o in offerings],
        trust=PublicTrustOut(tier=trust.tier, dimensions=public_dimensions(trust.dimensions),
                             explanation=public_explanation(trust.explanation), updatedAt=trust.updated_at),
        publishedAt=pro.published_at, isOwnProfile=own,
    )
