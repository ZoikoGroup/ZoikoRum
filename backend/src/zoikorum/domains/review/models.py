import uuid

from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from zoikorum.shared.db import Base, UUIDPk, CreatedAt, Timestamps


class Review(Base, UUIDPk, CreatedAt):
    __tablename__ = "reviews"
    __table_args__ = {"schema": "review"}

    contract_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False, unique=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    professional_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False, index=True)
    reviewer_identity_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    reviewer_name: Mapped[str] = mapped_column(String(200), nullable=False)
    organization_name: Mapped[str] = mapped_column(String(200), nullable=False)
    rating: Mapped[int] = mapped_column(Integer, nullable=False)
    comment: Mapped[str] = mapped_column(String(2000), nullable=False)
    engagement_reference: Mapped[str] = mapped_column(String(40), nullable=False)


class ReviewReply(Base, UUIDPk, Timestamps):
    """The reviewed professional's public answer to a review: one per review, editable. Every version is kept in the
    audit ledger (review.reply.created / review.reply.edited), so an edit never hides what was said before."""

    __tablename__ = "review_replies"
    __table_args__ = {"schema": "review"}

    review_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("review.reviews.id"), nullable=False, unique=True)
    professional_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False, index=True)
    author_identity_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    body: Mapped[str] = mapped_column(String(1500), nullable=False)
    edit_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
