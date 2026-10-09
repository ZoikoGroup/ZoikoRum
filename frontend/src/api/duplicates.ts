import { api } from './client'

export interface DuplicateCase {
  id: string; signal: string; status: 'OPEN' | 'ANSWERED' | 'MERGED' | 'NOT_DUPLICATE'; userAnswer: 'MERGE_REQUESTED' | 'NOT_ME' | null
  userNote: string | null; resolutionNote: string | null; createdAt: string; resolvedAt: string | null
  account: string | null; accountName: string | null; otherAccount: string | null; otherAccountName: string | null
  identityId: string | null; otherIdentityId: string | null
}

export const duplicatesApi = {
  mine: () => api<DuplicateCase[]>('/v1/me/duplicate-accounts'),
  answer: (id: string, answer: 'MERGE_REQUESTED' | 'NOT_ME', note?: string) =>
    api<DuplicateCase>(`/v1/me/duplicate-accounts/${id}/answer`, { method: 'POST', body: { answer, note } }),
  queue: () => api<DuplicateCase[]>('/v1/admin/duplicate-accounts'),
  resolve: (id: string, body: { outcome: 'MERGED' | 'NOT_DUPLICATE'; keepIdentityId?: string; note: string }) =>
    api<DuplicateCase>(`/v1/admin/duplicate-accounts/${id}/resolve`, { method: 'POST', body }),
}
