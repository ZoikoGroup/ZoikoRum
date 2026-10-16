"""Open briefs: a buyer describes a need once; matching professionals say they are interested; the buyer picks whom to ask.

A brief is not a request. Professionals see it only when it is in one of their specializations and in a country they
serve, and they see no organisation name - only its country and industry. Saying "interested" commits no one: the buyer
then sends the normal request (with every request check) to the professionals they choose, from the request form.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta

from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from zoikorum.domains.buyer import facade as buyer_facade
from zoikorum.domains.marketplace import facade as marketplace_facade
from zoikorum.domains.professional import facade as professional_facade
from zoikorum.domains.proposal.models import BriefInterest, OpenBrief
from zoikorum.domains.proposal.schemas import Budget, Duration, ProfessionalBrief
from zoikorum.domains.trust import facade as trust_facade
from zoikorum.shared import clock
from zoikorum.shared.auth import Actor, OrgRole
from zoikorum.shared.errors import Conflict, Forbidden, NotFound, PolicyBlocked, ValidationFailed
from zoikorum.shared.event_catalog import E
from zoikorum.shared.events import record_event

OPEN_DAYS = 14  # a brief takes interest for two weeks, then closes by itself
MAX_INTERESTS = 25


class BriefIn(BaseModel):
    organizationId: uuid.UUID
    service: str = Field(min_length=2, max_length=200)
    specialization: str = Field(min_length=2, max_length=120)
    objective: str = Field(min_length=5, max_length=300)
    details: str = Field(default="", max_length=1200)
    desiredStartDate: date | None = None
    estimatedDuration: Duration | None = None
    budget: Budget | None = None


class InterestIn(BaseModel):
    note: str = Field(default="", max_length=500)


class InterestOut(BaseModel):
    professional: ProfessionalBrief
    note: str
    createdAt: datetime


class BriefOut(BaseModel):
    id: uuid.UUID
    organizationId: uuid.UUID | None  # hidden from professionals
    country: str
    industry: str | None
    service: str
    specialization: str
    specializationName: str
    objective: str
    details: str
    desiredStartDate: date | None
    estimatedDuration: str | None
    budget: Budget | None
    status: str
    closesAt: datetime
    createdAt: datetime
    interests: list[InterestOut] | None  # the buyer's view only
    interestCount: int
    myInterest: bool  # the professional's view


def _open(b: OpenBrief) -> bool:
    return b.status == "OPEN" and b.closes_at > clock.now()


async def _names(session: AsyncSession) -> dict[str, str]:
    return {s["slug"]: s["name"] for s in await marketplace_facade.all_specializations(session)}


async def _out(session: AsyncSession, b: OpenBrief, *, buyer: bool, mine: uuid.UUID | None = None) -> BriefOut:
    rows = (await session.scalars(select(BriefInterest).where(BriefInterest.brief_id == b.id).order_by(BriefInterest.created_at))).all()
    interests = None
    if buyer:
        ids = [r.professional_id for r in rows]
        pros = await professional_facade.get_professionals(session, ids)
        trusts = await trust_facade.get_trust_many(session, ids)
        interests = [InterestOut(professional=ProfessionalBrief(
            id=r.professional_id, displayName=pros[r.professional_id].display_name if r.professional_id in pros else "Professional",
            headline=pros[r.professional_id].headline if r.professional_id in pros else None,
            photoUrl=pros[r.professional_id].photo_url if r.professional_id in pros else None,
            tier=trusts[r.professional_id].tier, country=pros[r.professional_id].country if r.professional_id in pros else None),
            note=r.note, createdAt=r.created_at) for r in rows]
    org = await buyer_facade.get_organization(session, b.organization_id)
    budget = Budget(maxMinor=b.budget_max_minor, currency=b.budget_currency) if b.budget_max_minor and b.budget_currency else None
    return BriefOut(id=b.id, organizationId=b.organization_id if buyer else None, country=b.country,
                    industry=getattr(org, "industry", None), service=b.service, specialization=b.specialization,
                    specializationName=(await _names(session)).get(b.specialization, b.specialization.replace("-", " ")),
                    objective=b.objective, details=b.details, desiredStartDate=b.desired_start_date,
                    estimatedDuration=b.estimated_duration, budget=budget, status="OPEN" if _open(b) else "CLOSED",
                    closesAt=b.closes_at, createdAt=b.created_at, interests=interests, interestCount=len(rows),
                    myInterest=mine is not None and any(r.professional_id == mine for r in rows))


async def _require_requester(session: AsyncSession, actor: Actor, org_id: uuid.UUID) -> None:
    roles = await buyer_facade.get_member_roles(session, org_id, actor.identity_id)
    if not roles:
        raise NotFound("Organisation not found")
    if not roles.intersection({OrgRole.REQUESTER, OrgRole.ORG_ADMIN}):
        raise Forbidden("Posting a brief needs the Requester role in your organisation", code="ROLE_REQUIRED")


async def post(session: AsyncSession, actor: Actor, body: BriefIn) -> BriefOut:
    await _require_requester(session, actor, body.organizationId)
    if body.specialization not in await _names(session):
        raise ValidationFailed("Choose a specialization from the list", code="UNKNOWN_SPECIALIZATION")
    if body.desiredStartDate and body.desiredStartDate < clock.now().date():
        raise ValidationFailed("The desired start date cannot be in the past", code="START_DATE_IN_PAST")
    org = await buyer_facade.get_organization(session, body.organizationId)
    b = OpenBrief(organization_id=body.organizationId, buyer_identity_id=actor.identity_id, country=org.country.upper(),
                  service=body.service.strip(), specialization=body.specialization, objective=body.objective.strip(),
                  details=body.details.strip(), desired_start_date=body.desiredStartDate, estimated_duration=body.estimatedDuration,
                  budget_max_minor=body.budget.maxMinor if body.budget else None, budget_currency=body.budget.currency if body.budget else None,
                  status="OPEN", closes_at=clock.now() + timedelta(days=OPEN_DAYS))
    session.add(b)
    await session.flush()
    record_event(session, E.OPEN_BRIEF_POSTED, aggregate_type="OpenBrief", aggregate_id=b.id, tenant_id=b.organization_id,
                 payload={"briefId": b.id, "specialization": b.specialization, "country": b.country})
    return await _out(session, b, buyer=True)


async def mine(session: AsyncSession, actor: Actor, organization_id: uuid.UUID) -> list[BriefOut]:
    if not await buyer_facade.get_member_roles(session, organization_id, actor.identity_id):
        raise NotFound("Organisation not found")
    rows = (await session.scalars(select(OpenBrief).where(OpenBrief.organization_id == organization_id)
                                  .order_by(OpenBrief.created_at.desc()).limit(50))).all()
    return [await _out(session, b, buyer=True) for b in rows]


async def close(session: AsyncSession, actor: Actor, brief_id: uuid.UUID) -> BriefOut:
    b = await session.get(OpenBrief, brief_id, with_for_update=True)
    if b is None:
        raise NotFound("Brief not found")
    await _require_requester(session, actor, b.organization_id)
    b.status = "CLOSED"
    return await _out(session, b, buyer=True)


async def _my_profile(session: AsyncSession, actor: Actor) -> professional_facade.ProfessionalSummary:
    pro = await professional_facade.get_professional_by_identity(session, actor.identity_id)
    if pro is None or pro.status != "PUBLISHED":
        raise Forbidden("Publish your professional profile to see open briefs", code="PROFILE_NOT_PUBLISHED")
    return pro


def _serves(pro: professional_facade.ProfessionalSummary, country: str) -> bool:
    return not pro.jurisdictions_served or country.upper() in {c.upper() for c in pro.jurisdictions_served}


async def matching(session: AsyncSession, actor: Actor) -> list[BriefOut]:
    """Open briefs in the professional's specializations and served countries, newest first. No buyer names."""
    pro = await _my_profile(session, actor)
    if not pro.specializations:
        return []
    rows = (await session.scalars(select(OpenBrief).where(
        OpenBrief.status == "OPEN", OpenBrief.closes_at > clock.now(), OpenBrief.specialization.in_(pro.specializations))
        .order_by(OpenBrief.created_at.desc()).limit(50))).all()
    mine_orgs = set(await buyer_facade.list_identity_organizations(session, actor.identity_id))
    return [await _out(session, b, buyer=False, mine=pro.id) for b in rows
            if _serves(pro, b.country) and b.organization_id not in mine_orgs]


