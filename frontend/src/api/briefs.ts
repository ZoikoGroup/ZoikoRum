import { api } from './client'
import type { Money } from './orgs'

/** Open briefs: a buyer describes a need once; matching professionals say they are interested (backend proposal/briefs.py). */

export interface BriefInterest {
  professional: { id: string; displayName: string; headline: string | null; photoUrl: string | null; tier: 'A' | 'B' | 'C'; country: string | null }
  note: string
  createdAt: string
}

export interface OpenBrief {
  id: string
  organizationId: string | null  // hidden from professionals
  country: string
  industry: string | null
  service: string
  specialization: string
  specializationName: string
  objective: string
  details: string
  desiredStartDate: string | null
  estimatedDuration: string | null
  budget: { minMinor: number | null; maxMinor: number; currency: string } | null
  status: 'OPEN' | 'CLOSED'
  closesAt: string
  createdAt: string
  interests: BriefInterest[] | null  // the buyer's view only
  interestCount: number
  myInterest: boolean
}

export interface BriefInput {
  organizationId: string
  service: string
  specialization: string
  objective: string
  details?: string
  desiredStartDate?: string | null
  estimatedDuration?: string | null
  budget?: { maxMinor: number; currency: string } | null
}

const B = '/v1/open-briefs'

export const briefApi = {
  post: (body: BriefInput) => api<OpenBrief>(B, { method: 'POST', body }),
  mine: (organizationId: string) => api<OpenBrief[]>(`${B}/mine`, { query: { organizationId } }),
  close: (id: string) => api<OpenBrief>(`${B}/${id}/close`, { method: 'POST' }),
  matching: () => api<OpenBrief[]>(`${B}/matching`),
  interest: (id: string, note: string) => api<OpenBrief>(`${B}/${id}/interest`, { method: 'POST', body: { note } }),
}

export const briefBudget = (b: OpenBrief): Money | null => (b.budget ? { amountMinor: b.budget.maxMinor, currency: b.budget.currency } : null)
