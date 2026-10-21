from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel, Field

from fastapi import APIRouter, Query, status

from zoikorum.domains.buyer import service
from zoikorum.domains.buyer.schemas import (
    BillingContactOut,
    BillingContactsIn,
    AcceptByTokenIn,
    AdminOrganizationOut,
    AdminOrganizationSummaryOut,
    BusinessUnitIn,
    BusinessUnitOut,
    CostCenterIn,
    LegalEntityIn,
    LegalEntityOut,
    CostCenterOut,
    InvitationOut,
    InviteIn,
    MemberOut,
    MemberPatch,
    OrganizationOut,
    OrganizationPatch,
)
from zoikorum.shared.auth import CurrentActor
from zoikorum.shared.db import DbSession
from zoikorum.shared.http import IfMatch, Page

router = APIRouter(prefix="/v1/organizations", tags=["buyer organizations"])


@router.get("/mine", response_model=list[OrganizationOut])
async def my_organizations(actor: CurrentActor, session: DbSession):
    return await service.my_organizations(session, actor)


# Invitations addressed to me (declared before /{org_id} routes).
@router.get("/invitations/mine", response_model=list[InvitationOut])
async def my_invitations(actor: CurrentActor, session: DbSession):
    return await service.my_invitations(session, actor)


@router.post("/invitations/accept", response_model=OrganizationOut)
async def accept_by_token(body: AcceptByTokenIn, actor: CurrentActor, session: DbSession):
    """Accept using the link from the invitation email."""
    return await service.accept_invitation(session, actor, token=body.token)


@router.post("/invitations/{invitation_id}/accept", response_model=OrganizationOut)
async def accept_by_id(invitation_id: uuid.UUID, actor: CurrentActor, session: DbSession):
    """Accept from the in-app invitations list (requires a confirmed email)."""
    return await service.accept_invitation(session, actor, invitation_id=invitation_id)


@router.post("/invitations/{invitation_id}/decline", status_code=status.HTTP_204_NO_CONTENT)
async def decline(invitation_id: uuid.UUID, actor: CurrentActor, session: DbSession) -> None:
    await service.decline_invitation(session, actor, invitation_id)


@router.get("/{org_id}", response_model=OrganizationOut)
async def get_organization(org_id: uuid.UUID, actor: CurrentActor, session: DbSession):
    return await service.get_organization(session, actor, org_id)


@router.patch("/{org_id}", response_model=OrganizationOut)
async def update_organization(org_id: uuid.UUID, body: OrganizationPatch, actor: CurrentActor, session: DbSession,
                              if_match: IfMatch = None):
    return await service.update_organization(session, actor, org_id, body.name, body.businessContext, body.industry,
                                             body.timeZone, if_match)


@router.get("/{org_id}/billing-contacts", response_model=list[BillingContactOut])
async def billing_contacts(org_id: uuid.UUID, actor: CurrentActor, session: DbSession):
    return await service.billing_contacts(session, actor, org_id)


@router.put("/{org_id}/billing-contacts", response_model=list[BillingContactOut])
async def set_billing_contacts(org_id: uuid.UUID, body: BillingContactsIn, actor: CurrentActor, session: DbSession):
    """Org Admin or Budget Owner: primary (and optional backup) billing contact."""
    return await service.set_billing_contacts(session, actor, org_id, body.primaryIdentityId, body.backupIdentityId)


@router.get("/{org_id}/members", response_model=list[MemberOut])
async def members(org_id: uuid.UUID, actor: CurrentActor, session: DbSession):
    return await service.list_members(session, actor, org_id)


@router.patch("/{org_id}/members/{identity_id}", response_model=MemberOut)
async def update_member(org_id: uuid.UUID, identity_id: uuid.UUID, body: MemberPatch, actor: CurrentActor, session: DbSession):
    return await service.update_member(session, actor, org_id, identity_id, body.roles, body.spendLimit,
                                       body.clearSpendLimit, body.businessUnitId)


