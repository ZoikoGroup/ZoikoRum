from __future__ import annotations
import asyncio
import hashlib
import json
import re
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
PURPOSES = {"proposal-draft", "contract-summary", "dispute-summary", "match-intent", "assistant-chat"}
CHAT_FALLBACK = (
    "I can only give general guidance right now because the AI model is unavailable. "
    "You can still browse Zoikorum normally or open the Help Center."
)
CHAT_UNHELPFUL = (
    "I could not answer that reliably. Try rephrasing the question, or open the Help Center for published guidance."
)
CHAT_INTENTS = {
    "enterprise_discovery", "professional_onboarding", "trust_verification", "contracts_milestones",
    "protected_payments", "pricing_public", "disputes_public", "support_handoff", "account_help", "general",
}
CHAT_INSTRUCTIONS = (
    "You are the Zoikorum AI Concierge for a governed professional-services marketplace. "
    "Explain how Zoikorum works: finding professionals, requests and briefs, proposals, contracts, milestones, "
    "protected payments, delivery, reviews, verification, disputes, pricing and account help. "
    "Answer safe general-knowledge questions too, briefly and accurately, even when they are not about Zoikorum. "
    "You advise only: never claim to approve, verify, sign, release funds, decide a dispute or view someone's "
    "private account, and never invent prices, policies, certifications or personal facts. "
    "Reply with one JSON object only, no code fences:\n"
    '{"intent":"one intent key","answer":"the direct answer in one or two sentences",'
    '"sections":[{"title":"short title","items":["short point","short point"]}],'
    '"suggestions":["follow-up question","follow-up question"],'
    '"limitations":"one sentence on what you cannot do"}\n'
    "intent keys: enterprise_discovery, professional_onboarding, trust_verification, contracts_milestones, "
    "protected_payments, pricing_public, disputes_public, support_handoff, account_help, general.\n"
    "Style: plain American English, practical, specific, no markdown, no marketing superlatives. Put the direct "
    "answer first. Use at most one section with two short items, or no section when one sentence is enough. Give "
    "two short follow-up questions in the user's voice in the suggestions field only; never add a questions "
    "section or repeat the suggestions in sections. Keep the whole reply under 70 words."
)
RELATED_PAGES = {
    "enterprise_discovery": [("Browse professionals", "/professionals"), ("Help Center", "/app/help")],
    "professional_onboarding": [("Trust & Safety Charter", "/legal/trust-and-safety"), ("Help Center", "/app/help")],
    "trust_verification": [("Trust & Safety Charter", "/legal/trust-and-safety"), ("Help Center", "/app/help")],
    "contracts_milestones": [("Terms of Service", "/legal/terms"), ("Help Center", "/app/help")],
    "protected_payments": [("Terms of Service", "/legal/terms"), ("Help Center", "/app/help")],
    "pricing_public": [("Help Center", "/app/help"), ("Contact options", "/app/help")],
    "disputes_public": [("Trust & Safety Charter", "/legal/trust-and-safety"), ("Help Center", "/app/help")],
    "support_handoff": [("Help Center", "/app/help"), ("Browse professionals", "/professionals")],
    "account_help": [("Help Center", "/app/help"), ("Security settings", "/app/security")],
    "general": [("Help Center", "/app/help"), ("Privacy Policy", "/legal/privacy")],
}
CHAT_SUGGESTIONS = [
    "How do I find the right professional?",
    "How are payments protected?",
    "How does verification work?",
]
GREETING_RE = re.compile(
    r"^(?:hi|hello|hey|hiya|greetings|good (?:morning|afternoon|evening))"
    r"(?:\s+(?:there|zoikorum))?[\s!.,?]*$",
    re.IGNORECASE,
)
GREETING_REPLY = {
    "intent": "general",
    "answer": ("Hi! I'm the Zoikorum AI Concierge. Ask me about finding professionals, proposals, contracts, "
               "protected payments, verification or disputes."),
    "sections": [{"title": "What I can help with", "items": [
        "Finding and comparing professionals", "Requests, proposals and contracts",
        "Protected payments, milestones and delivery", "Verification, reviews and disputes"]}],
    "suggestions": CHAT_SUGGESTIONS,
    "limitations": "I can explain published information only and cannot approve, verify, execute or decide anything.",
}
# Curated answers to the questions people ask most, served without the local model so they are instant.
# Wording follows the Help Center; the model still handles everything else.
FAQ_REPLIES = [
    {
        "pattern": re.compile(
            r"\b(?:join (?:zoikorum )?as a professional|become a professional|professional onboarding|"
            r"create a professional account|publish my profile)\b", re.I),
        "intent": "professional_onboarding",
        "answer": ("Create a professional account, complete identity and credential verification, then publish your "
                   "profile and offerings. A verification provider or compliance reviewer checks the evidence; AI "
                   "never decides a verification outcome."),
        "sections": [("Joining as a professional", [
            "Sign up, then complete identity and credential checks.",
            "Publish your profile, services and availability once verified.",
            "Requests and proposals appear in your dashboard."])],
        "suggestions": ["What does a Trust Tier mean?", "How does verification work?",
                        "How do requests and proposals work?"],
    },
    {
        "pattern": re.compile(
            r"\b(?:escrow|protected payments?|payments? (?:are )?protected|payment protection|"
            r"how (?:are|do) (?:payments?|funds?) (?:protected|released)|"
            r"when (?:is|does|do) .{0,30}(?:get paid|paid)|release (?:the |a )?(?:payment|funds)|"
            r"held in escrow)\b", re.I),
        "intent": "protected_payments",
        "answer": ("Professionals are paid only after the buyer accepts a milestone. Until then the funds stay in "
                   "escrow for that engagement and are released milestone by milestone."),
        "sections": [("How escrow works", [
            "The buyer funds a milestone before work starts.",
            "Funds stay held until the buyer accepts the delivered work.",
            "A dispute freezes the affected milestone funds until it is resolved."])],
        "suggestions": ["Does Zoikorum store my card?", "What happens if a dispute is raised?",
                        "When does work start?"],
    },
    {
        "pattern": re.compile(
            r"\b(?:store my card|save my card|card details|store my payment|payment method|"
            r"is zoikorum a bank|hold a balance)\b", re.I),
        "intent": "protected_payments",
        "answer": ("Zoikorum stores only a token from the payment partner, never your full card details. It is not a "
                   "bank and holds no balance for you."),
        "sections": [("Card and payment details", [
            "Card data is handled by the payment partner and tokenised.",
            "Zoikorum keeps the token, not the card number.",
            "Escrow funds belong to the engagement, not a Zoikorum balance."])],
        "suggestions": ["How are payments protected?", "How does milestone funding work?",
                        "Terms of Service"],
    },
    {
        "pattern": re.compile(
            r"\b(?:reset (?:my )?password|forgot (?:my )?password|password reset|lost password)\b", re.I),
        "intent": "account_help",
        "answer": ("Use the Forgot your password? link on the sign-in page to get a reset email. If it does not "
                   "arrive, check your spam folder and then contact support from the Help Center."),
        "sections": [("Resetting your password", [
            "Choose Forgot your password? on the sign-in page.",
            "Open the reset link sent to your email address.",
            "Contact support if the email does not arrive."])],
        "suggestions": ["How do I turn on two-step verification?", "How do I contact support?",
                        "How do I get or delete my data?"],
    },
    {
        "pattern": re.compile(
            r"\b(?:two-step|two step|2fa|authenticator|security settings|sign in|sign-in|"
            r"password|delete my data|get my data|privacy)\b", re.I),
        "intent": "account_help",
        "answer": ("Turn on two-step verification in Settings → Security; admin roles must use it. Use Settings → "
                   "Privacy & data to get or delete your data."),
        "sections": [("Account and security", [
            "Two-step verification lives in Settings → Security.",
            "Admin roles must keep two-step verification on.",
            "Privacy & data handles export and deletion requests."])],
        "suggestions": ["How do I contact support?", "How do I add a colleague?",
                        "Privacy Policy"],
    },
    {
        "pattern": re.compile(
            r"\b(?:verification|verified professional|trust tier|trust score|who verifies|"
            r"how does verification work|get verified)\b", re.I),
        "intent": "trust_verification",
        "answer": ("A verification provider or a compliance reviewer checks identity, credentials and eligibility; "
                   "AI never decides a verification outcome."),
        "sections": [("Trust Tiers", [
            "Tier A: identity, credentials and eligibility verified.",
            "Tier B: identity verified and restrictions clear.",
            "Tier C: verification not complete."])],
        "suggestions": ["Why can't I see a trust score?", "How do I join as a professional?",
                        "How does search rank professionals?"],
    },
    {
        "pattern": re.compile(
            r"\b(?:find (?:a |the )?(?:right )?professionals?|choose (?:a |the )?professional|"
            r"compare professionals?|search (?:for )?professionals?|how do i find|how can my company find|"
            r"search rank)\b", re.I),
        "intent": "enterprise_discovery",
        "answer": ("Search results are ranked by relevance to your words, then verification, availability and fit. "
                   "Nobody can pay to rank higher, and each result shows why it matched."),
        "sections": [("Finding and comparing", [
            "Use filters for service, location, availability and Trust Tier.",
            "Compare up to three professionals side by side.",
            "Open a profile or result to request a proposal."])],
        "suggestions": ["What does a Trust Tier mean?", "How do I ask for a proposal?",
                        "How do requests and proposals work?"],
    },
    {
        "pattern": re.compile(r"\bnda\b", re.I),
        "intent": "contracts_milestones",
        "answer": "Yes. A request can require an NDA before the professional sees its details.",
        "sections": [("NDAs", [
            "The requirement is set on the request.",
            "The professional accepts before seeing the brief.",
            "The acceptance is recorded with the engagement."])],
        "suggestions": ["How do I ask for a proposal?", "Can the terms change after signing?",
                        "When does work start?"],
    },
    {
        "pattern": re.compile(
            r"\b(?:proposal|ask for a proposal|request proposal|send a request|"
            r"how do (?:requests|proposals) work)\b", re.I),
        "intent": "contracts_milestones",
        "answer": ("Open a verified professional's profile or a search result and choose Request proposal. Describe "
                   "the work, deliverables and budget; the professional answers with a proposal you can compare, "
                   "revise or accept."),
        "sections": [("Requests and proposals", [
            "A request describes the work, deliverables and budget.",
            "The professional replies with a structured proposal.",
            "You can compare, revise or accept before a contract exists."])],
        "suggestions": ["Can I require an NDA?", "Can the terms change after signing?",
                        "When does work start?"],
    },
    {
        "pattern": re.compile(
            r"\b(?:cancel (?:a |the |my )?(?:contract|engagement)|end (?:a |the |my )?(?:contract|engagement)|"
            r"terminate (?:a |the |my )?(?:contract|engagement)|termination)\b", re.I),
        "intent": "contracts_milestones",
        "answer": ("If no money is held in escrow, the professional or the buyer's requester or approver can end the "
                   "engagement directly. If funds are held, send the other side a request to end it by agreement; "
                   "they can agree, decline, or let it lapse, and an open dispute decides how it ends."),
        "sections": [("Ending an engagement", [
            "No escrow funds: the authorised side can end it directly.",
            "Funds held: the other side must agree to the termination request.",
            "An open dispute decides how the engagement ends."])],
        "suggestions": ["What happens in a dispute?", "How are payments protected?",
                        "Can the terms change after signing?"],
    },
    {
        "pattern": re.compile(
            r"\b(?:contract|change order|terms change|when does work start|milestones?|"
            r"engagement terms)\b", re.I),
        "intent": "contracts_milestones",
        "answer": ("Work starts after the contract is signed and the first milestone is funded. Terms change only "
                   "through a versioned change order that both parties accept."),
        "sections": [("Contracts and milestones", [
            "Each milestone has an amount and a due date.",
            "The buyer funds a milestone before work on it starts.",
            "Change orders keep every accepted revision on record."])],
        "suggestions": ["How are payments protected?", "When is the professional paid?",
                        "What happens in a dispute?"],
    },
    {
        "pattern": re.compile(
            r"\b(?:dispute|disagreement|something went wrong|problem with (?:the )?(?:work|delivery)|"
            r"refund)\b", re.I),
        "intent": "disputes_public",
        "answer": ("If something goes wrong on a funded milestone, raise a dispute from the engagement. The "
                   "milestone's funds are frozen while a mediator reviews the evidence, and direct messages move "
                   "to the dispute thread."),
        "sections": [("When something goes wrong", [
            "Raise the dispute from the affected engagement.",
            "The affected milestone funds are frozen.",
            "A mediator reviews the evidence and records a decision."])],
        "suggestions": ["How are payments protected?", "How do I contact support?",
                        "Trust & Safety Charter"],
    },
    {
        "pattern": re.compile(
            r"\b(?:platform fee|fees?|commission|how much (?:does|do) (?:zoikorum|you) charge|"
            r"pricing|cost)\b", re.I),
        "intent": "pricing_public",
        "answer": ("The price for the work is agreed in the proposal and contract, and any platform fee is shown "
                   "there before you commit. Zoikorum does not add hidden charges."),
        "sections": [("Pricing", [
            "Professionals set their own proposal price.",
            "Any platform fee is displayed before signing.",
            "Escrow funding follows the agreed milestones."])],
        "suggestions": ["How are payments protected?", "How do I ask for a proposal?",
                        "Terms of Service"],
    },
    {
        "pattern": re.compile(
            r"\b(?:contact support|get help|help & support|help and support|customer service|"
            r"talk to (?:a )?human|contact us|how do i contact)\b", re.I),
        "intent": "support_handoff",
        "answer": ("Open Help & Support in the app to search answers or send a help request; we reply within one "
                   "business day. For disagreements about delivered work, raise a dispute from the engagement "
                   "instead."),
        "sections": [("Getting help", [
            "Search the Help Center for common answers.",
            "Send a help request with the page or error reference.",
            "Raise a dispute for problems with delivered work."])],
        "suggestions": ["What happens in a dispute?", "How do I turn on two-step verification?",
                        "How do I get or delete my data?"],
    },
    {
        "pattern": re.compile(
            r"\b(?:organisation|organization|add a colleague|team member|spending approval|"
            r"spend limit|who can approve)\b", re.I),
        "intent": "account_help",
        "answer": ("Approvers can approve spending up to their spend limit, and requesters cannot approve their own "
                   "requests. Org Admins invite members and assign roles from Organisation → Members & access."),
        "sections": [("Organisation and access", [
            "Org Admins manage members and roles.",
            "Approvers work within their spend limit.",
            "Requesters cannot approve their own requests."])],
        "suggestions": ["How do I turn on two-step verification?", "How do I contact support?",
                        "How do I get or delete my data?"],
    },
]
CHAT_CACHE: dict[str, tuple[float, dict, str]] = {}
CHAT_CACHE_TTL_SECONDS = 600
CHAT_CACHE_MAX = 200


