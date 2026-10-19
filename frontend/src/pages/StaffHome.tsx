import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { platformActivity, type AuditRecord } from '../api/audit'
import { PLATFORM_ROLES, ROLE_LABEL } from '../api/auth'
import { api } from '../api/client'
import { disputeApi, OPEN_PHASES } from '../api/disputes'
import { paymentsApi } from '../api/escrow'
import { adminApi, type AdminOverview } from '../api/saved'
import { supportApi } from '../api/support'
import { verificationApi, type QueueItem } from '../api/verification'
import { useAuth } from '../auth/AuthContext'
import { ago, describe } from '../components/activity'
import { Kpi } from '../components/dashboard'
import { Loading } from '../components/ui'

/** One operations queue on the dashboard: shown only to the roles that can work it (the same roles as its page). */
interface OpsQueue { key: string; label: string; to: string; roles: readonly string[]; mark: string; tone: string
  load: () => Promise<{ open: number; note?: string }> }

const PAGE = 100  // the most a queue endpoint returns at once: a full page shows as "100+"
const atLeast = (n: number) => (n >= PAGE ? `${PAGE}+` : String(n))

const QUEUES: OpsQueue[] = [
  { key: 'disputes', label: 'Dispute resolution', to: '/app/ops/disputes', roles: ['MEDIATOR', 'LEGAL', 'PLATFORM_ADMIN'], mark: '!', tone: 'red',
    load: async () => {
      const open = (await disputeApi.list('operator')).filter((d) => OPEN_PHASES.includes(d.status))
      const mediation = open.filter((d) => d.status === 'MEDIATION').length
      return { open: open.length, note: mediation ? `${mediation} in mediation` : undefined }
    } },
  { key: 'enforcement', label: 'Enforcement & risk flags', to: '/app/ops/safety', roles: PLATFORM_ROLES, mark: '⚑', tone: 'amber',
    load: async () => {
      const query = (status: string) => api<{ overdue: boolean }[]>('/v1/admin/enforcement-cases', { query: { status, limit: String(PAGE) } })
      const cases = (await Promise.all([query('TRIAGE'), query('ASSESSED')])).flat()
      const overdue = cases.filter((c) => c.overdue).length
      return { open: cases.length, note: overdue ? `${overdue} past triage target` : undefined }
    } },
  { key: 'money', label: 'Money problems', to: '/app/ops/money', roles: ['FINANCIAL_OPS', 'PLATFORM_ADMIN'], mark: '$', tone: 'red',
    load: async () => ({ open: (await paymentsApi.opsWorklist()).open }) },
  { key: 'dead', label: 'Dead letter deliveries', to: '/app/ops/dead-letters', roles: ['FINANCIAL_OPS', 'PLATFORM_ADMIN'], mark: '✉', tone: 'amber',
    load: async () => {
      const rows = await api<{ financial: boolean }[]>('/v1/admin/dead-letters', { query: { limit: String(PAGE) } })
      const financial = rows.filter((r) => r.financial).length
      return { open: rows.length, note: financial ? `${financial} affect money` : undefined }
    } },
  { key: 'support', label: 'Help requests', to: '/app/ops/support', roles: ['SUPPORT_AGENT', 'PLATFORM_ADMIN'], mark: '?', tone: 'blue',
    load: async () => {
      const rows = await supportApi.queue('OPEN')
      const overdue = rows.filter((r) => r.overdue).length
      return { open: rows.length, note: overdue ? `${overdue} past first-response target` : undefined }
    } },
  { key: 'incidents', label: 'Open incidents', to: '/app/ops/incidents', roles: PLATFORM_ROLES, mark: '▲', tone: 'red',
    load: async () => {
      const open = (await api<{ status: string; severity: string }[]>('/v1/admin/incidents')).filter((i) => i.status !== 'CLOSED')
      const major = open.filter((i) => i.severity === 'SEV1' || i.severity === 'SEV2').length
      return { open: open.length, note: major ? `${major} SEV1/SEV2` : undefined }
    } },
]
/** The headline marketplace figures for the last 30 days; the analytics page has the detail. */
interface Health { searches: number; zeroResultSearches: number; activations: number; disputesOpened: number; disputesResolved: number
  proposalContractConversionBps: number | null }

