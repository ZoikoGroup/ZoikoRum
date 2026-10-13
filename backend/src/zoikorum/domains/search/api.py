from __future__ import annotations

from datetime import datetime
import uuid

from fastapi import APIRouter, Query, Request

from zoikorum.config import get_settings

from zoikorum.domains.search import service
from zoikorum.domains.search.schemas import IntentIn, IntentOut, SearchOut, SearchParams, Sort
from zoikorum.shared.auth import CurrentActor, OptionalActor
from zoikorum.shared import ratelimit
from zoikorum.shared.db import DbSession
from zoikorum.shared.errors import RateLimited
from zoikorum.shared.http import caller_key

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


# AI calls cost money and time: a tighter budget than the general API limit, per signed-in session or client address.
INTENT_LIMIT = (10, 10)  # requests per minute, burst


@router.post("/v1/search/intent", response_model=IntentOut)
async def search_intent(body: IntentIn, request: Request, session: DbSession, actor: OptionalActor):
    """"Describe what you need": suggested filters with the reason for each. Nothing is searched or saved here."""
    if get_settings().rate_limit_enabled:
        caller = ":".join(caller_key(request))
        if not await ratelimit.get_buckets().take(ratelimit.bucket_key("intent", caller), *INTENT_LIMIT):
            raise RateLimited("Too many requests to describe what you need. Please wait a minute, or use the filters.")
    return await service.intent(session, body)


@router.post("/v1/admin/search/reindex")
async def reindex(actor: CurrentActor, session: DbSession) -> dict:
    """Platform Admin: rebuild the whole search projection from the owning domains."""
    return await service.reindex(session, actor)
