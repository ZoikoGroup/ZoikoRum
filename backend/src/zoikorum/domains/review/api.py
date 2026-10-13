import uuid
from fastapi import APIRouter
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from zoikorum.domains.review.models import Review
from zoikorum.domains.review import facade
from zoikorum.domains.buyer import facade as buyer
from zoikorum.domains.contract import facade as contract
from zoikorum.domains.identity import facade as identity
from zoikorum.domains.professional import facade as professional
from zoikorum.shared.auth import CurrentActor
from zoikorum.shared.db import DbSession
from zoikorum.shared.errors import Conflict, Forbidden, NotFound
from zoikorum.shared.events import record_audit
from zoikorum.shared.events import record_event
from zoikorum.shared.event_catalog import E
from zoikorum.shared.idempotency import IdempotencyKey

router = APIRouter(tags=["reviews"])


class ReviewIn(BaseModel):
    rating: int = Field(ge=1, le=5)
    comment: str = Field(min_length=10, max_length=2000)

    @field_validator("comment", mode="before")
    @classmethod
    def normalize_comment(cls, value):
        return value.strip() if isinstance(value, str) else value


def review_out(row: Review):
    return {"id": str(row.id), "rating": row.rating, "comment": row.comment, "reviewerName": row.reviewer_name,
            "organizationName": row.organization_name, "engagementReference": row.engagement_reference, "createdAt": row.created_at}


@router.get("/v1/professionals/{professional_id}/reviews")
async def list_reviews(professional_id: uuid.UUID, session: DbSession, limit: int = 20, offset: int = 0):
    pro = await professional.get_professional(session, professional_id)
    if pro is None or pro.status != "PUBLISHED":
        raise NotFound("Professional not found")
    rows = (await session.scalars(select(Review).where(Review.professional_id == professional_id).order_by(Review.created_at.desc(), Review.id).limit(max(1, min(limit, 100))).offset(max(0, offset)))).all()
    return {**await facade.rating_stats(session, professional_id), "items": [review_out(r) for r in rows]}


@router.get("/v1/contracts/{contract_id}/review")
async def contract_review(contract_id: uuid.UUID, actor: CurrentActor, session: DbSession):
    c = await contract.get_contract(session, contract_id)
    if c is None:
        raise NotFound("Contract not found")
    pro = await professional.get_professional(session, c.professional_id)
    if not await buyer.get_member_roles(session, c.organization_id, actor.identity_id) and (pro is None or pro.identity_id != actor.identity_id):
        raise NotFound("Contract not found")
    row = await session.scalar(select(Review).where(Review.contract_id == c.id))
    return review_out(row) if row else None


@router.post("/v1/contracts/{contract_id}/review", status_code=201)
async def create_review(contract_id: uuid.UUID, body: ReviewIn, actor: CurrentActor, session: DbSession, idem: IdempotencyKey):
    async def action():
        c = await contract.get_contract(session, contract_id)
        if c is None:
            raise NotFound("Contract not found")
        if not await buyer.get_member_roles(session, c.organization_id, actor.identity_id):
            raise Forbidden("Only a current buyer organisation member can review this engagement")
        pro = await professional.get_professional(session, c.professional_id)
        if pro is None or pro.identity_id == actor.identity_id:
            raise Forbidden("Self reviews are not allowed")
        if c.status != "COMPLETED":
            raise Conflict("Reviews are available after the engagement is completed", code="ENGAGEMENT_NOT_COMPLETED")
        # Serialize creation without modifying the owning contract domain.
        from sqlalchemy import text
        await session.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"), {"key": f"review:{c.id}"})
        if await session.scalar(select(Review.id).where(Review.contract_id == c.id)):
            raise Conflict("This engagement already has a review", code="REVIEW_EXISTS")
        who = await identity.get_identity(session, actor.identity_id)
        org = await buyer.get_organization(session, c.organization_id)
        row = Review(contract_id=c.id, organization_id=c.organization_id, professional_id=c.professional_id,
                     reviewer_identity_id=actor.identity_id, reviewer_name=who.display_name, organization_name=org.name,
                     engagement_reference=c.reference, rating=body.rating, comment=body.comment.strip())
        session.add(row)
        await session.flush()
        record_audit(session, "review.created", object_type="Review", object_id=row.id, tenant_id=c.organization_id,
                     details={"professionalId": str(c.professional_id), "contractId": str(c.id), "rating": body.rating})
        record_event(session, E.REVIEW_CREATED, aggregate_type="Review", aggregate_id=row.id, tenant_id=c.organization_id,
                     payload={"professionalId": c.professional_id, "contractId": c.id, "organizationId": c.organization_id, "rating": body.rating})
        return review_out(row)
    return await idem.run(session, actor, action, status_code=201)
