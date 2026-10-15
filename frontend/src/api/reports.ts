import { api } from './client'

export type ReportSubject = 'PROFESSIONAL' | 'IDENTITY' | 'ORGANIZATION' | 'REVIEW' | 'MESSAGE'
export type ReportCategory = 'MISCONDUCT' | 'FRAUD_OR_SCAM' | 'MISREPRESENTATION' | 'HARASSMENT_OR_ABUSE' | 'OFF_PLATFORM_PAYMENT'
  | 'UNSAFE_OR_ILLEGAL' | 'FAKE_REVIEW' | 'OTHER'

export interface UserReport {
  id: string
  subjectType: ReportSubject
  subjectId: string
  category: ReportCategory
  categoryLabel: string
  description: string
  confidential: boolean
  status: 'RECEIVED' | 'CLOSED'
  outcome: 'ACTION_TAKEN' | 'NO_ACTION' | null
  createdAt: string
  updatedAt: string
  reporter?: string  // staff view only
  possibleRetaliation?: boolean  // staff view only
}

export const REPORT_CATEGORIES: [ReportCategory, string][] = [
  ['OFF_PLATFORM_PAYMENT', 'Asked to pay outside Zoikorum'], ['FRAUD_OR_SCAM', 'Fraud or scam'],
  ['MISREPRESENTATION', 'False credentials or misrepresentation'], ['HARASSMENT_OR_ABUSE', 'Harassment or abuse'],
  ['MISCONDUCT', 'Professional misconduct'], ['FAKE_REVIEW', 'Fake or abusive review'], ['UNSAFE_OR_ILLEGAL', 'Unsafe or illegal'],
  ['OTHER', 'Something else'],
]

export const reportApi = {
  submit: (body: { subjectType: ReportSubject; subjectId: string; category: ReportCategory; description: string; confidential: boolean }) =>
    api<UserReport>('/v1/reports', { method: 'POST', body }),
  mine: () => api<UserReport[]>('/v1/reports/mine'),
  forCase: (caseId: string) => api<UserReport[]>(`/v1/admin/enforcement-cases/${caseId}/reports`),
  closeCase: (caseId: string, reason: string) => api(`/v1/admin/enforcement-cases/${caseId}/close`, { method: 'POST', body: { reason } }),
}
