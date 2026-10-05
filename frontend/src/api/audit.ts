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
