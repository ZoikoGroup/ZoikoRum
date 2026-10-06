"""Notification domain tables. First slice: per-person channel preferences (delivery comes later)."""

from __future__ import annotations

import uuid

from sqlalchemy import Boolean
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from zoikorum.shared.db import Base, Timestamps, UUIDPk

SCHEMA = "notification"


class Preference(Base, UUIDPk, Timestamps):
    """Channel opt-ins. Security and enforcement notices are always sent by email, whatever is chosen here."""

    __tablename__ = "preferences"
    __table_args__ = {"schema": SCHEMA}

    identity_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), unique=True, nullable=False)
    email: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    in_app: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    sms: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    marketing: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
