import { api } from './client'
import type { StoredFile, Upload } from './files'

export interface PolicyVersion { id: string; number: number; status: string; label: string; settings: Record<string, unknown>; rules: PolicyRule[] }
export interface PolicyRule { id: string; appliesTo: string[]; condition: Record<string, unknown>; decision: string; reasonCode: string; message: string; approval?: { mode: string; steps: { role: string; count: number }[]; timeoutHours: number; escalationRole: string } }
export interface PolicyProfile { id: string; orgId: string; name: string; description: string; status: string; version: number; activeVersionId: string | null; draftVersionId: string | null; versions: PolicyVersion[] }
export interface Approval { id: string; orgId: string; subjectType: string; subjectId: string; action: string; status: string; deadline: string; requesterIdentityId: string; workflows: { mode: string; steps: { id: string; role: string; count: number }[] }[]; reasons: { message: string }[]; votes: { id: string; identityId: string; stepId: string; role: string; reason: string; decision: string; valid: boolean }[] }
export interface ExceptionRequest { id: string; subjectType: string; subjectId: string; action: string; status: string; justification: string; documents: StoredFile[]; expiresAt: string; decisionReason: string | null; emergency?: boolean }
export interface Page<T> { items: T[]; nextCursor: string | null }
export interface PolicyChecks { checks: { severity: 'ERROR' | 'WARNING' | 'INFO'; code: string; message: string; rule: string | null }[]; appliesTo: string[]; riskLevel: string; version: string }
export interface PolicyDashboard {
  days: number; activeProfiles: number; draftProfiles: number; evaluations: number; decisions: Record<string, number>; interventionRate: number | null
  approvals: { requested: number; pending: number; granted: number; denied: number; expired: number; medianHoursToDecide: number | null }
  exceptions: { requested: number; granted: number; denied: number; emergency: number; rate: number | null }
  spendHeldBack: { currency: string; amountMinor: number }[]; topReasons: { code: string; count: number }[]
}
/** Procurement setup wizard progress; needsPolicySetup: no policy profile yet ("Define your policy"). */
export interface PolicySetup {
  orgId: string; needsPolicySetup: boolean; hasProfile: boolean; hasActivePolicy: boolean; engagements: number; firstEngagement: boolean
  complete: boolean; steps: { key: 'ORGANISATION' | 'POLICY' | 'APPROVERS' | 'BUDGETS'; label: string; done: boolean }[]
  facts: { orgType?: string; basicsComplete?: boolean; members?: number; roles?: Record<string, number>; businessUnits?: number; costCenters?: number; budgetedCostCenters?: number; legalEntities?: number }
}
/** Live policy indicators of one engagement (GET /v1/policy/engagement-indicators). */
export interface EngagementIndicator {
  contractId: string; policyVersion: string; riskLevel: 'LOW' | 'MEDIUM' | 'HIGH'; riskReasons: string[]
  exception: { flag: boolean; open: number; granted: number; latestStatus: string | null; emergency: boolean }
  approvals: {
    total: number; pending: number; granted: number; denied: number; expired: number
    current: { id: string; action: string; subjectType: string; status: string; stepsDone: number; stepsRequired: number; nextRole: string | null; deadline: string } | null
  }
}
export const policyApi = {
  setup: (orgId: string) => api<PolicySetup>('/v1/policy/setup', { query: { orgId } }),
  /** Up to 100 contracts of the organisation; others are left out. */
  indicators: (orgId: string, contractIds: string[]) =>
    api<{ items: EngagementIndicator[] }>(`/v1/policy/engagement-indicators?orgId=${orgId}${contractIds.map((c) => `&contractIds=${c}`).join('')}`),
  profiles: (orgId: string, cursor?: string) => api<Page<PolicyProfile>>(`/v1/policy/profiles?orgId=${orgId}${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ''}`),
  create: (body: { orgId: string; name: string; description: string; template: string; businessUnitIds?: string[]; riskLevel?: string; settings?: Record<string, unknown> }) => api<PolicyProfile>('/v1/policy/profiles', { headers: { 'Idempotency-Key': crypto.randomUUID() }, method: 'POST', body }),
  dryRun: (body: { orgId: string; action: string; subjectType: string; subjectId: string; attributes: Record<string, unknown>; previewProfileId: string }) => api<{ decision: string; reasons: { message: string }[] }>('/v1/policy/dry-run', { headers: { 'Idempotency-Key': crypto.randomUUID() }, method: 'POST', body }),
  save: (id: string, version: number, settings: Record<string, unknown>, rules: PolicyRule[]) => api<PolicyProfile>(`/v1/policy/profiles/${id}/draft`, { headers: { 'Idempotency-Key': crypto.randomUUID() }, method: 'PUT', body: { version, settings, rules } }),
  draft: (id: string) => api<PolicyProfile>(`/v1/policy/profiles/${id}/draft`, { headers: { 'Idempotency-Key': crypto.randomUUID() }, method: 'POST' }),
  activate: (id: string) => api<PolicyProfile>(`/v1/policy/profiles/${id}/activate`, { headers: { 'Idempotency-Key': crypto.randomUUID() }, method: 'POST' }),
  impact: (id: string) => api<{ eligibleProfessionals: number; scope: string }>(`/v1/policy/profiles/${id}/impact`),
  approvals: (orgId: string, cursor?: string) => api<Page<Approval>>(`/v1/policy/approvals?orgId=${orgId}${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ''}`),
  decide: (id: string, decision: 'GRANT' | 'DENY', reason: string, stepId?: string) => api<Approval>(`/v1/policy/approvals/${id}/decide`, { headers: { 'Idempotency-Key': crypto.randomUUID() }, method: 'POST', body: { decision, reason, stepId } }),
  exceptions: (orgId: string, cursor?: string) => api<Page<ExceptionRequest>>(`/v1/policy/exceptions?orgId=${orgId}${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ''}`),
  checks: (id: string) => api<PolicyChecks>(`/v1/policy/profiles/${id}/checks`),
  dashboard: (orgId: string, days = 30) => api<PolicyDashboard>('/v1/policy/dashboard', { query: { orgId, days: String(days) } }),
  requestException: (body: { orgId: string; subjectType: string; subjectId: string; action: string; justification: string; documents: Upload[]; expiresAt: string; emergency?: boolean }) => api<ExceptionRequest>('/v1/policy/exceptions', { headers: { 'Idempotency-Key': crypto.randomUUID() }, method: 'POST', body }),
  decideException: (id: string, decision: 'GRANT' | 'DENY', reason: string) => api<ExceptionRequest>(`/v1/policy/exceptions/${id}/decide`, { headers: { 'Idempotency-Key': crypto.randomUUID() }, method: 'POST', body: { decision, reason } }),
}
