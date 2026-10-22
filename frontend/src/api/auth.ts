import type { ApprovalRequest } from './approvals'
import { api, type TokenPair } from './client'

export type AccountType = 'BUYER' | 'PROFESSIONAL' | 'FIRM' | 'ENTERPRISE'
export type Persona = 'BUYER' | 'PROFESSIONAL' | 'FIRM_ADMIN' | 'ENTERPRISE_ADMIN' | 'ENTERPRISE_MEMBER'
export type Dashboard = 'buyer' | 'professional' | 'firm' | 'enterprise' | 'ops'

export const PLATFORM_ROLES = [
  'PLATFORM_ADMIN', 'TS_ANALYST', 'COMPLIANCE_OFFICER', 'RISK_LEAD', 'LEGAL',
  'MEDIATOR', 'FINANCIAL_OPS', 'EXECUTIVE', 'AI_SAFETY_REVIEWER', 'SUPPORT_AGENT',
] as const
export type PlatformRole = (typeof PLATFORM_ROLES)[number]

export interface User {
  id: string
  email: string
  displayName: string
  country: string
  status: string
  emailConfirmed: boolean
  mfaEnabled: boolean
  mfaRequired: boolean
  mfaBypass?: boolean  // development only: authenticator codes switched off
  personas: Persona[]
  primaryPersona: Persona | null
  platformRoles: PlatformRole[]
  organizationName: string | null
  defaultDashboard: Dashboard
  createdAt: string
}

export interface Passkey { id: string; name: string; backedUp: boolean; createdAt: string; lastUsedAt: string | null }

export interface AuthResult {
  tokens: TokenPair
  user: User
}

export interface RegisterInput {
  email: string
  password: string
  displayName: string
  country: string
  accountType: AccountType
  organizationName?: string
  acceptTerms: true
}

/** One account in the staff Users list. */
export interface UserRow {
  id: string
  email: string
  displayName: string
  country: string
  personas: string[]
  platformRoles: string[]
  status: 'ACTIVE' | 'SUSPENDED' | 'DELETED'
  emailConfirmed: boolean
  mfaEnabled: boolean
  createdAt: string
  lastSignInAt: string | null
}
export type UserRoleFilter = '' | 'BUYER' | 'PROFESSIONAL' | 'FIRM_ADMIN' | 'ENTERPRISE_ADMIN' | 'ENTERPRISE_MEMBER' | 'STAFF'

export interface StaffMember {
  id: string
  email: string
  displayName: string
  platformRoles: PlatformRole[]
  mfaEnabled: boolean
  status: string
  /** Just-in-time roles: when each one ends (roles not listed are permanent). */
  roleExpiries?: Partial<Record<PlatformRole, string>>
}

