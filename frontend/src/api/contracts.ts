import { api } from './client'
import type { StoredFile, Upload } from './files'
import type { Money } from './orgs'

/* Contracts & engagements (Step 7): the agreement generated from an accepted proposal, signatures (buyer first,
   then the professional; each needs a fresh two-step confirmation) and milestones. */

export type ContractStatus = 'PENDING_SIGNATURE' | 'ACTIVE' | 'COMPLETED' | 'TERMINATED' | 'DISPUTED'
export type MilestoneStatus = 'PENDING_FUNDING' | 'IN_PROGRESS' | 'SUBMITTED' | 'REVISION_REQUESTED' | 'ACCEPTANCE_PENDING_APPROVAL'
  | 'ACCEPTED' | 'DISPUTED' | 'CANCELLED'

export interface ContractMilestone {
  id: string
  sequence: number
  title: string
  description: string
  amount: Money
  dueDate: string | null
  deliverableKeys: string[]
  status: MilestoneStatus
  startedAt: string | null
  submittedAt: string | null
  acceptanceDueAt: string | null
  reviewOverdue: boolean
  acceptedAt: string | null
  revisionCount: number
  lastRevisionReason: string | null
  submissions: { id: string; note: string; files: StoredFile[]; submittedAt: string }[]
  partialOffer: { amount: Money; refund: Money; reason: string; offeredAt: string } | null
  acceptedRelease: Money | null
}

export interface ContractTerms {
  objective: string
  scope: string
  deliverables: { key: string; title: string; description: string; acceptanceCriteria: string }[]
  milestones: { sequence: number; title: string; amountMinor: number; dueDate: string | null; deliverableKeys: string[] }[]
  assumptions: string[]
  exclusions: string[]
  startDate: string | null
  endDate: string | null
  governingLaw?: string  // set by an enterprise policy; otherwise the Terms of Service apply
}

export interface ChangeOrder {
  id: string
  contractId: string
  proposedByIdentityId: string
  proposerParty: 'BUYER' | 'PROFESSIONAL'
  type: 'ADD_DELIVERABLE' | 'MODIFY_DELIVERABLE' | 'EXTEND_TIMELINE' | 'PRICING_CHANGE'
  delta: Record<string, unknown>
  impact: string
  baseContractVersion: number
  status: 'PROPOSED' | 'APPROVED' | 'REJECTED'
  decidedByIdentityId: string | null
  decisionReason: string | null
  decidedAt: string | null
  appliedVersion: number | null
  createdAt: string
  preview: { label: string; before: string; after: string }[]
}

export interface ContractRevision {
  contractVersion: number
  changeOrderId: string | null
  currency: string
  total: Money
  terms: ContractTerms
  milestones: { id: string; sequence: number; title: string; amountMinor: number; currency: string; dueDate: string | null; deliverableKeys: string[] }[]
  termsHash: string
  documentSha256: string
  createdAt: string
}

export interface Contract {
  id: string
  reference: string
  proposalId: string
  requestId: string
  organizationId: string
  professionalId: string
  title: string
  engagementType: string
  pricingModel: string | null
  status: ContractStatus
  pendingChangeOrderId: string | null
  total: Money
  termsHash: string
  contractVersion: number
  parties: { role: 'BUYER' | 'PROFESSIONAL'; name: string; detail: string | null }[]
  terms: ContractTerms
  ndaRequired: boolean
  documentSha256: string
  policyVersionLabel: string
  signatureDeadline: string
  activatedAt: string | null
  completedAt: string | null
  signatures: { party: 'BUYER' | 'PROFESSIONAL'; signerName: string; contractVersion: number; termsHash: string; authStrength: string; signedAt: string }[]
  changeOrders: ChangeOrder[]
  revisions: ContractRevision[]
  milestones: ContractMilestone[]
  viewerRole: 'BUYER' | 'PROFESSIONAL' | 'OPERATOR'
  nextAction: string
  canSign: boolean
  acceptedAmount: Money
  /** End at once (nothing in escrow, no dispute) or ask the other side to agree (money is held). */
  canEndNow: boolean
  pausedAt?: string | null
  pauseReason?: string | null
  canRequestEnd: boolean
  terminationRequest: TerminationRequest | null
  createdAt: string
  version: number
}

export interface TerminationRequest {
  id: string
  requesterParty: 'BUYER' | 'PROFESSIONAL'
  reason: string
  status: 'PENDING' | 'AGREED' | 'DECLINED' | 'WITHDRAWN' | 'LAPSED' | 'CANCELLED'
  expiresAt: string
  decisionNote: string | null
  decidedAt: string | null
  createdAt: string
  canAnswer: boolean
  canWithdraw: boolean
}

export interface ActivityEntry { at: string; what: string; action: string; by: string; hash: string }
export interface EngagementFile { source: string; name: string; sha256: string; size: number; uploadedAt: string | null; url: string }

export interface ContractSummary { role: 'buyer' | 'professional'; contracts: Partial<Record<ContractStatus, number>>; milestones: Partial<Record<MilestoneStatus, number>> }

const C = '/v1/contracts'
const idem = () => ({ 'Idempotency-Key': crypto.randomUUID() })

export const deliveredFileUrl = (contractId: string, sha256: string) => `${C}/${contractId}/files/${sha256}`

