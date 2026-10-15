import { api } from './client'

export type SupportTopic = 'ACCOUNT' | 'VERIFICATION' | 'REQUESTS_PROPOSALS' | 'ENGAGEMENT' | 'PAYMENTS' | 'DISPUTE' | 'TECHNICAL' | 'OTHER'

export interface SupportMessage { id: string; fromStaff: boolean; authorName: string; body: string; createdAt: string }
export interface SupportRequest {
  id: string
  reference: string
  topic: SupportTopic
  subject: string
  status: 'OPEN' | 'WAITING_ON_YOU' | 'RESOLVED'
  context: { page?: string; contractId?: string; engagement?: string; errorReference?: string }
  firstResponseDueAt: string
  firstRespondedAt: string | null
  overdue: boolean
  resolvedAt: string | null
  requesterName: string | null
  assignedToName: string | null
  messages: SupportMessage[]
  createdAt: string
  updatedAt: string
}

export const SUPPORT_TOPICS: [SupportTopic, string][] = [
  ['ACCOUNT', 'My account or signing in'], ['VERIFICATION', 'Verification and Trust Tier'], ['REQUESTS_PROPOSALS', 'Requests and proposals'],
  ['ENGAGEMENT', 'An engagement or contract'], ['PAYMENTS', 'Payments, payouts or refunds'], ['DISPUTE', 'A dispute'],
  ['TECHNICAL', 'Something is not working'], ['OTHER', 'Something else'],
]

export const SUPPORT_STATUS: Record<SupportRequest['status'], { label: string; tone: '' | 'green' | 'warn' }> = {
  OPEN: { label: 'With our team', tone: '' }, WAITING_ON_YOU: { label: 'Answered: your reply?', tone: 'warn' }, RESOLVED: { label: 'Resolved', tone: 'green' },
}

export const supportApi = {
  open: (body: { topic: SupportTopic; subject: string; message: string; context: { page?: string; contractId?: string; errorReference?: string } }) =>
    api<SupportRequest>('/v1/support/requests', { method: 'POST', body }),
  mine: () => api<SupportRequest[]>('/v1/support/requests'),
  get: (id: string) => api<SupportRequest>(`/v1/support/requests/${id}`),
  reply: (id: string, message: string) => api<SupportRequest>(`/v1/support/requests/${id}/messages`, { method: 'POST', body: { message } }),
  resolve: (id: string) => api<SupportRequest>(`/v1/support/requests/${id}/resolve`, { method: 'POST' }),
  queue: (status?: string) => api<SupportRequest[]>('/v1/admin/support/requests', { query: status ? { status } : {} }),
  agentGet: (id: string) => api<SupportRequest>(`/v1/admin/support/requests/${id}`),
  agentReply: (id: string, message: string, resolve: boolean) =>
    api<SupportRequest>(`/v1/admin/support/requests/${id}/messages`, { method: 'POST', body: { message, resolve } }),
}
