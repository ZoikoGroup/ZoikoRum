"""Specialization matching for "Can't find yours?" (AI assists, humans decide - Architecture 10.1).

Given the professional's own words and the live taxonomy, return up to five existing specializations that fit and,
when nothing fits well, a DRAFT for a new one. The draft is only a suggestion: an admin approves, merges or rejects it.

Claude is used when ZK_AI_PROVIDER=anthropic and ZK_ANTHROPIC_API_KEY is set (and the `anthropic` package is
installed). Any problem - no key, network, timeout, refusal, unexpected output - falls back to deterministic keyword
matching, so the feature always works and never raises to the caller.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from pydantic import BaseModel, Field

from zoikorum.config import get_settings

log = logging.getLogger("zoikorum.ai")
PROMPT_VERSION = "spec-match-1"
MAX_MATCHES = 5


@dataclass(frozen=True)
class CatalogEntry:
    slug: str
    name: str
    category_slug: str
    category_name: str
    group_slug: str
    group_name: str


@dataclass(frozen=True)
class Draft:
    name: str
    category_slug: str | None
    group_slug: str | None
    description: str
    credential_likely: bool


@dataclass(frozen=True)
class SpecializationMatch:
    slugs: tuple[str, ...]  # best first, all from the catalog
    draft: Draft | None  # only when nothing in the catalog fits well
    source: str  # "ai:<model>@<promptVersion>" or "fallback:keyword"


# ---- Keyword fallback -------------------------------------------------------------------------------------------

_STOP = {"and", "the", "for", "with", "of", "in", "to", "a", "an", "i", "my", "we", "our", "on", "at", "by", "from", "build",
         "building", "help", "do", "doing", "work", "services", "service", "expert", "specialist", "consultant"}


def _words(text: str) -> set[str]:
    out = set()
    for w in re.findall(r"[a-z0-9+#]+", text.lower()):
        if w in _STOP or len(w) < 2:
            continue
        out.add(w[:-1] if len(w) > 4 and w.endswith("s") else w)  # crude plural folding: "models" -> "model"
    return out


def keyword_match(text: str, catalog: list[CatalogEntry]) -> SpecializationMatch:
    want = _words(text)
    scored = []
    for e in catalog:
        name_hits = len(want & _words(e.name))
        context_hits = len(want & _words(f"{e.group_name} {e.category_name}"))
        score = name_hits * 3 + context_hits
        if score:
            scored.append((score, e))
    scored.sort(key=lambda x: (-x[0], x[1].name))
    slugs = tuple(e.slug for _, e in scored[:MAX_MATCHES])
    draft = None
    if not scored or scored[0][0] < 3:  # nothing matches by name: offer a draft in the closest category
        best = scored[0][1] if scored else None
        name = re.sub(r"\s+", " ", text.strip())[:80].strip(" .,")
        draft = Draft(name=name[:1].upper() + name[1:], category_slug=best.category_slug if best else None,
                      group_slug=best.group_slug if best else None, description=text.strip()[:500], credential_likely=False)
    return SpecializationMatch(slugs=slugs, draft=draft, source="fallback:keyword")


# ---- Claude -------------------------------------------------------------------------------------------------------

class _DraftOut(BaseModel):
    name: str = Field(description="Short specialization name in title case, 2-6 words, no company names")
    category_slug: str = Field(description="One category slug from the catalog")
    group_slug: str = Field(description="One group slug from the catalog, inside that category")
    description: str = Field(description="One sentence describing the work")
    credential_likely: bool = Field(description="True if this work is usually licensed or certified by law")


class _MatchOut(BaseModel):
    matching_slugs: list[str] = Field(description="Up to 5 specialization slugs from the catalog, best first")
    needs_new_specialization: bool = Field(description="True only if no catalog specialization describes the work well")
    draft: _DraftOut | None = None


_SYSTEM = (
    "You map a professional's own description of their work onto a fixed specialization catalog for a professional-"
    "services marketplace. Return up to 5 catalog slugs that genuinely fit, best first; never invent slugs. If none "
    "describes the work well, set needs_new_specialization and draft one new specialization that fits under an "
    "existing category and group. Keep names generic (a skill, not a person or company). Mark credential_likely only "
    "for work that normally requires a licence or certification (e.g. audit, legal advice, penetration testing)."
)


async def _claude_match(text: str, catalog: list[CatalogEntry]) -> SpecializationMatch | None:
    s = get_settings()
    if s.ai_provider != "anthropic" or not s.anthropic_api_key:
        return None
    try:
        import anthropic  # optional dependency: only needed when an API key is configured
    except ImportError:
        log.warning("ai_provider=anthropic but the anthropic package is not installed; using keyword matching")
        return None
    lines = "\n".join(f"{e.slug} | {e.name} | group {e.group_slug} ({e.group_name}) | category {e.category_slug} ({e.category_name})"
                      for e in catalog)
    try:
        client = anthropic.AsyncAnthropic(api_key=s.anthropic_api_key, timeout=20.0, max_retries=1)
        response = await client.messages.parse(
            model=s.ai_model,
            max_tokens=2000,
            system=[{"type": "text", "text": _SYSTEM}, {"type": "text", "text": f"Catalog (slug | name | group | category):\n{lines}",
                                                         "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": f"The professional describes their work as:\n\n{text}"}],
            output_format=_MatchOut,
        )
    except anthropic.APIError as exc:  # network, rate limit, auth, server errors
        log.warning("specialization matching via Claude failed (%s); using keyword matching", type(exc).__name__)
        return None
    if response.stop_reason == "refusal" or response.parsed_output is None:
        return None
    out = response.parsed_output
    known = {e.slug: e for e in catalog}
    slugs = tuple(dict.fromkeys(x for x in out.matching_slugs if x in known))[:MAX_MATCHES]
    draft = None
    if out.needs_new_specialization and out.draft:
        groups = {e.group_slug: e.category_slug for e in catalog}
        group = out.draft.group_slug if out.draft.group_slug in groups else None
        draft = Draft(name=out.draft.name.strip()[:120], category_slug=groups.get(group) if group else None, group_slug=group,
                      description=out.draft.description.strip()[:500], credential_likely=out.draft.credential_likely)
    return SpecializationMatch(slugs=slugs, draft=draft, source=f"ai:{s.ai_model}@{PROMPT_VERSION}")


async def match_specializations(text: str, catalog: list[CatalogEntry]) -> SpecializationMatch:
    """Never raises: Claude when configured, otherwise (or on any failure) keyword matching."""
    try:
        result = await _claude_match(text, catalog)
    except Exception:  # noqa: BLE001 - AI must degrade, never break the caller
        log.exception("unexpected error in specialization matching; using keyword matching")
        result = None
    return result or keyword_match(text, catalog)
