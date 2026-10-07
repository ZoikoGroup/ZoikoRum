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
  milestones: ContractMilestone[]
  viewerRole: 'BUYER' | 'PROFESSIONAL' | 'OPERATOR'
  nextAction: string
  canSign: boolean
  acceptedAmount: Money
  createdAt: string
  version: number
}

export interface ContractSummary { role: 'buyer' | 'professional'; contracts: Partial<Record<ContractStatus, number>>; milestones: Partial<Record<MilestoneStatus, number>> }

const C = '/v1/contracts'
const idem = () => ({ 'Idempotency-Key': crypto.randomUUID() })

export const deliveredFileUrl = (contractId: string, sha256: string) => `${C}/${contractId}/files/${sha256}`

export const contractApi = {
  list: (role: 'buyer' | 'professional', status?: string) =>
    api<{ items: Contract[] }>(C, { query: { role, limit: '100', ...(status ? { status } : {}) } }).then((r) => r.items),
  summary: (role: 'buyer' | 'professional') => api<ContractSummary>(`${C}/summary`, { query: { role } }),
  get: (id: string) => api<Contract>(`${C}/${id}`),
  document: (id: string) => api<string>(`${C}/${id}/document`, { text: true }),
  sign: (id: string, termsHash: string) => api<Contract>(`${C}/${id}/sign`, { method: 'POST', body: { termsHash }, headers: idem() }),
  submit: (milestoneId: string, note: string, files: Upload[]) =>
    api<Contract>(`/v1/milestones/${milestoneId}/submit`, { method: 'POST', body: { note, files } }),
  accept: (milestoneId: string) => api<Contract>(`/v1/milestones/${milestoneId}/accept`, { method: 'POST', headers: idem() }),
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
