import { api } from './client'
import type { Money } from './orgs'

/* Requests & proposals (Step 6). A buyer sends one requirement to 1–3 chosen professionals; each answers with a
   structured proposal or declines. Commercial actions carry an Idempotency-Key so a double click never doubles up. */

export type RequestStatus = 'DRAFT' | 'OPEN' | 'PROPOSAL_RECEIVED' | 'CLOSED' | 'DECLINED' | 'CANCELLED'
export type ProposalStatus = 'DRAFT' | 'SUBMITTED' | 'UNDER_REVIEW' | 'REVISION_REQUESTED' | 'PENDING_APPROVAL' | 'ACCEPTED'
  | 'REJECTED' | 'WITHDRAWN' | 'EXPIRED'
export type EngagementType = 'ADVISORY' | 'PROJECT' | 'RETAINER' | 'FRACTIONAL'
export type Duration = 'ONE_TWO_WEEKS' | 'THREE_SIX_WEEKS' | 'TWO_THREE_MONTHS' | 'THREE_SIX_MONTHS' | 'ONGOING'
export type DeclineReason = 'OUT_OF_SCOPE' | 'NO_CAPACITY' | 'TIMELINE' | 'BUDGET' | 'CONFLICT_OF_INTEREST' | 'JURISDICTION' | 'OTHER'

export interface Budget { minMinor: number | null; maxMinor: number; currency: string }
export interface Attachment { name: string; sha256: string; size: number }
export interface ProfessionalBrief { id: string; displayName: string; headline: string | null; photoUrl: string | null; tier: 'A' | 'B' | 'C'; country: string | null }

export interface ProposalRequest {
  id: string
  groupId: string
  organizationId: string
  organizationName: string | null
  buyerIdentityId: string
  buyerName: string | null
  professional: ProfessionalBrief
  offeringId: string | null
  service: string
  specialization: string | null
  engagementType: EngagementType
  businessContext: string | null
  detailsHidden: boolean
  objective: string | null
  details: string | null
  location: string | null
  attachments: Attachment[]
  desiredStartDate: string
  estimatedDuration: Duration
  budget: Budget | null
  deliveryMode: 'REMOTE' | 'ONSITE' | 'HYBRID'
  ndaRequired: boolean
  ndaAccepted: boolean
  status: RequestStatus
  sentAt: string | null
  closedAt: string | null
  reasonCode: string | null
  reasonNote: string | null
  proposal: { id: string; status: ProposalStatus; total: Money; submittedAt: string | null; validUntil: string | null } | null
  groupSize: number
  viewerRole: 'BUYER' | 'PROFESSIONAL' | 'OPERATOR'
  createdAt: string
  version: number
}

export interface RequestInput {
  organizationId: string
  professionalIds: string[]
  offeringId?: string | null
  service: string
  specialization?: string | null
  engagementType: EngagementType
  businessContext?: string | null
  objective: string
  details: string
  desiredStartDate: string
  estimatedDuration: Duration
  budget?: Budget | null
  deliveryMode: 'REMOTE' | 'ONSITE' | 'HYBRID'
  location?: string | null
  ndaRequired: boolean
  attachments: Attachment[]
  acknowledged: boolean
  draft: boolean
}

export interface Deliverable { key: string; title: string; description: string; acceptanceCriteria: string }
export interface Milestone { title: string; description: string; amountMinor: number; dueDate: string | null; deliverableKeys: string[] }
export interface Delta { field: string; label: string; requested: string; proposed: string; status: 'MATCH' | 'WITHIN' | 'ABOVE' | 'BELOW' | 'EARLIER' | 'LATER' | 'CHANGED' }

export interface ProposalInput {
  summary: string
  scopeAlignment: 'CONFIRMED' | 'ADJUSTED'
  scopeNotes: string | null
  deliverables: Deliverable[]
  milestones: Milestone[]
  pricingModel: 'HOURLY' | 'FIXED' | 'RETAINER'
  currency: string
  startDate: string | null
  endDate: string | null
  assumptions: string[]
  exclusions: string[]
  validUntil: string | null
}

export interface Proposal extends ProposalInput {
  id: string
  requestId: string
  groupId: string
  organizationId: string
  professional: ProfessionalBrief
  status: ProposalStatus
  total: Money
  expired: boolean
  revisionRequests: { at: string; changes: { field: string; requested: string }[]; note: string | null }[]
  revisionCount: number
  submittedAt: string | null
  decidedAt: string | null
  reasonCode: string | null
  reasonNote: string | null
  termsHash: string | null
  deltas: Delta[]
  createdAt: string
  updatedAt: string
  version: number
}

export interface RequestSummary { role: 'buyer' | 'professional'; requests: Partial<Record<RequestStatus, number>>; proposals: Partial<Record<ProposalStatus, number>> }

const R = '/v1/proposal-requests'
const P = '/v1/proposals'
const idem = () => ({ 'Idempotency-Key': crypto.randomUUID() })