async def _ollama_chat(settings, message: str) -> str:
    """Local model through Ollama's chat API, so the assistant answers without an external API key."""
    import httpx

    async with httpx.AsyncClient(timeout=120) as client:
        response = await client.post(f"{settings.ollama_url.rstrip('/')}/api/chat", json={
            "model": settings.ollama_model,
            "messages": [{"role": "system", "content": CHAT_INSTRUCTIONS},
                         {"role": "user", "content": message}],
            "stream": False,
            "format": "json",
            "keep_alive": "30m",
            "options": {"temperature": 0.2, "num_predict": 300},
        })
        response.raise_for_status()
        return ((response.json().get("message") or {}).get("content") or "").strip()


def _clean(value, limit: int = 500) -> str:
    return " ".join(str(value or "").split())[:limit]


def _is_greeting(message: str) -> bool:
    return bool(GREETING_RE.match(" ".join(message.split())))


def _normalize_chat(raw: str) -> dict:
    """Validate the model's JSON contract; degrade gracefully to the raw text if it is not JSON."""
    text = raw.strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = text[text.find("\n") + 1:] if "\n" in text else text
    data = {}
    start, end = raw.find("{"), raw.rfind("}")
    if start >= 0 and end > start:
        try:
            data = json.loads(raw[start:end + 1])
        except json.JSONDecodeError:
            data = {}
    if not isinstance(data, dict):
        data = {}
    answer = _clean(data.get("answer") or data.get("text") or raw, 1200)
    if re.fullmatch(r"<[^>]*>", answer):
        answer = ""
    intent = data.get("intent") if data.get("intent") in CHAT_INTENTS else "general"
    sections = []
    for section in data.get("sections") or []:
        if not isinstance(section, dict):
            continue
        title = _clean(section.get("title"), 80)
        items = [_clean(item, 280) for item in (section.get("items") or []) if _clean(item, 280)]
        if title and items:
            sections.append({"title": title, "items": items[:4]})
        if len(sections) == 3:
            break
    suggestions = [_clean(item, 140) for item in (data.get("suggestions") or []) if _clean(item, 140)]
    suggestions = suggestions[:3] or CHAT_SUGGESTIONS[:2]
    limitations = _clean(data.get("limitations"), 260) or (
        "I can explain published information only and cannot approve, verify, execute or decide anything.")
    return {
        "intent": intent,
        "answer": answer or CHAT_UNHELPFUL,
        "sections": sections,
        "suggestions": suggestions,
        "limitations": limitations,
        "related": [{"label": label, "to": to} for label, to in RELATED_PAGES.get(intent, RELATED_PAGES["general"])],
    }


