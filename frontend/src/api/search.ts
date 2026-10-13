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
  servedJurisdictions: string[]
  licensedJurisdictions: string[]
}

export interface Facet { value: string; label: string; count: number }
/** The buyer organisation's policy applied to the results, and how many professionals it left out. */
export interface PolicyFilter {
  organizationId: string; organizationName: string; minTier: string; requiredDimensions: string[]
  jurisdictions: string[] | null; hidden: number
}
export interface SearchResponse { total: number; items: SearchResult[]; facets: Record<string, Facet[]>; policy?: PolicyFilter | null }

export type SearchQuery = Partial<Record<
  'q' | 'category' | 'spec' | 'specMatch' | 'tier' | 'verified' | 'engagementType' | 'delivery' | 'availability' |
  'pricingModel' | 'credential' | 'jurisdiction' | 'experience' | 'publishedAfter' | 'sort' | 'limit' | 'offset', string>>

/** Filters suggested from the buyer's own words ("Describe what you need"), with one reason per filter. */
export interface IntentFilters {
  q: string | null; spec: string[]; engagementType: string | null; delivery: string | null; availability: string | null
  jurisdiction: string | null; verified: string[]
}
export interface IntentResponse { filters: IntentFilters; reasons: string[]; source: string }

export const searchApi = {
  professionals: (query: SearchQuery) => {
    const clean = Object.fromEntries(Object.entries(query).filter(([, v]) => v)) as Record<string, string>
    return api<SearchResponse>('/v1/search/professionals', { query: clean })
  },
  intent: (text: string) => api<IntentResponse>('/v1/search/intent', { method: 'POST', body: { text } }),
}
