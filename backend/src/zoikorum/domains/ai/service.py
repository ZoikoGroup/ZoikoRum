from __future__ import annotations
import hashlib
import time
import uuid
from sqlalchemy import select
from zoikorum.domains.ai.models import InferenceLog, PromptVersion
from zoikorum.domains.ai import providers
from zoikorum.config import get_settings
from zoikorum.shared.events import record_event
from zoikorum.shared.event_catalog import E
from zoikorum.shared.errors import Conflict, NotFound, ValidationFailed
from zoikorum.shared.crypto import canonical_json

DISCLAIMER = "Advisory assistance only. Verify against the source documents. This output does not approve terms, execute a contract, release funds or decide a dispute."
PURPOSES = {"proposal-draft", "contract-summary", "dispute-summary", "match-intent"}


async def infer(session, actor_id, purpose, subject_id, facts, fallback):
    started = time.monotonic()
    settings = get_settings()
    model = settings.ai_model if settings.ai_provider == "anthropic" else "offline:v1"
    prompt = await session.scalar(select(PromptVersion).where(PromptVersion.prompt_key == purpose,
        PromptVersion.status == "APPROVED", PromptVersion.target_model == model).order_by(PromptVersion.version.desc()).limit(1))
    output, fallback_used = fallback, True
    if prompt and (settings.ai_provider == "offline" or (settings.ai_provider == "anthropic" and settings.anthropic_api_key)):
        try:
            output = await providers.provider().generate(prompt.instructions, canonical_json(facts).decode())
            if not output.strip():
                raise ValueError("Empty provider output")
            fallback_used = False
        except Exception:
            output = fallback
    log = InferenceLog(prompt_id=prompt.id if prompt else None, prompt_version=prompt.version if prompt else None,
        model=model if not fallback_used else "fallback:deterministic:v1", input_sha256=hashlib.sha256(canonical_json(facts)).hexdigest(),
        output=output, purpose=purpose, subject_id=subject_id, requested_by=actor_id,
        latency_ms=round((time.monotonic() - started) * 1000), fallback_used=fallback_used)
    session.add(log); await session.flush()
    record_event(session, E.AI_OUTPUT_GENERATED, aggregate_type="InferenceLog", aggregate_id=log.id,
                 payload={"inferenceId": log.id, "purpose": purpose, "subjectId": subject_id, "promptVersion": log.prompt_version,
                          "model": log.model, "fallbackUsed": fallback_used, "inputHash": log.input_sha256})
    return {"text": output, "disclaimer": DISCLAIMER, "model": log.model, "promptVersion": log.prompt_version,
            "fallbackUsed": fallback_used, "inferenceId": str(log.id)}


def prompt_out(p):
    return {"id": str(p.id), "promptKey": p.prompt_key, "version": p.version, "owner": str(p.owner), "targetModel": p.target_model,
            "instructions": p.instructions, "goldenTests": p.golden_tests, "status": p.status, "approvedBy": str(p.approved_by) if p.approved_by else None}


async def create_prompt(session, actor, body):
    from zoikorum.domains.admin import facade as admin
    from zoikorum.domains.identity import facade as identity
    from zoikorum.shared.auth import PlatformRole
    from zoikorum.shared.errors import Forbidden
    actor.require_platform_role(PlatformRole.AI_SAFETY_REVIEWER); actor.require_step_up()
    if PlatformRole.AI_SAFETY_REVIEWER not in await identity.live_platform_roles(session, actor.identity_id):
        raise Forbidden("Requires live AI Safety Reviewer authority")
    from sqlalchemy import text
    await session.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"), {"key": f"prompt:{body.promptKey}"})
    latest = await session.scalar(select(PromptVersion.version).where(PromptVersion.prompt_key == body.promptKey).order_by(PromptVersion.version.desc()).limit(1)) or 0
    p = PromptVersion(prompt_key=body.promptKey, version=latest + 1, owner=actor.identity_id, target_model=body.targetModel,
                      instructions=body.instructions, golden_tests=[t.model_dump() for t in body.goldenTests])
    session.add(p); await session.flush()
    return prompt_out(p)


async def approve_prompt(session, actor, prompt_id):
    from zoikorum.domains.identity import facade as identity
    from zoikorum.shared.auth import PlatformRole
    from zoikorum.shared.errors import Forbidden
    actor.require_platform_role(PlatformRole.AI_SAFETY_REVIEWER); actor.require_step_up()
    if PlatformRole.AI_SAFETY_REVIEWER not in await identity.live_platform_roles(session, actor.identity_id):
        raise Forbidden("Requires live AI Safety Reviewer authority")
    p = await session.get(PromptVersion, prompt_id, with_for_update=True)
    if not p:
        raise NotFound("Prompt version not found")
    if p.status != "DRAFT":
        raise Conflict("Only a draft prompt can be approved")
    model = get_settings().ai_model if get_settings().ai_provider == "anthropic" else "offline:v1"
    if p.target_model != model:
        raise ValidationFailed("Configure the target provider/model before validating this prompt")
    if get_settings().ai_provider == "anthropic" and not get_settings().anthropic_api_key:
        raise Conflict("Configure the provider credentials before approving this prompt", code="AI_PROVIDER_UNAVAILABLE")
    for test in p.golden_tests:
        try:
            result = await providers.provider().generate(p.instructions, test["input"])
        except Exception as exc:
            raise Conflict("The provider could not validate golden tests; the prompt remains unapproved", code="AI_PROVIDER_UNAVAILABLE") from exc
        if not all(word.casefold() in result.casefold() for word in test["mustContain"]):
            raise Conflict("Golden tests failed; prompt remains unapproved", code="PROMPT_TEST_FAILED")
    p.status, p.approved_by = "APPROVED", actor.identity_id
    record_event(session, E.PROMPT_VERSION_ACTIVATED, aggregate_type="PromptVersion", aggregate_id=p.id,
        payload={"promptKey": p.prompt_key, "version": p.version, "approvedBy": actor.identity_id, "targetModel": p.target_model})
    return prompt_out(p)
