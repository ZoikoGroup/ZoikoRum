import { api } from './client'
import type { Money } from './orgs'

// ---- Capability taxonomy (public) ----------------------------------------------

export interface TaxonomySpecialization {
  slug: string
  name: string
  requiresCredential: boolean
  regulated: boolean
  deliverableTemplates: string[]
  credentialHints: string[]
}
export interface TaxonomyGroup extends TaxonomySpecialization { specializations: TaxonomySpecialization[] }
export interface TaxonomyCategory extends TaxonomySpecialization { version: number; groups: TaxonomyGroup[] }

export interface SpecializationMatch { slug: string; name: string; groupName: string; categoryName: string }
export interface SpecializationDraft { name: string; categorySlug: string | null; groupSlug: string | null; description: string; credentialLikely: boolean }
export interface SpecializationSuggestion {
  id: string; text: string; name: string; categorySlug: string | null; groupSlug: string | null; description: string; credentialLikely: boolean
  source: string; status: 'PENDING' | 'APPROVED' | 'MERGED' | 'REJECTED'; resolvedSlug: string | null; resolutionNote: string | null
  professionalId: string | null; professionalName: string | null; createdAt: string; resolvedAt: string | null
}

export const taxonomyApi = {
  all: () => api<{ categories: TaxonomyCategory[] }>('/v1/taxonomy', { auth: false }).then((r) => r.categories),
  /** "Can't find yours?": match your own words to existing specializations (AI when configured, keywords otherwise). */
  suggest: (text: string) => api<{ matches: SpecializationMatch[]; draft: SpecializationDraft | null; source: string }>('/v1/taxonomy/suggest', { method: 'POST', body: { text } }),
  submitSuggestion: (body: { text: string; name: string; categorySlug?: string | null; groupSlug?: string | null; description?: string; credentialLikely?: boolean; source?: string }) =>
    api<SpecializationSuggestion>('/v1/taxonomy/suggestions', { method: 'POST', body }),
  mySuggestions: () => api<SpecializationSuggestion[]>('/v1/taxonomy/suggestions/mine'),
  queue: () => api<SpecializationSuggestion[]>('/v1/admin/taxonomy/suggestions'),
  decide: (id: string, body: { action: 'APPROVE' | 'MERGE' | 'REJECT'; name?: string; groupSlug?: string; requiresCredential?: boolean; regulated?: boolean; mergeSlug?: string; note?: string }) =>
    api<SpecializationSuggestion>(`/v1/admin/taxonomy/suggestions/${id}/decision`, { method: 'POST', body }),
}

// ---- Professional profile ----------------------------------------------------

export const ENGAGEMENT_TYPES = ['ADVISORY', 'PROJECT', 'RETAINER', 'FRACTIONAL'] as const
export const DELIVERY_MODES = ['REMOTE', 'ONSITE', 'HYBRID'] as const
export const PRICING_MODELS = ['HOURLY', 'FIXED', 'RETAINER', 'CUSTOM'] as const
export const AVAILABILITY = ['NOW', 'TWO_WEEKS', 'ONE_MONTH', 'NOT_SPECIFIED'] as const
export const EXPERIENCE_BANDS = ['0-2', '3-5', '6-10', '11-15', '16+'] as const
export const RATE_UNITS = ['HOUR', 'DAY', 'MONTH', 'PROJECT'] as const
export const CREDENTIAL_TYPES = ['LICENSE', 'CERTIFICATION', 'MEMBERSHIP', 'DEGREE'] as const
export const CURRENCIES = ['USD', 'GBP', 'EUR', 'INR', 'CAD', 'AUD', 'SGD', 'AED', 'ZAR'] as const

export type EngagementType = (typeof ENGAGEMENT_TYPES)[number]
export type DeliveryMode = (typeof DELIVERY_MODES)[number]
export type PricingModel = (typeof PRICING_MODELS)[number]
export type Availability = (typeof AVAILABILITY)[number]

