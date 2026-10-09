"""Hosted identity verification, authenticated receipts and human review for negative results.

Partners (``ZK_VERIFICATION_PROVIDER``): ``persona``, ``veriff``, and ``simulated`` (development only: the page offers the
answers a partner can give). Every partner answer goes through ``apply_result``:

    approved                -> verified automatically (a positive provider result)
    declined / failed       -> a compliance officer decides (a negative result is never final on its own)
    needs_review, completed -> a compliance officer decides
    resubmission_requested  -> more information needed: the professional starts a new hosted session
    submitted               -> in review while the partner decides
    abandoned               -> nothing changes: the professional can start again
Receipts are signed and stored once (``ProviderEvent``); late or repeated answers never undo a result or a human decision.
"""
import hashlib
import hmac
import json

from sqlalchemy import select

from zoikorum.config import DEV_ENVS, get_settings
from zoikorum.domains.verification import service
from zoikorum.domains.verification.models import ProviderSession, ProviderEvent
from zoikorum.domains.verification.providers import PersonaProvider, SimulatedProvider, VERIFF_STATUS, VeriffProvider
from zoikorum.shared import clock
from zoikorum.shared.errors import NotFound, Unauthenticated, ValidationFailed, Conflict, ServiceUnavailable
from zoikorum.shared.event_catalog import E
from zoikorum.shared.events import record_audit

PARTNER_NAMES = {"persona": "Persona", "veriff": "Veriff", "simulated": "Veriff (simulated)"}
# A partner answer after which the professional may start a fresh hosted session.
RESTARTABLE = ("resubmission_requested", "abandoned")


def configuration():
    settings = get_settings()
    provider = settings.verification_provider
    configured = {"persona": bool(settings.persona_api_key and settings.persona_template_id and settings.persona_webhook_secret),
                  "veriff": bool(settings.veriff_api_key and settings.veriff_shared_secret),
                  "simulated": settings.env in (*DEV_ENVS, "test")}.get(provider, False)
    return {"provider": provider, "hostedIdentity": provider in PARTNER_NAMES, "configured": configured,
            "partnerName": PARTNER_NAMES.get(provider)}


def _partner(settings):
    if settings.verification_provider == "persona":
        return PersonaProvider(settings)
    if settings.verification_provider == "veriff":
        return VeriffProvider(settings)
    if settings.verification_provider == "simulated" and settings.env in (*DEV_ENVS, "test"):
        return SimulatedProvider(settings)
    raise Conflict("Online identity verification is not switched on. Upload a document instead.", code="HOSTED_NOT_AVAILABLE")


async def _own_identity_case(session, actor, case_id):
    case = await service._case(session, case_id, lock=True)
    if not await service._is_owner(session, actor, case.subject_type, case.subject_id):
        raise NotFound("Verification case not found")
    if case.verification_type != "IDENTITY":
        raise Conflict("Hosted verification is available only for an identity case")
    return case


async def hosted(session, actor, case_id):
    case = await _own_identity_case(session, actor, case_id)
    actor.require_step_up()
    if case.status not in service.OPEN_STATES:
        raise Conflict("Hosted verification is available only for an open identity case")
    settings = get_settings()
    provider = _partner(settings)
    name = getattr(provider, "name", settings.verification_provider)
    existing = await session.scalar(select(ProviderSession).where(ProviderSession.case_id == case.id).with_for_update())
    fresh = existing is None or existing.status in RESTARTABLE or (existing.provider and existing.provider != name)
    if fresh:
        ref = await provider.create(case.id)
        if existing is not None:  # remember the replaced session, so its late answers are acknowledged and ignored
            session.add(ProviderEvent(event_id=f"superseded:{existing.provider_ref}", event_type="session.superseded",
                                      payload_sha256=hashlib.sha256(existing.provider_ref.encode()).hexdigest()))
        if existing is None:
            existing = ProviderSession(case_id=case.id, provider_ref=ref)
            session.add(existing)
        existing.provider_ref, existing.provider, existing.status, existing.reason = ref, name, "pending", None
        existing.hosted_url = getattr(provider, "created_url", None)
        await session.flush()
    url = existing.hosted_url or await provider.link(existing.provider_ref)
    record_audit(session, "verification.provider.session.started", object_type="VerificationCase", object_id=case.id,
                 details={"provider": name, "newSession": bool(fresh)})
    return {"url": url, "status": existing.status, "provider": name}


