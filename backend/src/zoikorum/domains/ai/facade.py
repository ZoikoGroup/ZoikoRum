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
    import re
    words = tuple(dict.fromkeys(re.findall(r"[\w-]+", text.lower())[:100]))
    from zoikorum.domains.marketplace import facade as marketplace
    names = await marketplace.specialization_names(session)
    matched = tuple(slug for slug, name in names.items() if set(re.findall(r"[\w-]+", name.lower())).intersection(words))
    return MatchIntent(specializations=matched, engagement_type=None, keywords=words, source="fallback:keyword")


# ---- Specialization matching ("Can't find yours?") ----------------------------------------------------------------
from zoikorum.domains.ai.specializations import (  # noqa: E402  (contract re-export for other domains)
    CatalogEntry,
    Draft,
    SpecializationMatch,
    match_specializations,
)

# ---- "Describe what you need" search ------------------------------------------------------------------------------
from zoikorum.domains.ai.intent import SearchIntent, extract_search_intent  # noqa: E402  (contract re-export)

# ---- First look at uploaded verification documents --------------------------------------------------------------------
from zoikorum.domains.ai.claude import save_inference_logs  # noqa: E402  (contract re-export)
from zoikorum.domains.ai.documents import DocumentCheck, assess_document, not_checked  # noqa: E402  (contract re-export)

__all__ = ["CatalogEntry", "DocumentCheck", "Draft", "MatchIntent", "SearchIntent", "SpecializationMatch", "assess_document",
           "extract_match_intent", "extract_search_intent", "match_specializations", "not_checked", "save_inference_logs"]


async def risk_top(session, actor, limit: int = 25) -> list[dict]:
    from zoikorum.domains.ai import risk
    return await risk.top(session, actor, limit)


async def risk_explain(session, actor, subject_type: str, subject_id):
    from zoikorum.domains.ai import risk
    return await risk.explain(session, actor, subject_type, subject_id)
