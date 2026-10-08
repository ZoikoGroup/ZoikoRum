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