export const LABEL: Record<string, string> = {
  ADVISORY: 'Advisory', PROJECT: 'Project', RETAINER: 'Retainer', FRACTIONAL: 'Fractional',
  REMOTE: 'Remote', ONSITE: 'On-site', HYBRID: 'Hybrid',
  HOURLY: 'Hourly', FIXED: 'Fixed fee', CUSTOM: 'Quote on request',
  NOW: 'Available now', TWO_WEEKS: 'Within 2 weeks', ONE_MONTH: 'Within a month', NOT_SPECIFIED: 'Not specified',
  AT_CAPACITY: 'At capacity',
  LICENSE: 'Licence', CERTIFICATION: 'Certification', MEMBERSHIP: 'Professional membership', DEGREE: 'Degree',
  DRAFT: 'Draft', PUBLISHED: 'Published', UNPUBLISHED: 'Unpublished', SUSPENDED: 'Suspended',
  ACTIVE: 'Active', PAUSED: 'Paused',
}
// Separate map: PROJECT is both an engagement type ("Project") and a rate unit ("per project").
export const RATE_UNIT_LABEL: Record<string, string> = { HOUR: 'per hour', DAY: 'per day', MONTH: 'per month', PROJECT: 'per project' }

export interface SpecializationRef { slug: string; name: string; primary: boolean; requiresCredential: boolean; regulated: boolean }

export interface Profile {
  pendingSpecializations?: string[]  // suggested, waiting for an admin
  id: string
  photoUrl: string | null
  firmId: string | null
  status: 'DRAFT' | 'PUBLISHED' | 'UNPUBLISHED' | 'SUSPENDED'
  displayName: string
  legalName: string | null
  headline: string | null
  yearsExperienceBand: string | null
  bio: string | null
  languages: string[]
  country: string
  city: string | null
  website: string | null
  primaryCategory: string | null
  specializations: SpecializationRef[]
  engagementTypes: EngagementType[]
  deliveryModes: DeliveryMode[]
  pricingModels: PricingModel[]
  indicativeRate: Money | null
  rateUnit: string | null
  availability: Availability
  maxConcurrentEngagements: number | null
  temporarilyUnavailable: boolean
  weeklyHours?: number | null
  servedJurisdictions: string[]
  licensedJurisdictions: string[]
  crossBorderAcknowledged: boolean
  publishedAt: string | null
  version: number
}

export interface ProfilePatch {
  displayName?: string
  legalName?: string
  headline?: string
  yearsExperienceBand?: string
  bio?: string
  languages?: string[]
  city?: string
  country?: string
  website?: string
  engagementTypes?: EngagementType[]
  deliveryModes?: DeliveryMode[]
  pricingModels?: PricingModel[]
  indicativeRate?: Money | null
  rateUnit?: string
  clearRate?: boolean
}

export interface ReadinessItem { key: string; label: string; done: boolean; required: boolean }
export interface Readiness { canPublish: boolean; items: ReadinessItem[] }

export interface Credential {
  id: string
  credentialType: string
  name: string
  issuingBody: string
  registrationNumber: string | null
  jurisdiction: string | null
  issuedOn: string | null
  expiresOn: string | null
  specialization: string | null
  status: string
  displayLabel: string
}
export interface CredentialInput {
  credentialType: string
  name: string
  issuingBody: string
  registrationNumber?: string
  jurisdiction?: string
  issuedOn?: string
  expiresOn?: string
  specialization?: string
}

export interface Offering {
  id: string
  title: string
  specialization: string
  specializationName: string | null
  summary: string | null
  deliverables: string[]
  engagementTypes: EngagementType[]
  pricingModel: PricingModel
  startingPrice: Money | null
  typicalDuration: string | null
  status: 'DRAFT' | 'ACTIVE' | 'PAUSED'
  version: number
}
export interface OfferingInput {
  title: string
  specialization: string
  summary?: string
  deliverables: string[]
  engagementTypes: EngagementType[]
  pricingModel: PricingModel
  startingPrice?: Money | null
  clearStartingPrice?: boolean
  typicalDuration?: string
}

export interface PublicProfile {
  id: string
  photoUrl: string | null
  displayName: string
  headline: string | null
  yearsExperienceBand: string | null
  bio: string | null
  languages: string[]
  country: string
  city: string | null
  primaryCategory: string | null
  primaryCategoryName: string | null
  specializations: SpecializationRef[]
  engagementTypes: string[]
  deliveryModes: string[]
  pricingModels: string[]
  indicativeRate: Money | null
  rateUnit: string | null
  availability: string
  weeklyHours?: number | null
  servedJurisdictions: string[]
  licensedJurisdictions: string[]
  credentials: { name: string; issuingBody: string; jurisdiction: string | null; status: string; displayLabel: string }[]
  offerings: Offering[]
  trust: { tier: 'A' | 'B' | 'C'; dimensions: Record<string, string>; explanation: string[]; updatedAt: string | null }
  verifiedJurisdictions: string[]
  publishedAt: string | null
  isOwnProfile: boolean
  history: { completedEngagements: number; onTimeRate: number | null; medianResponseHours: number | null; newToPlatform: boolean } | null
  firm: { id: string; name: string; verified: boolean } | null
  pendingSpecializations?: string[]
}

