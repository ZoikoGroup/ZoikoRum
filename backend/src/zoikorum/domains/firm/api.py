from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Header, status

from zoikorum.domains.firm import service
from zoikorum.domains.firm.schemas import (
    AcceptByTokenIn,
    FirmInvitationOut,
    FirmInviteIn,
    FirmMemberOut,
    FirmMemberPatch,
    FirmOut,
    FirmPatch,
)
from zoikorum.shared.auth import CurrentActor
from zoikorum.shared.db import DbSession

router = APIRouter(prefix="/v1/firms", tags=["firms"])


@router.get("/mine", response_model=list[FirmOut])
async def my_firms(actor: CurrentActor, session: DbSession):
    return await service.my_firms(session, actor)


@router.get("/invitations/mine", response_model=list[FirmInvitationOut])
async def my_invitations(actor: CurrentActor, session: DbSession):
    return await service.my_invitations(session, actor)


@router.post("/invitations/accept", response_model=FirmOut)
async def accept_by_token(body: AcceptByTokenIn, actor: CurrentActor, session: DbSession):
    return await service.accept_invitation(session, actor, token=body.token)


@router.post("/invitations/{invitation_id}/accept", response_model=FirmOut)
async def accept_by_id(invitation_id: uuid.UUID, actor: CurrentActor, session: DbSession):
    return await service.accept_invitation(session, actor, invitation_id=invitation_id)


@router.post("/invitations/{invitation_id}/decline", status_code=status.HTTP_204_NO_CONTENT)
async def decline(invitation_id: uuid.UUID, actor: CurrentActor, session: DbSession) -> None:
    await service.decline_invitation(session, actor, invitation_id)


@router.get("/{firm_id}", response_model=FirmOut)
async def get_firm(firm_id: uuid.UUID, actor: CurrentActor, session: DbSession):
    return await service.get_firm(session, actor, firm_id)


@router.patch("/{firm_id}", response_model=FirmOut)
async def update_firm(
    firm_id: uuid.UUID, body: FirmPatch, actor: CurrentActor, session: DbSession,
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
):
    version = int(if_match.strip('"')) if if_match and if_match.strip('"').isdigit() else None
    return await service.update_firm(session, actor, firm_id, body, version)


@router.get("/{firm_id}/members", response_model=list[FirmMemberOut])
async def members(firm_id: uuid.UUID, actor: CurrentActor, session: DbSession):
    return await service.list_members(session, actor, firm_id)


@router.patch("/{firm_id}/members/{identity_id}", response_model=FirmMemberOut)
async def update_member(firm_id: uuid.UUID, identity_id: uuid.UUID, body: FirmMemberPatch, actor: CurrentActor, session: DbSession):
    return await service.update_member_roles(session, actor, firm_id, identity_id, body.roles)


@router.delete("/{firm_id}/members/{identity_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_member(firm_id: uuid.UUID, identity_id: uuid.UUID, actor: CurrentActor, session: DbSession) -> None:
    await service.remove_member(session, actor, firm_id, identity_id)


@router.post("/{firm_id}/invitations", response_model=FirmInvitationOut, status_code=status.HTTP_201_CREATED)
async def invite(firm_id: uuid.UUID, body: FirmInviteIn, actor: CurrentActor, session: DbSession):
    return await service.invite(session, actor, firm_id, body.email, body.roles)


@router.get("/{firm_id}/invitations", response_model=list[FirmInvitationOut])
async def invitations(firm_id: uuid.UUID, actor: CurrentActor, session: DbSession):
    return await service.list_invitations(session, actor, firm_id)


@router.delete("/{firm_id}/invitations/{invitation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_invitation(firm_id: uuid.UUID, invitation_id: uuid.UUID, actor: CurrentActor, session: DbSession) -> None:
    await service.revoke_invitation(session, actor, firm_id, invitation_id)