export const authApi = {
  register: (input: RegisterInput) =>
    api<AuthResult & { emailConfirmationToken: string | null }>('/v1/auth/register', { method: 'POST', body: input, auth: false }),
  /** portal: which sign-in page this is; the server keeps staff and customer accounts on their own page. */
  login: (email: string, password: string, totpCode?: string, recoveryCode?: string, portal?: 'customer' | 'staff') =>
    api<AuthResult>('/v1/auth/login', { method: 'POST', body: { email, password, totpCode, recoveryCode, portal }, auth: false }),
  logout: () => api<void>('/v1/auth/logout', { method: 'POST' }),
  me: () => api<User>('/v1/me'),
  confirmEmail: (token: string) => api<User>('/v1/auth/confirm-email', { method: 'POST', body: { token }, auth: false }),
  /** Sends a new confirmation link (one a minute). The token comes back only in local development. */
  resendConfirmation: () => api<{ message: string; emailConfirmationToken: string | null }>('/v1/me/email-confirmation', { method: 'POST' }),
  forgotPassword: (email: string) =>
    api<{ message: string; resetToken: string | null }>('/v1/auth/password/forgot', { method: 'POST', body: { email }, auth: false }),
  resetPassword: (token: string, newPassword: string) =>
    api<void>('/v1/auth/password/reset', { method: 'POST', body: { token, newPassword }, auth: false }),
  enrollMfa: () => api<{ secret: string; otpauthUri: string }>('/v1/auth/mfa/enroll', { method: 'POST' }),
  /** Turns two-step verification on; returns one-time recovery codes, shown only this once. */
  verifyMfa: (totpCode: string) => api<{ recoveryCodes: string[] }>('/v1/auth/mfa/verify', { method: 'POST', body: { totpCode } }),
  newRecoveryCodes: () => api<{ recoveryCodes: string[] }>('/v1/auth/mfa/recovery-codes', { method: 'POST' }),
  resetMfa: (id: string, reason: string) => api<User>(`/v1/admin/identities/${id}/mfa-reset`, { method: 'POST', body: { reason } }),
  stepUp: (totpCode: string) => api<TokenPair>('/v1/auth/step-up', { method: 'POST', body: { totpCode } }),
  // Passkeys (WebAuthn): options come from the server, the answer is signed on this device (lib/passkeys.ts).
  passkeys: () => api<Passkey[]>('/v1/me/passkeys'),
  passkeyOptions: (password: string) => api<Record<string, unknown>>('/v1/me/passkeys/options', { method: 'POST', body: { password } }),
  addPasskey: (name: string, credential: Record<string, unknown>) => api<Passkey>('/v1/me/passkeys', { method: 'POST', body: { name, credential } }),
  removePasskey: (id: string) => api<void>(`/v1/me/passkeys/${id}`, { method: 'DELETE' }),
  passkeyLoginOptions: () => api<Record<string, unknown>>('/v1/auth/passkey/options', { method: 'POST', auth: false }),
  passkeyLogin: (credential: Record<string, unknown>, portal?: 'customer' | 'staff') =>
    api<AuthResult>('/v1/auth/passkey', { method: 'POST', body: { credential, portal }, auth: false }),
  passkeyStepUpOptions: () => api<Record<string, unknown>>('/v1/auth/step-up/passkey/options', { method: 'POST' }),
  passkeyStepUp: (credential: Record<string, unknown>) => api<TokenPair>('/v1/auth/step-up/passkey', { method: 'POST', body: { credential } }),
  addAccountType: (accountType: 'BUYER' | 'PROFESSIONAL') =>
    api<AuthResult>('/v1/me/account-types', { method: 'POST', body: { accountType } }),

  // Platform Admin / Trust & Safety
  listUsers: (filters: { q?: string; role?: UserRoleFilter; status?: string; cursor?: string | null }) =>
    api<{ items: UserRow[]; nextCursor: string | null }>('/v1/admin/users', { query: Object.fromEntries(
      Object.entries({ ...filters, limit: '50' }).filter(([, v]) => v)) as Record<string, string> }),
  listStaff: () => api<StaffMember[]>('/v1/admin/staff'),
  lookup: (email: string) => api<StaffMember>('/v1/admin/identities/lookup', { query: { email } }),
  /** Staff role changes are maker-checker requests (202): another Platform Admin approves them before they apply. */
  grantRole: (id: string, role: PlatformRole, justification: string, expiresAt?: string | null) =>
    api<ApprovalRequest>(`/v1/admin/identities/${id}/platform-roles`, { method: 'POST', body: { role, justification, expiresAt: expiresAt ?? null } }),
  revokeRole: (id: string, role: PlatformRole, justification: string) =>
    api<ApprovalRequest>(`/v1/admin/identities/${id}/platform-roles/${role}`, { method: 'DELETE', query: { justification } }),
}

export const ROLE_LABEL: Record<string, string> = {
  BUYER: 'Buyer',
  PROFESSIONAL: 'Professional',
  FIRM_ADMIN: 'Firm Admin',
  ENTERPRISE_ADMIN: 'Enterprise Admin',
  ENTERPRISE_MEMBER: 'Enterprise Member',
  PLATFORM_ADMIN: 'Platform Admin',
  TS_ANALYST: 'Trust & Safety Analyst',
  COMPLIANCE_OFFICER: 'Compliance Officer',
  RISK_LEAD: 'Risk Lead',
  LEGAL: 'Legal',
  MEDIATOR: 'Mediator',
  FINANCIAL_OPS: 'Financial Ops',
  EXECUTIVE: 'Executive',
  AI_SAFETY_REVIEWER: 'AI Safety Reviewer',
  SUPPORT_AGENT: 'Support Agent',
}

export const DASHBOARD_FOR_PERSONA: Record<Persona, Dashboard> = {
  BUYER: 'buyer',
  PROFESSIONAL: 'professional',
  FIRM_ADMIN: 'firm',
  ENTERPRISE_ADMIN: 'enterprise',
  ENTERPRISE_MEMBER: 'enterprise',
}