function HealthStrip() {
  const [h, setH] = useState<Health | null>(null)
  useEffect(() => {
    const to = new Date()
    api<Health>('/v1/analytics/marketplace-health', { query: { from: new Date(to.getTime() - 30 * 86400_000).toISOString(), to: to.toISOString() } })
      .then(setH).catch(() => {})
  }, [])
  if (!h) return null
  const pct = (part: number, whole: number) => (whole ? `${Math.round((part / whole) * 100)}%` : '—')
  return (
    <section className="card panel">
      <div className="panel-head"><h2>Marketplace, last 30 days</h2><Link className="small" to="/app/ops/analytics">Analytics</Link></div>
      <ul className="checklist">
        <li><span>Searches</span><strong>{h.searches} <span className="muted small">({pct(h.zeroResultSearches, h.searches)} with no results)</span></strong></li>
        <li><span>Engagements started</span><strong>{h.activations}</strong></li>
        <li><span>Proposals that became contracts</span><strong>{h.proposalContractConversionBps == null ? '—' : `${(h.proposalContractConversionBps / 100).toFixed(1)}%`}</strong></li>
        <li><span>Disputes opened / resolved</span><strong>{h.disputesOpened} / {h.disputesResolved}</strong></li>
      </ul>
    </section>
  )
}

const queuesFor =(held: readonly string[]) => QUEUES.filter((q) => q.roles.some((r) => held.includes(r)))

