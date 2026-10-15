from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class PreferencesIO(BaseModel):
    email: bool = True
    inApp: bool = True
    sms: bool = False
    marketing: bool = False
    digest: Literal["OFF", "DAILY", "WEEKLY"] = "OFF"  # bundle non-urgent emails into one summary
    mandatoryNotice: str = "Security and account-protection messages are always sent by email."
