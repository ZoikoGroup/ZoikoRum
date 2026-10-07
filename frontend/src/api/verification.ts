import { api } from './client'
import type { Upload } from './files'

export type SubjectType = 'PROFESSIONAL' | 'FIRM'
export type SelfServiceType = 'IDENTITY' | 'JURISDICTION' | 'INSURANCE' | 'FIRM_REGISTRATION'
export type EvidenceType = 'ID_DOCUMENT' | 'PROOF_OF_ADDRESS' | 'LICENSE' | 'CERTIFICATE' | 'INSURANCE_POLICY' | 'REGISTRATION_DOCUMENT' | 'OTHER'

export interface Evidence {
  id: string; evidenceType: string; fileName: string; sha256: string; sizeBytes: number
  contentType: string | null; hasFile: boolean; uploadedAt: string
}
export type EvidenceContentType = 'application/pdf' | 'image/jpeg' | 'image/png'
export interface EvidenceUploadItem { name: string; sha256: string; size: number; contentType: EvidenceContentType; dataBase64: string }

export interface VerificationCase {
  id: string
  subjectType: SubjectType
  subjectId: string
  verificationType: string
  status: 'PENDING' | 'IN_REVIEW' | 'NEEDS_INFO' | 'VERIFIED' | 'FAILED' | 'EXPIRED' | 'REVOKED'
  label: string
  jurisdiction: string | null
  credentialClaimId: string | null
  specialization: string | null
  estimatedCompletion: string | null
  verifiedAt: string | null
  expiresAt: string | null
  reasonCode: string | null
  publicReason: string | null
  isMine: boolean
  evidence: Evidence[]
  createdAt: string
  version: number
}

export interface QueueItem {
  id: string
  subjectType: SubjectType
  subjectId: string
  subjectName: string | null
  verificationType: string
  status: string
  label: string
  jurisdiction: string | null
  providerResult: string | null
  evidenceCount: number
  estimatedCompletion: string | null
  overdue: boolean
  createdAt: string
}

export interface Trust {
  professionalId: string
  tier: 'A' | 'B' | 'C'
  tierLabel: string
  score: number | null  // owner and Trust & Safety only
  dimensions: Record<string, string>
  explanation: string[]
  updatedAt: string | null
}

export interface TrustHistory {
  tierChanges: { fromTier: string; toTier: string; reasons: string[]; at: string }[]
  signals: { type: string; adverse: boolean; summary: string; at: string }[]
  flags: string[]
}

const V = '/v1/verification'
export const verificationApi = {
  start: (body: { verificationType: SelfServiceType; subjectType: SubjectType; subjectId: string; jurisdiction?: string }) =>
    api<VerificationCase>(`${V}/cases`, { method: 'POST', body }),
  get: (id: string) => api<VerificationCase>(`${V}/cases/${id}`),
  forSubject: (type: SubjectType, id: string) => api<VerificationCase[]>(`${V}/subjects/${type}/${id}`),
  addEvidence: (id: string, evidenceType: EvidenceType, items: Upload[]) =>
    api<VerificationCase>(`${V}/cases/${id}/evidence`, { method: 'POST', body: { evidenceType, items } }),
  queue: (cursor?: string | null) =>
    api<{ items: QueueItem[]; nextCursor: string | null }>(`${V}/review-queue`, { query: cursor ? { cursor } : undefined }),
  decide: (id: string, body: { decision: 'VERIFIED' | 'FAILED' | 'NEEDS_INFO'; reasonCode: string; publicReason?: string; expiresAt?: string }) =>
    api<VerificationCase>(`${V}/cases/${id}/decision`, { method: 'POST', body }),
  revoke: (id: string, reasonCode: string, publicReason: string) =>
    api<VerificationCase>(`${V}/cases/${id}/revoke`, { method: 'POST', body: { reasonCode, publicReason } }),
}

export const trustApi = {
  get: (professionalId: string) => api<Trust>(`/v1/trust/professionals/${professionalId}`),
  history: (professionalId: string) => api<TrustHistory>(`/v1/trust/professionals/${professionalId}/history`),
}

/** Owner or reviewer opens an uploaded verification document (audited). */
export const evidenceFileUrl = (id: string) => `${V}/evidence/${id}/file`

export { sha256OfFile } from './files'

export const CASE_STATUS: Record<string, { label: string; cls: string }> = {
  PENDING: { label: 'Waiting for documents', cls: 'warn' },
  IN_REVIEW: { label: 'In review', cls: '' },
  NEEDS_INFO: { label: 'More information needed', cls: 'warn' },
  VERIFIED: { label: 'Verified', cls: 'green' },
  FAILED: { label: 'Not verified', cls: 'warn' },
  EXPIRED: { label: 'Expired', cls: 'warn' },
  REVOKED: { label: 'Revoked', cls: 'warn' },
}

// Plain-language dimension values (Homepage wireframe s.3.3).
export const DIMENSIONS: { key: string; label: string }[] = [
  { key: 'identity', label: 'Identity' },
  { key: 'credentials', label: 'Credentials' },
  { key: 'jurisdiction', label: 'Jurisdiction' },
  { key: 'restrictions', label: 'Restrictions' },
  { key: 'insurance', label: 'Insurance' },
]
export const DIMENSION_VALUE: Record<string, { label: string; good: boolean }> = {
  VERIFIED: { label: 'Verified', good: true }, VALIDATED: { label: 'Validated', good: true },
  ELIGIBLE: { label: 'Eligible', good: true }, CLEAR: { label: 'Clear', good: true },
  NOT_APPLICABLE: { label: 'Not applicable', good: true }, NOT_REQUIRED: { label: 'Not required', good: true },
  PARTIAL: { label: 'Partial', good: false }, PENDING: { label: 'Pending', good: false },
  NONE: { label: 'Not verified', good: false }, UNKNOWN: { label: 'Not verified', good: false },
  RESTRICTED: { label: 'Restricted', good: false }, FLAGGED: { label: 'Flagged', good: false },
}