/** Admin / operations dashboard: platform counts, recent activity and the moderation queues. All figures are live. */
export function StaffHome() {
  const { user } = useAuth()
  const [overview, setOverview] = useState<AdminOverview | null>(null)
  const [queue, setQueue] = useState<QueueItem[] | null>(null)
  const [activity, setActivity] = useState<AuditRecord[] | null>(null)
  const roles = user?.platformRoles ?? []
  const isOfficer = roles.includes('COMPLIANCE_OFFICER')
  const canReadLedger = roles.some((r) => r === 'COMPLIANCE_OFFICER' || r === 'LEGAL' || r === 'PLATFORM_ADMIN')
  const rolesKey = roles.join(',')
  const myQueues = queuesFor(roles)
  // missing while loading; a queue that fails to load says so rather than showing a misleading zero
  const [counts, setCounts] = useState<Record<string, { open: number; note?: string } | 'error'>>({})
  useEffect(() => {
    adminApi.overview().then(setOverview).catch(() => {})
    if (isOfficer) verificationApi.queue().then((p) => setQueue(p.items)).catch(() => setQueue([]))
    if (canReadLedger) platformActivity(40).then(setActivity).catch(() => setActivity([]))
  }, [isOfficer, canReadLedger])
  useEffect(() => {
    let live = true
    for (const q of queuesFor(rolesKey.split(','))) {
      q.load().then((c) => { if (live) setCounts((s) => ({ ...s, [q.key]: c })) })
        .catch(() => { if (live) setCounts((s) => ({ ...s, [q.key]: 'error' })) })
    }
    return () => { live = false }
  }, [rolesKey])
  if (!user) return null

  const o = overview
  const rows = (activity ?? []).map((r) => ({ r, text: describe(r) })).filter((x) => x.text).slice(0, 8)
  return (
    <>
      <div className="home-head">
        <div>
          <h1>Admin Dashboard</h1>
          <p className="muted" style={{ margin: 0 }}>Overview of platform activity and key metrics · {roles.map((r) => ROLE_LABEL[r] ?? r).join(', ')}</p>
        </div>
        <div className="row">
          {isOfficer && <Link className="btn btn-primary" to="/app/ops/verification">Review queue</Link>}
          {roles.includes('PLATFORM_ADMIN') && <Link className="btn btn-secondary" to="/app/ops/staff">Staff &amp; roles</Link>}
        </div>
      </div>

      <div className="kpi-row">
        {roles.some((r) => r === 'PLATFORM_ADMIN' || r === 'TS_ANALYST')
          ? <Link to="/app/ops/users"><Kpi icon="team" tone="green" label="Total Accounts" value={o?.accounts.total ?? '—'} note={o ? `${o.accounts.enterprise} enterprise users · view all` : ' '} /></Link>
          : <Kpi icon="team" tone="green" label="Total Accounts" value={o?.accounts.total ?? '—'} note={o ? `${o.accounts.enterprise} enterprise users` : ' '} />}
        <Kpi icon="building" tone="blue" label="Buyers" value={o?.accounts.buyers ?? '—'} note="Accounts that hire" />
        <Kpi icon="user" tone="violet" label="Professionals" value={o?.professionalProfiles.published ?? '—'}
          note={o ? `published of ${o.professionalProfiles.total} profiles` : ' '} />
        <Kpi icon="shield" tone={o?.verification.overdue ? 'red' : 'amber'} label="Open Verifications" value={o?.verification.open ?? '—'}
          note={o ? (o.verification.overdue ? `${o.verification.overdue} past service level` : 'None overdue') : ' '} />
        <Kpi icon="team" tone="teal" label="Firm Admins" value={o?.accounts.firmAdmins ?? '—'} note="Accounts that run a firm" />
      </div>

      <div className="home-grid">
        <div>
          <section className="card panel">
            <div className="panel-head"><h2>Recent Activity</h2></div>
            {!canReadLedger ? <p className="muted small" style={{ margin: 0 }}>Platform activity is visible to Compliance, Legal and Platform Admins.</p>
              : activity === null ? <Loading lines={1} /> : rows.length === 0 ? <p className="muted small">No activity yet.</p> : (
                <table className="data">
                  <thead><tr><th>Activity</th><th>Area</th><th>Time</th></tr></thead>
                  <tbody>{rows.map(({ r, text }) => (
                    <tr key={r.id}><td>{text}</td><td className="muted small">{r.objectType}</td><td className="muted small">{ago(r.occurredAt)}</td></tr>
                  ))}</tbody>
                </table>
              )}
            <p className="muted small" style={{ margin: '10px 0 0' }}>From the tamper-evident audit ledger.</p>
          </section>
          <HealthStrip />
        </div>

        <aside>
          <section className="card panel attention">
            <div className="panel-head"><h2>Pending Moderation</h2></div>
            <ul className="action-list">
              <li>
                <span className="kpi-icon violet" aria-hidden>✓</span>
                <span><strong>Verification reviews</strong><br /><span className="muted small">
                  {isOfficer ? `${queue?.length ?? 0} pending` : `${o?.verification.open ?? 0} open · reviewed by Compliance Officers`}</span></span>
                {isOfficer ? <Link className="btn btn-secondary btn-sm" to="/app/ops/verification">Review</Link> : <span />}
              </li>
              {myQueues.map((q) => {
                const c = counts[q.key]
                return (
                  <li key={q.key}>
                    <span className={`kpi-icon ${q.tone}`} aria-hidden>{q.mark}</span>
                    <span><strong>{q.label}</strong><br /><span className="muted small">
                      {c === undefined ? 'Loading…' : c === 'error' ? 'Could not load: open the queue'
                        : `${atLeast(c.open)} open${c.note ? ` · ${c.note}` : ''}`}</span></span>
                    <Link className="btn btn-secondary btn-sm" to={q.to}>Open</Link>
                  </li>
                )
              })}
            </ul>
          </section>
          {isOfficer && queue && queue.length > 0 && (
            <section className="card panel">
              <div className="panel-head"><h2>Oldest in the queue</h2></div>
              <ul className="activity">
                {queue.slice(-5).reverse().map((q) => (
                  <li key={q.id}><span className="dot" aria-hidden /><span>{q.label} · {q.subjectName ?? 'Unknown'}</span>
                    <span className="muted small">{q.overdue ? 'Overdue' : ago(q.createdAt)}</span></li>
                ))}
              </ul>
            </section>
          )}
          <section className="card panel">
            <div className="panel-head"><h2>Staff rules</h2></div>
            <ul className="why" style={{ margin: 0 }}>
              <li>Every decision is made by a named person and logged.</li>
              <li>Sensitive actions ask for a fresh two-step code.</li>
              <li>Nobody reviews their own case.</li>
              <li>AI may flag, never decide.</li>
            </ul>
          </section>
        </aside>
      </div>
    </>
  )
}
