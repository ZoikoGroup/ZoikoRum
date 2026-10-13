# ADR-012: Built-in AI prompts registered in code

**Status:** Accepted  
**Date:** 2026-10-13

## Context

The handbook allows no unregistered production prompt (14.3). Three features call Claude: describe-what-you-need search, the first look at verification documents, and specialization matching. Their prompts are tied to the feature's code and output schema.

## Decision

They are registered in `domains/ai/claude.py` (`BUILT_IN`: key, version, purpose, owner, golden set, fallback) and change only through code review, with golden sets in `tests/golden/` run against the real model (`tests/test_ai_golden.py`). Each can be switched off without a release (`ZK_AI_DISABLED_PROMPTS`), all share one circuit breaker, and every call is logged in `ai.inference_logs` with a hash of the input, never the input. Admin-authored assistant prompts keep the database registry with AI Safety Reviewer approval.

## Consequences

Prompt and parsing code change and are reviewed together; rollback is a switch or a revert. Golden sets need a real key and cost money, so they run before a prompt or model change, not in every CI run.

## Alternatives considered

Keeping these prompts in the database registry (a database edit could break the feature's output parsing).
