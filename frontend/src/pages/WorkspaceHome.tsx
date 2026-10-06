import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { firmApi, orgApi, type Organization } from '../api/orgs'
import { LABEL } from '../api/professional'
import { formatMoney } from '../api/orgs'
import { CONTRACT_STATUS, contractApi, type Contract } from '../api/contracts'
import { proposalApi, requestStatus, type ProposalRequest } from '../api/proposals'
import { savedApi, type SavedProfessional } from '../api/saved'
import { useAuth } from '../auth/AuthContext'
import { ActionList, Avatar, greeting, Icon, type Action } from '../components/dashboard'
import { EmptyTable, PortalHeader, StatCard, Tabs } from '../components/portal'
import { AccountAlerts } from './Dashboards'

/* Customer dashboard: management design + Buyer Dashboard & Engagement wireframe (5 summary cards,
   attention strip, engagements, assurance, requests & proposals, saved professionals). Real data only;
   modules waiting on later steps show what will appear there. */

type EngTab = 'all' | 'signing' | 'active' | 'completed'
const engBucket = (c: Contract): EngTab => (c.status === 'PENDING_SIGNATURE' ? 'signing' : c.status === 'ACTIVE' ? 'active' : 'completed')
type ReqTab = 'all' | 'open' | 'proposals' | 'accepted' | 'declined'
const reqBucket = (r: ProposalRequest): ReqTab => {
  const s = r.proposal?.status
  if (s === 'ACCEPTED') return 'accepted'
  if (s && ['SUBMITTED', 'UNDER_REVIEW', 'REVISION_REQUESTED'].includes(s)) return 'proposals'
  if (['DRAFT', 'OPEN', 'PROPOSAL_RECEIVED'].includes(r.status)) return 'open'
  return 'declined'
}

// How every engagement is protected (Buyer Dashboard s.9, Payments & Escrow). Rules, not statuses.
const ASSURANCE: { icon: 'shield' | 'contract' | 'lock' | 'check' | 'help' | 'request'; label: string; value: string }[] = [
  { icon: 'shield', label: 'Professional verification', value: 'Checked before contracting' },
  { icon: 'contract', label: 'Agreement', value: 'Signed contract required' },
  { icon: 'lock', label: 'Payment protection', value: 'Escrow for every milestone' },
  { icon: 'check', label: 'Release condition', value: 'Your milestone approval' },
  { icon: 'help', label: 'Dispute route', value: 'Available, funds held' },
  { icon: 'request', label: 'Engagement record', value: 'Audit-grade, exportable' },
]

