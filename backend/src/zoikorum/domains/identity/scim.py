"""SCIM 2.0 provisioning (RFC 7643/7644, the Users resource): the organisation's identity provider adds, updates and
removes members automatically.

Authenticated by the organisation's SCIM token (identity/sso.py, rotate_scim_token); it can only manage that
organisation's members, and only addresses in the organisation's SSO email domains. Removing a user ends their
membership; their personal account and history stay.
"""

from __future__ import annotations

import hashlib
import re
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from zoikorum.domains.identity.models import Identity, SsoConnection
from zoikorum.domains.identity.sso import _new_identity
from zoikorum.shared.auth import OrgRole, Persona
from zoikorum.shared.errors import Conflict, NotFound, Unauthenticated, ValidationFailed
from zoikorum.shared.events import record_audit

USER = "urn:ietf:params:scim:schemas:core:2.0:User"
LIST = "urn:ietf:params:scim:api:messages:2.0:ListResponse"
ROLES = set(OrgRole.ALL) - {OrgRole.ORG_ADMIN}  # admin rights are given by people in the app, never by provisioning


async def connection_for(session: AsyncSession, authorization: str | None) -> SsoConnection:
    token = (authorization or "")[7:] if (authorization or "").startswith("Bearer ") else ""
    c = await session.scalar(select(SsoConnection).where(SsoConnection.scim_token_hash == hashlib.sha256(token.encode()).hexdigest())) \
        if token else None
    if c is None or not c.enabled:
        raise Unauthenticated("Invalid SCIM token")
    return c


def _roles(body: dict, default: list[str]) -> list[str]:
    asked = [r.get("value") if isinstance(r, dict) else r for r in body.get("roles", [])]
    picked = [r for r in asked if r in ROLES]
    return picked or list(default)


async def _user(session: AsyncSession, c: SsoConnection, identity: Identity) -> dict:
    from zoikorum.domains.buyer import facade as buyer
    roles = await buyer.get_member_roles(session, c.organization_id, identity.id)
    return {"schemas": [USER], "id": str(identity.id), "userName": identity.email, "displayName": identity.display_name,
            "name": {"formatted": identity.display_name}, "emails": [{"value": identity.email, "primary": True}],
            "active": bool(roles), "roles": [{"value": r} for r in sorted(roles)], "meta": {"resourceType": "User"}}


async def list_users(session: AsyncSession, c: SsoConnection, filter_: str | None, start: int, count: int) -> dict:
    from zoikorum.domains.buyer import facade as buyer
    if filter_:
        m = re.fullmatch(r'\s*userName\s+eq\s+"([^"]+)"\s*', filter_)
        if not m:
            raise ValidationFailed("Only userName eq filters are supported", code="invalidFilter")
        identity = await session.scalar(select(Identity).where(Identity.email == m.group(1).lower()))
        found = [identity] if identity and await buyer.get_member_roles(session, c.organization_id, identity.id) else []
    else:
        ids = await buyer.member_roles_by_identity(session, c.organization_id)
        found = [i for i in (await session.scalars(select(Identity).where(Identity.id.in_(list(ids))).order_by(Identity.email))).all()]
    page = found[max(0, start - 1): max(0, start - 1) + count]
    return {"schemas": [LIST], "totalResults": len(found), "startIndex": start, "itemsPerPage": len(page),
            "Resources": [await _user(session, c, i) for i in page]}


