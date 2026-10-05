from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Header, Response, status

from zoikorum.domains.professional import service
from zoikorum.domains.professional.schemas import (
    AvailabilityIn,
    CredentialIn,
    CredentialOut,
    JurisdictionsIn,
    OfferingIn,
    OfferingOut,
    OfferingPatch,
    PhotoIn,
    ProfileOut,
    ProfilePatch,
    PublicProfileOut,
    PublishIn,
    ReadinessOut,
    RegisterIn,
    SpecializationsIn,
)
from zoikorum.shared.auth import CurrentActor, OptionalActor
from zoikorum.shared.db import DbSession

router = APIRouter(prefix="/v1/professionals", tags=["professionals"])

IfMatch = Annotated[str | None, Header(alias="If-Match")]


def _version(if_match: str | None) -> int | None:
    return int(if_match.strip('"')) if if_match and if_match.strip('"').isdigit() else None


@router.post("", response_model=ProfileOut, status_code=status.HTTP_201_CREATED)
async def register(body: RegisterIn, actor: CurrentActor, session: DbSession):
    return await service.register(session, actor, body)


@router.get("/me", response_model=ProfileOut)
async def me(actor: CurrentActor, session: DbSession):
    return await service.get_me(session, actor)


@router.patch("/me", response_model=ProfileOut)
async def update_me(body: ProfilePatch, actor: CurrentActor, session: DbSession, if_match: IfMatch = None):
    return await service.update_me(session, actor, body, _version(if_match))


@router.put("/me/photo", response_model=ProfileOut)
async def set_photo(body: PhotoIn, actor: CurrentActor, session: DbSession):
    """Profile photo: JPEG, PNG or WebP under 2 MB, sent as base64."""
    return await service.set_photo(session, actor, body)


@router.delete("/me/photo", response_model=ProfileOut)
async def remove_photo(actor: CurrentActor, session: DbSession):
    return await service.remove_photo(session, actor)


@router.get("/{professional_id}/photo")
async def photo(professional_id: uuid.UUID, actor: OptionalActor, session: DbSession) -> Response:
    data, content_type = await service.photo(session, actor, professional_id)
    return Response(data, media_type=content_type, headers={"Cache-Control": "public, max-age=86400",
                                                            "X-Content-Type-Options": "nosniff"})


@router.put("/me/specializations", response_model=ProfileOut)
async def specializations(body: SpecializationsIn, actor: CurrentActor, session: DbSession):
    return await service.set_specializations(session, actor, body)


@router.put("/me/jurisdictions", response_model=ProfileOut)
async def jurisdictions(body: JurisdictionsIn, actor: CurrentActor, session: DbSession):
    return await service.set_jurisdictions(session, actor, body)


@router.put("/me/availability", response_model=ProfileOut)
async def availability(body: AvailabilityIn, actor: CurrentActor, session: DbSession):
    return await service.set_availability(session, actor, body)


@router.get("/me/readiness", response_model=ReadinessOut)
async def readiness(actor: CurrentActor, session: DbSession):
    return await service.readiness(session, actor)


@router.post("/me/publish", response_model=ProfileOut)
async def publish(body: PublishIn, actor: CurrentActor, session: DbSession):
    # body.attestAccurate is validated as `true` by the schema: publishing requires the accuracy attestation.
    return await service.publish(session, actor)


@router.post("/me/unpublish", response_model=ProfileOut)
async def unpublish(actor: CurrentActor, session: DbSession):
    return await service.unpublish(session, actor)


@router.post("/me/credentials", response_model=CredentialOut, status_code=status.HTTP_201_CREATED)
async def add_credential(body: CredentialIn, actor: CurrentActor, session: DbSession):
    return await service.add_credential(session, actor, body)


@router.get("/me/credentials", response_model=list[CredentialOut])
async def credentials(actor: CurrentActor, session: DbSession):
    return await service.list_credentials(session, actor)


@router.delete("/me/credentials/{claim_id}", status_code=status.HTTP_204_NO_CONTENT)
async def withdraw_credential(claim_id: uuid.UUID, actor: CurrentActor, session: DbSession) -> None:
    await service.withdraw_credential(session, actor, claim_id)


@router.post("/me/offerings", response_model=OfferingOut, status_code=status.HTTP_201_CREATED)
async def create_offering(body: OfferingIn, actor: CurrentActor, session: DbSession):
    return await service.create_offering(session, actor, body)


@router.get("/me/offerings", response_model=list[OfferingOut])
async def offerings(actor: CurrentActor, session: DbSession):
    return await service.list_offerings(session, actor)


@router.get("/me/offerings/{offering_id}", response_model=OfferingOut)
async def offering(offering_id: uuid.UUID, actor: CurrentActor, session: DbSession):
    return await service.get_offering(session, actor, offering_id)


@router.patch("/me/offerings/{offering_id}", response_model=OfferingOut)
async def update_offering(offering_id: uuid.UUID, body: OfferingPatch, actor: CurrentActor, session: DbSession,
                          if_match: IfMatch = None):
    return await service.update_offering(session, actor, offering_id, body, _version(if_match))


@router.post("/me/offerings/{offering_id}/activate", response_model=OfferingOut)
async def activate_offering(offering_id: uuid.UUID, actor: CurrentActor, session: DbSession):
    return await service.set_offering_status(session, actor, offering_id, "ACTIVE")


@router.post("/me/offerings/{offering_id}/pause", response_model=OfferingOut)
async def pause_offering(offering_id: uuid.UUID, actor: CurrentActor, session: DbSession):
    return await service.set_offering_status(session, actor, offering_id, "PAUSED")


@router.get("/{professional_id}", response_model=PublicProfileOut)
async def public_profile(professional_id: uuid.UUID, actor: OptionalActor, session: DbSession):
    """Public profile. Works without signing in."""
    return await service.public_profile(session, actor, professional_id)
