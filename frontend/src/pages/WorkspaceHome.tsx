import { useEffect, useState, type ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { auditApi, type AuditRecord } from '../api/audit'
import { firmApi, orgApi, type Organization } from '../api/orgs'
import { LABEL } from '../api/professional'
import { savedApi, type SavedProfessional } from '../api/saved'
import { useAuth } from '../auth/AuthContext'
import { ActivityList } from '../components/activity'
import { ActionList, greeting, Icon, Kpi, type Action } from '../components/dashboard'
import { AccountAlerts } from './Dashboards'

/* Customer dashboard (Buyer Dashboard & Engagement Management wireframe): five summary cards, then
   engagements, requests, payments, activity and saved professionals. Every figure is real; modules whose
   feature is not live yet show an empty state that says what will appear there. */

function EmptyRow({ cols, children }: { cols: number; children: ReactNode }) {
  return <tr><td colSpan={cols} className="empty-row">{children}</td></tr>
}

export function WorkspaceHome({ kind }: { kind: 'buyer' | 'enterprise' }) {
  const { user } = useAuth()
  const [org, setOrg] = useState<Organization | null>(null)
  const [loading, setLoading] = useState(true)
  const [myInvites, setMyInvites] = useState(0)
  const [orgInvites, setOrgInvites] = useState(0)
  const [units, setUnits] = useState<number | null>(null)
  const [hasExceptionAuthority, setHasExceptionAuthority] = useState(true)
  const [activity, setActivity] = useState<AuditRecord[] | null>(null)
  const [saved, setSaved] = useState<SavedProfessional[]>([])

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      try {
        // Organizations are created by the background worker right after sign-up: retry briefly.
        for (let attempt = 0; attempt < 10 && !cancelled; attempt++) {
          const orgs = await orgApi.mine()
          const found = kind === 'enterprise'
            ? orgs.find((o) => o.orgType !== 'INDIVIDUAL') : orgs.find((o) => o.orgType === 'INDIVIDUAL') ?? orgs[0]
          if (found) { setOrg(found); break }
          await new Promise((r) => setTimeout(r, 800))
        }
        const [o, f, s] = await Promise.all([orgApi.myInvitations(), firmApi.myInvitations(), savedApi.list()])
        if (!cancelled) { setMyInvites(o.length + f.length); setSaved(s) }
      } catch { /* each panel shows its own empty state */ }
      if (!cancelled) setLoading(false)
    })()
    return () => { cancelled = true }
  }, [kind])

  const isAdmin = !!org?.myRoles.includes('ORG_ADMIN')
  const canSeeActivity = !!org && (isAdmin || org.myRoles.includes('LEGAL_REVIEWER'))
  useEffect(() => {
    if (!org) return
    if (canSeeActivity) auditApi.recent(org.id, 15).then(setActivity).catch(() => setActivity([]))
    if (kind === 'enterprise') {
      orgApi.businessUnits(org.id).then((u) => setUnits(u.length)).catch(() => {})
      if (isAdmin) {
        orgApi.invitations(org.id).then((i) => setOrgInvites(i.length)).catch(() => {})
        orgApi.members(org.id).then((ms) => setHasExceptionAuthority(ms.some((m) =>
          m.roles.includes('EXCEPTION_AUTHORITY') && !m.roles.includes('ORG_ADMIN')))).catch(() => {})
      }
    }
  }, [org, kind, isAdmin, canSeeActivity])

  if (!user) return null
  if (loading) return <p className="muted">Loading…</p>

  const actions: Action[] = []
  if (!user.emailConfirmed) actions.push({ title: 'Confirm your email address', detail: 'Needed before you can accept invitations', priority: 'High', to: '/app/account', icon: 'mail' })
  if (myInvites > 0) actions.push({ title: `Respond to ${myInvites} invitation${myInvites > 1 ? 's' : ''}`, detail: 'You were invited to join a team', priority: 'Medium', to: '/app/invitations', icon: 'bell' })
  if (kind === 'enterprise' && org && isAdmin) {
    if (org.memberCount <= 1) actions.push({ title: 'Invite your team', detail: 'Add requesters, approvers and budget owners', priority: 'Medium', to: '/app/enterprise/team', icon: 'team' })
    if (!hasExceptionAuthority) actions.push({ title: 'Name an Exception Authority', detail: 'Must be someone other than an Org Admin', priority: 'Medium', to: '/app/enterprise/team', icon: 'shield' })
    if (units === 0) actions.push({ title: 'Add business units and cost centers', detail: 'Used for budgets and approval routing', priority: 'Low', to: '/app/enterprise/structure', icon: 'building' })
    if (orgInvites > 0) actions.push({ title: `${orgInvites} invitation${orgInvites > 1 ? 's' : ''} not yet accepted`, detail: 'Remind your colleagues or resend', priority: 'Low', to: '/app/enterprise/team', icon: 'mail' })
  }
  if (saved.length === 0) actions.push({ title: 'Find and save professionals', detail: 'Build a shortlist by specialization and Trust Tier', priority: 'Low', to: '/professionals', icon: 'search' })

  return (
    <>
      <div className="home-head">
        <div>
          <h1>{greeting(user.displayName)}</h1>
          <p className="muted" style={{ margin: 0 }}>
            {org && kind === 'enterprise' ? `${org.name} · ` : ''}Find the right professionals and get your work done — governed from start to finish.
          </p>
        </div>
        <Link className="btn btn-primary" to="/professionals"><Icon name="search" /> Find a Professional</Link>
      </div>
      <AccountAlerts />

      {/* s.4 Summary cards (max 5, each clickable) */}
      <div className="kpi-row five">
        <a href="#engagements"><Kpi icon="contract" tone="blue" label="Active Engagements" value={0} note="Contracts in progress" /></a>
        <a href="#actions"><Kpi icon="bell" tone="amber" label="Pending Actions" value={actions.length} note={actions.length ? 'Needs your attention' : 'All caught up'} /></a>
        <a href="#proposals"><Kpi icon="proposal" tone="violet" label="Open Proposals" value={0} note="Awaiting your decision" /></a>
        <a href="#payments"><Kpi icon="shield" tone="teal" label="Funds in Protection" value="—" note="Live when payments launch" /></a>
        <a href="#saved"><Kpi icon="star" tone="green" label="Saved Professionals" value={saved.length} note="Your shortlist" /></a>
      </div>

      {/* s.11 Pending actions: highlighted strip */}
      <section className="card panel attention" id="actions">
        <div className="panel-head"><h2>Pending Actions</h2></div>
        <ActionList actions={actions} empty="You're all caught up." />
      </section>

      <div className="home-grid">
        <div>
          {/* s.5 Active engagements */}
          <section className="card panel" id="engagements">
            <div className="panel-head"><h2>Active Engagements</h2></div>
            <table className="data">
              <thead><tr><th>Professional</th><th>Service</th><th>Status</th><th>Milestone</th><th>Payment</th><th>Actions</th></tr></thead>
              <tbody><EmptyRow cols={6}>
                <strong>No active engagements.</strong> Once a proposal is accepted and the contract signed, track milestones,
                approvals and payments here.
              </EmptyRow></tbody>
            </table>
          </section>

          {/* s.10 Proposals & requests */}
          <section className="card panel" id="proposals">
            <div className="panel-head"><h2>Proposals &amp; Requests</h2></div>
            <table className="data">
              <thead><tr><th>Professional</th><th>Service</th><th>Price</th><th>Status</th><th>Response deadline</th><th>Actions</th></tr></thead>
              <tbody><EmptyRow cols={6}>
                <strong>No requests yet.</strong> Requests you send, proposals you receive and expired proposals appear here.
                Requesting proposals opens in the next release.
              </EmptyRow></tbody>
            </table>
          </section>

          {/* s.13 Saved & monitoring */}
          <section className="card panel" id="saved">
            <div className="panel-head"><h2>Saved Professionals</h2>{saved.length > 0 && <Link className="small" to="/app/saved">View all</Link>}</div>
            {saved.length === 0 ? (
              <p className="muted small" style={{ margin: 0 }}>Nothing saved yet. <Link to="/professionals">Browse professionals</Link> and use ☆ Save to build a shortlist.</p>
            ) : (
              <ul className="pro-list">
                {saved.slice(0, 5).map((s) => (
                  <li key={s.professionalId}>
                    <span className="avatar" aria-hidden>{s.displayName.split(/\s+/).map((w) => w[0]).slice(0, 2).join('').toUpperCase()}</span>
                    <span><Link to={`/professionals/${s.professionalId}`}><strong>{s.displayName}</strong></Link>
                      <span className="muted small"> · {s.primarySpecialization ?? s.headline} · {LABEL[s.availability] ?? s.availability}</span></span>
                    <span className={`badge ${s.tier === 'C' ? 'warn' : 'green'}`}>Tier {s.tier}</span>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </div>

        <aside>
          {/* s.9 Payments & protection */}
          <section className="card panel" id="payments">
            <div className="panel-head"><h2>Payments &amp; Protection</h2></div>
            <ul className="checklist">
              <li><span>Held in escrow</span><strong>—</strong></li>
              <li><span>Scheduled for release</span><strong>—</strong></li>
              <li><span>Released</span><strong>—</strong></li>
            </ul>
            <ul className="why-inline" style={{ marginTop: 10 }}>
              <li>Escrow-style holding</li><li>Conditional release</li><li>Dispute path available</li>
            </ul>
            <p className="muted small" style={{ margin: '8px 0 0' }}>Live when payments launch.</p>
          </section>

          {/* s.12 Messages & activity */}
          <section className="card panel">
            <div className="panel-head"><h2>Messages &amp; Activity</h2></div>
            {!canSeeActivity ? <p className="muted small" style={{ margin: 0 }}>Activity is visible to Org Admins and Legal Reviewers.</p>
              : activity === null ? <p className="muted small" style={{ margin: 0 }}>Loading…</p> : <ActivityList records={activity} />}
            <p className="muted small" style={{ margin: '10px 0 0' }}>Engagement messages arrive with contracts.</p>
          </section>

          {/* s.14 Enterprise controls (contextual) */}
          {kind === 'enterprise' && (
            <section className="card panel">
              <div className="panel-head"><h2>Enterprise Controls</h2><Link className="small" to="/app/enterprise/team">View enterprise controls →</Link></div>
              <ul className="checklist">
                <li><Link to="/app/enterprise/team">Team &amp; roles</Link><span className="muted small">{org?.memberCount ?? 0} members</span></li>
                <li><Link to="/app/enterprise/structure">Business units &amp; cost centers</Link><span className="muted small">{units ?? 0} units</span></li>
                <li><span>Policy profiles &amp; approval workflows</span><span className="badge">Soon</span></li>
                <li><span>Audit log export</span><span className="badge">Soon</span></li>
              </ul>
            </section>
          )}
        </aside>
      </div>
    </>
  )
}

export const BuyerHome = () => <WorkspaceHome kind="buyer" />
export const EnterpriseHome = () => <WorkspaceHome kind="enterprise" />
