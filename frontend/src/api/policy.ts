import { api } from './client'
import type { StoredFile, Upload } from './files'

export interface PolicyVersion { id: string; number: number; status: string; label: string; settings: Record<string, unknown>; rules: PolicyRule[] }
export interface PolicyRule { id: string; appliesTo: string[]; condition: Record<string, unknown>; decision: string; reasonCode: string; message: string; approval?: { mode: string; steps: { role: string; count: number }[]; timeoutHours: number; escalationRole: string } }
export interface PolicyProfile { id: string; orgId: string; name: string; description: string; status: string; version: number; activeVersionId: string | null; draftVersionId: string | null; versions: PolicyVersion[] }
export interface Approval { id: string; orgId: string; subjectType: string; subjectId: string; action: string; status: string; deadline: string; requesterIdentityId: string; workflows: { mode: string; steps: { id: string; role: string; count: number }[] }[]; reasons: { message: string }[]; votes: { id: string; identityId: string; stepId: string; role: string; reason: string; decision: string; valid: boolean }[] }
export interface ExceptionRequest { id: string; subjectType: string; subjectId: string; action: string; status: string; justification: string; documents: StoredFile[]; expiresAt: string; decisionReason: string | null }
export interface Page<T> { items: T[]; nextCursor: string | null }
export const policyApi = {
  profiles: (orgId: string, cursor?: string) => api<Page<PolicyProfile>>(`/v1/policy/profiles?orgId=${orgId}${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ''}`),
  create: (body: { orgId: string; name: string; description: string; template: string; businessUnitIds?: string[]; riskLevel?: string }) => api<PolicyProfile>('/v1/policy/profiles', { method: 'POST', body }),
  dryRun: (body: { orgId: string; action: string; subjectType: string; subjectId: string; attributes: Record<string, unknown>; previewProfileId: string }) => api<{ decision: string; reasons: { message: string }[] }>('/v1/policy/dry-run', { method: 'POST', body }),
  save: (id: string, version: number, settings: Record<string, unknown>, rules: PolicyRule[]) => api<PolicyProfile>(`/v1/policy/profiles/${id}/draft`, { method: 'PUT', body: { version, settings, rules } }),
  draft: (id: string) => api<PolicyProfile>(`/v1/policy/profiles/${id}/draft`, { method: 'POST' }),
  activate: (id: string) => api<PolicyProfile>(`/v1/policy/profiles/${id}/activate`, { method: 'POST' }),
  impact: (id: string) => api<{ eligibleProfessionals: number; scope: string }>(`/v1/policy/profiles/${id}/impact`),
  approvals: (orgId: string, cursor?: string) => api<Page<Approval>>(`/v1/policy/approvals?orgId=${orgId}${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ''}`),
  decide: (id: string, decision: 'GRANT' | 'DENY', reason: string, stepId?: string) => api<Approval>(`/v1/policy/approvals/${id}/decide`, { method: 'POST', body: { decision, reason, stepId } }),
  exceptions: (orgId: string, cursor?: string) => api<Page<ExceptionRequest>>(`/v1/policy/exceptions?orgId=${orgId}${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ''}`),
  requestException: (body: { orgId: string; subjectType: string; subjectId: string; action: string; justification: string; documents: Upload[]; expiresAt: string }) => api<ExceptionRequest>('/v1/policy/exceptions', { method: 'POST', body }),
  decideException: (id: string, decision: 'GRANT' | 'DENY', reason: string) => api<ExceptionRequest>(`/v1/policy/exceptions/${id}/decide`, { method: 'POST', body: { decision, reason } }),
}
