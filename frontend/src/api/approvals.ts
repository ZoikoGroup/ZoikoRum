import { api } from './client'

/* Maker-checker approvals for privileged staff actions (backend admin/approvals.py). One staff member asks, a different
   person holding the required role approves, and only then is the action carried out: REQUESTED -> APPLIED | FAILED,
   or REJECTED | EXPIRED | CANCELLED. Asking and deciding both need a fresh two-step code. */

export type ApprovalKind = 'GRANT_PLATFORM_ROLE' | 'REVOKE_PLATFORM_ROLE' | 'SWITCH_CHANGE' | 'FINANCIAL_EXCEPTION_RESOLVE'
  | 'DEAD_LETTER_REPLAY_FINANCIAL' | 'AUDIT_EXPORT'
export type ApprovalStatus = 'REQUESTED' | 'APPLIED' | 'FAILED' | 'REJECTED' | 'EXPIRED' | 'CANCELLED'

export interface ApprovalPerson { id: string; displayName: string | null; email: string | null }

export interface ApprovalRequest {
  id: string
  kind: ApprovalKind
  status: ApprovalStatus
  summary: string
  payload: Record<string, unknown>
  justification: string
  requestedBy: ApprovalPerson
  requestedAt: string
  expiresAt: string
  approverRoles: string[]
  decidedBy: ApprovalPerson | null
  decidedAt: string | null
  decisionNote: string | null
  appliedAt: string | null
  applyError: string | null
  result: Record<string, unknown> | null
  canDecide: boolean
  canCancel: boolean
}

export interface ApprovalSummary { awaitingMe: number; myOpen: number; applied7d: number; rejectedOrExpired7d: number; failed7d: number }

export const KIND_LABEL: Record<ApprovalKind, string> = {
  GRANT_PLATFORM_ROLE: 'Grant staff role',
  REVOKE_PLATFORM_ROLE: 'Remove staff role',
  SWITCH_CHANGE: 'Operational switch',
  FINANCIAL_EXCEPTION_RESOLVE: 'Close financial exception',
  DEAD_LETTER_REPLAY_FINANCIAL: 'Replay money event',
  AUDIT_EXPORT: 'Audit export',
}

export const STATUS_LABEL: Record<ApprovalStatus, string> = {
  REQUESTED: 'Awaiting approval',
  APPLIED: 'Approved · applied',
  FAILED: 'Approved · failed',
  REJECTED: 'Rejected',
  EXPIRED: 'Expired',
  CANCELLED: 'Cancelled',
}

/** Who may approve, in words, for the "awaiting approval by another …" message. */
export function approverText(roles: string[]): string {
  const names: Record<string, string> = {
    PLATFORM_ADMIN: 'Platform Admin', FINANCIAL_OPS: 'Financial Operations member', COMPLIANCE_OFFICER: 'Compliance Officer', LEGAL: 'Legal reviewer',
  }
  return roles.map((r) => names[r] ?? r.toLowerCase().replace(/_/g, ' ')).join(' or ')
}

/** The notice every privileged action shows instead of "done": nothing has changed yet. */
export function submittedNotice(r: ApprovalRequest): string {
  return `Request submitted — awaiting approval by another ${approverText(r.approverRoles)}. Nothing changes until it is approved.`
}

export const approvalsApi = {
  list: (filters: { status?: string; kind?: string; mine?: boolean; awaitingMe?: boolean; limit?: number; offset?: number } = {}) =>
    api<ApprovalRequest[]>('/v1/admin/approval-requests', {
      query: Object.fromEntries(Object.entries(filters).filter(([, v]) => v !== undefined && v !== '' && v !== false).map(([k, v]) => [k, String(v)])),
    }),
  summary: () => api<ApprovalSummary>('/v1/admin/approval-requests/summary'),
  get: (id: string) => api<ApprovalRequest>(`/v1/admin/approval-requests/${id}`),
  create: (kind: ApprovalKind, payload: Record<string, unknown>, justification: string) =>
    api<ApprovalRequest>('/v1/admin/approval-requests', { method: 'POST', body: { kind, payload, justification } }),
  decide: (id: string, approve: boolean, note?: string) =>
    api<ApprovalRequest>(`/v1/admin/approval-requests/${id}/decision`, { method: 'POST', body: { approve, note: note || null } }),
  cancel: (id: string) => api<ApprovalRequest>(`/v1/admin/approval-requests/${id}/cancel`, { method: 'POST' }),
}
