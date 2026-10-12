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

__all__ = ["CatalogEntry", "Draft", "MatchIntent", "SearchIntent", "SpecializationMatch", "extract_match_intent",
           "extract_search_intent", "match_specializations"]

async def privacy_export(session, identity_id):
    from zoikorum.shared.privacy_exports import export_rows
    from zoikorum.domains.ai.models import InferenceLog
    return {
        'inference_logs': await export_rows(session, InferenceLog, InferenceLog.requested_by == identity_id, ['prompt_id', 'prompt_version', 'model', 'input_sha256', 'purpose', 'subject_id', 'requested_by', 'latency_ms', 'fallback_used', 'id', 'created_at']),
    }