export function WorkspaceHome({ kind }: { kind: 'buyer' | 'enterprise' }) {
  const { user } = useAuth()
  const [org, setOrg] = useState<Organization | null>(null)
  const [loading, setLoading] = useState(true)
  const [myInvites, setMyInvites] = useState(0)
  const [orgInvites, setOrgInvites] = useState(0)
  const [units, setUnits] = useState<number | null>(null)
  const [hasExceptionAuthority, setHasExceptionAuthority] = useState(true)
  const [saved, setSaved] = useState<SavedProfessional[]>([])
  const [engTab, setEngTab] = useState<EngTab>('all')
  const [contracts, setContracts] = useState<Contract[]>([])
  const [reqTab, setReqTab] = useState<ReqTab>('all')
  const [requests, setRequests] = useState<ProposalRequest[]>([])
  const [hideBanner, setHideBanner] = useState(false)

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
        const [o, f, s, rq, ct] = await Promise.all([orgApi.myInvitations(), firmApi.myInvitations(), savedApi.list(),
          proposalApi.list('buyer').catch(() => []), contractApi.list('buyer').catch(() => [])])
        if (!cancelled) { setMyInvites(o.length + f.length); setSaved(s); setRequests(rq); setContracts(ct) }
      } catch { /* each panel shows its own empty state */ }
      if (!cancelled) setLoading(false)
    })()
    return () => { cancelled = true }
  }, [kind])

  const isAdmin = !!org?.myRoles.includes('ORG_ADMIN')
  useEffect(() => {
    if (!org || kind !== 'enterprise') return
    orgApi.businessUnits(org.id).then((u) => setUnits(u.length)).catch(() => {})
    if (isAdmin) {
      orgApi.invitations(org.id).then((i) => setOrgInvites(i.length)).catch(() => {})
      orgApi.members(org.id).then((ms) => setHasExceptionAuthority(ms.some((m) =>
        m.roles.includes('EXCEPTION_AUTHORITY') && !m.roles.includes('ORG_ADMIN')))).catch(() => {})
    }
  }, [org, kind, isAdmin])

  if (!user) return null
  if (loading) return <p className="muted">Loading…</p>

  const actions: Action[] = []
  if (!user.emailConfirmed) actions.push({ title: 'Confirm your email address', detail: 'Needed before you can accept invitations', priority: 'High', to: '/app/settings', icon: 'mail' })
  if (myInvites > 0) actions.push({ title: `Respond to ${myInvites} invitation${myInvites > 1 ? 's' : ''}`, detail: 'You were invited to join a team', priority: 'Medium', to: '/app/invitations', icon: 'bell' })
  if (kind === 'enterprise' && org && isAdmin) {
    if (org.memberCount <= 1) actions.push({ title: 'Invite your team', detail: 'Add requesters, approvers and budget owners', priority: 'Medium', to: '/app/organisation?tab=members', icon: 'team' })
    if (!hasExceptionAuthority) actions.push({ title: 'Name an Exception Authority', detail: 'Must be someone other than an Org Admin', priority: 'Medium', to: '/app/organisation?tab=roles', icon: 'shield' })
    if (units === 0) actions.push({ title: 'Add business units and cost centers', detail: 'Used for budgets and approval routing', priority: 'Low', to: '/app/enterprise/structure', icon: 'building' })
    if (orgInvites > 0) actions.push({ title: `${orgInvites} invitation${orgInvites > 1 ? 's' : ''} not yet accepted`, detail: 'Remind your colleagues or resend', priority: 'Low', to: '/app/organisation?tab=members', icon: 'mail' })
  }
  const toSign = contracts.filter((c) => c.canSign)
  if (toSign.length > 0) actions.unshift({ title: `Sign the contract: ${toSign[0].title}`, detail: `${toSign[0].reference} · then the professional countersigns`, priority: 'High', to: `/app/engagements/${toSign[0].id}`, icon: 'contract' })
  const toApprove = contracts.flatMap((c) => c.milestones.filter((m) => m.status === 'SUBMITTED').map((m) => ({ c, m })))
  if (toApprove.length > 0) actions.unshift({ title: `Review submitted work: M${toApprove[0].m.sequence} ${toApprove[0].m.title}`, detail: toApprove[0].c.title, priority: 'High', to: `/app/engagements/${toApprove[0].c.id}`, icon: 'check' })
  const toReview = requests.filter((r) => r.proposal && ['SUBMITTED', 'UNDER_REVIEW'].includes(r.proposal.status))
  if (toReview.length > 0) actions.unshift({ title: `Review ${toReview.length} proposal${toReview.length > 1 ? 's' : ''}`, detail: `${toReview[0].professional.displayName} replied to “${toReview[0].service}”`, priority: 'High', to: `/app/requests/${toReview[0].id}`, icon: 'proposal' })
  const drafts = requests.filter((r) => r.status === 'DRAFT')
  if (drafts.length > 0) actions.push({ title: 'Finish your draft request', detail: drafts[0].service, priority: 'Medium', to: `/app/requests/${drafts[0].id}`, icon: 'request' })
  if (saved.length === 0) actions.push({ title: 'Find and save professionals', detail: 'Build a shortlist by specialization and Trust Tier', priority: 'Low', to: '/app/find', icon: 'search' })
  const urgent = actions.filter((a) => a.priority !== 'Low')

  return (
    <>
      <PortalHeader eyebrow="Welcome back" title={greeting(user.displayName)}
        subtitle={<>{org && kind === 'enterprise' ? `${org.name} · ` : ''}Manage professional engagements from verified selection through protected completion.</>}
        actions={<>
          <Link className="btn btn-primary" to="/app/find"><Icon name="search" /> Find a Professional</Link>
          <Link className="btn btn-secondary" to="/app/requests/new"><Icon name="request" /> Create a Request</Link>
        </>} />
      <AccountAlerts />

      <div className="stat-row five">
        <StatCard icon="bell" tone="amber" label="Action Required" value={urgent.length} sub={urgent.length ? 'Needs your attention' : 'All caught up'} to="#actions" />
        <StatCard icon="request" tone="blue" label="Open Requests" value={new Set(requests.filter((r) => ['OPEN', 'PROPOSAL_RECEIVED'].includes(r.status)).map((r) => r.groupId)).size}
          sub="Waiting for or receiving proposals" to="/app/requests" />
        <StatCard icon="proposal" tone="violet" label="Proposals" value={toReview.length} sub="Awaiting your review" to="/app/proposals" />
        <StatCard icon="briefcase" tone="green" label="Active Engagements" value={contracts.filter((c) => c.status === 'ACTIVE').length}
          sub={toSign.length ? `${toSign.length} awaiting your signature` : 'In progress'} to="/app/engagements" />
        <StatCard icon="lock" tone="teal" label="Protected Funds" to="/app/payments" sub="In escrow, until you accept"
          value={(() => { const held = contracts.flatMap((c) => c.milestones.filter((m) => ['IN_PROGRESS', 'SUBMITTED', 'REVISION_REQUESTED'].includes(m.status)))
            return held.length ? formatMoney({ amountMinor: held.reduce((s, m) => s + m.amount.amountMinor, 0), currency: held[0].amount.currency }) : formatMoney({ amountMinor: 0, currency: contracts[0]?.total.currency ?? 'USD' }) })()} />
      </div>

      {urgent.length > 0 && !hideBanner && (
        <div className="attention-banner" role="status">
          <span className="kpi-icon amber"><Icon name="bell" /></span>
          <div><strong>{urgent.length} action{urgent.length > 1 ? 's' : ''} require{urgent.length === 1 ? 's' : ''} your attention</strong>
            <div className="muted small">{urgent[0].title}: {urgent[0].detail}</div></div>
          <Link className="btn btn-warn" to={urgent[0].to}>Review now</Link>
          <button className="icon-btn" aria-label="Dismiss" onClick={() => setHideBanner(true)}>×</button>
        </div>
      )}

      <div className="home-grid wide">
        <div>
          <section className="card panel" id="engagements">
            <div className="panel-head"><h2>Your Engagements</h2><Link className="small" to="/app/engagements">View all</Link></div>
            <Tabs<EngTab> tabs={(['all', 'signing', 'active', 'completed'] as const).map((k) => ({ key: k,
              label: { all: 'All', signing: 'Awaiting signature', active: 'In progress', completed: 'Completed' }[k],
              count: k === 'all' ? contracts.length : contracts.filter((c) => engBucket(c) === k).length }))} value={engTab} onChange={setEngTab} />
            {contracts.filter((c) => engTab === 'all' || engBucket(c) === engTab).length === 0 ? (
              <EmptyTable columns={['Professional', 'Service', 'Stage', 'Next action', 'Value']}>
                <strong>No engagements here.</strong> When you accept a proposal, its contract appears here for signing.
              </EmptyTable>
            ) : (
              <table className="data">
                <thead><tr><th>Professional</th><th>Service</th><th>Stage</th><th>Next action</th><th>Value</th></tr></thead>
                <tbody>{contracts.filter((c) => engTab === 'all' || engBucket(c) === engTab).slice(0, 6).map((c) => (
                  <tr key={c.id}>
                    <td className="small">{c.parties.find((p) => p.role === 'PROFESSIONAL')?.name}</td>
                    <td><Link to={`/app/engagements/${c.id}`}><strong>{c.title}</strong></Link></td>
                    <td><span className={`badge ${CONTRACT_STATUS[c.status].tone}`}>{CONTRACT_STATUS[c.status].label}</span></td>
                    <td className="small">{c.nextAction}</td>
                    <td className="small">{formatMoney(c.total)}</td>
                  </tr>))}</tbody>
              </table>
            )}
          </section>

          <section className="card panel" id="requests">
            <div className="panel-head"><h2>Requests &amp; Proposals</h2><Link className="small" to="/app/requests">View all</Link></div>
            <Tabs<ReqTab> tabs={(['all', 'open', 'proposals', 'accepted', 'declined'] as const).map((k) => ({ key: k,
              label: { all: 'All', open: 'Open Requests', proposals: 'Proposals', accepted: 'Accepted', declined: 'Closed' }[k],
              count: k === 'all' ? requests.length : requests.filter((r) => reqBucket(r) === k).length }))} value={reqTab} onChange={setReqTab} />
            {requests.filter((r) => reqTab === 'all' || reqBucket(r) === reqTab).length === 0 ? (
              <EmptyTable columns={['Request', 'Professional', 'Status', 'Proposal', 'Sent']}>
                <strong>Nothing here yet.</strong> Choose professionals in <Link to="/app/find">Find</Link> and select <strong>Request proposal</strong>.
              </EmptyTable>
            ) : (
              <table className="data">
                <thead><tr><th>Request</th><th>Professional</th><th>Status</th><th>Proposal</th><th>Sent</th></tr></thead>
                <tbody>{requests.filter((r) => reqTab === 'all' || reqBucket(r) === reqTab).slice(0, 6).map((r) => (
                  <tr key={r.id}>
                    <td><Link to={`/app/requests/${r.id}`}><strong>{r.service}</strong></Link></td>
                    <td className="small">{r.professional.displayName}</td>
                    <td><span className={`badge ${requestStatus(r).tone}`}>{requestStatus(r).label}</span></td>
                    <td className="small">{r.proposal ? formatMoney(r.proposal.total) : '—'}</td>
                    <td className="small">{r.sentAt ? new Date(r.sentAt).toLocaleDateString() : 'Draft'}</td>
                  </tr>))}</tbody>
              </table>
            )}
          </section>
        </div>

        <aside>
          <section className="card panel attention" id="actions">
            <div className="panel-head"><h2>Pending Actions</h2></div>
            <ActionList actions={actions} empty="You're all caught up." />
          </section>

          <section className="card panel">
            <div className="panel-head"><h2><Icon name="shield" /> Engagement Assurance</h2></div>
            <ul className="assurance">
              {ASSURANCE.map((a) => (
                <li key={a.label}><Icon name={a.icon} /><span>{a.label}</span><span className="ok">✓ {a.value}</span></li>
              ))}
            </ul>
            <div className="protect-note"><Icon name="lock" /><div><strong>Your work is protected</strong>
              <div className="small">Funds are held under protection and released only when agreed conditions are met.</div></div></div>
          </section>

          <section className="card panel" id="saved">
            <div className="panel-head"><h2>Saved Professionals</h2><Link className="small" to="/app/saved">View all</Link></div>
            {saved.length === 0 ? (
              <p className="muted small" style={{ margin: 0 }}>Nothing saved yet. <Link to="/app/find">Find professionals</Link> and save them to compare.</p>
            ) : (
              <ul className="pro-list">
                {saved.slice(0, 4).map((s) => (
                  <li key={s.professionalId}>
                    <Avatar name={s.displayName} photoUrl={s.photoUrl} size={36} />
                    <span><strong>{s.displayName}</strong>
                      <span className="muted small"> · {s.primarySpecialization ?? s.headline} · {LABEL[s.availability] ?? s.availability}</span></span>
                    <Link className="btn btn-secondary btn-sm" to={`/professionals/${s.professionalId}`}>View profile</Link>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </aside>
      </div>
    </>
  )
}

export const BuyerHome = () => <WorkspaceHome kind="buyer" />
export const EnterpriseHome = () => <WorkspaceHome kind="enterprise" />
