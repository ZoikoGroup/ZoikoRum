"""Credential-free adapter contract checks; no external services are contacted."""
import io
from urllib.parse import parse_qs

import httpx
import pytest

from prodsettings import PRODUCTION
from zoikorum.config import Settings
from zoikorum.domains.payments import providers
from zoikorum.domains.payments.stripe_provider import StripeProvider
from zoikorum.shared import storage
from zoikorum.shared.errors import ServiceUnavailable, ValidationFailed


def stripe_settings(**kwargs):
    return Settings(_env_file=None, **({"stripe_secret_key": "sk_test_fixture", "stripe_webhook_secret": "whsec_fixture", "payment_flow_approved": True} | kwargs))


def test_production_never_selects_fake_payment_or_local_storage(monkeypatch):
    settings = Settings(_env_file=None, **PRODUCTION, payment_provider="fake", storage_provider="local")
    monkeypatch.setattr(providers, "get_settings", lambda: settings)
    monkeypatch.setattr(storage, "get_settings", lambda: settings)
    with pytest.raises(ServiceUnavailable): providers.get_provider()
    with pytest.raises(ServiceUnavailable): storage.get_storage()


def test_missing_payment_credentials_and_flow_approval_are_explicit():
    for settings in (Settings(_env_file=None, stripe_secret_key=None), stripe_settings(payment_flow_approved=False)):
        with pytest.raises(ServiceUnavailable): StripeProvider(settings)


def test_hosted_checkout_is_pending_and_has_a_durable_request_key():
    calls = []
    def handle(request):
        calls.append(request)
        return httpx.Response(200, json={"id": "cs_fixture", "url": "https://checkout.stripe.com/c/pay/fixture"})
    provider = StripeProvider(stripe_settings(), transport=httpx.MockTransport(handle))
    result = provider.charge("hosted_checkout", 12345, "EUR", idempotency_key="funding-reference")
    assert result.ok and result.pending and result.provider_ref == "cs_fixture"
    assert calls[0].headers["Idempotency-Key"] == "funding:funding-reference"
    body = parse_qs(calls[0].content.decode())
    assert body["line_items[0][price_data][unit_amount]"] == ["12345"]
    assert body["line_items[0][price_data][currency]"] == ["eur"]
    with pytest.raises(ValidationFailed): provider.charge("tok_visa", 100, "USD", idempotency_key="other")


def test_transfer_and_bank_payout_are_separate_and_retryable():
    calls = []
    def handle(request):
        calls.append(request)
        return httpx.Response(200, json={"id": "tr_fixture" if request.url.path.endswith("transfers") else "po_fixture"})
    provider = StripeProvider(stripe_settings(), transport=httpx.MockTransport(handle))
    result = provider.payout("acct_fixture", 900, "USD", idempotency_key="release-id")
    assert result.pending and len(calls) == 1 and result.provider_ref == "tr_fixture"
    bank = provider.bank_payout("acct_fixture", 900, "USD", idempotency_key="release-id:1")
    assert bank.pending and bank.provider_ref == "po_fixture"
    assert calls[1].headers["Stripe-Account"] == "acct_fixture"
    assert calls[1].headers["Idempotency-Key"] == "payout:release-id:1"


def test_checkout_requires_paid_status_and_maps_currency():
    provider = StripeProvider(stripe_settings())
    event = {"id": "evt_one", "type": "checkout.session.completed", "data": {"object": {"id": "cs_one", "payment_status": "unpaid"}}}
    assert provider.normalize_event(event)["type"] == "ignored"
    event["data"]["object"].update(payment_status="paid", amount_total=1200, currency="eur")
    normalized = provider.normalize_event(event)
    assert normalized["type"] == "charge.succeeded"
    assert normalized["data"]["currency"] == "EUR"


