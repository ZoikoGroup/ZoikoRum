import { api } from './client'
import type { Money } from './orgs'

/* Escrow & payments (Step 8). Buyers fund milestones; money is held until the milestone is accepted, then released to
   the professional minus the platform fee. Only provider tokens are used: no card or bank numbers are stored. */

export type AllocationState = 'UNFUNDED' | 'FUNDING' | 'HELD' | 'ON_HOLD' | 'RELEASE_PENDING_APPROVAL' | 'RELEASED' | 'PARTIALLY_RELEASED' | 'REFUNDED'

export interface Escrow {
  id: string
  contractId: string
  status: 'UNFUNDED' | 'FUNDED' | 'PARTIALLY_RELEASED' | 'FULLY_RELEASED' | 'DISPUTED' | 'REFUNDED' | 'CLOSED'
  currency: string
  total: Money
  funded: Money
  held: Money
  released: Money
  fees: Money
  refunded: Money
  unfunded: Money
  feeBps: number
  allocations: { milestoneId: string; sequence: number; title: string; amount: Money; state: AllocationState; released: Money; fee: Money; fundedAt: string | null; releasedAt: string | null }[]
  fundings: { id: string; amount: Money; milestoneIds: string[]; status: 'REQUESTED' | 'CAPTURED' | 'FAILED'; failureMessage: string | null; createdAt: string; capturedAt: string | null }[]
  viewerRole: 'BUYER' | 'PROFESSIONAL' | 'OPERATOR'
  canFund: boolean
}

export interface LedgerLine {
  id: string; entryGroupId: string; entryType: string; ledgerAccount: string; debit: Money; credit: Money
  referenceType: string; referenceId: string; milestoneId: string | null; memo: string; createdAt: string
}

export interface Payout { id: string; contractId: string; milestoneId: string | null; gross: Money; fee: Money; net: Money; status: 'QUEUED' | 'INITIATED' | 'SETTLED' | 'FAILED'; failureMessage: string | null
  expectedAt: string | null; delayReason: string | null; settledAt: string | null; createdAt: string }
export interface Earnings {
  payoutAccount: { holderName: string; country: string; currency: string; label: string; status: string; createdAt: string } | null
  payouts: Payout[]
  totals: Partial<{ settled: Money; pending: Money; failed: Money; fees: Money }>
  totalsByCurrency: Record<string, { settled: Money; pending: Money; failed: Money; fees: Money }>
  monthlySettledByCurrency: Money[]
}
export interface Invoice { id: string; number: string; contractId: string; milestoneId: string | null; lines: { description: string; amountMinor: number }[]; tax: Money; total: Money; issuedAt: string }
export interface Charge { id: string; contractId: string; amount: Money; status: 'CREATED' | 'CAPTURED' | 'FAILED' | 'CHARGED_BACK'; methodLabel: string; failureMessage: string | null; createdAt: string
  capturedAt: string | null; chargedBackAt: string | null }
export interface ReconciliationCheck { name: string; currency: string; ledger: number; payments: number; provider: number | null; difference: number; ok: boolean }
export interface Reconciliation { id: string; day: string; status: 'MATCHED' | 'MISMATCH'; mismatches: number; checks: ReconciliationCheck[]; runBy: string; updatedAt: string }

const idem = () => ({ 'Idempotency-Key': crypto.randomUUID() })

export const escrowApi = {
  byContract: (contractId: string) => api<Escrow>(`/v1/escrow/by-contract/${contractId}`),
  ledger: (id: string) => api<LedgerLine[]>(`/v1/escrow/${id}/ledger`),
  fund: (id: string, body: { milestoneIds?: string[]; all?: boolean; paymentMethodToken: string }) =>
    api<Escrow>(`/v1/escrow/${id}/fund`, { method: 'POST', body, headers: idem() }),
}

export const paymentsApi = {
  configuration: () => api<{ provider: string; configured: boolean; testMode: boolean; hostedCheckout: boolean; hostedOnboarding: boolean }>('/v1/payments/configuration'),
  checkout: (fundingId: string) => api<{ status: string; url: string | null }>(`/v1/payments/fundings/${fundingId}/checkout`),
  onboarding: () => api<{ url: string; status: string }>('/v1/payout-accounts/me/onboarding', { method: 'POST', headers: idem() }),
  earnings: () => api<Earnings>('/v1/payments/earnings/me'),
  setPayoutAccount: (body: { holderName: string; country: string; currency: string; accountNumber: string }) =>
    api<Earnings['payoutAccount']>('/v1/payout-accounts/me', { method: 'PUT', body }),
  invoices: (organizationId: string) => api<Invoice[]>('/v1/payments/invoices', { query: { organizationId } }),
  charges: (organizationId: string) => api<Charge[]>('/v1/payments/charges', { query: { organizationId } }),
  reconciliations: () => api<Reconciliation[]>('/v1/payments/reconciliations'),
  reconcile: (day: string) => api<Reconciliation>('/v1/payments/reconciliations', { method: 'POST', body: { day } }),
}

// Test-mode payment methods from the (fake) payment provider. A real provider's card form returns a token like these.
export const TEST_CARDS: [string, string][] = [['tok_visa', 'Test Visa •••• 4242 (succeeds)'], ['tok_mastercard', 'Test Mastercard •••• 4444 (succeeds)'],
  ['tok_fail', 'Test card that is declined']]

export const ALLOCATION_STATE: Record<AllocationState, { label: string; tone: '' | 'green' | 'warn' }> = {
  UNFUNDED: { label: 'Not funded', tone: '' }, FUNDING: { label: 'Payment processing', tone: 'warn' }, HELD: { label: 'Held in escrow', tone: 'green' },
  ON_HOLD: { label: 'Frozen (dispute)', tone: 'warn' }, RELEASE_PENDING_APPROVAL: { label: 'Release awaiting approval', tone: 'warn' },
  RELEASED: { label: 'Released', tone: 'green' }, PARTIALLY_RELEASED: { label: 'Partly released', tone: 'warn' }, REFUNDED: { label: 'Refunded', tone: '' },
}
export const PAYOUT_STATUS: Record<Payout['status'], { label: string; tone: '' | 'green' | 'warn' }> = {
  QUEUED: { label: 'Waiting for payout account', tone: 'warn' }, INITIATED: { label: 'Sending', tone: 'warn' },
  SETTLED: { label: 'Paid out', tone: 'green' }, FAILED: { label: 'Failed', tone: '' },
}
