import { api } from './client'

export interface SavedProfessional {
  professionalId: string
  displayName: string
  headline: string | null
  primarySpecialization: string | null
  tier: 'A' | 'B' | 'C'
  availability: string
  available: boolean
  savedAt: string
}

export const savedApi = {
  list: () => api<SavedProfessional[]>('/v1/saved/professionals'),
  save: (professionalId: string) => api<void>('/v1/saved/professionals', { method: 'POST', body: { professionalId } }),
  remove: (professionalId: string) => api<void>(`/v1/saved/professionals/${professionalId}`, { method: 'DELETE' }),
}

export interface AdminOverview {
  accounts: { total: number; buyers: number; professionals: number; firmAdmins: number; enterprise: number }
  professionalProfiles: { total: number; published: number }
  verification: { open: number; overdue: number }
}

export const adminApi = {
  overview: () => api<AdminOverview>('/v1/admin/overview'),
}
