import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { platformActivity, type AuditRecord } from '../api/audit'
import { ROLE_LABEL } from '../api/auth'
import { adminApi, type AdminOverview } from '../api/saved'
import { verificationApi, type QueueItem } from '../api/verification'
import { useAuth } from '../auth/AuthContext'
import { ago, describe } from '../components/activity'
import { Kpi } from '../components/dashboard'

/** Admin / operations dashboard: platform counts, recent activity and the moderation queues. All figures are live. */
export function StaffHome() {
  const { user } = useAuth()
  const [overview, setOverview] = useState<AdminOverview | null>(null)
  const [queue, setQueue] = useState<QueueItem[] | null>(null)
  const [activity, setActivity] = useState<AuditRecord[] | null>(null)
  const roles = user?.platformRoles ?? []
  const isOfficer = roles.includes('COMPLIANCE_OFFICER')
  const canReadLedger = roles.some((r) => r === 'COMPLIANCE_OFFICER' || r === 'LEGAL' || r === 'PLATFORM_ADMIN')
  useEffect(() => {
    adminApi.overview().then(setOverview).catch(() => {})
    if (isOfficer) verificationApi.queue().then((p) => setQueue(p.items)).catch(() => setQueue([]))
    if (canReadLedger) platformActivity(40).then(setActivity).catch(() => setActivity([]))
  }, [isOfficer, canReadLedger])
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
        <Kpi icon="team" tone="teal" label="Firms" value={o?.accounts.firmAdmins ?? '—'} note="Firm admin accounts" />
      </div>

      <div className="home-grid">
        <section className="card panel">
          <div className="panel-head"><h2>Recent Activity</h2></div>
          {!canReadLedger ? <p className="muted small" style={{ margin: 0 }}>Platform activity is visible to Compliance, Legal and Platform Admins.</p>
            : activity === null ? <p className="muted small">Loading…</p> : rows.length === 0 ? <p className="muted small">No activity yet.</p> : (
              <table className="data">
                <thead><tr><th>Activity</th><th>Area</th><th>Time</th></tr></thead>
                <tbody>{rows.map(({ r, text }) => (
                  <tr key={r.id}><td>{text}</td><td className="muted small">{r.objectType}</td><td className="muted small">{ago(r.occurredAt)}</td></tr>
                ))}</tbody>
              </table>
            )}
          <p className="muted small" style={{ margin: '10px 0 0' }}>From the tamper-evident audit ledger.</p>
        </section>

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
              <li><span className="kpi-icon red" aria-hidden>!</span>
                <span><strong>Dispute resolution</strong><br /><span className="muted small">Arrives with disputes</span></span><span className="badge">Soon</span></li>
              <li><span className="kpi-icon amber" aria-hidden>⚑</span>
                <span><strong>Enforcement &amp; risk flags</strong><br /><span className="muted small">Arrives with Trust &amp; Safety tools</span></span><span className="badge">Soon</span></li>
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
