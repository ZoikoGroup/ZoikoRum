"""SCIM 2.0 provisioning (RFC 7643/7644, the Users and Groups resources): the organisation's identity provider adds,
updates and removes members automatically, and manages their organisation roles through groups.

Groups: a group maps to one organisation role, by the connection's group-role map ({display name: role}) or by being
named after the role ("APPROVER", "Budget Owner"). Its members hold that role; a role that some group maps to is then
managed by groups only (taken away when the person leaves the last such group). Roles no group maps to are left as set
in the app or by the user's own "roles" attribute. Organisation Admin is never given by provisioning. Groups that map to
no role are kept (identity providers push every assigned group) and change nothing.

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

from zoikorum.domains.identity.models import Identity, ScimGroup, SsoConnection
from zoikorum.domains.identity.sso import _new_identity
from zoikorum.shared.auth import OrgRole, Persona
from zoikorum.shared.errors import Conflict, NotFound, Unauthenticated, ValidationFailed
from zoikorum.shared.events import record_audit

USER = "urn:ietf:params:scim:schemas:core:2.0:User"
GROUP = "urn:ietf:params:scim:schemas:core:2.0:Group"
PATCH_OP = "urn:ietf:params:scim:api:messages:2.0:PatchOp"
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


# ---- Groups --------------------------------------------------------------------------------------------------------------

def group_role(c: SsoConnection, display_name: str) -> str | None:
    """The organisation role a group grants: the connection's map first, then a group named after a role."""
    mapped = (c.group_role_map or {}).get(display_name)
    if mapped in ROLES:
        return mapped
    named = re.sub(r"[^A-Z]+", "_", display_name.strip().upper()).strip("_")
    return named if named in ROLES else None


def _group_out(c: SsoConnection, g: ScimGroup, identities: dict[uuid.UUID, Identity]) -> dict:
    return {"schemas": [GROUP], "id": str(g.id), "displayName": g.display_name, "externalId": g.external_id,
            "members": [{"value": str(m), "display": identities[m].email if m in identities else None, "type": "User"}
                        for m in g.member_ids],
            "meta": {"resourceType": "Group", "created": g.created_at, "lastModified": g.updated_at},
            "urn:zoikorum:scim:Group": {"role": group_role(c, g.display_name)}}


async def _identities(session: AsyncSession, ids) -> dict[uuid.UUID, Identity]:
    ids = list(ids)
    if not ids:
        return {}
    return {i.id: i for i in (await session.scalars(select(Identity).where(Identity.id.in_(ids)))).all()}


async def _member_ids(session: AsyncSession, c: SsoConnection, members) -> list[uuid.UUID]:
    """Group members must be the organisation's users (by SCIM user id), in its SSO domains."""
    from zoikorum.domains.buyer import facade as buyer

    out = []
    for m in members or []:
        value = m.get("value") if isinstance(m, dict) else m
        try:
            identity = await session.get(Identity, uuid.UUID(str(value)))
        except ValueError:
            identity = None
        if identity is None or identity.email.rsplit("@", 1)[-1] not in c.email_domains \
                or not await buyer.get_member_roles(session, c.organization_id, identity.id):
            raise ValidationFailed(f"Group member {value} is not a user of this organisation", code="invalidValue")
        if identity.id not in out:
            out.append(identity.id)
    return out


async def _sync_roles(session: AsyncSession, c: SsoConnection, identity_ids, also_managed=frozenset()) -> None:
    """Re-derive the group-managed roles of these people from the groups they are in."""
    from zoikorum.domains.buyer import facade as buyer

    groups = (await session.scalars(select(ScimGroup).where(ScimGroup.organization_id == c.organization_id))).all()
    managed = {r for g in groups if (r := group_role(c, g.display_name))} | (set(also_managed) - {None})
    for identity in (await _identities(session, set(identity_ids))).values():
        current = set(await buyer.get_member_roles(session, c.organization_id, identity.id))
        if not current:
            continue  # not (or no longer) a member: groups never re-add a removed person
        from_groups = {group_role(c, g.display_name) for g in groups if identity.id in g.member_ids} - {None}
        roles = (current - managed) | from_groups
        if not roles - {OrgRole.ORG_ADMIN}:
            roles |= set(c.default_roles)
        if roles != current:
            await buyer.ensure_member(session, c.organization_id, identity.id, identity.email, identity.display_name, sorted(roles))
            record_audit(session, "identity.scim.roles_synced", object_type="Identity", object_id=identity.id,
                         tenant_id=c.organization_id, details={"roles": sorted(roles)})


async def _group(session: AsyncSession, c: SsoConnection, group_id: str, *, lock: bool = False) -> ScimGroup:
    try:
        g = await session.get(ScimGroup, uuid.UUID(group_id), with_for_update=lock)
    except ValueError:
        g = None
    if g is None or g.organization_id != c.organization_id:
        raise NotFound("Group not found")
    return g


