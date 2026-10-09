"""Hosted identity verification, authenticated receipts and human review for negative results."""
import hashlib
import hmac
import json
import uuid

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from zoikorum.config import get_settings
from zoikorum.domains.verification import service
from zoikorum.domains.verification.models import ProviderSession, ProviderEvent
from zoikorum.domains.verification.providers import PersonaProvider
from zoikorum.shared import clock
from zoikorum.shared.errors import NotFound, Unauthenticated, ValidationFailed, Conflict, ServiceUnavailable
from zoikorum.shared.events import record_audit


def configuration():
    settings = get_settings()
    return {"provider": settings.verification_provider, "hostedIdentity": settings.verification_provider == "persona",
            "configured": settings.verification_provider == "persona" and bool(settings.persona_api_key and settings.persona_template_id and settings.persona_webhook_secret)}


async def hosted(session, actor, case_id):
    case = await service._case(session, case_id, lock=True)
    if not await service._is_owner(session, actor, case.subject_type, case.subject_id):
        raise NotFound("Verification case not found")
    actor.require_step_up()
    if case.verification_type != "IDENTITY" or case.status not in service.OPEN_STATES:
        raise Conflict("Hosted verification is available only for an open identity case")
    provider = PersonaProvider(get_settings())
    existing = await session.scalar(select(ProviderSession).where(ProviderSession.case_id == case.id))
    if not existing:
        existing = ProviderSession(case_id=case.id, provider_ref=await provider.create(case.id))
        session.add(existing)
        await session.flush()
    url = await provider.link(existing.provider_ref)
    record_audit(session, "verification.provider.session.started", object_type="VerificationCase", object_id=case.id)
    return {"url": url, "status": existing.status}


def verify_signature(signature, body, secret):
    try:
        parts = dict(part.split("=", 1) for part in signature.split(","))
        timestamp = int(parts["t"])
        expected = hmac.new(secret.encode(), str(timestamp).encode() + b"." + body, hashlib.sha256).hexdigest()
        return abs(clock.now().timestamp() - timestamp) <= 300 and hmac.compare_digest(expected, parts.get("v1", ""))
    except (AttributeError, ValueError, KeyError):
        return False


async def receipt(session, signature, body):
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
        raise ServiceUnavailable("Verification session is not committed yet; retry this receipt", code="WEBHOOK_REFERENCE_PENDING")
    duplicate = await session.scalar(select(ProviderEvent.id).where(ProviderEvent.event_id == event["id"]))
    if duplicate:
        return {"received": True, "duplicate": True}
    case = await service._case(session, inquiry_session.case_id, lock=True)
    reference = inquiry["attributes"].get("reference-id")
    if reference and reference != str(case.id):
        raise ValidationFailed("Identity receipt does not match the case")
    session.add(ProviderEvent(event_id=event["id"], event_type=kind, payload_sha256=hashlib.sha256(body).hexdigest()))
    # Do not let late started/completed events undo an issued result or human decision.
    if case.status in service.OPEN_STATES and (inquiry_session.status not in ("approved", "failed", "declined") or status == "approved"):
        if status == "approved" and kind == "inquiry.approved":
            case.provider_result, inquiry_session.status = "PASS", status
            await service._verify(session, case, reviewer_id=None, expires_at=None)
        elif status in ("completed", "failed", "declined", "needs_review", "expired"):
            case.provider_result = "FAIL" if status in ("failed", "declined") else "REVIEW"
            inquiry_session.status = status
            if case.status in ("PENDING", "NEEDS_INFO"):
                case.status = "IN_REVIEW"
    record_audit(session, "verification.provider.receipt", object_type="VerificationCase", object_id=case.id,
                 evidence_hash=hashlib.sha256(body).hexdigest(), details={"eventType": kind, "providerStatus": status})
    return {"received": True, "duplicate": False}
