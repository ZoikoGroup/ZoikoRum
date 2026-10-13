"""Golden sets for the built-in prompts (Engineering Handbook 14.3-14.4), run against the real model.

Skipped by default: they cost money and need a key. Run them before changing a prompt, its version or ZK_AI_MODEL:

    ZK_LIVE_AI_TESTS=1 ZK_AI_PROVIDER=anthropic ZK_ANTHROPIC_API_KEY=... pytest tests/test_ai_golden.py -m unit

Each case states the least the answer must get right (and, for prompt-injection cases, what it must not do), so a
better answer still passes.
"""

from __future__ import annotations

import io
import json
import os
from pathlib import Path

import pytest

from test_taxonomy_suggestions import catalog
from zoikorum.config import get_settings
from zoikorum.domains.ai import claude, documents, intent, specializations

GOLDEN = Path(__file__).resolve().parent / "golden"
live = pytest.mark.skipif(
    os.environ.get("ZK_LIVE_AI_TESTS") != "1" or not get_settings().anthropic_api_key
    or get_settings().ai_provider != "anthropic",
    reason="live AI tests are off (set ZK_LIVE_AI_TESTS=1 with an Anthropic key)")


def cases(name: str):
    return json.loads((GOLDEN / name).read_text(encoding="utf-8"))


def png(spec: dict) -> bytes:
    from PIL import Image, ImageDraw

    if "blank" in spec:
        image = Image.new("RGB", (800, 500), spec["blank"])
    else:
        image = Image.new("RGB", (800, 500), "white")
        ImageDraw.Draw(image).multiline_text((40, 40), spec["text"], fill="black", font_size=32, spacing=12)
    out = io.BytesIO()
    image.save(out, "PNG")
    return out.getvalue()


@pytest.mark.unit
@live
@pytest.mark.parametrize("case", cases("search_intent.json"), ids=lambda c: c["input"][:40])
async def test_search_intent(case):
    i = await intent.extract_search_intent(case["input"], catalog())
    want = case["expect"]
    assert i.source.endswith(intent.PROMPT_VERSION), "fell back to keyword rules: the call failed"
    if "specializationsAnyOf" in want:
        assert set(i.specializations) & set(want["specializationsAnyOf"]), i
    if "specializations" in want:
        assert list(i.specializations) == want["specializations"], i
    for field, attr in (("engagementType", "engagement_type"), ("jurisdiction", "jurisdiction"),
                        ("availability", "availability"), ("delivery", "delivery")):
        if field in want:
            assert getattr(i, attr) == want[field], (field, i)
    assert set(want.get("verifiedIncludes", [])) <= set(i.verified), i


@pytest.mark.unit
@live
@pytest.mark.parametrize("case", cases("spec_match.json"), ids=lambda c: c["input"][:40])
async def test_spec_match(case):
    known = {e.slug for e in catalog()}
    m = await specializations.match_specializations(case["input"], catalog())
    want = case["expect"]
    assert set(m.slugs) <= known  # never an invented slug
    if "slugsAnyOf" in want:
        assert set(m.slugs) & set(want["slugsAnyOf"]), m
    if "slugs" in want:
        assert list(m.slugs) == want["slugs"], m
    if want.get("draft"):
        assert m.draft is not None, m


@pytest.mark.unit
@live
@pytest.mark.parametrize("case", cases("document_check.json"), ids=lambda c: c["requested"][:30])
async def test_document_check(case):
    result = await documents.assess_document(png(case["image"]), "image/png", case["requested"])
    assert result.source.endswith(documents.PROMPT_VERSION), result
    assert result.verdict in case["expect"]["verdictIn"], result


@pytest.mark.unit
def test_golden_sets_cover_every_built_in_prompt():
    assert {Path(p.golden_tests).name for p in claude.BUILT_IN.values()} == {f.name for f in GOLDEN.glob("*.json")}
