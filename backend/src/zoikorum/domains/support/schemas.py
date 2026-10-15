from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

Topic = Literal["ACCOUNT", "VERIFICATION", "REQUESTS_PROPOSALS", "ENGAGEMENT", "PAYMENTS", "DISPUTE", "TECHNICAL", "OTHER"]


class SupportContextIn(BaseModel):
    page: str | None = Field(default=None, max_length=300)
    contractId: uuid.UUID | None = None
    errorReference: str | None = Field(default=None, max_length=100)  # the correlation id shown with an error


class SupportRequestIn(BaseModel):
    topic: Topic
    subject: str = Field(min_length=5, max_length=200)
    message: str = Field(min_length=10, max_length=5000)
    context: SupportContextIn = Field(default_factory=SupportContextIn)


class SupportReplyIn(BaseModel):
    message: str = Field(min_length=2, max_length=5000)
    resolve: bool = False  # staff: answer and mark resolved in one step


class SupportMessageOut(BaseModel):
    id: uuid.UUID
    fromStaff: bool
    authorName: str
    body: str
    createdAt: datetime


class SupportRequestOut(BaseModel):
    id: uuid.UUID
    reference: str
    topic: str
    subject: str
    status: str
    context: dict
    firstResponseDueAt: datetime
    firstRespondedAt: datetime | None
    overdue: bool
    resolvedAt: datetime | None
    requesterName: str | None = None  # staff view
    assignedToName: str | None = None
    messages: list[SupportMessageOut] = []
    createdAt: datetime
    updatedAt: datetime
