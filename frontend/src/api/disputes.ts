import { api } from './client'
import type { StoredFile, Upload } from './files'
import type { Money } from './orgs'

/* Disputes (Step 9): funds freeze on submission; evidence; structured direct resolution; mediation; a platform decision
   needs the mediator and a second reviewer with the Legal role; escrow executes the outcome and the case is sealed. */

export type DisputeCategory = 'SCOPE_DELIVERABLES' | 'QUALITY_ACCEPTANCE' | 'TIMELINE_DELAY' | 'PAYMENT_RELEASE' | 'PROFESSIONAL_CONDUCT'
  | 'COMPLIANCE_BREACH' | 'JURISDICTION_LEGAL'
export type DisputeOutcome = 'REWORK' | 'PARTIAL_RELEASE' | 'FULL_RELEASE' | 'PARTIAL_REFUND' | 'FULL_REFUND' | 'TIMELINE_EXTENSION' | 'TERMINATION'
export type DisputeStatus = 'EVIDENCE_COLLECTION' | 'DIRECT_RESOLUTION' | 'MEDIATION' | 'DECIDED' | 'ENFORCED' | 'CLOSED'
export type EvidenceType = 'CONTRACT_SCOPE' | 'MILESTONE_DEFINITION' | 'DELIVERABLE' | 'COMMUNICATION' | 'CHANGE_ORDER' | 'PAYMENT_RECORD' | 'THIRD_PARTY' | 'OTHER'

export interface Allocation { milestoneId: string; sequence: number; title: string; release: Money; refund: Money; milestoneOutcome: string }
export interface RawAllocation { milestoneId: string; releaseMinor: number; refundMinor: number; milestoneOutcome?: string }
export interface Resolution { outcome: DisputeOutcome; allocations: RawAllocation[]; summary: string; citations: string[]; acceptedBy?: string[]; rejectedBy?: string[] }

export interface Dispute {
  id: string
  reference: string
  contractId: string
  contractReference: string
  milestones: { id: string; sequence: number; title: string; amount: Money }[]
  category: DisputeCategory
  summary: string
  desiredOutcome: DisputeOutcome
  context: string
  initiatorParty: 'BUYER' | 'PROFESSIONAL' | 'PLATFORM'
  status: DisputeStatus
  disputed: Money
  evidenceDeadline: string
  evidenceComplete: string[]
  directDeadline: string | null
  mediatorAssigned: boolean
  recommendation: Resolution | null
  pendingDecision: (Resolution & { proposedBy: string }) | null
  decision: { plainSummary: string; outcome: DisputeOutcome; allocations: RawAllocation[]; decisionPath: 'DIRECT' | 'MEDIATION' | 'PLATFORM'
    evidenceReferences: string[]; policyCitations: string[]; appealEligible: boolean; appealNote: string } | null
  decidedAt: string | null
  closedAt: string | null
  evidence: { id: string; party: string; evidenceType: EvidenceType; description: string; items: StoredFile[]; submittedAt: string }[]
  proposals: { id: string; party: string; outcome: DisputeOutcome; allocations: Allocation[]; note: string; status: string; createdAt: string; respondedAt: string | null; mine: boolean }[]
  timeline: { kind: string; actor: string; text: string; at: string }[]
  viewerRole: 'BUYER' | 'PROFESSIONAL' | 'MEDIATOR' | 'OPERATOR'
  canEscalate: boolean
  nextStep: string
  createdAt: string
}

const D = '/v1/disputes'
const idem = () => ({ 'Idempotency-Key': crypto.randomUUID() })

export const disputeFileUrl = (disputeId: string, sha256: string) => `/v1/disputes/${disputeId}/files/${sha256}`

