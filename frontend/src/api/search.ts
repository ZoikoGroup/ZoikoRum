import { api } from './client'
import type { Money } from './orgs'

export interface SearchResult {
  professionalId: string
  photoUrl: string | null
  displayName: string
  headline: string | null
  country: string
  city: string | null
  specializations: { slug: string; name: string; primary: boolean }[]
  engagementTypes: string[]
  deliveryModes: string[]
  pricingModels: string[]
  availability: string
  startingPrice: Money | null
  tier: 'A' | 'B' | 'C'
  tierLabel: string
  trustScore: number
  whyThisResult: string[]
  dimensions: Record<string, string>
  languages: string[]
  yearsExperienceBand: string | null
}

export interface Facet { value: string; label: string; count: number }
export interface SearchResponse { total: number; items: SearchResult[]; facets: Record<string, Facet[]> }

export type SearchQuery = Partial<Record<
  'q' | 'category' | 'spec' | 'specMatch' | 'tier' | 'verified' | 'engagementType' | 'delivery' | 'availability' |
  'pricingModel' | 'credential' | 'jurisdiction' | 'experience' | 'publishedAfter' | 'sort' | 'limit' | 'offset', string>>

export const searchApi = {
  professionals: (query: SearchQuery) => {
    const clean = Object.fromEntries(Object.entries(query).filter(([, v]) => v)) as Record<string, string>
    return api<SearchResponse>('/v1/search/professionals', { query: clean })
  },
}