async def interest(session: AsyncSession, actor: Actor, brief_id: uuid.UUID, body: InterestIn) -> BriefOut:
    pro = await _my_profile(session, actor)
    b = await session.get(OpenBrief, brief_id, with_for_update=True)
    if b is None or b.specialization not in pro.specializations:
        raise NotFound("Brief not found")
    if not _open(b):
        raise Conflict("This brief is closed", code="BRIEF_CLOSED")
    if not _serves(pro, b.country):
        raise PolicyBlocked("You do not list this buyer's country among the places you serve", code="JURISDICTION_CONFLICT")
    if await session.scalar(select(BriefInterest.id).where(BriefInterest.brief_id == b.id, BriefInterest.professional_id == pro.id)):
        return await _out(session, b, buyer=False, mine=pro.id)  # already interested: idempotent
    if (await session.scalar(select(func.count()).select_from(BriefInterest).where(BriefInterest.brief_id == b.id)) or 0) >= MAX_INTERESTS:
        raise Conflict("This brief already has as many interested professionals as the buyer can review", code="BRIEF_FULL")
    session.add(BriefInterest(brief_id=b.id, professional_id=pro.id, note=body.note.strip()))
    await session.flush()
    record_event(session, E.OPEN_BRIEF_INTEREST, aggregate_type="OpenBrief", aggregate_id=b.id, tenant_id=b.organization_id,
                 payload={"briefId": b.id, "organizationId": b.organization_id, "audience": "BUYER",
                          "professionalId": pro.id, "service": b.service})
    return await _out(session, b, buyer=False, mine=pro.id)
