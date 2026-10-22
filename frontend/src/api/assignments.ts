import { api } from './client'

/* Case owners across the staff console (admin/assignments.py). One owner per case, any workstream; escalations are
   flagged with a reason. Support requests use their own owner field (assignedTo), which these endpoints read and write. */

export type CaseKind = 'VERIFICATION_CASE' | 'VERIFICATION_APPEAL' | 'ENFORCEMENT_CASE' | 'DISPUTE' | 'SUPPORT_REQUEST' | 'DUPLICATE'
  | 'ENTERPRISE_APPLICATION' | 'TAXONOMY_SUGGESTION' | 'PAYMENT_EXCEPTION' | 'DEAD_LETTER'

export interface Assignment {
  kind: CaseKind
  caseId: string
  ownerId: string | null
  ownerName: string | null
  escalated: boolean
  escalationReason: string | null
  escalatedAt: string | null
  updatedBy: string | null
  updatedByName: string | null
  updatedAt: string | null
}

export interface AssignableStaff { id: string; name: string; email: string; roles: string[]; you: boolean }

export const assignmentKey = (kind: CaseKind, caseId: string) => `${kind}:${caseId}`

const path = (kind: CaseKind, caseId: string) => `/v1/admin/assignments/${kind}/${encodeURIComponent(caseId)}`

export const assignmentsApi = {
  list: (q: { kinds?: CaseKind[]; ownerId?: string; mine?: boolean } = {}) =>
    api<Assignment[]>('/v1/admin/assignments', { query: {
      ...(q.kinds?.length ? { kinds: q.kinds.join(',') } : {}), ...(q.ownerId ? { ownerId: q.ownerId } : {}), ...(q.mine ? { mine: 'true' } : {}),
    } }),
  assignable: (kind: CaseKind) => api<AssignableStaff[]>('/v1/admin/assignable-staff', { query: { kind } }),
  /** Assign or reassign; ownerId null releases the case. */
  setOwner: (kind: CaseKind, caseId: string, ownerId: string | null, note?: string) =>
    api<Assignment>(path(kind, caseId), { method: 'PUT', body: { ownerId, ...(note ? { note } : {}) } }),
  escalate: (kind: CaseKind, caseId: string, reason: string) =>
    api<Assignment>(`${path(kind, caseId)}/escalate`, { method: 'POST', body: { reason } }),
  deEscalate: (kind: CaseKind, caseId: string) => api<Assignment>(`${path(kind, caseId)}/de-escalate`, { method: 'POST' }),
}
