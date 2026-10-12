"""Federation boundary. Unvalidated assertions must never create authenticated users."""
from __future__ import annotations
from pydantic import BaseModel
from zoikorum.shared.errors import ServiceUnavailable

class SSOProfile(BaseModel):
    email: str
    first_name: str
    last_name: str
    groups: list[str]
    provider: str

async def handle_saml_assertion(xml_payload: str) -> SSOProfile:
    raise ServiceUnavailable("SAML assertion verification is not configured", code="SSO_NOT_CONFIGURED")

async def sync_scim_user(action: str, email: str, attributes: dict) -> None:
    raise ServiceUnavailable("SCIM provisioning is not configured", code="SCIM_NOT_CONFIGURED")
