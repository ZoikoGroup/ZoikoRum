from __future__ import annotations

from pydantic import BaseModel


class PreferencesIO(BaseModel):
    email: bool = True
    inApp: bool = True
    sms: bool = False
    marketing: bool = False
    mandatoryNotice: str = "Security and account-protection messages are always sent by email."
