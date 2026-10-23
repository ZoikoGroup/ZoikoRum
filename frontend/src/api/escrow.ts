import type { ApprovalRequest } from './approvals'
import { allPages, api } from './client'
import type { Money } from './orgs'

/* Escrow & payments (Step 8). Buyers fund milestones; money is held until the milestone is accepted, then released to
   the professional minus the platform fee. Only provider tokens are used: no card or bank numbers are stored. */

export type AllocationState = 'UNFUNDED' | 'FUNDING' | 'HELD' | 'ON_HOLD' | 'RELEASE_PENDING_APPROVAL' | 'RELEASED' | 'PARTIALLY_RELEASED' | 'REFUNDED'
  | 'CANCELLED' | 'EXPIRED'
export type ReleaseModel = 'MILESTONE' | 'RETAINER' | 'FIXED'
export const RELEASE_MODELS: [ReleaseModel, string, string][] = [
  ['MILESTONE', 'Milestone release', 'Fund each milestone before its work starts; each is released when you accept it.'],
  ['FIXED', 'Fixed release', 'Fund the whole fee at once; it is still released milestone by milestone, on your acceptance.'],
  ['RETAINER', 'Retainer release', 'Fund each cycle before it starts; each is released when you accept that cycle.'],
]
export interface Protection {
  releaseModel: ReleaseModel | null; approverIdentityId: string | null; approverName: string | null; confirmedAt: string | null
  explanation: string; disputeHold: string; firstFunding: string[]
}
export interface Screening { status: 'CLEAR' | 'PENDING' | 'FLAGGED' | 'NOT_SCREENED'; message: string | null }

