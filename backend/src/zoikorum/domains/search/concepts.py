"""Semantic matching (Search: semantic search with rank fusion), computed inside the platform.

Each professional and each search query becomes a sparse concept vector over the capability taxonomy: the specialization
names themselves plus everyday synonyms ("books" -> bookkeeping, "CFO" -> finance leadership, "VAT" -> indirect tax).
Search ranks by the cosine similarity of those vectors and fuses it with the full-text rank (reciprocal rank fusion), so
"someone to do my books" finds bookkeepers. Nothing is sent outside the platform and no database extension is needed.
"""

from __future__ import annotations

import math
import re
import time

from sqlalchemy.ext.asyncio import AsyncSession

STOP = {"and", "or", "the", "a", "an", "of", "for", "to", "in", "on", "with", "my", "our", "we", "i", "need", "someone", "who",
        "can", "help", "services", "service", "support", "advisory", "consulting", "consultant", "expert", "specialist", "do",
        "management", "planning", "reporting", "&", "-", "/"}
# Everyday words -> words that appear in specialization names (matched against the live taxonomy, so they never point
# at a specialization that does not exist).
SYNONYMS = {
    "books": "bookkeeping", "bookkeeper": "bookkeeping", "accounts": "accounting", "accountant": "accounting",
    "ledger": "bookkeeping", "reconciliation": "bookkeeping", "cfo": "cfo", "finance director": "finance director",
    "controller": "controller", "vat": "vat", "gst": "gst", "sales tax": "sales tax", "tax return": "tax compliance",
    "filing": "tax compliance", "returns": "tax compliance", "payroll": "payroll", "audit": "audit", "auditor": "audit",
    "forecast": "forecasting", "budget": "budgeting", "fp&a": "fp-and-a", "m&a": "mergers", "acquisition": "mergers",
    "due diligence": "due diligence", "valuation": "valuation", "ifrs": "ifrs", "gaap": "gaap", "sox": "sox",
    "internal controls": "internal controls", "transfer pricing": "transfer pricing", "r&d": "r-and-d", "erp": "erp",
    "netsuite": "erp", "sap": "erp", "esg": "esg", "sustainability": "esg", "aml": "aml", "fraud": "forensic",
    "treasury": "treasury", "cash flow": "cash", "fundraising": "capital", "investor": "capital", "startup": "fractional",
    "part-time": "fractional", "interim": "fractional", "month end": "close", "year end": "close", "consolidation": "consolidation",
}
_index: tuple[float, dict[str, dict]] | None = None  # slug -> {"name", "tokens"}; refreshed every 10 minutes


def _tokens(text: str) -> list[str]:
    return [t for t in re.findall(r"[a-z0-9][a-z0-9&\-]*", text.lower()) if t not in STOP and len(t) > 1]


async def _taxonomy(session: AsyncSession) -> dict[str, dict]:
    global _index
    if _index and time.monotonic() - _index[0] < 600:
        return _index[1]
    from zoikorum.domains.marketplace import facade as marketplace_facade
    specs = await marketplace_facade.all_specializations(session)
    _index = (time.monotonic(), {s["slug"]: {"name": s["name"], "tokens": set(_tokens(s["name"] + " " + s["slug"].replace("-", " ")))}
                                 for s in specs})
    return _index[1]


def _expand(text: str) -> set[str]:
    low = f" {text.lower()} "
    words = set(_tokens(text))
    for phrase, target in SYNONYMS.items():
        if f" {phrase} " in low or phrase in words:
            words |= set(_tokens(target.replace("-", " "))) | {target}
    return words


async def vector(session: AsyncSession, text: str, specializations: dict[str, float] | None = None) -> dict[str, float]:
    """Concept weights for a text (and, for a profile, its own specializations at full weight)."""
    index = await _taxonomy(session)
    words = _expand(text)
    vec: dict[str, float] = {}
    for slug, entry in index.items():
        if not entry["tokens"]:
            continue
        hits = len(entry["tokens"] & words) + (1 if slug in words else 0)
        if hits:
            vec[slug] = round(min(1.0, hits / len(entry["tokens"])), 3)
    for slug, w in (specializations or {}).items():
        vec[slug] = max(vec.get(slug, 0.0), w)
    return vec


def cosine(a: dict[str, float], b: dict[str, float]) -> float:
    common = set(a) & set(b)
    if not common:
        return 0.0
    dot = sum(a[k] * b[k] for k in common)
    return dot / (math.sqrt(sum(v * v for v in a.values())) * math.sqrt(sum(v * v for v in b.values())))


def fuse(*rankings: list[str], k: int = 60) -> dict[str, float]:
    """Reciprocal rank fusion: each list is ids best-first; a missing id contributes nothing from that list."""
    out: dict[str, float] = {}
    for ranking in rankings:
        for pos, key in enumerate(ranking):
            out[key] = out.get(key, 0.0) + 1.0 / (k + pos + 1)
    return out


def name_of(session_index_slug: str) -> str:
    return (_index[1].get(session_index_slug, {}).get("name") if _index else None) or session_index_slug.replace("-", " ")
