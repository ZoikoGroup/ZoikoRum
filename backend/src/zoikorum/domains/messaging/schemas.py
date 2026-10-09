from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator

ContextType = Literal["PROPOSAL_REQUEST", "CONTRACT", "DISPUTE"]


class ThreadIn(BaseModel):
    contextType: ContextType
    contextId: uuid.UUID


class UploadIn(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    dataBase64: str = Field(min_length=1, max_length=14_000_000)


class AttachmentOut(BaseModel):
    id: uuid.UUID
    name: str
    contentType: str
    size: int
    sha256: str
    fileVersion: int
    uploadedAt: datetime


class MessageIn(BaseModel):
    body: str = Field(default="", max_length=5000)
    attachments: list[uuid.UUID] = Field(default_factory=list, max_length=5)

    @model_validator(mode="after")
    def content(self):
        self.body = self.body.strip()
        if not self.body and not self.attachments:
            raise ValueError("Write a message or attach a file")
        if len(set(self.attachments)) != len(self.attachments):
            raise ValueError("An attachment can only be included once")
        return self


class MessageOut(BaseModel):
    id: uuid.UUID
    sequence: int
    senderIdentityId: uuid.UUID | None
    senderName: str
    body: str
    attachments: list[AttachmentOut]
    contentHash: str
    sentAt: datetime


class ThreadOut(BaseModel):
    id: uuid.UUID
    contextType: ContextType
    contextId: uuid.UUID
    title: str
    locked: bool
    lockReason: str | None
    canSend: bool
    unreadCount: int
    lastSequence: int
    updatedAt: datetime
    createdAt: datetime
    counterpartName: str
    viewerRole: Literal["BUYER", "PROFESSIONAL"]
    professionalId: uuid.UUID
    photoUrl: str | None
    headline: str | None
    country: str | None
    lastMessage: str
    lastMessageFromSystem: bool


class ReadIn(BaseModel):
    throughSequence: int = Field(ge=0)


class UnreadSummaryOut(BaseModel):
    unreadThreads: int = Field(ge=0)
    unreadMessages: int = Field(ge=0)