class CloudClient:
    def __init__(self): self.writes = []; self.reads = []; self.holds = []
    def get_bucket_versioning(self, **kwargs): return {"Status": "Enabled"}
    def put_object(self, **kwargs): self.writes.append(kwargs); return {"VersionId": "version-one"}
    def get_object(self, **kwargs): self.reads.append(kwargs); return {"Body": io.BytesIO(b"evidence")}
    def put_object_legal_hold(self, **kwargs): self.holds.append(kwargs)


def test_cloud_objects_bind_versions_encryption_retention_and_legal_hold():
    client = CloudClient()
    adapter = storage.S3Storage(Settings(_env_file=None, s3_bucket="fixture", s3_object_lock_mode="COMPLIANCE", s3_retention_days=365), client)
    assert adapter.put("evidence/file", b"evidence") == "version-one"
    args = client.writes[0]
    assert args["IfNoneMatch"] == "*" and args["ServerSideEncryption"] == "AES256"
    assert args["ObjectLockMode"] == "COMPLIANCE" and args["ChecksumSHA256"]
    assert adapter.get("evidence/file", "version-one") == b"evidence"
    assert client.reads[0]["VersionId"] == "version-one"
    adapter.legal_hold("evidence/file", "version-one", True)
    assert client.holds[0]["LegalHold"] == {"Status": "ON"}
    with pytest.raises(ValidationFailed): adapter.delete("evidence/file")
    with pytest.raises(ValidationFailed): adapter.put("../outside", b"no")


async def test_persona_hosted_links_and_signature_contract():
    from zoikorum.domains.verification.providers import PersonaProvider
    from zoikorum.domains.verification.integration import verify_signature
    from zoikorum.domains.payments.providers import sign_webhook
    calls = []
    async def handle(request):
        calls.append(request)
        return httpx.Response(200, json={"data": {"id": "inq_fixture"}, "meta": {"one-time-link": "https://withpersona.com/verify?code=fixture"}})
    settings = Settings(_env_file=None, persona_api_key="fixture", persona_template_id="itmpl_fixture", persona_webhook_secret="fixture-secret")
    provider = PersonaProvider(settings, httpx.MockTransport(handle))
    assert await provider.create("case-id") == "inq_fixture"
    assert await provider.link("inq_fixture") == "https://withpersona.com/verify?code=fixture"
    assert calls[0].headers["Idempotency-Key"] == "inquiry:case-id"
    body = b"signed receipt"
    signature = sign_webhook(body, "fixture-secret")
    assert verify_signature(signature, body, "fixture-secret")
    assert not verify_signature(signature, body + b"changed", "fixture-secret")
    assert not verify_signature(signature, body, "wrong")


async def test_hosted_checkout_waits_for_verified_capture(client, make_user, drain, monkeypatch):
    import json
    from test_contract import signed_contract
    from zoikorum.domains.payments import service, webhooks
    from zoikorum.domains.payments.providers import FakeProvider, ChargeResult, sign_webhook
    class Delayed(FakeProvider):
        name = "stripe"
        def charge(self, token, amount_minor, currency, **kwargs):
            return ChargeResult(True, provider_ref="cs_fixture", pending=True)
        def normalize_event(self, event): return event
    partner = Delayed()
    monkeypatch.setattr(service, "get_provider", lambda: partner)
    monkeypatch.setattr(webhooks, "get_provider", lambda: partner)
    pro, profile, buyer, contract = await signed_contract(client, make_user, drain)
    escrow = (await client.get(f"/v1/escrow/by-contract/{contract['id']}", headers=buyer.h)).json()
    response = await client.post(f"/v1/escrow/{escrow['id']}/fund", headers=buyer.idem(), json={"all": True, "paymentMethodToken": "hosted_checkout"})
    assert response.status_code == 200, response.text
    await drain()
    current = (await client.get(f"/v1/escrow/{escrow['id']}", headers=buyer.h)).json()
    assert current["held"]["amountMinor"] == 0
    assert all(a["state"] == "FUNDING" for a in current["allocations"])
    event = {"id": "evt_capture", "type": "charge.succeeded", "data": {"ref": "cs_fixture", "amountMinor": current["total"]["amountMinor"], "currency": current["currency"]}}
    body = json.dumps(event).encode()
    rejected = await client.post('/v1/payments/webhooks/stripe', content=body, headers={"Webhook-Signature": "invalid"})
    assert rejected.status_code == 401
    headers = {"Stripe-Signature": sign_webhook(body, "dev-webhook-secret"), "Content-Type": "application/json"}
    receipt = await client.post('/v1/payments/webhooks/stripe', content=body, headers=headers)
    assert receipt.status_code == 200, receipt.text
    repeated = await client.post('/v1/payments/webhooks/stripe', content=body, headers=headers)
    assert repeated.json()["duplicate"] is True
    await drain()
    funded = (await client.get(f"/v1/escrow/{escrow['id']}", headers=buyer.h)).json()
    assert funded["held"]["amountMinor"] == funded["total"]["amountMinor"]
    assert all(a["state"] == "HELD" for a in funded["allocations"])