const P = '/v1/professionals'
/** Professional Dashboard s.17: a buyer organisation in the professional's client list. */
export interface SavedBuyer {
  id: string; organizationId: string; name: string; country: string | null; note: string | null; alerts: boolean
  requests: number; engagements: number; completed: number; lastActivityAt: string | null; savedAt: string
}
export interface BuyerCandidate {
  organizationId: string; name: string; country: string | null; saved: boolean
  requests: number; engagements: number; completed: number; lastActivityAt: string | null
}

export const proApi = {
  savedBuyers: () => api<SavedBuyer[]>(`${P}/me/saved-buyers`),
  buyerCandidates: () => api<BuyerCandidate[]>(`${P}/me/buyer-candidates`),
  saveBuyer: (organizationId: string) => api<SavedBuyer>(`${P}/me/saved-buyers`, { method: 'POST', body: { organizationId } }),
  updateSavedBuyer: (id: string, body: { note?: string; alerts?: boolean }) =>
    api<SavedBuyer>(`${P}/me/saved-buyers/${id}`, { method: 'PATCH', body }),
  removeSavedBuyer: (id: string) => api<void>(`${P}/me/saved-buyers/${id}`, { method: 'DELETE' }),
  create: (body: { firmId?: string | null }) => api<Profile>(P, { method: 'POST', body }),
  setFirm: (firmId: string | null) => api<Profile>(`${P}/me/firm`, { method: 'PUT', body: { firmId } }),
  me: () => api<Profile>(`${P}/me`),
  setPhoto: (contentType: string, dataBase64: string) =>
    api<Profile>(`${P}/me/photo`, { method: 'PUT', body: { contentType, dataBase64 } }),
  removePhoto: () => api<Profile>(`${P}/me/photo`, { method: 'DELETE' }),
  update: (version: number, body: ProfilePatch) =>
    api<Profile>(`${P}/me`, { method: 'PATCH', body, headers: { 'If-Match': String(version) } }),
  setSpecializations: (primary: string, secondary: string[]) =>
    api<Profile>(`${P}/me/specializations`, { method: 'PUT', body: { primary, secondary } }),
  setJurisdictions: (body: { served: string[]; licensed: string[]; crossBorderAcknowledged: boolean }) =>
    api<Profile>(`${P}/me/jurisdictions`, { method: 'PUT', body }),
  setAvailability: (body: { availability: Availability; maxConcurrentEngagements: number | null; temporarilyUnavailable: boolean; weeklyHours?: number | null }) =>
    api<Profile>(`${P}/me/availability`, { method: 'PUT', body }),
  readiness: () => api<Readiness>(`${P}/me/readiness`),
  publish: () => api<Profile>(`${P}/me/publish`, { method: 'POST', body: { attestAccurate: true } }),
  unpublish: () => api<Profile>(`${P}/me/unpublish`, { method: 'POST' }),
  credentials: () => api<Credential[]>(`${P}/me/credentials`),
  addCredential: (body: CredentialInput) => api<Credential>(`${P}/me/credentials`, { method: 'POST', body }),
  withdrawCredential: (id: string) => api<void>(`${P}/me/credentials/${id}`, { method: 'DELETE' }),
  offerings: () => api<Offering[]>(`${P}/me/offerings`),
  createOffering: (body: OfferingInput) => api<Offering>(`${P}/me/offerings`, { method: 'POST', body }),
  updateOffering: (id: string, version: number, body: Partial<OfferingInput>) =>
    api<Offering>(`${P}/me/offerings/${id}`, { method: 'PATCH', body, headers: { 'If-Match': String(version) } }),
  activateOffering: (id: string) => api<Offering>(`${P}/me/offerings/${id}/activate`, { method: 'POST' }),
  pauseOffering: (id: string) => api<Offering>(`${P}/me/offerings/${id}/pause`, { method: 'POST' }),
  publicProfile: (id: string) => api<PublicProfile>(`${P}/${id}`),
}

/** Major-unit text ("1500.50") <-> integer minor units. Two-decimal currencies only for now. */
export const toMinor = (major: string) => Math.round(Number(major) * 100)
export const toMajor = (m: Money | null) => (m ? String(m.amountMinor / 100) : '')
