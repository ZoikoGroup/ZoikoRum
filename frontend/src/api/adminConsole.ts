import { api } from './client'

/* Staff-wide read models for the admin console (organisations, professionals, contracts, protected funds,
   configuration). Every list is cursor-paged like /v1/admin/users; each has a summary endpoint for the KPI cards. */

export interface Page<T> { items: T[]; nextCursor: string | null }

const query = (filters: Record<string, string | null | undefined>) =>
  Object.fromEntries(Object.entries(filters).filter(([, v]) => v)) as Record<string, string>

export interface AdminOrganization {
  id: string; name: string; kind: 'BUYER' | 'ENTERPRISE' | 'FIRM'; status: string; country: string | null; industry: string | null
  memberCount: number; verificationStatus: string | null; contractCount: number; createdAt: string
  primaryContact: { name: string; email: string } | null
}
export interface AdminOrganizationSummary { total: number; buyer: number; enterprise: number; firm: number; suspended: number; newLast30Days: number }

export interface AdminProfessional {
  id: string; identityId: string; displayName: string; headline: string | null; specialization: string | null; category: string | null
  country: string | null; tier: 'A' | 'B' | 'C' | null; publication: 'PUBLISHED' | 'DRAFT' | 'IN_REVIEW' | 'RESTRICTED'
  verification: { identity: string; credentials: string; jurisdiction: string }
  activeEngagements: number; lifetimeEngagements: number; createdAt: string
}
export interface AdminProfessionalSummary {
  total: number; published: number; inReview: number; draft: number; restricted: number; identityVerified: number
  tiers: { A: number; B: number; C: number }
}

export interface AdminMilestone { id: string; sequence: number; title: string; status: string; amountMinor: number; dueDate: string | null }
export interface AdminContract {
  id: string; title: string; status: string; version: number; currency: string; totalMinor: number
  buyer: { organizationId: string; name: string; country: string | null }
  professional: { id: string; name: string; country: string | null }
  milestones: AdminMilestone[]; fundedMinor: number; releasedMinor: number; hasOpenDispute: boolean
  createdAt: string; signedAt: string | null; updatedAt: string
}
export interface AdminContractSummary { total: number; byStatus: Record<string, number>; milestonesByStatus: Record<string, number>; openDisputes: number }

export interface AdminEscrowRow {
  id: string; contractId: string; contractTitle: string; milestoneId: string | null; milestoneSequence: number | null
  buyerName: string; professionalName: string; currency: string; amountMinor: number; status: string
  provider: string | null; providerReference: string | null; updatedAt: string
}
export interface AdminEscrowSummary { buckets: { status: string; currency: string; count: number; amountMinor: number }[] }

export interface AdminConfig {
  environment: string; version: string | null
  groups: { domain: string; settings: { key: string; value: string; description: string | null }[] }[]
}

export const adminConsoleApi = {
  organizations: (f: { q?: string; kind?: string; status?: string; cursor?: string | null } = {}) =>
    api<Page<AdminOrganization>>('/v1/admin/organizations', { query: query({ ...f, limit: '50' }) }),
  organizationSummary: () => api<AdminOrganizationSummary>('/v1/admin/organizations/summary'),
  professionals: (f: { q?: string; publication?: string; tier?: string; country?: string; cursor?: string | null } = {}) =>
    api<Page<AdminProfessional>>('/v1/admin/professionals', { query: query({ ...f, limit: '50' }) }),
  professionalSummary: () => api<AdminProfessionalSummary>('/v1/admin/professionals/summary'),
  contracts: (f: { q?: string; status?: string; cursor?: string | null } = {}) =>
    api<Page<AdminContract>>('/v1/admin/contracts', { query: query({ ...f, limit: '50' }) }),
  contractSummary: () => api<AdminContractSummary>('/v1/admin/contracts/summary'),
  escrow: (f: { status?: string; currency?: string; cursor?: string | null } = {}) =>
    api<Page<AdminEscrowRow>>('/v1/admin/escrow', { query: query({ ...f, limit: '50' }) }),
  escrowSummary: () => api<AdminEscrowSummary>('/v1/admin/escrow/summary'),
  config: () => api<AdminConfig>('/v1/admin/config'),
}