async def test_persona_owner_scope_receipts_and_late_events(client, make_user, drain, sf, monkeypatch):
    import json
    from zoikorum.domains.verification import integration
    from zoikorum.domains.payments.providers import sign_webhook
    settings = Settings(_env_file=None, verification_provider="persona", persona_webhook_secret="fixture-secret")
    monkeypatch.setattr(integration, "get_settings", lambda: settings)
    owner = await make_user("hosted-owner", account_type="PROFESSIONAL")
    profile = (await client.post('/v1/professionals', headers=owner.h, json={})).json()
    await drain(); await owner.step_up()
    case = (await client.post('/v1/verification/cases', headers=owner.h, json={"subjectType": "PROFESSIONAL", "subjectId": profile["id"], "verificationType": "IDENTITY"})).json()
    counts = {"created": 0}
    class Partner:
        def __init__(self, settings): pass
        async def create(self, case_id): counts["created"] += 1; return "inq_fixture"
        async def link(self, inquiry): return "https://withpersona.com/verify?code=fixture"
    monkeypatch.setattr(integration, "PersonaProvider", Partner)
    url = f"/v1/verification/cases/{case['id']}/hosted-session"
    stranger = await make_user("hosted-stranger")
    assert (await client.post(url, headers=stranger.h)).status_code == 404
    assert (await client.post(url, headers=owner.h)).status_code == 200
    assert (await client.post(url, headers=owner.h)).status_code == 200
    assert counts["created"] == 1
    async def send(event_id, status):
        body = json.dumps({"data": {"id": event_id, "attributes": {"name": "inquiry." + status, "payload": {"data": {"id": "inq_fixture", "attributes": {"status": status, "reference-id": case["id"]}}}}}}).encode()
        return await client.post('/v1/verification/webhooks/persona', content=body, headers={"Persona-Signature": sign_webhook(body, "fixture-secret")})
    assert (await send("evt_completed", "completed")).status_code == 200
    read = f"/v1/verification/cases/{case['id']}"
    assert (await client.get(read, headers=owner.h)).json()["status"] == "IN_REVIEW"
    approved = await send("evt_approved", "approved")
    assert approved.status_code == 200, approved.text
    assert (await send("evt_approved", "approved")).json()["duplicate"] is True
    assert (await send("evt_late", "completed")).status_code == 200
    assert (await client.get(read, headers=owner.h)).json()["status"] == "VERIFIED"
    await drain()
    trust_url = f"/v1/trust/professionals/{profile['id']}"
    # The profile is still a draft: verification does not make it publicly visible.
    assert (await client.get(trust_url)).status_code == 404
    assert (await client.get(trust_url, headers=stranger.h)).status_code == 404
    snapshot = await client.get(trust_url, headers=owner.h)
    assert snapshot.status_code == 200, snapshot.text
    assert snapshot.json()["tier"] == "B"
    assert snapshot.json()["dimensions"]["identity"] == "VERIFIED"
