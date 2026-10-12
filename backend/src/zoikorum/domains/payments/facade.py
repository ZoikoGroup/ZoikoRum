"""Payments facade - CONTRACT. Signatures are fixed."""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession


async def has_valid_payout_account(session: AsyncSession, professional_id: uuid.UUID) -> bool:
    from zoikorum.domains.payments.service import has_valid_payout_account as check

    return await check(session, professional_id)


def require_available() -> None:
    from zoikorum.domains.payments.integration import configuration
    from zoikorum.shared.errors import ServiceUnavailable
    if not configuration()["configured"]:
        raise ServiceUnavailable("Payment integration is not configured; no funding was requested", code="INTEGRATION_NOT_CONFIGURED")


async def privacy_export_contracts(session, contract_ids, professional_id=None):
    from zoikorum.shared.privacy_exports import export_rows
    from zoikorum.domains.payments.models import PaymentIntent, Payout, Invoice, Refund
    return {
        'payment_intents': await export_rows(session, PaymentIntent, PaymentIntent.contract_id.in_(contract_ids), ['funding_id', 'escrow_account_id', 'contract_id', 'organization_id', 'amount_minor', 'currency', 'status', 'provider', 'method_label', 'failure_code', 'failure_message', 'captured_at', 'charged_back_at', 'chargeback_minor', 'chargeback_reason', 'id', 'updated_at', 'created_at']),
        'payouts': await export_rows(session, Payout, Payout.professional_id == professional_id, ['release_id', 'professional_id', 'contract_id', 'milestone_id', 'gross_minor', 'fee_minor', 'amount_minor', 'currency', 'status', 'transfer_ref', 'provider_attempt', 'failure_message', 'expected_at', 'settled_at', 'id', 'updated_at', 'created_at']) if professional_id else [],
        'invoices': await export_rows(session, Invoice, Invoice.contract_id.in_(contract_ids), ['number', 'release_id', 'organization_id', 'contract_id', 'milestone_id', 'lines', 'tax_minor', 'total_minor', 'currency', 'issued_at', 'id', 'updated_at', 'created_at']),
        'refunds': await export_rows(session, Refund, Refund.contract_id.in_(contract_ids), ['escrow_refund_id', 'payment_intent_id', 'organization_id', 'contract_id', 'milestone_id', 'dispute_id', 'amount_minor', 'currency', 'status', 'settled_at', 'id', 'updated_at', 'created_at']),
    }