def _match_faq(message: str):
    return next((entry for entry in FAQ_REPLIES if entry["pattern"].search(message)), None)


def _curated_reply(entry: dict) -> dict:
    return {
        "intent": entry["intent"],
        "answer": entry["answer"],
        "sections": [{"title": title, "items": list(items)} for title, items in entry["sections"]],
        "suggestions": list(entry["suggestions"]),
        "limitations": "I can explain published information only and cannot approve, verify, execute or decide anything.",
        "related": [{"label": label, "to": to}
                    for label, to in RELATED_PAGES.get(entry["intent"], RELATED_PAGES["general"])],
    }


def _fallback_chat() -> dict:
    return {
        "intent": "general",
        "answer": CHAT_FALLBACK,
        "sections": [{"title": "What I can help with", "items": [
            "Finding and comparing professionals", "Requests, proposals and contracts",
            "Protected payments, milestones and delivery", "Verification, reviews and disputes"]}],
        "suggestions": CHAT_SUGGESTIONS,
        "limitations": "AI assistance is offline; I cannot access your account or take any action.",
        "related": [{"label": label, "to": to} for label, to in RELATED_PAGES["general"]],
    }


async def chat(session, actor_id, message: str):
    started = time.monotonic()
    settings = get_settings()
    facts = {"message": message[:4000]}
    faq = _match_faq(message)
    if _is_greeting(message):
        payload = {**GREETING_REPLY, "related": [{"label": label, "to": to}
                                                 for label, to in RELATED_PAGES["general"]]}
        model, fallback_used = "deterministic:greeting:v1", False
    elif faq:
        payload, model, fallback_used = _curated_reply(faq), "deterministic:faq:v1", False
    else:
        key = " ".join(message.lower().split())
        cached = CHAT_CACHE.get(key)
        if cached and time.monotonic() - cached[0] < CHAT_CACHE_TTL_SECONDS:
            payload, model, fallback_used = cached[1], cached[2], cached[3]
        else:
            fallback_used = True
            payload = _fallback_chat()
            for attempt in range(2):
                try:
                    if settings.ai_provider == "anthropic" and settings.anthropic_api_key:
                        raw = await providers.provider().generate(CHAT_INSTRUCTIONS, message[:4000])
                        model = settings.ai_model
                    else:
                        raw = await _ollama_chat(settings, message[:4000])
                        model = f"ollama:{settings.ollama_model}"
                    if not raw.strip():
                        raise ValueError("Empty provider output")
                    payload = _normalize_chat(raw)
                    fallback_used = False
                    break
                except Exception:
                    if attempt == 0:
                        await asyncio.sleep(0.8)
            if fallback_used:
                payload, model = _fallback_chat(), "fallback:deterministic:v1"
            else:
                if len(CHAT_CACHE) >= CHAT_CACHE_MAX:
                    CHAT_CACHE.pop(next(iter(CHAT_CACHE)))
                CHAT_CACHE[key] = (time.monotonic(), payload, model, fallback_used)
    output = json.dumps({
        "intent": payload["intent"],
        "answerSha256": hashlib.sha256(payload["answer"].encode("utf-8")).hexdigest(),
        "answerLength": len(payload["answer"]),
        "sectionCount": len(payload["sections"]),
        "suggestionCount": len(payload["suggestions"]),
        "redacted": True,
    }, ensure_ascii=False)
    log = InferenceLog(prompt_id=None, prompt_version=None,
        model=model if not fallback_used else "fallback:deterministic:v1",
        input_sha256=hashlib.sha256(canonical_json(facts)).hexdigest(), output=output, purpose="assistant-chat",
        subject_id=None, requested_by=actor_id, latency_ms=round((time.monotonic() - started) * 1000),
        fallback_used=fallback_used)
    session.add(log); await session.flush()
    record_event(session, E.AI_OUTPUT_GENERATED, aggregate_type="InferenceLog", aggregate_id=log.id,
                 payload={"inferenceId": log.id, "purpose": "assistant-chat", "subjectId": None,
                          "promptVersion": None, "model": log.model, "fallbackUsed": fallback_used,
                          "inputHash": log.input_sha256})
    return {"answerId": str(log.id), **payload, "text": payload["answer"], "disclaimer": DISCLAIMER,
            "model": log.model, "fallbackUsed": fallback_used, "inferenceId": str(log.id)}


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
    from zoikorum.shared.capabilities import Cap, capabilities_for
    from zoikorum.shared.errors import Forbidden
    actor.require_capability(Cap.AI_PROMPTS_MANAGE); actor.require_step_up()
    if Cap.AI_PROMPTS_MANAGE not in capabilities_for(await identity.live_platform_roles(session, actor.identity_id)):
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
    from zoikorum.shared.capabilities import Cap, capabilities_for
    from zoikorum.shared.errors import Forbidden
    actor.require_capability(Cap.AI_PROMPTS_MANAGE); actor.require_step_up()
    if Cap.AI_PROMPTS_MANAGE not in capabilities_for(await identity.live_platform_roles(session, actor.identity_id)):
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
