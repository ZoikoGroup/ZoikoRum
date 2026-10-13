import type { AuditRecord } from '../api/audit'
import { ORG_ROLE_INFO, type OrgRole } from '../api/orgs'

/* Audit-ledger records in plain language, for "Recent activity" panels. */

// High-volume or internal events that would drown out what people actually did.
const NOISE = ['search.query.', 'trust.profile.signal_added', 'trust.profile.score_recomputed', 'audit.', 'buyer.buyer.registered',
  'marketplace.listing.viewed']

const roleNames = (roles: unknown) => {
  const list = (Array.isArray(roles) ? roles : []).map((r) => ORG_ROLE_INFO[r as OrgRole]?.label ?? String(r))
  return list.length > 2 ? `${list.slice(0, 2).join(', ')} +${list.length - 2}` : list.join(', ')
}

export function describe(r: AuditRecord): string | null {
  const d = r.details
  const key = r.action.replace(/^zoikorum\./, '').replace(/\.v\d+$/, '')
  if (NOISE.some((n) => key.startsWith(n))) return null
  switch (key) {
    case 'identity.identity.created': return 'New account registered'
    case 'buyer.organization.created': return `Organization “${d.name}” created`
    case 'buyer.organization.updated': return 'Organization details updated'
    case 'buyer.organization.member_added': return d.invitationId ? `New team member joined (${roleNames(d.roles)})` : 'Organization owner added'
    case 'buyer.organization.member_invited': return `Invitation sent to ${d.email}`
    case 'buyer.organization.invitation_revoked': return 'An invitation was revoked'
    case 'buyer.organization.role_assigned': return `Team roles changed (${roleNames(d.roles)})`
    case 'buyer.organization.member_removed': return 'A team member was removed'
    case 'buyer.business_unit.created': return `Business unit “${d.name}” added`
    case 'buyer.cost_center.created': return `Cost center ${d.code} “${d.name}” added`
    case 'firm.firm.registered': return `Firm “${d.legalName}” registered`
    case 'firm.firm.verified': return 'Firm registration verified'
    case 'professional.professional.registered': return 'Professional profile created'
    case 'professional.professional.profile_published': return 'Professional profile published'
    case 'professional.professional.profile_unpublished': return 'Professional profile unpublished'
    case 'professional.credential.submitted': return `Credential submitted: ${d.credentialName}`
    case 'professional.offering.created': return 'Service offering created'
    case 'verification.case.started': return `Verification started: ${d.label}`
    case 'verification.case.evidence_submitted': return `Documents submitted: ${d.label}`
    case 'verification.case.completed': return `Verified: ${d.label}`
    case 'verification.case.failed': return `Not verified: ${d.label}`
    case 'verification.case.needs_info': return `More information requested: ${d.label}`
    case 'verification.case.revoked': return `Verification revoked: ${d.label}`
    case 'trust.profile.tier_changed': return `Trust Tier changed ${d.fromTier} → ${d.toTier}`
    case 'marketplace.listing.bookmarked': return 'A professional was saved'
    default: {
      const text = key.split('.').slice(-2).map((p) => p.replace(/_/g, ' ')).join(': ')
      return text.charAt(0).toUpperCase() + text.slice(1)
    }
  }
}

export function ago(iso: string): string {
  const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000)
  if (s < 60) return 'just now'
  if (s < 3600) return `${Math.floor(s / 60)} min ago`
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`
  return `${Math.floor(s / 86400)} d ago`
}

export function ActivityList({ records, limit = 8 }: { records: AuditRecord[]; limit?: number }) {
  const rows = records.map((r) => ({ r, text: describe(r) })).filter((x) => x.text).slice(0, limit)
  if (rows.length === 0) return <p className="muted small" style={{ margin: 0 }}>No activity yet.</p>
  return (
    <ul className="activity">
      {rows.map(({ r, text }) => (
        <li key={r.id}><span className="dot" aria-hidden /><span>{text}</span><span className="muted small">{ago(r.occurredAt)}</span></li>
      ))}
    </ul>
  )
}