@router.delete("/{org_id}/members/{identity_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_member(org_id: uuid.UUID, identity_id: uuid.UUID, actor: CurrentActor, session: DbSession) -> None:
    await service.remove_member(session, actor, org_id, identity_id)


@router.post("/{org_id}/invitations", response_model=InvitationOut, status_code=status.HTTP_201_CREATED)
async def invite(org_id: uuid.UUID, body: InviteIn, actor: CurrentActor, session: DbSession):
    return await service.invite(session, actor, org_id, body.email, body.roles, body.spendLimit, body.businessUnitId)


@router.get("/{org_id}/invitations", response_model=list[InvitationOut])
async def invitations(org_id: uuid.UUID, actor: CurrentActor, session: DbSession):
    return await service.list_invitations(session, actor, org_id)


@router.delete("/{org_id}/invitations/{invitation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_invitation(org_id: uuid.UUID, invitation_id: uuid.UUID, actor: CurrentActor, session: DbSession) -> None:
    await service.revoke_invitation(session, actor, org_id, invitation_id)


@router.get("/{org_id}/business-units", response_model=list[BusinessUnitOut])
async def business_units(org_id: uuid.UUID, actor: CurrentActor, session: DbSession):
    return await service.list_business_units(session, actor, org_id)


@router.post("/{org_id}/business-units", response_model=BusinessUnitOut, status_code=status.HTTP_201_CREATED)
async def create_business_unit(org_id: uuid.UUID, body: BusinessUnitIn, actor: CurrentActor, session: DbSession):
    return await service.create_business_unit(session, actor, org_id, body.name, body.parentId)


@router.get("/{org_id}/legal-entities", response_model=list[LegalEntityOut])
async def legal_entities(org_id: uuid.UUID, actor: CurrentActor, session: DbSession):
    """The registered companies this organisation contracts and is invoiced through (any member can see them)."""
    return await service.list_legal_entities(session, actor, org_id)


@router.post("/{org_id}/legal-entities", response_model=LegalEntityOut, status_code=status.HTTP_201_CREATED)
async def create_legal_entity(org_id: uuid.UUID, body: LegalEntityIn, actor: CurrentActor, session: DbSession):
    """Organisation admin. The first entity becomes the default."""
    return await service.create_legal_entity(session, actor, org_id, body)


@router.put("/{org_id}/legal-entities/{entity_id}", response_model=LegalEntityOut)
async def update_legal_entity(org_id: uuid.UUID, entity_id: uuid.UUID, body: LegalEntityIn, actor: CurrentActor,
                              session: DbSession):
    """Organisation admin. Applies to new contracts and invoices; signed contracts keep their details."""
    return await service.update_legal_entity(session, actor, org_id, entity_id, body)


@router.post("/{org_id}/legal-entities/{entity_id}/archive", response_model=LegalEntityOut)
async def archive_legal_entity(org_id: uuid.UUID, entity_id: uuid.UUID, actor: CurrentActor, session: DbSession):
    """Organisation admin. No new requests through it; past contracts and invoices keep it."""
    return await service.archive_legal_entity(session, actor, org_id, entity_id)


@router.get("/{org_id}/cost-centers", response_model=list[CostCenterOut])
async def cost_centers(org_id: uuid.UUID, actor: CurrentActor, session: DbSession):
    return await service.list_cost_centers(session, actor, org_id)


@router.post("/{org_id}/cost-centers", response_model=CostCenterOut, status_code=status.HTTP_201_CREATED)
async def create_cost_center(org_id: uuid.UUID, body: CostCenterIn, actor: CurrentActor, session: DbSession):
    return await service.create_cost_center(session, actor, org_id, body.name, body.code, body.businessUnitId, body.quarterlyBudget)


class MergeUnitsIn(BaseModel):
    targetId: uuid.UUID  # the unit that remains


@router.post("/{org_id}/business-units/{unit_id}/merge", response_model=list[BusinessUnitOut])
async def merge_business_units(org_id: uuid.UUID, unit_id: uuid.UUID, body: MergeUnitsIn, actor: CurrentActor, session: DbSession):
    """Organisation Admin: fold this unit into another; everything it held moves to that unit."""
    return await service.merge_business_units(session, actor, org_id, unit_id, body.targetId)


class ApiKeyIn(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    scope: Literal["READ", "WRITE"] = "READ"
    expiresInDays: int | None = Field(default=None, ge=1, le=730)


@router.get("/{org_id}/api-keys")
async def list_api_keys(org_id: uuid.UUID, actor: CurrentActor, session: DbSession) -> list[dict]:
    """Organisation Admin: the organisation's API keys (never the keys themselves)."""
    from zoikorum.domains.buyer import api_keys
    return await api_keys.list_keys(session, actor, org_id)


@router.post("/{org_id}/api-keys", status_code=status.HTTP_201_CREATED)
async def create_api_key(org_id: uuid.UUID, body: ApiKeyIn, actor: CurrentActor, session: DbSession) -> dict:
    """Organisation Admin: create a key (shown once). It acts as you, with your current roles, and never confirms
    actions that need two-step sign-in."""
    from zoikorum.domains.buyer import api_keys
    return await api_keys.create_key(session, actor, org_id, body.name, body.scope, body.expiresInDays)


@router.post("/{org_id}/api-keys/{key_id}/revoke")
async def revoke_api_key(org_id: uuid.UUID, key_id: uuid.UUID, actor: CurrentActor, session: DbSession) -> dict:
    from zoikorum.domains.buyer import api_keys
    return await api_keys.revoke_key(session, actor, org_id, key_id)


# Staff admin console: every organisation on the platform (outside the /v1/organizations prefix).
admin_router = APIRouter(prefix="/v1/admin/organizations", tags=["buyer organizations"])


@admin_router.get("", response_model=Page[AdminOrganizationOut])
async def admin_organizations(actor: CurrentActor, session: DbSession, q: str | None = Query(default=None, max_length=200),
                              kind: Literal["BUYER", "ENTERPRISE", "FIRM"] | None = None,
                              status_: Literal["ACTIVE", "SUSPENDED"] | None = Query(default=None, alias="status"),
                              cursor: str | None = None, limit: int | None = Query(default=None, ge=1, le=100)):
    """Platform Admin / Trust & Safety / Compliance / Support: buyer organisations, enterprises and firms, searchable by
    name. Reads are audited."""
    return await service.admin_organizations(session, actor, q, kind, status_, cursor, limit)


@admin_router.get("/summary", response_model=AdminOrganizationSummaryOut)
async def admin_organization_summary(actor: CurrentActor, session: DbSession):
    return await service.admin_organization_summary(session, actor)
