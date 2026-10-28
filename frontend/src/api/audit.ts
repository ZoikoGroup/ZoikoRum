import { api } from './client'

export interface AuditRecord {
  id: string
  seq: number
  action: string
  actorId: string | null
  objectType: string
  objectId: string
  details: Record<string, unknown>
  occurredAt: string
}

export const auditApi = {
  /** Latest audit-ledger records for an organization (Org Admin or Legal Reviewer). */
  recent: (tenantId: string, limit = 8) =>
    api<{ items: AuditRecord[] }>('/v1/audit/records', { query: { tenantId, limit: String(limit), newestFirst: 'true' } })
      .then((r) => r.items),
}

/** Staff (Compliance Officer, Legal, Platform Admin): latest records across the platform. */
export const platformActivity = (limit = 30) =>
  api<{ items: AuditRecord[] }>('/v1/audit/records', { query: { limit: String(limit), newestFirst: 'true' } }).then((r) => r.items)

export interface ChainCheck { valid: boolean; checked: number; headHash?: string; brokenAtSeq?: number }

/** Compliance Officers and Platform Admins: recompute every hash of the audit ledger, in order. A broken link also
    raises a HashChainBroken incident. */
export const verifyAuditChain = () => api<ChainCheck>('/v1/audit/chain/verify', { method: 'POST' })

/** Org Admins / Legal Reviewers: export the organisation's audit records as CSV (hash-chained ledger). */
export async function exportAuditCsv(tenantId: string): Promise<string> {
  const job = await api<{ id: string }>('/v1/audit/exports', { method: 'POST', body: { tenantId, format: 'csv' } })
  return api<string>(`/v1/audit/exports/${job.id}/download`, { text: true })
}

export type AuditFormat = 'pdf' | 'csv' | 'json'

/** Org Admins / Legal Reviewers: the organisation's audit log as a file (PDF, CSV or JSON), built on the server. */
export async function exportAuditFile(tenantId: string, format: AuditFormat): Promise<Blob> {
  const job = await api<{ id: string }>('/v1/audit/exports', { method: 'POST', body: { tenantId, format } })
  return api<Blob>(`/v1/audit/exports/${job.id}/download`, { blob: true })
}
