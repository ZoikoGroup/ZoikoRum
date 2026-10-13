"""Hosted partner workflows; no payment secrets or bank details exposed to the frontend."""
import asyncio
from sqlalchemy import select, text

from zoikorum.config import get_settings
from zoikorum.domains.payments import service
from zoikorum.domains.payments.models import PayoutAccount, PaymentIntent
from zoikorum.domains.payments.providers import get_provider
from zoikorum.domains.identity import facade as identity
from zoikorum.shared.errors import NotFound, ServiceUnavailable, PolicyBlocked
from zoikorum.shared.events import record_audit


def configuration():
    settings = get_settings()
    ready = (settings.payment_provider == "fake" and settings.env in ("local", "test", "development")) or (
        settings.payment_provider == "stripe" and bool(settings.stripe_secret_key and settings.stripe_webhook_secret and settings.payment_flow_approved))
    return {"provider": settings.payment_provider, "configured": ready,
            "testMode": settings.payment_provider == "fake" or bool(settings.stripe_secret_key and settings.stripe_secret_key.startswith("sk_test_")),
            "hostedCheckout": settings.payment_provider == "stripe", "hostedOnboarding": settings.payment_provider == "stripe"}


async def checkout(session, actor, funding_id):
    intent = await session.scalar(select(PaymentIntent).where(PaymentIntent.funding_id == funding_id))
    if not intent:
        return {"status": "PREPARING", "url": None}
    await service._require_member(session, actor, intent.organization_id)
    if intent.provider != "stripe" or intent.status != "CREATED" or not intent.provider_ref:
        return {"status": intent.status, "url": None}
    url = await asyncio.to_thread(get_provider().checkout_url, intent.provider_ref)
    return {"status": intent.status, "url": url}


async def onboarding(session, actor):
    actor.require_step_up()
    provider = get_provider()
    if provider.name != "stripe":
        raise ServiceUnavailable("Hosted onboarding is not enabled", code="INTEGRATION_NOT_CONFIGURED")
    pro = await service._my_professional(session, actor)
    trust = await service.trust_facade.get_trust(session, pro.id)
    if trust.tier == "C" or trust.dimensions.get("restrictions") != "CLEAR":
        raise PolicyBlocked("Complete identity and restrictions verification before payout onboarding", code="PAYOUT_COMPLIANCE_REQUIRED")
    who = await identity.get_identity(session, actor.identity_id)
    # Serialize creation on the owner's profile through an existing account-independent advisory lock.
    await session.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"), {"key": "payments.onboarding:" + str(pro.id)})
    account = await session.scalar(select(PayoutAccount).where(PayoutAccount.professional_id == pro.id).with_for_update())
    if account and account.provider != "stripe":
        raise PolicyBlocked("Existing payout accounts require a reviewed provider migration", code="PAYMENT_PROVIDER_MIGRATION_REQUIRED")
    if not account:
        reference = await asyncio.to_thread(provider.connected_account, who.country, who.email, str(pro.id))
        account = PayoutAccount(professional_id=pro.id, created_by=actor.identity_id, holder_name=who.display_name,
            country=who.country, currency="USD", last4="", provider="stripe", provider_account_ref=reference, status="PENDING")
        session.add(account)
        await session.flush()
    url = await asyncio.to_thread(provider.onboarding_url, account.provider_account_ref)
    record_audit(session, "payments.onboarding.started", object_type="PayoutAccount", object_id=account.id, tenant_id=pro.id)
    return {"url": url, "status": account.status}