async def apply_result(session, provider_session, case, status, reason=None):
    """One partner answer for one case. Returns what happened, for the receipt and the audit record."""
    decided = provider_session.status in ("approved", "failed", "declined")
    if case.status not in service.OPEN_STATES or (decided and status != "approved"):
        return "ignored"  # late or repeated answers never undo a result or a human decision
    if status == "submitted":
        if provider_session.status != "pending":
            return "ignored"
        provider_session.status = "submitted"
        _move(case, "IN_REVIEW")
        return "submitted"
    if status == "abandoned":
        if provider_session.status in ("pending", "submitted"):
            provider_session.status = "abandoned"
        return "abandoned"
    provider_session.status, provider_session.reason = status, (str(reason)[:300] if reason else None)
    if status == "approved":
        case.provider_result = "PASS"
        if case.status == "NEEDS_INFO":
            _move(case, "IN_REVIEW")  # NEEDS_INFO cannot jump straight to VERIFIED
        await service._verify(session, case, reviewer_id=None, expires_at=None)
        return "verified"
    if status == "resubmission_requested":
        _move(case, "NEEDS_INFO")
        case.reason_code = "PROVIDER_RESUBMISSION"
        case.public_reason = ("We could not read your document or selfie clearly. Please try again in good light"
                              + (f" ({reason})." if reason else "."))
        service._evt(session, E.VERIFICATION_NEEDS_INFO, case, reasonCode=case.reason_code, publicReason=case.public_reason)
        return "needs info"
    if status in ("completed", "failed", "declined", "needs_review", "expired"):
        case.provider_result = "FAIL" if status in ("failed", "declined") else "REVIEW"
        _move(case, "IN_REVIEW")
        return "human review"
    return "ignored"


def _move(case, status):
    if case.status != status:
        service.CASE_STATES.assert_can(case.status, status)
        case.status = status


async def _receipt(session, provider_session, event_id, kind, body, status, reason=None):
    """Stores the receipt once, then applies it."""
    if await session.scalar(select(ProviderEvent.id).where(ProviderEvent.event_id == event_id)):
        return {"received": True, "duplicate": True}
    case = await service._case(session, provider_session.case_id, lock=True)
    digest = hashlib.sha256(body).hexdigest()
    session.add(ProviderEvent(event_id=event_id, event_type=kind, payload_sha256=digest))
    outcome = await apply_result(session, provider_session, case, status, reason) if status else "ignored"
    record_audit(session, "verification.provider.receipt", object_type="VerificationCase", object_id=case.id,
                 evidence_hash=digest, details={"eventType": kind, "providerStatus": status, "outcome": outcome})
    return {"received": True, "duplicate": False}


async def _superseded(session, ref) -> bool:
    return bool(await session.scalar(select(ProviderEvent.id).where(ProviderEvent.event_id == f"superseded:{ref}")))


def verify_signature(signature, body, secret):
    try:
        parts = dict(part.split("=", 1) for part in signature.split(","))
        timestamp = int(parts["t"])
        expected = hmac.new(secret.encode(), str(timestamp).encode() + b"." + body, hashlib.sha256).hexdigest()
        return abs(clock.now().timestamp() - timestamp) <= 300 and hmac.compare_digest(expected, parts.get("v1", ""))
    except (AttributeError, ValueError, KeyError):
        return False


async def receipt(session, signature, body):
    """Persona webhook (Persona-Signature: t=<unix>,v1=<HMAC>)."""
    settings = get_settings()
    if settings.verification_provider != "persona" or not settings.persona_webhook_secret or not verify_signature(signature, body, settings.persona_webhook_secret):
        raise Unauthenticated("Invalid identity partner signature", code="INVALID_SIGNATURE")
    try:
        event = json.loads(body)["data"]
        attributes = event["attributes"]
        kind = attributes["name"]
        inquiry = attributes["payload"]["data"]
        status = inquiry["attributes"]["status"]
    except (ValueError, KeyError, TypeError) as exc:
        raise ValidationFailed("Invalid identity partner event") from exc
    if not kind.startswith("inquiry."):
        return {"received": True, "ignored": True}
    inquiry_session = await session.scalar(select(ProviderSession).where(ProviderSession.provider_ref == inquiry["id"]).with_for_update())
    if not inquiry_session:
        if await _superseded(session, inquiry["id"]):
            return {"received": True, "ignored": True}
        raise ServiceUnavailable("Verification session is not committed yet; retry this receipt", code="WEBHOOK_REFERENCE_PENDING")
    reference = inquiry["attributes"].get("reference-id")
    if reference and reference != str(inquiry_session.case_id):
        raise ValidationFailed("Identity receipt does not match the case")
    # Persona: only the inquiry.approved event approves; a bare "approved" status on another event is not enough.
    if status == "approved" and kind != "inquiry.approved":
        status = None
    elif status not in ("approved", "completed", "failed", "declined", "needs_review", "expired"):
        status = None
    return await _receipt(session, inquiry_session, event["id"], kind, body, status)


