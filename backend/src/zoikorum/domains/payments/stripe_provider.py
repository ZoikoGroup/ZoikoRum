"""Stripe hosted Checkout and Connect. This adapter does not claim to provide legal escrow."""
from __future__ import annotations

import httpx

from zoikorum.domains.payments.providers import ChargeResult, PayoutResult, verify_signature
from zoikorum.shared.errors import ServiceUnavailable, ValidationFailed


class StripeProvider:
    name = "stripe"

    def __init__(self, settings, transport=None):
        self.settings, self.transport = settings, transport
        if not (settings.stripe_secret_key and settings.stripe_webhook_secret and settings.payment_flow_approved):
            raise ServiceUnavailable("Stripe credentials have not been configured", code="INTEGRATION_NOT_CONFIGURED")

    def request(self, method, path, data=None, *, key=None, account=None):
        headers = {"Authorization": f"Bearer {self.settings.stripe_secret_key}"}
        if key:
            headers["Idempotency-Key"] = key
        if account:
            headers["Stripe-Account"] = account
        if self.settings.stripe_api_version:
            headers["Stripe-Version"] = self.settings.stripe_api_version
        try:
            with httpx.Client(base_url="https://api.stripe.com/v1/", timeout=20, transport=self.transport) as client:
                response = client.request(method, path, params=data if method == "GET" else None,
                                          data=data if method != "GET" else None, headers=headers)
        except httpx.HTTPError as exc:
            raise ServiceUnavailable("Payment partner could not be reached", code="PROVIDER_UNAVAILABLE") from exc
        if response.status_code >= 500 or response.status_code == 429:
            raise ServiceUnavailable("Payment partner is temporarily unavailable", code="PROVIDER_UNAVAILABLE")
        if response.status_code >= 400:
            raise ValidationFailed("The payment partner rejected this operation; check the account configuration", code="PROVIDER_REJECTED")
        return response.json()

    def charge(self, token, amount_minor, currency, *, idempotency_key=None):
        if not idempotency_key:
            raise ValidationFailed("A durable funding reference is required")
        if token != "hosted_checkout":
            raise ValidationFailed("Use the hosted payment page", code="HOSTED_CHECKOUT_REQUIRED")
        root = self.settings.frontend_url.rstrip("/")
        result = self.request("POST", "checkout/sessions", {
            "mode": "payment", "client_reference_id": idempotency_key,
            "success_url": root + "/app/payments?checkout=returned",
            "cancel_url": root + "/app/payments?checkout=cancelled",
            "line_items[0][price_data][currency]": currency.lower(),
            "line_items[0][price_data][unit_amount]": str(amount_minor),
            "line_items[0][price_data][product_data][name]": "Zoikorum milestone funding",
            "line_items[0][quantity]": "1", "payment_method_types[0]": "card",
            "payment_intent_data[metadata][fundingReference]": idempotency_key,
        }, key="funding:" + idempotency_key)
        return ChargeResult(True, provider_ref=result["id"], pending=True, checkout_url=result["url"], method_label="Stripe Checkout")

    def checkout_url(self, reference):
        return self.request("GET", "checkout/sessions/" + reference).get("url")

    def connected_account(self, country, email, reference):
        if country not in self.settings.payment_operating_countries:
            raise ValidationFailed("This country has not been enabled for the payment partner", code="PAYMENT_COUNTRY_NOT_ENABLED")
        return self.request("POST", "accounts", {"type": "express", "country": country, "email": email,
            "capabilities[transfers][requested]": "true", "settings[payouts][schedule][interval]": "manual",
            "metadata[professionalId]": reference}, key="account:" + reference)["id"]

    def onboarding_url(self, account):
        root = self.settings.frontend_url.rstrip("/") + "/app/professional/earnings"
        return self.request("POST", "account_links", {"account": account, "type": "account_onboarding",
            "refresh_url": root + "?onboarding=refresh", "return_url": root + "?onboarding=returned"})["url"]

    def create_payout_account(self, *args):
        raise ValidationFailed("Bank details must be collected on the payment partner's hosted onboarding page", code="HOSTED_ONBOARDING_REQUIRED")

    def payout(self, account_ref, amount_minor, currency, *, idempotency_key=None):
        if not idempotency_key:
            raise ValidationFailed("A durable payout reference is required")
        result = self.request("POST", "transfers", {"destination": account_ref, "amount": str(amount_minor),
            "currency": currency.lower(), "metadata[payoutReference]": idempotency_key}, key="transfer:" + idempotency_key)
        return PayoutResult(True, provider_ref=result["id"], pending=True)

    def bank_payout(self, account_ref, amount_minor, currency, *, idempotency_key):
        result = self.request("POST", "payouts", {"amount": str(amount_minor), "currency": currency.lower(),
            "metadata[payoutReference]": idempotency_key.split(":", 1)[0]}, key="payout:" + idempotency_key, account=account_ref)
        return PayoutResult(True, provider_ref=result["id"], pending=True)

    def refund(self, charge_ref, amount_minor, currency, *, idempotency_key=None):
        if not charge_ref or not idempotency_key:
            raise ValidationFailed("The original charge and durable refund reference are required")
        payment_intent = self.request("GET", "checkout/sessions/" + charge_ref).get("payment_intent")
        if not payment_intent:
            raise ValidationFailed("The original checkout has not completed")
        result = self.request("POST", "refunds", {"payment_intent": payment_intent, "amount": str(amount_minor),
                              "metadata[refundReference]": idempotency_key},
                              key="refund:" + idempotency_key)
        return PayoutResult(True, provider_ref=result["id"], pending=result.get("status") != "succeeded")

    def verify_webhook(self, signature_header, body):
        secret = self.settings.stripe_webhook_secret
        return bool(secret and verify_signature(signature_header, body, secret, self.settings.webhook_tolerance_seconds))

    def pages(self, path, params=None, account=None):
        parameters = {"limit": "100", **(params or {})}
        for _ in range(1000):
            page = self.request("GET", path, parameters, account=account)
            yield from page["data"]
            if not page.get("has_more"):
                return
            if not page["data"]:
                break
            parameters["starting_after"] = page["data"][-1]["id"]
        raise ServiceUnavailable("Provider report pagination could not complete", code="PROVIDER_REPORT_INCOMPLETE")

    def report(self, since, until):
        from zoikorum.domains.payments.providers import ProviderReport
        report = ProviderReport()
        for transaction in self.pages("balance_transactions", {"created[gte]": int(since.timestamp()), "created[lt]": int(until.timestamp())}):
            collection = report.charges if transaction["type"] == "charge" else report.refunds if transaction["type"] == "refund" else None
            if collection is not None:
                currency = transaction["currency"].upper()
                collection[currency] = collection.get(currency, 0) + abs(transaction["amount"])
        for account in self.pages("accounts"):
            if not account.get("metadata", {}).get("professionalId"):
                continue
            for payout in self.pages("payouts", {"arrival_date[gte]": int(since.timestamp()), "arrival_date[lt]": int(until.timestamp())}, account["id"]):
                if payout["status"] == "paid" and payout.get("metadata", {}).get("payoutReference"):
                    currency = payout["currency"].upper()
                    report.payouts[currency] = report.payouts.get(currency, 0) + payout["amount"]
        return report

    def normalize_event(self, event):
        kind, obj = event["type"], event.get("data", {}).get("object", {})
        mapped, data = "ignored", {"ref": obj.get("id")}
        if kind in ("checkout.session.completed", "checkout.session.async_payment_succeeded") and obj.get("payment_status") == "paid":
            mapped = "charge.succeeded"
            data.update(amountMinor=obj.get("amount_total"), currency=str(obj.get("currency", "")).upper())
        elif kind in ("checkout.session.expired", "checkout.session.async_payment_failed"):
            mapped = "charge.failed"
        elif kind in ("payout.paid", "payout.failed"):
            mapped = kind
            data.update(message=obj.get("failure_message"), account=event.get("account"), releaseReference=obj.get("metadata", {}).get("payoutReference"))
        elif kind == "transfer.created":
            mapped = "transfer.created"
            data.update(account=obj.get("destination"), releaseReference=obj.get("metadata", {}).get("payoutReference"))
        elif kind in ("refund.created", "refund.updated", "refund.failed"):
            mapped = "refund.succeeded" if obj.get("status") == "succeeded" else "refund.failed" if obj.get("status") in ("failed", "canceled") else "ignored"
        elif kind == "account.updated":
            mapped = "account.updated"
            data.update(payoutsEnabled=bool(obj.get("payouts_enabled")), detailsSubmitted=bool(obj.get("details_submitted")))
        elif kind == "charge.dispute.created":
            payment = self.request("GET", "payment_intents/" + obj["payment_intent"])
            mapped = "charge.dispute.created"
            data.update(fundingReference=payment.get("metadata", {}).get("fundingReference"), amountMinor=obj["amount"], reason=obj.get("reason"))
        return {"id": event["id"], "type": mapped, "data": data}
