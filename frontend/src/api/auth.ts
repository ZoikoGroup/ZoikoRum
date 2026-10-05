import { api, type TokenPair } from './client'

export type AccountType = 'BUYER' | 'PROFESSIONAL' | 'FIRM' | 'ENTERPRISE'
export type Persona = 'BUYER' | 'PROFESSIONAL' | 'FIRM_ADMIN' | 'ENTERPRISE_ADMIN'
export type Dashboard = 'buyer' | 'professional' | 'firm' | 'enterprise' | 'ops'

export const PLATFORM_ROLES = [
  'PLATFORM_ADMIN', 'TS_ANALYST', 'COMPLIANCE_OFFICER', 'RISK_LEAD', 'LEGAL',
  'MEDIATOR', 'FINANCIAL_OPS', 'EXECUTIVE', 'AI_SAFETY_REVIEWER',
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
  personas: Persona[]
  primaryPersona: Persona | null
  platformRoles: PlatformRole[]
  organizationName: string | null
  defaultDashboard: Dashboard
  createdAt: string
}

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

export interface StaffMember {
  id: string
  email: string
  displayName: string
  platformRoles: PlatformRole[]
  mfaEnabled: boolean
  status: string
}

export const authApi = {
  register: (input: RegisterInput) =>
    api<AuthResult & { emailConfirmationToken: string | null }>('/v1/auth/register', { method: 'POST', body: input, auth: false }),
  login: (email: string, password: string, totpCode?: string) =>
    api<AuthResult>('/v1/auth/login', { method: 'POST', body: { email, password, totpCode }, auth: false }),
  logout: () => api<void>('/v1/auth/logout', { method: 'POST' }),
  me: () => api<User>('/v1/me'),
  confirmEmail: (token: string) => api<User>('/v1/auth/confirm-email', { method: 'POST', body: { token }, auth: false }),
  forgotPassword: (email: string) =>
    api<{ message: string; resetToken: string | null }>('/v1/auth/password/forgot', { method: 'POST', body: { email }, auth: false }),
  resetPassword: (token: string, newPassword: string) =>
    api<void>('/v1/auth/password/reset', { method: 'POST', body: { token, newPassword }, auth: false }),
  enrollMfa: () => api<{ secret: string; otpauthUri: string }>('/v1/auth/mfa/enroll', { method: 'POST' }),
  verifyMfa: (totpCode: string) => api<void>('/v1/auth/mfa/verify', { method: 'POST', body: { totpCode } }),
  stepUp: (totpCode: string) => api<TokenPair>('/v1/auth/step-up', { method: 'POST', body: { totpCode } }),
  addAccountType: (accountType: 'BUYER' | 'PROFESSIONAL') =>
    api<AuthResult>('/v1/me/account-types', { method: 'POST', body: { accountType } }),

  // Platform Admin
  listStaff: () => api<StaffMember[]>('/v1/admin/staff'),
  lookup: (email: string) => api<StaffMember>('/v1/admin/identities/lookup', { query: { email } }),
  grantRole: (id: string, role: PlatformRole) =>
    api<User>(`/v1/admin/identities/${id}/platform-roles`, { method: 'POST', body: { role } }),
  revokeRole: (id: string, role: PlatformRole) =>
    api<User>(`/v1/admin/identities/${id}/platform-roles/${role}`, { method: 'DELETE' }),
}

export const ROLE_LABEL: Record<string, string> = {
  BUYER: 'Buyer',
  PROFESSIONAL: 'Professional',
  FIRM_ADMIN: 'Firm Admin',
  ENTERPRISE_ADMIN: 'Enterprise Admin',
  PLATFORM_ADMIN: 'Platform Admin',
  TS_ANALYST: 'Trust & Safety Analyst',
  COMPLIANCE_OFFICER: 'Compliance Officer',
  RISK_LEAD: 'Risk Lead',
  LEGAL: 'Legal',
  MEDIATOR: 'Mediator',
  FINANCIAL_OPS: 'Financial Ops',
  EXECUTIVE: 'Executive',
  AI_SAFETY_REVIEWER: 'AI Safety Reviewer',
}

export const DASHBOARD_FOR_PERSONA: Record<Persona, Dashboard> = {
  BUYER: 'buyer',
  PROFESSIONAL: 'professional',
  FIRM_ADMIN: 'firm',
  ENTERPRISE_ADMIN: 'enterprise',
}