async def veriff_receipt(session, headers, body):
    """Veriff decision and event webhooks (X-HMAC-SIGNATURE: HMAC-SHA256 of the body with the shared secret)."""
    settings = get_settings()
    if settings.verification_provider != "veriff":
        raise Unauthenticated("Invalid identity partner signature", code="INVALID_SIGNATURE")
    partner = VeriffProvider(settings)
    if not partner.verify(headers.get("x-hmac-signature") or headers.get("x-signature"), body):
        raise Unauthenticated("Invalid identity partner signature", code="INVALID_SIGNATURE")
    try:
        data = json.loads(body)
    except ValueError as exc:
        raise ValidationFailed("Invalid identity partner event") from exc
    if isinstance(data.get("verification"), dict):  # decision webhook
        found = data["verification"]
        ref, kind, status, reason = found.get("id"), "decision." + str(found.get("status")), VERIFF_STATUS.get(found.get("status")), found.get("reason")
        vendor = found.get("vendorData")
    elif data.get("action") and data.get("id"):  # event webhook: started, submitted, ...
        ref, kind, reason = data["id"], "event." + str(data["action"]), None
        status, vendor = ("submitted" if data["action"] == "submitted" else None), data.get("vendorData")
    else:
        return {"received": True, "ignored": True}
    provider_session = await session.scalar(select(ProviderSession).where(ProviderSession.provider_ref == str(ref)).with_for_update())
    if not provider_session:
        if await _superseded(session, ref):
            return {"received": True, "ignored": True}
        raise ServiceUnavailable("Verification session is not committed yet; retry this receipt", code="WEBHOOK_REFERENCE_PENDING")
    if vendor and vendor != str(provider_session.case_id):
        raise ValidationFailed("Identity receipt does not match the case")
    # Veriff decision webhooks carry no event id: the body's fingerprint identifies a retried delivery.
    return await _receipt(session, provider_session, "veriff:" + hashlib.sha256(body).hexdigest(), kind, body, status, reason)


async def refresh(session, actor, case_id):
    """Back from the partner: fetch the answer now instead of waiting for the webhook (needed where none can arrive)."""
    case = await _own_identity_case(session, actor, case_id)
    provider_session = await session.scalar(select(ProviderSession).where(ProviderSession.case_id == case.id).with_for_update())
    settings = get_settings()
    if provider_session and provider_session.provider == "veriff" and settings.verification_provider == "veriff" \
            and case.status in service.OPEN_STATES and provider_session.status in ("pending", "submitted"):
        answer = await VeriffProvider(settings).decision(provider_session.provider_ref)
        if answer:
            status, reason = answer
            body = json.dumps({"session": provider_session.provider_ref, "status": status}).encode()
            await _receipt(session, provider_session, f"veriff-poll:{provider_session.provider_ref}:{status}",
                           "poll." + status, body, status, reason)
            await session.flush()
    return await service._out(session, case, True)


SIMULATED_REASONS = {"declined": "Document does not match the selfie (simulated)", "resubmission_requested": "Photo too blurry (simulated)"}


async def simulate(session, actor, case_id, status):
    """Development only: give the answer a partner would give."""
    settings = get_settings()
    if settings.verification_provider != "simulated" or settings.env not in (*DEV_ENVS, "test"):
        raise NotFound("Not available")
    case = await _own_identity_case(session, actor, case_id)
    provider_session = await session.scalar(select(ProviderSession).where(ProviderSession.case_id == case.id).with_for_update())
    if not provider_session or provider_session.status != "pending":
        raise Conflict("Start the identity check first", code="HOSTED_NOT_STARTED")
    await apply_result(session, provider_session, case, status, SIMULATED_REASONS.get(status))
    await session.flush()
    return await service._out(session, case, True)