export const contractApi = {
  list: (role: 'buyer' | 'professional', status?: string) =>
    api<{ items: Contract[] }>(C, { query: { role, limit: '100', ...(status ? { status } : {}) } }).then((r) => r.items),
  summary: (role: 'buyer' | 'professional') => api<ContractSummary>(`${C}/summary`, { query: { role } }),
  get: (id: string) => api<Contract>(`${C}/${id}`),
  document: (id: string, version?: number) => api<string>(
    version ? `${C}/${id}/versions/${version}/document` : `${C}/${id}/document`, { text: true },
  ),
  /** The agreement as a PDF with its SHA-256 on every page (audited). */
  documentPdf: (id: string, version?: number) => api<Blob>(
    version ? `${C}/${id}/versions/${version}/document.pdf` : `${C}/${id}/document.pdf`, { blob: true },
  ),
  sign: (id: string, termsHash: string) => api<Contract>(`${C}/${id}/sign`, { method: 'POST', body: { termsHash }, headers: idem() }),
  proposeChange: (id: string, body: { type: ChangeOrder['type']; delta: Record<string, unknown>; impact: string }) =>
    api<Contract>(`${C}/${id}/change-orders`, { method: 'POST', body, headers: idem() }),
  approveChange: (changeOrderId: string) =>
    api<Contract>(`/v1/change-orders/${changeOrderId}/approve`, { method: 'POST', headers: idem() }),
  rejectChange: (changeOrderId: string, reason?: string) =>
    api<Contract>(`/v1/change-orders/${changeOrderId}/reject`, { method: 'POST', body: reason ? { reason } : {}, headers: idem() }),
  submit: (milestoneId: string, note: string, files: Upload[]) =>
    api<Contract>(`/v1/milestones/${milestoneId}/submit`, { method: 'POST', body: { note, files } }),
  accept: (milestoneId: string) => api<Contract>(`/v1/milestones/${milestoneId}/accept`, { method: 'POST', headers: idem() }),
  offerPartial: (milestoneId: string, amountMinor: number, reason: string) =>
    api<Contract>(`/v1/milestones/${milestoneId}/partial-acceptance`, { method: 'POST', body: { amountMinor, reason } }),
  answerPartial: (milestoneId: string, agree: boolean) =>
    api<Contract>(`/v1/milestones/${milestoneId}/partial-acceptance/${agree ? 'agree' : 'decline'}`, { method: 'POST', headers: idem() }),
  cancelRemainingCycles: (id: string, reason: string) =>
    api<Contract>(`${C}/${id}/cancel-remaining-cycles`, { method: 'POST', body: { reason }, headers: idem() }),
  activity: (id: string) => api<ActivityEntry[]>(`${C}/${id}/activity`),
  policyState: (id: string) => api<PolicyState>(`${C}/${id}/policy-state`),
  pause: (id: string, reason?: string) => api<Contract>(`${C}/${id}/pause`, { method: 'POST', body: { reason: reason || null } }),
  resume: (id: string) => api<Contract>(`${C}/${id}/resume`, { method: 'POST' }),
  files: (id: string) => api<EngagementFile[]>(`${C}/${id}/all-files`),
  evidencePack: (id: string, format: 'pdf' | 'json') => api<Blob>(`${C}/${id}/evidence-pack`, { query: { format }, blob: true }),
  terminate: (id: string, reason: string, mutual: boolean) =>
    api<Contract>(`${C}/${id}/terminate`, { method: 'POST', body: { reason, mutual }, headers: idem() }),
  answerTermination: (id: string, agree: boolean, note?: string) =>
    api<Contract>(`${C}/${id}/termination/decision`, { method: 'POST', body: { agree, note: note || null }, headers: idem() }),
  withdrawTermination: (id: string) => api<Contract>(`${C}/${id}/termination/withdraw`, { method: 'POST' }),
  requestRevision: (milestoneId: string, reason: string) =>
    api<Contract>(`/v1/milestones/${milestoneId}/request-revision`, { method: 'POST', body: { reason } }),
}

export const CONTRACT_STATUS: Record<ContractStatus, { label: string; tone: '' | 'green' | 'warn' }> = {
  PENDING_SIGNATURE: { label: 'Awaiting signatures', tone: 'warn' }, ACTIVE: { label: 'Active', tone: 'green' },
  COMPLETED: { label: 'Completed', tone: 'green' }, TERMINATED: { label: 'Terminated', tone: '' }, DISPUTED: { label: 'Disputed', tone: 'warn' },
}
export const MILESTONE_STATUS: Record<MilestoneStatus, { label: string; tone: '' | 'green' | 'warn' }> = {
  PENDING_FUNDING: { label: 'Awaiting funding', tone: '' }, IN_PROGRESS: { label: 'In progress', tone: 'warn' },
  SUBMITTED: { label: 'Submitted for review', tone: 'warn' }, REVISION_REQUESTED: { label: 'Revision requested', tone: 'warn' },
  ACCEPTANCE_PENDING_APPROVAL: { label: 'Awaiting approval', tone: 'warn' }, ACCEPTED: { label: 'Accepted', tone: 'green' },
  DISPUTED: { label: 'Disputed', tone: 'warn' }, CANCELLED: { label: 'Cancelled', tone: '' },
}

/** What the engagement's agreed policy would decide for the next money actions (buyer side only). */
export interface PolicyState {
  contractId: string
  policyVersion: string
  actions: { action: 'ESCROW_FUND' | 'MILESTONE_ACCEPT' | 'ESCROW_RELEASE'; label: string; milestoneId: string; milestone: string
    decision: 'ALLOW' | 'REQUIRE_APPROVAL' | 'REQUIRE_EXCEPTION' | 'BLOCK'; reasons: { code: string; message: string }[] }[]
}
