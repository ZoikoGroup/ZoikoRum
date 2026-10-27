import uuid
from fastapi import APIRouter
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from zoikorum.domains.review.models import Review, ReviewReply
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


class ReplyIn(BaseModel):
    body: str = Field(min_length=2, max_length=1500)

    @field_validator("body", mode="before")
    @classmethod
    def normalize_body(cls, value):
        return value.strip() if isinstance(value, str) else value


def reply_out(row: ReviewReply | None):
    if row is None:
        return None
    return {"id": str(row.id), "body": row.body, "createdAt": row.created_at, "updatedAt": row.updated_at, "edited": row.edit_count > 0}


def review_out(row: Review, reply: ReviewReply | None = None):
    return {"id": str(row.id), "rating": row.rating, "comment": row.comment, "reviewerName": row.reviewer_name,
            "organizationName": row.organization_name, "engagementReference": row.engagement_reference, "createdAt": row.created_at,
            "reply": reply_out(reply)}


@router.get("/v1/professionals/{professional_id}/reviews")
async def list_reviews(professional_id: uuid.UUID, session: DbSession, limit: int = 20, offset: int = 0):
    pro = await professional.get_professional(session, professional_id)
    if pro is None or pro.status != "PUBLISHED":
        raise NotFound("Professional not found")
    rows = (await session.scalars(select(Review).where(Review.professional_id == professional_id).order_by(Review.created_at.desc(), Review.id).limit(max(1, min(limit, 100))).offset(max(0, offset)))).all()
    replies = {r.review_id: r for r in (await session.scalars(select(ReviewReply).where(
        ReviewReply.review_id.in_([r.id for r in rows])))).all()} if rows else {}
    return {**await facade.rating_stats(session, professional_id), "items": [review_out(r, replies.get(r.id)) for r in rows]}


@router.put("/v1/reviews/{review_id}/reply")
async def reply_to_review(review_id: uuid.UUID, body: ReplyIn, actor: CurrentActor, session: DbSession):
    """The reviewed professional answers a review in public: one reply per review, editable. The first reply and every
    edit are audited with a fingerprint of the text, so earlier wording can be proven if it is ever questioned."""
    import hashlib

    review = await session.get(Review, review_id)
    if review is None:
        raise NotFound("Review not found")
    pro = await professional.get_professional(session, review.professional_id)
    if pro is None or pro.identity_id != actor.identity_id:
        raise Forbidden("Only the professional who was reviewed can reply")
    text = body.body.strip()
    fingerprint = hashlib.sha256(text.encode()).hexdigest()
    reply = await session.scalar(select(ReviewReply).where(ReviewReply.review_id == review.id).with_for_update())
    if reply is None:
        reply = ReviewReply(review_id=review.id, professional_id=review.professional_id, author_identity_id=actor.identity_id, body=text)
        session.add(reply)
        await session.flush()
        record_audit(session, "review.reply.created", object_type="Review", object_id=review.id,
                     details={"replyId": str(reply.id), "professionalId": str(review.professional_id)}, evidence_hash=fingerprint)
    elif reply.body != text:
        reply.body, reply.edit_count = text, reply.edit_count + 1
        await session.flush()
        record_audit(session, "review.reply.edited", object_type="Review", object_id=review.id,
                     details={"replyId": str(reply.id), "professionalId": str(review.professional_id), "edit": reply.edit_count},
                     evidence_hash=fingerprint)
    await session.refresh(reply)
    return review_out(review, reply)


@router.get("/v1/contracts/{contract_id}/review")
async def contract_review(contract_id: uuid.UUID, actor: CurrentActor, session: DbSession):
    c = await contract.get_contract(session, contract_id)
    if c is None:
        raise NotFound("Contract not found")
    pro = await professional.get_professional(session, c.professional_id)
    if not await buyer.get_member_roles(session, c.organization_id, actor.identity_id) and (pro is None or pro.identity_id != actor.identity_id):
        raise NotFound("Contract not found")
    row = await session.scalar(select(Review).where(Review.contract_id == c.id))
    if row is None:
        return None
    return review_out(row, await session.scalar(select(ReviewReply).where(ReviewReply.review_id == row.id)))


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
