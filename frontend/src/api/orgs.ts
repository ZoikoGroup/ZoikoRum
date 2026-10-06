import { api } from './client'

export interface Money {
  amountMinor: number
  currency: string
}

export const ORG_ROLES = ['ORG_ADMIN', 'REQUESTER', 'APPROVER', 'BUDGET_OWNER', 'LEGAL_REVIEWER', 'EXCEPTION_AUTHORITY'] as const
export type OrgRole = (typeof ORG_ROLES)[number]

// Enterprise Policy Profiles doc, s.11 "Approval & Authority Model".
export const ORG_ROLE_INFO: Record<OrgRole, { label: string; desc: string }> = {
  ORG_ADMIN: { label: 'Org Admin', desc: 'Manages the organization, team access and settings.' },
  REQUESTER: { label: 'Requester', desc: 'Raises engagement requests and proposal requests.' },
  APPROVER: { label: 'Approver', desc: 'Approves engagements and releases up to their spend limit.' },
  BUDGET_OWNER: { label: 'Budget Owner', desc: 'Owns cost-center spend and release thresholds.' },
  LEGAL_REVIEWER: { label: 'Legal Reviewer', desc: 'Reviews contracts, clauses and audit exports.' },
  EXCEPTION_AUTHORITY: { label: 'Exception Authority', desc: 'The only role that may approve policy exceptions.' },
}

export const FIRM_ROLES = ['FIRM_ADMIN', 'FIRM_MEMBER', 'AUTHORIZED_REPRESENTATIVE'] as const
export type FirmRole = (typeof FIRM_ROLES)[number]
export const FIRM_ROLE_INFO: Record<FirmRole, { label: string; desc: string }> = {
  FIRM_ADMIN: { label: 'Firm Admin', desc: 'Manages the firm profile and its professionals.' },
  FIRM_MEMBER: { label: 'Firm Member', desc: 'A professional delivering work under the firm.' },
  AUTHORIZED_REPRESENTATIVE: { label: 'Authorized Representative', desc: 'Legally acts for the firm. Identity must be verified.' },
}

export interface Organization {
  id: string
  name: string
  orgType: 'INDIVIDUAL' | 'BUSINESS' | 'ENTERPRISE'
  country: string
  status: string
  businessContext: string | null
  industry: string | null
  timeZone: string | null
  myRoles: OrgRole[]
  memberCount: number
  createdAt: string
}

export interface BillingContact { identityId: string; displayName: string; email: string; isPrimary: boolean }

export interface OrgMember {
  identityId: string
  email: string
  displayName: string
  roles: OrgRole[]
  spendLimit: Money | null
  businessUnitId: string | null
  joinedAt: string
  lastActiveAt: string | null
}

export interface Invitation {
  id: string
  organizationId?: string
  organizationName?: string
  firmId?: string
  firmName?: string
  email: string
  roles: string[]
  spendLimit?: Money | null
  status: string
  expiresAt: string
  createdAt: string
  devInviteUrl: string | null
}

export interface BusinessUnit { id: string; name: string; parentId: string | null }
export interface CostCenter { id: string; name: string; code: string; businessUnitId: string | null; quarterlyBudget: Money | null }

export interface Firm {
  id: string
  legalName: string
  tradingName: string | null
  registrationNumber: string | null
  hqCountry: string
  sizeBand: string | null
  primaryCategory: string | null
  website: string | null
  status: string
  myRoles: FirmRole[]
  memberCount: number
  hasAuthorizedRepresentative: boolean
  version: number
  createdAt: string
}

export interface FirmMember { identityId: string; email: string; displayName: string; roles: FirmRole[]; joinedAt: string }

