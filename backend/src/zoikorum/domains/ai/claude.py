"""The one way the built-in AI features call Claude (Engineering Handbook 14.3 "no unregistered production prompt", 21.4
circuit breakers).

* Every built-in prompt is registered in ``BUILT_IN`` with its version, owner, golden tests and rollback plan, and is
  listed to AI Safety Reviewers (GET /v1/ai/prompts/built-in).
* A prompt can be switched off without a release (ZK_AI_DISABLED_PROMPTS): its feature falls back to its non-AI rules.
* All calls share one circuit breaker, so a Claude outage makes features fall back at once instead of waiting.
* Every call is written to ``ai.inference_logs`` when the caller passes its session: prompt and version, model, a hash
  of the input (never the input itself), the answer, latency and whether the feature fell back.

Callers get the parsed answer or ``None`` and must then use their non-AI rules: AI never breaks a feature.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
import uuid
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from zoikorum.config import get_settings
from zoikorum.shared.circuit import CircuitBreaker
from zoikorum.shared.metrics import AI_CALLS

log = logging.getLogger("zoikorum.ai")


@dataclass(frozen=True)
class BuiltInPrompt:
    key: str
    version: int
    purpose: str
    owner: str
    golden_tests: str  # where the golden set lives; run with a real key before changing the prompt or the model
    fallback: str  # what the feature does without AI: also the rollback plan

    @property
    def label(self) -> str:
        return f"{self.key}-{self.version}"


BUILT_IN: dict[str, BuiltInPrompt] = {p.key: p for p in (
    BuiltInPrompt("search-intent", 1, "Turn a buyer's own words into search filters the buyer then reviews",
                  "Search", "tests/golden/search_intent.json", "Keyword rules (ai/intent.py keyword_intent)"),
    BuiltInPrompt("document-check", 1, "First look at an uploaded verification file for the reviewer; never a decision",
                  "Verification", "tests/golden/document_check.json", "No automatic check: the reviewer looks at the file"),
    BuiltInPrompt("spec-match", 1, "Match a professional's description of their work to the specialization catalog",
                  "Marketplace", "tests/golden/spec_match.json", "Keyword matching (ai/specializations.py keyword_match)"),
)}


@lru_cache
def breaker() -> CircuitBreaker:
    s = get_settings()
    return CircuitBreaker("AI assistant", s.provider_breaker_failures, s.provider_breaker_reset_seconds)


def available(prompt: BuiltInPrompt) -> bool:
    s = get_settings()
    return s.ai_provider == "anthropic" and bool(s.anthropic_api_key) and prompt.key not in s.ai_disabled_prompts


def input_hash(*parts: Any) -> str:
    raw = json.dumps(parts, default=str, sort_keys=True, ensure_ascii=False).encode()
    return hashlib.sha256(raw).hexdigest()


async def parse(prompt: BuiltInPrompt, output_format: type[BaseModel], *, input_sha256: str, timeout: float,
                session: AsyncSession | None = None, subject_id: uuid.UUID | None = None,
                requested_by: uuid.UUID | None = None, **request: Any) -> BaseModel | None:
    """``messages.parse`` for a registered prompt. Returns the parsed answer, or None when the feature must fall back
    (switched off, no key, package missing, outage, open circuit, refusal, no usable answer). Never raises."""
    if not available(prompt):
        return None
    if session is not None:
        from zoikorum.domains.admin import facade as admin_facade

        if await admin_facade.is_paused(session, "AI_ASSIST"):
            return None  # staff switched AI assistance off: the feature uses its non-AI rules
    s = get_settings()
    started = time.monotonic()
    answer: BaseModel | None = None
    try:
        import anthropic  # optional dependency: only needed when an API key is configured

        async def call():
            async with anthropic.AsyncAnthropic(api_key=s.anthropic_api_key, timeout=timeout, max_retries=1) as client:
                return await client.messages.parse(model=s.ai_model, output_format=output_format, **request)

        response = await breaker().acall(call)
        if response.stop_reason == "refusal" or response.parsed_output is None:
            outcome = "no answer" if response.stop_reason != "refusal" else "refused"
        else:
            answer, outcome = response.parsed_output, "answered"
    except ImportError:
        outcome = "anthropic package not installed"
    except Exception as exc:  # noqa: BLE001 - network, rate limit, auth, server errors, open circuit
        outcome = f"failed: {type(exc).__name__}"
    latency = round((time.monotonic() - started) * 1000)
    AI_CALLS.labels(prompt.key, outcome.split(":")[0]).inc()
    log.info("ai call prompt=%s model=%s outcome=%s latency_ms=%d", prompt.label, s.ai_model, outcome, latency)
    if session is not None:
        from zoikorum.domains.ai.models import InferenceLog

        session.add(InferenceLog(
            prompt_version=prompt.version, model=s.ai_model, input_sha256=input_sha256, purpose=prompt.key,
            output=answer.model_dump_json() if answer is not None else f"[{outcome}]",
            subject_id=subject_id, requested_by=requested_by, latency_ms=latency, fallback_used=answer is None))
    return answer
