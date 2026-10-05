from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel


class TrustOut(BaseModel):
    professionalId: uuid.UUID
    tier: str
    tierLabel: str
    score: int | None  # owner and Trust & Safety only
    dimensions: dict[str, str]
    explanation: list[str]
    updatedAt: datetime | None


class TierChangeOut(BaseModel):
    fromTier: str
    toTier: str
    reasons: list[str]
    at: datetime


class SignalOut(BaseModel):
    type: str
    adverse: bool
    summary: str
    at: datetime


class TrustHistoryOut(BaseModel):
    tierChanges: list[TierChangeOut]
    signals: list[SignalOut]
    flags: list[str]