export interface Escrow {
  autoFundingEnabledAt?: string | null
  protection?: Protection | null
  buyerScreening?: Screening | null  // buyer side only: FLAGGED blocks funding, PENDING warns
  id: string
  contractId: string
  status: 'UNFUNDED' | 'FUNDED' | 'PARTIALLY_RELEASED' | 'FULLY_RELEASED' | 'DISPUTED' | 'REFUNDED' | 'CLOSED' | 'EXPIRED'
  currency: string
  total: Money
  funded: Money
  held: Money
  released: Money
  fees: Money
  refunded: Money
  unfunded: Money
  feeBps: number
  allocations: { milestoneId: string; sequence: number; title: string; amount: Money; state: AllocationState; released: Money; fee: Money; fundedAt: string | null; releasedAt: string | null; releaseReference?: string | null
    releaseId?: string | null; releaseApprovalDueAt?: string | null }[]
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
export interface Refund { id: string; contractId: string; milestoneId: string | null; disputeId: string | null; amount: Money
  status: 'INITIATED' | 'SETTLED' | 'FAILED'; failureMessage: string | null; createdAt: string; settledAt: string | null }
export interface OpsItem { kind: 'PAYOUT' | 'REFUND' | 'CHARGEBACK_LOSS'; id: string; amount: Money; engagement: string; contractId: string
  buyer: string; professional: string; problem: string; since: string; canRetry: boolean; resolution: string | null; resolvedAt: string | null }
export interface ReconciliationCheck { name: string; currency: string; ledger: number; payments: number; provider: number | null; difference: number; ok: boolean }
export interface Reconciliation { id: string; day: string; status: 'MATCHED' | 'MISMATCH'; mismatches: number; checks: ReconciliationCheck[]; runBy: string; updatedAt: string
  /** CLEAN only when nothing differed and no break for the day is unresolved. */
  runStatus: 'CLEAN' | 'BREAKS_OPEN' | 'BREAKS_RESOLVED'; breaks: number; openBreaks: number }
export type BreakStatus = 'OPEN' | 'EVIDENCE_GATHERING' | 'REVIEWED' | 'CLOSED'
export interface ReconciliationBreak { id: string; batchId: string; day: string; kind: string; currency: string; amountMinor: number
  references: { batchId?: string; ledger?: number; payments?: number; provider?: number | null }; status: BreakStatus
  ownerId: string | null; owner: string | null; resolutionNote: string | null; reviewedBy: string | null; reviewedAt: string | null
  closedBy: string | null; closedAt: string | null; history: { at: string; by: string; fromStatus: string | null; toStatus: string; note: string | null }[]
  createdAt: string; updatedAt: string }

const idem = () => ({ 'Idempotency-Key': crypto.randomUUID() })

export interface PaymentsOverview {
  totals: { currency: string; heldMinor: number; frozenMinor: number; awaitingFundingMinor: number; releasedMinor: number }[]
  vendors: { professionalId: string; name: string; currency: string; engagements: number; heldMinor: number; frozenMinor: number; awaitingFundingMinor: number; releasedMinor: number }[]
  releaseTimeline: { accountId: string; contractId: string; reference: string; vendor: string; milestone: string; amountMinor: number; currency: string; dueDate: string | null; status: string | null }[]
  awaitingFunding: { accountId: string; contractId: string; reference: string; vendor: string; milestoneId: string; milestone: string; amountMinor: number; currency: string; dueDate: string | null }[]
}

export const escrowApi = {
  byContract: (contractId: string) => api<Escrow>(`/v1/escrow/by-contract/${contractId}`),
  /** One page of ledger lines, oldest first; pass the previous page's nextCursor for the next one. */
  ledger: (id: string, cursor?: string | null) =>
    api<{ items: LedgerLine[]; nextCursor: string | null }>(`/v1/escrow/${id}/ledger`, { query: cursor ? { cursor } : {} }),
  setProtection: (id: string, body: { releaseModel: ReleaseModel; approverIdentityId?: string | null; disputeHoldAcknowledged: boolean }) =>
    api<Escrow>(`/v1/escrow/${id}/protection`, { method: 'PUT', body }),
  /** The receipt for one release as a PDF (audited). */
  releaseReceipt: (releaseId: string) => api<Blob>(`/v1/escrow/releases/${releaseId}/receipt`, { blob: true }),
  fund: (id: string, body: { milestoneIds?: string[]; all?: boolean; paymentMethodToken: string }) =>
    api<Escrow>(`/v1/escrow/${id}/fund`, { method: 'POST', body, headers: idem() }),
  autoFunding: (id: string, paymentMethodToken: string | null) =>
    api<Escrow>(`/v1/escrow/${id}/auto-funding`, { method: 'PUT', body: { paymentMethodToken } }),
  overview: (organizationId: string) => api<PaymentsOverview>(`/v1/escrow/organization/${organizationId}/overview`),
  bulkFund: (items: { accountId: string; milestoneIds: string[] }[], paymentMethodToken: string) =>
    api<{ funded: number; failed: number; results: { accountId: string; ok: boolean; code?: string; detail?: string }[] }>(
      '/v1/escrow/bulk-fund', { method: 'POST', body: { items, paymentMethodToken }, headers: idem() }),
}

export const paymentsApi = {
  configuration: () => api<{ provider: string; configured: boolean; testMode: boolean; hostedCheckout: boolean; hostedOnboarding: boolean }>('/v1/payments/configuration'),
  checkout: (fundingId: string) => api<{ status: string; url: string | null }>(`/v1/payments/fundings/${fundingId}/checkout`),
  onboarding: () => api<{ url: string; status: string }>('/v1/payout-accounts/me/onboarding', { method: 'POST', headers: idem() }),
  earnings: () => api<Earnings>('/v1/payments/earnings/me'),
  setPayoutAccount: (body: { holderName: string; country: string; currency: string; accountNumber: string }) =>
    api<Earnings['payoutAccount']>('/v1/payout-accounts/me', { method: 'PUT', body }),
  invoices: (organizationId: string) => allPages<Invoice>('/v1/payments/invoices', { organizationId }),
  /** The invoice as a PDF (members of the buyer organisation; audited). */
  invoicePdf: (id: string) => api<Blob>(`/v1/payments/invoices/${id}/pdf`, { blob: true }),
  payoutPdf: (id: string) => api<Blob>(`/v1/payments/payouts/${id}/pdf`, { blob: true }),
  charges: (organizationId: string) => allPages<Charge>('/v1/payments/charges', { organizationId }),
  refunds: (organizationId: string) => allPages<Refund>('/v1/payments/refunds', { organizationId }),
  opsWorklist: (includeResolved = false) =>
    api<{ items: OpsItem[]; open: number }>('/v1/payments/ops/worklist', { query: includeResolved ? { includeResolved: 'true' } : {} }),
  opsRetry: (kind: 'PAYOUT' | 'REFUND', id: string) => api<{ items: OpsItem[]; open: number }>(`/v1/payments/ops/${kind}/${id}/retry`, { method: 'POST' }),
  /** A maker-checker request (202): the item is closed only when a second Financial Operations member approves it. */
  opsResolve: (kind: OpsItem['kind'], id: string, outcome: 'RECOVERED' | 'WRITTEN_OFF' | 'SETTLED_OUTSIDE', note: string) =>
    api<ApprovalRequest>(`/v1/payments/ops/${kind}/${id}/resolve`, { method: 'POST', body: { outcome, note } }),
  reconciliations: () => api<Reconciliation[]>('/v1/payments/reconciliations'),
  reconcile: (day: string) => api<Reconciliation>('/v1/payments/reconciliations', { method: 'POST', body: { day } }),
  reconciliationBreaks: (status?: BreakStatus) =>
    api<ReconciliationBreak[]>('/v1/payments/reconciliation-breaks', { query: status ? { status } : {} }),
  /** One step on: OPEN -> EVIDENCE_GATHERING -> REVIEWED -> CLOSED (closing needs step-up and a different person from the reviewer). */
  advanceBreak: (id: string, status: Exclude<BreakStatus, 'OPEN'>, note: string) =>
    api<ReconciliationBreak>(`/v1/payments/reconciliation-breaks/${id}/advance`, { method: 'POST', body: { status, note } }),
}

// Test-mode payment methods from the (fake) payment provider. A real provider's card form returns a token like these.
export const TEST_CARDS: [string, string][] = [['tok_visa', 'Test Visa •••• 4242 (succeeds)'], ['tok_mastercard', 'Test Mastercard •••• 4444 (succeeds)'],
  ['tok_fail', 'Test card that is declined']]

export const ALLOCATION_STATE: Record<AllocationState, { label: string; tone: '' | 'green' | 'warn' }> = {
  UNFUNDED: { label: 'Not funded', tone: '' }, FUNDING: { label: 'Payment processing', tone: 'warn' }, HELD: { label: 'Held in escrow', tone: 'green' },
  ON_HOLD: { label: 'Frozen (dispute)', tone: 'warn' }, RELEASE_PENDING_APPROVAL: { label: 'Release awaiting approval', tone: 'warn' },
  RELEASED: { label: 'Released', tone: 'green' }, PARTIALLY_RELEASED: { label: 'Partly released', tone: 'warn' }, REFUNDED: { label: 'Refunded', tone: '' },
  CANCELLED: { label: 'Cancelled', tone: '' }, EXPIRED: { label: 'Expired (never funded)', tone: '' },
}
export const PAYOUT_STATUS: Record<Payout['status'], { label: string; tone: '' | 'green' | 'warn' }> = {
  QUEUED: { label: 'Waiting for payout account', tone: 'warn' }, INITIATED: { label: 'Sending', tone: 'warn' },
  SETTLED: { label: 'Paid out', tone: 'green' }, FAILED: { label: 'Failed', tone: '' },
}
