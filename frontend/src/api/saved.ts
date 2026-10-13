import { api } from './client'
import type { Money } from './orgs'

export interface SavedProfessional {
  professionalId: string
  displayName: string
  headline: string | null
  photoUrl: string | null
  city: string | null
  country: string | null
  languages: string[]
  yearsExperienceBand: string | null
  primarySpecialization: string | null
  specializations: string[]
  engagementTypes: string[]
  pricingModels: string[]
  startingPrice: Money | null
  tier: 'A' | 'B' | 'C'
  dimensions: Record<string, string>
  lastVerifiedAt: string | null
  availability: string
  available: boolean
  collectionIds: string[]
  savedAt: string
}

export interface Collection { id: string; name: string; count: number; updatedAt: string }

export interface CompareItem {
  professionalId: string
  displayName: string
  headline: string | null
  photoUrl: string | null
  country: string
  tier: 'A' | 'B' | 'C'
  dimensions: Record<string, string>
  verifiedCredentials: string[]
  specializations: string[]
  engagementTypes: string[]
  deliveryModes: string[]
  pricingModels: string[]
  startingPrice: Money | null
  availability: string
  yearsExperienceBand: string | null
  servedJurisdictions: string[]
  licensedJurisdictions: string[]
  languages: string[]
}

export interface SavedSearch { id: string; name: string; params: Record<string, string>; lastViewedAt: string; createdAt: string }

export const savedApi = {
  searches: () => api<SavedSearch[]>('/v1/saved/searches'),
  saveSearch: (name: string, params: Record<string, string>) => api<SavedSearch>('/v1/saved/searches', { method: 'POST', body: { name, params } }),
  searchViewed: (id: string) => api<SavedSearch>(`/v1/saved/searches/${id}/viewed`, { method: 'POST' }),
  deleteSearch: (id: string) => api<void>(`/v1/saved/searches/${id}`, { method: 'DELETE' }),
  list: () => api<SavedProfessional[]>('/v1/saved/professionals'),
  save: (professionalId: string) => api<void>('/v1/saved/professionals', { method: 'POST', body: { professionalId } }),
  remove: (professionalId: string) => api<void>(`/v1/saved/professionals/${professionalId}`, { method: 'DELETE' }),
  collections: () => api<Collection[]>('/v1/saved/collections'),
  createCollection: (name: string) => api<Collection>('/v1/saved/collections', { method: 'POST', body: { name } }),
  renameCollection: (id: string, name: string) => api<Collection>(`/v1/saved/collections/${id}`, { method: 'PATCH', body: { name } }),
  deleteCollection: (id: string) => api<void>(`/v1/saved/collections/${id}`, { method: 'DELETE' }),
  addToCollection: (id: string, professionalIds: string[]) =>
    api<Collection>(`/v1/saved/collections/${id}/items`, { method: 'POST', body: { professionalIds } }),
  removeFromCollection: (id: string, professionalId: string) =>
    api<void>(`/v1/saved/collections/${id}/items/${professionalId}`, { method: 'DELETE' }),
  compare: (ids: string[]) => api<CompareItem[]>('/v1/compare', { query: { ids: ids.join(',') } }),
}

export interface AdminOverview {
  accounts: { total: number; buyers: number; professionals: number; firmAdmins: number; enterprise: number }
  professionalProfiles: { total: number; published: number }
  verification: { open: number; overdue: number }
}

export const adminApi = {
  overview: () => api<AdminOverview>('/v1/admin/overview'),
}