export const proposalApi = {
  createRequests: (body: RequestInput) => api<ProposalRequest[]>(R, { method: 'POST', body, headers: idem() }),
  list: (role: 'buyer' | 'professional', status?: string) =>
    api<{ items: ProposalRequest[]; nextCursor: string | null }>(R, { query: { role, limit: '100', ...(status ? { status } : {}) } }).then((r) => r.items),
  summary: (role: 'buyer' | 'professional') => api<RequestSummary>(`${R}/summary`, { query: { role } }),
  get: (id: string) => api<ProposalRequest>(`${R}/${id}`),
  send: (id: string) => api<ProposalRequest[]>(`${R}/${id}/send`, { method: 'POST', body: { acknowledged: true }, headers: idem() }),
  cancel: (id: string, note?: string) => api<ProposalRequest>(`${R}/${id}/cancel`, { method: 'POST', body: { note: note || null } }),
  acceptNda: (id: string) => api<ProposalRequest>(`${R}/${id}/accept-nda`, { method: 'POST' }),
  decline: (id: string, reasonCode: DeclineReason, note?: string) =>
    api<ProposalRequest>(`${R}/${id}/decline`, { method: 'POST', body: { reasonCode, note: note || null } }),
  proposals: (requestId: string) => api<Proposal[]>(`${R}/${requestId}/proposals`),
  createProposal: (requestId: string, body: ProposalInput) => api<Proposal>(`${R}/${requestId}/proposals`, { method: 'POST', body }),
  getProposal: (id: string) => api<Proposal>(`${P}/${id}`),
  updateProposal: (id: string, body: ProposalInput) => api<Proposal>(`${P}/${id}`, { method: 'PATCH', body }),
  submit: (id: string) => api<Proposal>(`${P}/${id}/submit`, { method: 'POST', headers: idem() }),
  withdraw: (id: string) => api<Proposal>(`${P}/${id}/withdraw`, { method: 'POST' }),
  requestRevision: (id: string, changes: { field: string; requested: string }[], note?: string) =>
    api<Proposal>(`${P}/${id}/request-revision`, { method: 'POST', body: { changes, note: note || null } }),
  reject: (id: string, note?: string) => api<Proposal>(`${P}/${id}/reject`, { method: 'POST', body: { reasonCode: 'NOT_SELECTED', note: note || null } }),
  accept: (id: string) => api<Proposal>(`${P}/${id}/accept`, { method: 'POST', headers: idem() }),
}

export const DURATIONS: [Duration, string][] = [
  ['ONE_TWO_WEEKS', '1–2 weeks'], ['THREE_SIX_WEEKS', '3–6 weeks'], ['TWO_THREE_MONTHS', '2–3 months'],
  ['THREE_SIX_MONTHS', '3–6 months'], ['ONGOING', 'Ongoing'],
]
export const DURATION_LABEL = Object.fromEntries(DURATIONS) as Record<Duration, string>
export const DECLINE_REASONS: [DeclineReason, string][] = [
  ['OUT_OF_SCOPE', 'Outside my expertise'], ['NO_CAPACITY', 'No capacity right now'], ['TIMELINE', 'Timeline does not work'],
  ['BUDGET', 'Budget does not fit'], ['CONFLICT_OF_INTEREST', 'Conflict of interest'], ['JURISDICTION', 'Jurisdiction restriction'],
  ['OTHER', 'Other'],
]

/** Plain-language status, from the viewer's point of view. */
export function requestStatus(r: ProposalRequest): { label: string; tone: '' | 'green' | 'warn' } {
  const p = r.proposal
  if (r.status === 'DRAFT') return { label: 'Draft', tone: '' }
  if (r.status === 'CANCELLED') return { label: 'Cancelled', tone: '' }
  if (r.status === 'DECLINED') return { label: 'Declined', tone: '' }
  if (p?.status === 'ACCEPTED') return { label: 'Accepted', tone: 'green' }
  if (p?.status === 'REVISION_REQUESTED') return { label: 'Revision requested', tone: 'warn' }
  if (p && ['SUBMITTED', 'UNDER_REVIEW'].includes(p.status)) return { label: r.viewerRole === 'BUYER' ? 'Proposal received' : 'Proposal sent', tone: 'green' }
  if (p?.status === 'EXPIRED') return { label: 'Expired', tone: '' }
  if (r.status === 'CLOSED') return { label: 'Closed', tone: '' }
  if (r.viewerRole === 'PROFESSIONAL') return { label: p?.status === 'DRAFT' ? 'Draft proposal' : 'Awaiting your proposal', tone: 'warn' }
  return { label: 'Awaiting proposal', tone: '' }
}

export const PROPOSAL_STATUS: Record<ProposalStatus, { label: string; tone: '' | 'green' | 'warn' }> = {
  DRAFT: { label: 'Draft', tone: '' }, SUBMITTED: { label: 'Awaiting review', tone: 'warn' }, UNDER_REVIEW: { label: 'Under review', tone: 'warn' },
  REVISION_REQUESTED: { label: 'Revision requested', tone: 'warn' }, PENDING_APPROVAL: { label: 'Pending approval', tone: 'warn' },
  ACCEPTED: { label: 'Accepted', tone: 'green' }, REJECTED: { label: 'Not selected', tone: '' }, WITHDRAWN: { label: 'Withdrawn', tone: '' },
  EXPIRED: { label: 'Expired', tone: '' },
}

export function budgetText(b: Budget | null): string {
  if (!b) return 'Open to proposal'
  const f = (m: number) => new Intl.NumberFormat(undefined, { style: 'currency', currency: b.currency, maximumFractionDigits: 0 }).format(m / 100)
  return b.minMinor ? `${f(b.minMinor)} – ${f(b.maxMinor)}` : `Up to ${f(b.maxMinor)}`
}
