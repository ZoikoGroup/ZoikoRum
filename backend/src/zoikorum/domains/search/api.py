from __future__ import annotations

from datetime import datetime
import uuid

from fastapi import APIRouter, Query

from zoikorum.domains.search import service
from zoikorum.domains.search.schemas import SearchOut, SearchParams, Sort
from zoikorum.shared.auth import CurrentActor, OptionalActor
from zoikorum.shared.db import DbSession

router = APIRouter(tags=["search"])


def _csv(value: str | None) -> list[str]:
    return [v.strip() for v in (value or "").split(",") if v.strip()]


@router.get("/v1/search/professionals", response_model=SearchOut)
async def search_professionals(
    session: DbSession, actor: OptionalActor,
    organizationId: uuid.UUID | None = None,
    q: str | None = Query(default=None, max_length=200),
    category: str | None = None,
    spec: str | None = Query(default=None, description="Comma-separated specialization slugs"),
    specMatch: str = Query(default="any", pattern="^(any|all)$"),
    tier: str | None = Query(default=None, description="Comma-separated: A,B,C"),
    verified: str | None = Query(default=None, description="Comma-separated: identity,credentials,jurisdiction,insurance,restrictions"),
    engagementType: str | None = None,
    delivery: str | None = None,
    availability: str | None = None,
    pricingModel: str | None = None,
    credential: str | None = Query(default=None, max_length=100),
    jurisdiction: str | None = Query(default=None, pattern="^[A-Za-z]{2}$"),
    experience: str | None = Query(default=None, pattern=r"^(0-2|3-5|6-10|11-15|16\+)$"),
    publishedAfter: datetime | None = None,
    sort: Sort = "best",
    limit: int = Query(default=20, ge=1, le=50),
    offset: int = Query(default=0, ge=0, le=1000),
):
    """Public discovery. Only published, non-suspended professionals; every result says why it matched."""
    params = SearchParams(organizationId=organizationId, q=q, category=category, spec=_csv(spec), specMatch=specMatch, tier=_csv(tier), verified=_csv(verified),
                          engagementType=engagementType, delivery=delivery, availability=availability, pricingModel=pricingModel,
                          credential=credential, jurisdiction=jurisdiction, experience=experience, publishedAfter=publishedAfter,
                          sort=sort, limit=limit, offset=offset)
    return await service.search(session, actor, params)


@router.post("/v1/admin/search/reindex")
async def reindex(actor: CurrentActor, session: DbSession) -> dict:
    """Platform Admin: rebuild the whole search projection from the owning domains."""
    return await service.reindex(session, actor)