const O = '/v1/organizations'
export const orgApi = {
  mine: () => api<Organization[]>(`${O}/mine`),
  get: (id: string) => api<Organization>(`${O}/${id}`),
  update: (id: string, body: { name?: string; industry?: string; timeZone?: string; businessContext?: string }) =>
    api<Organization>(`${O}/${id}`, { method: 'PATCH', body }),
  billingContacts: (id: string) => api<BillingContact[]>(`${O}/${id}/billing-contacts`),
  setBillingContacts: (id: string, primaryIdentityId: string, backupIdentityId?: string | null) =>
    api<BillingContact[]>(`${O}/${id}/billing-contacts`, { method: 'PUT', body: { primaryIdentityId, backupIdentityId: backupIdentityId || null } }),
  members: (id: string) => api<OrgMember[]>(`${O}/${id}/members`),
  updateMember: (id: string, identityId: string, body: { roles?: OrgRole[]; spendLimit?: Money | null; clearSpendLimit?: boolean }) =>
    api<OrgMember>(`${O}/${id}/members/${identityId}`, { method: 'PATCH', body }),
  removeMember: (id: string, identityId: string) => api<void>(`${O}/${id}/members/${identityId}`, { method: 'DELETE' }),
  invite: (id: string, body: { email: string; roles: OrgRole[]; spendLimit?: Money | null }) =>
    api<Invitation>(`${O}/${id}/invitations`, { method: 'POST', body }),
  invitations: (id: string) => api<Invitation[]>(`${O}/${id}/invitations`),
  revokeInvitation: (id: string, invId: string) => api<void>(`${O}/${id}/invitations/${invId}`, { method: 'DELETE' }),
  myInvitations: () => api<Invitation[]>(`${O}/invitations/mine`),
  acceptByToken: (token: string) => api<Organization>(`${O}/invitations/accept`, { method: 'POST', body: { token } }),
  acceptById: (invId: string) => api<Organization>(`${O}/invitations/${invId}/accept`, { method: 'POST' }),
  decline: (invId: string) => api<void>(`${O}/invitations/${invId}/decline`, { method: 'POST' }),
  businessUnits: (id: string) => api<BusinessUnit[]>(`${O}/${id}/business-units`),
  createBusinessUnit: (id: string, name: string) => api<BusinessUnit>(`${O}/${id}/business-units`, { method: 'POST', body: { name } }),
  costCenters: (id: string) => api<CostCenter[]>(`${O}/${id}/cost-centers`),
  createCostCenter: (id: string, body: { name: string; code: string; businessUnitId?: string | null; quarterlyBudget?: Money | null }) =>
    api<CostCenter>(`${O}/${id}/cost-centers`, { method: 'POST', body }),
}

const F = '/v1/firms'
export const firmApi = {
  mine: () => api<Firm[]>(`${F}/mine`),
  update: (id: string, version: number, body: Partial<Pick<Firm, 'legalName' | 'tradingName' | 'registrationNumber' | 'hqCountry' | 'sizeBand' | 'primaryCategory' | 'website'>>) =>
    api<Firm>(`${F}/${id}`, { method: 'PATCH', body, headers: { 'If-Match': String(version) } }),
  members: (id: string) => api<FirmMember[]>(`${F}/${id}/members`),
  updateMember: (id: string, identityId: string, roles: FirmRole[]) =>
    api<FirmMember>(`${F}/${id}/members/${identityId}`, { method: 'PATCH', body: { roles } }),
  removeMember: (id: string, identityId: string) => api<void>(`${F}/${id}/members/${identityId}`, { method: 'DELETE' }),
  invite: (id: string, email: string, roles: FirmRole[]) => api<Invitation>(`${F}/${id}/invitations`, { method: 'POST', body: { email, roles } }),
  invitations: (id: string) => api<Invitation[]>(`${F}/${id}/invitations`),
  revokeInvitation: (id: string, invId: string) => api<void>(`${F}/${id}/invitations/${invId}`, { method: 'DELETE' }),
  myInvitations: () => api<Invitation[]>(`${F}/invitations/mine`),
  acceptByToken: (token: string) => api<Firm>(`${F}/invitations/accept`, { method: 'POST', body: { token } }),
  acceptById: (invId: string) => api<Firm>(`${F}/invitations/${invId}/accept`, { method: 'POST' }),
  decline: (invId: string) => api<void>(`${F}/invitations/${invId}/decline`, { method: 'POST' }),
}

export function formatMoney(m: Money | null | undefined): string {
  if (!m) return '—'
  return new Intl.NumberFormat(undefined, { style: 'currency', currency: m.currency, maximumFractionDigits: 0 }).format(m.amountMinor / 100)
}
