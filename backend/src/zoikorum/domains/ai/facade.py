"""AI facade - CONTRACT. AI assists; it never decides (Architecture 10.1).

Every function must degrade gracefully: on provider failure return a
deterministic non-AI fallback, never raise to the caller.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True)
class MatchIntent:
    specializations: tuple[str, ...]  # taxonomy slugs
    engagement_type: str | None
    keywords: tuple[str, ...]
    source: str  # "ai:<model>@<promptVersion>" or "fallback:keyword"


async def extract_match_intent(session: AsyncSession, text: str) -> MatchIntent:
    raise NotImplementedError


# ---- Specialization matching ("Can't find yours?") ----------------------------------------------------------------
from zoikorum.domains.ai.specializations import (  # noqa: E402  (contract re-export for other domains)
    CatalogEntry,
    Draft,
    SpecializationMatch,
    match_specializations,
)

__all__ = ["CatalogEntry", "Draft", "MatchIntent", "SpecializationMatch", "extract_match_intent", "match_specializations"]