export const disputeApi = {
  open: (body: { contractId: string; milestoneIds: string[]; category: DisputeCategory; summary: string; desiredOutcome: DisputeOutcome; context: string }) =>
    api<Dispute>(D, { method: 'POST', body, headers: idem() }),
  list: (role: 'buyer' | 'professional' | 'operator', contractId?: string) =>
    api<Dispute[]>(D, { query: { role, ...(contractId ? { contractId } : {}) } }),
  get: (id: string) => api<Dispute>(`${D}/${id}`),
  addEvidence: (id: string, body: { evidenceType: EvidenceType; description: string; items: Upload[] }) =>
    api<Dispute>(`${D}/${id}/evidence`, { method: 'POST', body }),
  evidenceComplete: (id: string) => api<Dispute>(`${D}/${id}/evidence/complete`, { method: 'POST' }),
  propose: (id: string, body: { outcome: DisputeOutcome; allocations: RawAllocation[]; note: string }) =>
    api<Dispute>(`${D}/${id}/resolution-proposals`, { method: 'POST', body }),
  acceptProposal: (pid: string) => api<Dispute>(`/v1/resolution-proposals/${pid}/accept`, { method: 'POST', headers: idem() }),
  rejectProposal: (pid: string) => api<Dispute>(`/v1/resolution-proposals/${pid}/reject`, { method: 'POST' }),
  escalate: (id: string) => api<Dispute>(`${D}/${id}/escalate`, { method: 'POST' }),
  assignMediator: (id: string, mediatorIdentityId: string) => api<Dispute>(`${D}/${id}/assign-mediator`, { method: 'POST', body: { mediatorIdentityId } }),
  recommend: (id: string, body: { outcome: DisputeOutcome; allocations: RawAllocation[]; summary: string; citations: string[] }) =>
    api<Dispute>(`${D}/${id}/recommendation`, { method: 'POST', body }),
  answerRecommendation: (id: string, accept: boolean) =>
    api<Dispute>(`${D}/${id}/recommendation/${accept ? 'accept' : 'reject'}`, { method: 'POST', headers: accept ? idem() : undefined }),
  proposeDecision: (id: string, body: { outcome: DisputeOutcome; allocations: RawAllocation[]; summary: string; citations: string[] }) =>
    api<Dispute>(`${D}/${id}/decision`, { method: 'POST', body }),
  approveDecision: (id: string) => api<Dispute>(`${D}/${id}/decision/approve`, { method: 'POST', headers: idem() }),
}

export const CATEGORIES: [DisputeCategory, string][] = [
  ['SCOPE_DELIVERABLES', 'Scope & deliverables'], ['QUALITY_ACCEPTANCE', 'Quality / acceptance'], ['TIMELINE_DELAY', 'Timeline & delays'],
  ['PAYMENT_RELEASE', 'Payment & milestone release'], ['PROFESSIONAL_CONDUCT', 'Professional conduct'], ['COMPLIANCE_BREACH', 'Compliance / policy breach'],
  ['JURISDICTION_LEGAL', 'Jurisdictional or legal constraint'],
]
export const OUTCOMES: [DisputeOutcome, string][] = [
  ['REWORK', 'Rework'], ['PARTIAL_RELEASE', 'Partial release'], ['FULL_RELEASE', 'Full release'], ['PARTIAL_REFUND', 'Partial refund'],
  ['FULL_REFUND', 'Full refund'], ['TIMELINE_EXTENSION', 'Timeline extension'], ['TERMINATION', 'Engagement termination'],
]
export const EVIDENCE_TYPES: [EvidenceType, string][] = [
  ['DELIVERABLE', 'Deliverable'], ['CONTRACT_SCOPE', 'Contract & scope'], ['MILESTONE_DEFINITION', 'Milestone definition'],
  ['COMMUNICATION', 'Communication record'], ['CHANGE_ORDER', 'Change order'], ['PAYMENT_RECORD', 'Payment record'],
  ['THIRD_PARTY', 'Third-party document'], ['OTHER', 'Other'],
]
export const CATEGORY_LABEL = Object.fromEntries(CATEGORIES) as Record<DisputeCategory, string>
export const OUTCOME_LABEL = Object.fromEntries(OUTCOMES) as Record<DisputeOutcome, string>
export const PHASE: Record<DisputeStatus, { label: string; tone: '' | 'green' | 'warn' }> = {
  EVIDENCE_COLLECTION: { label: 'Evidence collection', tone: 'warn' }, DIRECT_RESOLUTION: { label: 'Direct resolution', tone: 'warn' },
  MEDIATION: { label: 'Mediation', tone: 'warn' }, DECIDED: { label: 'Decision issued', tone: 'green' }, ENFORCED: { label: 'Enforced', tone: 'green' },
  CLOSED: { label: 'Closed', tone: '' },
}
export const OPEN_PHASES: DisputeStatus[] = ['EVIDENCE_COLLECTION', 'DIRECT_RESOLUTION', 'MEDIATION']