async def create_user(session: AsyncSession, c: SsoConnection, body: dict) -> dict:
    from zoikorum.domains.buyer import facade as buyer
    email = (body.get("userName") or next((e.get("value") for e in body.get("emails", []) if e.get("value")), "")).lower()
    if not email or email.rsplit("@", 1)[-1] not in c.email_domains:
        raise ValidationFailed("userName must be an address in the organisation's single sign-on domains", code="invalidValue")
    identity = await session.scalar(select(Identity).where(Identity.email == email))
    if identity and await buyer.get_member_roles(session, c.organization_id, identity.id):
        raise Conflict("User already exists", code="uniqueness")
    if identity is None:
        name = body.get("displayName") or (body.get("name") or {}).get("formatted") or email.split("@")[0]
        identity = await _new_identity(session, email, name, Persona.ENTERPRISE_MEMBER)
    await buyer.ensure_member(session, c.organization_id, identity.id, email, identity.display_name, _roles(body, c.default_roles))
    record_audit(session, "identity.scim.user_provisioned", object_type="Identity", object_id=identity.id, tenant_id=c.organization_id)
    return await _user(session, c, identity)


async def _member_identity(session: AsyncSession, c: SsoConnection, user_id: str, *, active_only: bool = True) -> Identity:
    from zoikorum.domains.buyer import facade as buyer
    try:
        identity = await session.get(Identity, uuid.UUID(user_id))
    except ValueError:
        identity = None
    if identity is None or (active_only and not await buyer.get_member_roles(session, c.organization_id, identity.id)) \
            or identity.email.rsplit("@", 1)[-1] not in c.email_domains:
        raise NotFound("User not found")
    return identity


async def get_user(session: AsyncSession, c: SsoConnection, user_id: str) -> dict:
    return await _user(session, c, await _member_identity(session, c, user_id))


async def update_user(session: AsyncSession, c: SsoConnection, user_id: str, body: dict) -> dict:
    """PUT (whole user) or PATCH (Operations): active and roles are what this platform takes from the provider."""
    from zoikorum.domains.buyer import facade as buyer
    identity = await _member_identity(session, c, user_id, active_only=False)
    active, roles = None, None
    if "Operations" in body:
        for op in body["Operations"]:
            path, value = (op.get("path") or "").lower(), op.get("value")
            if path == "active":
                active = value in (True, "true", "True")
            elif path == "roles":
                roles = _roles({"roles": value if isinstance(value, list) else [value]}, c.default_roles)
            elif not path and isinstance(value, dict):
                if "active" in value:
                    active = value["active"] in (True, "true", "True")
                if "roles" in value:
                    roles = _roles(value, c.default_roles)
    else:
        active = body.get("active", True) in (True, "true", "True")
        roles = _roles(body, c.default_roles) if "roles" in body else None
    current = await buyer.get_member_roles(session, c.organization_id, identity.id)
    if active is False:
        await buyer.deactivate_member(session, c.organization_id, identity.id)
        record_audit(session, "identity.scim.user_deactivated", object_type="Identity", object_id=identity.id, tenant_id=c.organization_id)
    elif active is True or roles is not None:
        keep = sorted(set(current) & {OrgRole.ORG_ADMIN})  # admin rights given in the app are kept
        await buyer.ensure_member(session, c.organization_id, identity.id, identity.email, identity.display_name,
                                  sorted(set((roles or [r for r in current if r != OrgRole.ORG_ADMIN] or c.default_roles)) | set(keep)))
    return await _user(session, c, identity)


async def delete_user(session: AsyncSession, c: SsoConnection, user_id: str) -> None:
    from zoikorum.domains.buyer import facade as buyer
    identity = await _member_identity(session, c, user_id, active_only=False)
    await buyer.deactivate_member(session, c.organization_id, identity.id)
    record_audit(session, "identity.scim.user_deactivated", object_type="Identity", object_id=identity.id, tenant_id=c.organization_id)


SERVICE_PROVIDER_CONFIG = {
    "schemas": ["urn:ietf:params:scim:schemas:core:2.0:ServiceProviderConfig"],
    "patch": {"supported": True}, "bulk": {"supported": False, "maxOperations": 0, "maxPayloadSize": 0},
    "filter": {"supported": True, "maxResults": 200}, "changePassword": {"supported": False}, "sort": {"supported": False},
    "etag": {"supported": False},
    "authenticationSchemes": [{"type": "oauthbearertoken", "name": "Bearer token", "description": "The organisation's SCIM token"}],
}