async def list_groups(session: AsyncSession, c: SsoConnection, filter_: str | None, start: int, count: int) -> dict:
    stmt = select(ScimGroup).where(ScimGroup.organization_id == c.organization_id).order_by(ScimGroup.display_name)
    if filter_:
        m = re.fullmatch(r'\s*(displayName|externalId)\s+eq\s+"([^"]+)"\s*', filter_)
        if not m:
            raise ValidationFailed("Only displayName eq and externalId eq filters are supported", code="invalidFilter")
        stmt = stmt.where((ScimGroup.display_name if m.group(1) == "displayName" else ScimGroup.external_id) == m.group(2))
    found = (await session.scalars(stmt)).all()
    page = found[max(0, start - 1): max(0, start - 1) + count]
    identities = await _identities(session, {m for g in page for m in g.member_ids})
    return {"schemas": [LIST], "totalResults": len(found), "startIndex": start, "itemsPerPage": len(page),
            "Resources": [_group_out(c, g, identities) for g in page]}


async def get_group(session: AsyncSession, c: SsoConnection, group_id: str) -> dict:
    g = await _group(session, c, group_id)
    return _group_out(c, g, await _identities(session, g.member_ids))


async def create_group(session: AsyncSession, c: SsoConnection, body: dict) -> dict:
    name = (body.get("displayName") or "").strip()
    if not name or len(name) > 200:
        raise ValidationFailed("displayName is required", code="invalidValue")
    if await session.scalar(select(ScimGroup).where(ScimGroup.organization_id == c.organization_id, ScimGroup.display_name == name)):
        raise Conflict("Group already exists", code="uniqueness")
    g = ScimGroup(organization_id=c.organization_id, display_name=name, external_id=(body.get("externalId") or None),
                  member_ids=await _member_ids(session, c, body.get("members")))
    session.add(g)
    await session.flush()
    await _sync_roles(session, c, g.member_ids)
    record_audit(session, "identity.scim.group_created", object_type="ScimGroup", object_id=g.id, tenant_id=c.organization_id,
                 details={"displayName": name, "role": group_role(c, name), "members": len(g.member_ids)})
    return _group_out(c, g, await _identities(session, g.member_ids))


def _member_filter(path: str) -> str | None:
    m = re.fullmatch(r'members\[\s*value\s+eq\s+"([^"]+)"\s*\]', path.strip())
    return m.group(1) if m else None


async def update_group(session: AsyncSession, c: SsoConnection, group_id: str, body: dict) -> dict:
    """PUT (the whole group) or PATCH (add/remove/replace members, replace displayName / externalId)."""
    g = await _group(session, c, group_id, lock=True)
    before, name_before = set(g.member_ids), g.display_name
    members = list(g.member_ids)
    if "Operations" in body:
        for op in body["Operations"]:
            kind, path, value = (op.get("op") or "").lower(), (op.get("path") or ""), op.get("value")
            if path.lower() == "members" or (not path and kind in ("add", "replace") and isinstance(value, dict) and "members" in value):
                listed = await _member_ids(session, c, value.get("members") if isinstance(value, dict) else value)
                if kind == "add":
                    members += [m for m in listed if m not in members]
                elif kind == "replace":
                    members = listed
                elif kind == "remove":
                    members = [m for m in members if m not in listed] if value else []
            elif (who := _member_filter(path)) and kind == "remove":
                members = [m for m in members if str(m) != who]
            if isinstance(value, dict) and not path:
                if "displayName" in value:
                    g.display_name = str(value["displayName"]).strip()[:200] or g.display_name
                if "externalId" in value:
                    g.external_id = value["externalId"] or None
            elif path == "displayName" and value:
                g.display_name = str(value).strip()[:200]
            elif path == "externalId":
                g.external_id = value or None
    else:
        g.display_name = (body.get("displayName") or g.display_name).strip()[:200]
        g.external_id = body.get("externalId", g.external_id) or None
        members = await _member_ids(session, c, body.get("members"))
    if g.display_name != name_before and await session.scalar(select(ScimGroup.id).where(
            ScimGroup.organization_id == c.organization_id, ScimGroup.display_name == g.display_name, ScimGroup.id != g.id)):
        raise Conflict("Another group has this name", code="uniqueness")
    g.member_ids = members
    await session.flush()
    await _sync_roles(session, c, before | set(members), {group_role(c, name_before)})
    record_audit(session, "identity.scim.group_updated", object_type="ScimGroup", object_id=g.id, tenant_id=c.organization_id,
                 details={"displayName": g.display_name, "role": group_role(c, g.display_name), "members": len(members)})
    return _group_out(c, g, await _identities(session, g.member_ids))


async def delete_group(session: AsyncSession, c: SsoConnection, group_id: str) -> None:
    g = await _group(session, c, group_id, lock=True)
    affected = list(g.member_ids)
    await session.delete(g)
    await session.flush()
    await _sync_roles(session, c, affected, {group_role(c, g.display_name)})
    record_audit(session, "identity.scim.group_deleted", object_type="ScimGroup", object_id=g.id, tenant_id=c.organization_id,
                 details={"displayName": g.display_name})


SERVICE_PROVIDER_CONFIG = {
    "schemas": ["urn:ietf:params:scim:schemas:core:2.0:ServiceProviderConfig"],
    "patch": {"supported": True}, "bulk": {"supported": False, "maxOperations": 0, "maxPayloadSize": 0},
    "filter": {"supported": True, "maxResults": 200}, "changePassword": {"supported": False}, "sort": {"supported": False},
    "etag": {"supported": False},
    "authenticationSchemes": [{"type": "oauthbearertoken", "name": "Bearer token", "description": "The organisation's SCIM token"}],
}
