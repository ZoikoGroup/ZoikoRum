import { useEffect, useState, type FormEvent } from 'react'
import { Link } from 'react-router-dom'
import type { Contract } from '../api/contracts'
import type { Earnings } from '../api/escrow'
import { messagingApi, type MessageThread } from '../api/messaging'
import { formatMoney } from '../api/orgs'
import { AVAILABILITY, LABEL, proApi, type Availability, type EnterpriseReadiness, type Insights, type Profile, type SavedBuyer } from '../api/professional'
import { earningsRows } from '../lib/dashboardRows'
import { formatCurrencies } from '../lib/money'
import { Icon } from './dashboard'
import { HoursSlider } from './HoursSlider'
import { ErrorAlert } from './ui'

/* Professional Dashboard modules beyond the summary: earnings breakdown (s.12), availability & capacity (s.13),
   messages (s.14), and opportunities & performance (s.16, s.17, s.20) behind one card. */

const STATUS_TONE: Record<string, string> = { Delayed: 'red', 'On hold': 'warn', 'Under review': 'warn', 'Paying out': '', Held: '', Released: 'green' }
const day = (iso: string | null) => (iso ? new Date(iso.length === 10 ? `${iso}T00:00:00` : iso).toLocaleDateString() : '—')

/** s.12: earnings cards (this month, pending release, lifetime) and money per milestone, problems first. */
export function EarningsPanel({ earnings, contracts, pendingRelease }: { earnings: Earnings | null; contracts: Contract[]; pendingRelease: string }) {
  const rows = earningsRows(contracts, earnings?.payouts ?? [])
  const total = (key: 'pending' | 'settled') => earnings ? formatCurrencies(Object.values(earnings.totalsByCurrency).map((t) => t[key])) : '—'
  return (
    <section className="card panel" id="earnings">
      <div className="panel-head"><h2>Earnings &amp; Payouts</h2><Link className="small" to="/app/professional/earnings">View all</Link></div>
      <dl className="facts">
        <dt>Paid out this month (UTC)</dt><dd>{earnings ? formatCurrencies(earnings.monthlySettledByCurrency) : '—'}</dd>
        <dt>Pending release</dt><dd title="Held in escrow until the buyer accepts the milestone">{pendingRelease}</dd>
        <dt>Waiting for payout</dt><dd>{total('pending')}</dd>
        <dt>Lifetime paid out</dt><dd>{total('settled')}</dd>
      </dl>
      {rows.length === 0 ? <p className="muted small" style={{ margin: 0 }}>Money appears here once a buyer funds a milestone. It is released when they accept the work.</p> : (
        <table className="data">
          <thead><tr><th>Engagement</th><th>Milestone</th><th>Amount</th><th>Status</th><th>ETA</th></tr></thead>
          <tbody>{rows.slice(0, 6).map((r) => (
            <tr key={r.key}>
              <td className="small"><Link to={`/app/professional/engagements/${r.contractId}`}>{r.engagement}</Link></td>
              <td className="small">{r.milestone}</td>
              <td className="small">{formatMoney(r.amount)}</td>
              <td><span className={`badge ${STATUS_TONE[r.status]}`}>{r.status}</span>{r.detail && <div className="muted small">{r.detail}</div>}</td>
              <td className="small">{day(r.eta)}</td>
            </tr>))}</tbody>
        </table>
      )}
      {earnings && !earnings.payoutAccount && <p className="muted small" style={{ margin: '8px 0 0' }}>
        Add a <Link to="/app/professional/earnings">payout account</Link> so released money can be paid to you.</p>}
    </section>
  )
}

/** s.13: when you can start, how many engagements at once, hours a week and a pause switch. Saved straight away;
    the profile, search ranking and "At capacity" follow from it. */
export function AvailabilityPanel({ profile, active, onSaved }: { profile: Profile; active: number; onSaved: (p: Profile) => void }) {
  const [availability, setAvailability] = useState<Availability>(profile.availability)
  const [max, setMax] = useState(profile.maxConcurrentEngagements?.toString() ?? '')
  const [paused, setPaused] = useState(profile.temporarilyUnavailable)
  const [hours, setHours] = useState<number | null>(profile.weeklyHours ?? null)
  const [busy, setBusy] = useState(false)
  const [saved, setSaved] = useState(false)
  const [error, setError] = useState<unknown>(null)
  const limit = profile.maxConcurrentEngagements
  const atCapacity = profile.temporarilyUnavailable || (limit !== null && active >= limit)

  async function submit(e: FormEvent) {
    e.preventDefault()
    setBusy(true); setError(null); setSaved(false)
    try {
      onSaved(await proApi.setAvailability({ availability, maxConcurrentEngagements: max ? Number(max) : null, temporarilyUnavailable: paused, weeklyHours: hours }))
      setSaved(true)
    } catch (err) { setError(err) } finally { setBusy(false) }
  }

  return (
    <section className="card panel" id="availability">
      <div className="panel-head"><h2>Availability &amp; Capacity</h2>
        <span className={`badge ${atCapacity ? 'warn' : 'green'}`}>{atCapacity ? 'At capacity' : 'Taking new work'}</span></div>
      <p className="muted small" style={{ marginTop: 0 }}>{active} active engagement{active === 1 ? '' : 's'}{limit !== null ? ` of ${limit} at most` : ''}.
        Buyers see “At capacity” when you reach your limit or pause.</p>
      <ErrorAlert error={error} />
      <form onSubmit={submit}>
        <div className="field">
          <label htmlFor="dash-when">When can you start new work?</label>
          <select id="dash-when" className="input" value={availability} onChange={(e) => setAvailability(e.target.value as Availability)}>
            {AVAILABILITY.map((a) => <option key={a} value={a}>{LABEL[a]}</option>)}
          </select>
        </div>
        <div className="field">
          <label htmlFor="dash-max">Most engagements at once (optional)</label>
          <input id="dash-max" className="input" type="number" min={1} max={50} value={max} onChange={(e) => setMax(e.target.value)} />
        </div>
        <HoursSlider value={hours} onChange={setHours} />
        <label className="checkbox">
          <input type="checkbox" checked={paused} onChange={(e) => setPaused(e.target.checked)} />
          <span>Temporarily not taking new work</span>
        </label>
        <div className="row" style={{ alignItems: 'center' }}>
          <button className="btn btn-secondary btn-sm" disabled={busy}>{busy ? 'Saving…' : 'Save availability'}</button>
          {saved && <span className="muted small" role="status">Saved.</span>}
        </div>
      </form>
    </section>
  )
}

/** s.14: the latest engagement and request conversations. */
export function RecentMessages() {
  const [threads, setThreads] = useState<MessageThread[] | null>(null)
  useEffect(() => { messagingApi.list().then((p) => setThreads(p.items.slice(0, 4))).catch(() => setThreads([])) }, [])
  return (
    <section className="card panel" id="messages">
      <div className="panel-head"><h2>Messages &amp; Activity</h2><Link className="small" to="/app/messages">All messages</Link></div>
      {!threads?.length ? <p className="muted small" style={{ margin: 0 }}>{threads ? 'No conversations yet. Each request and engagement has its own.' : 'Loading…'}</p> : (
        <ul className="pro-list">{threads.map((t) => (
          <li key={t.id}><Icon name="message" /><span><Link to={`/app/messages?contextType=${t.contextType}&contextId=${t.contextId}`}><strong>{t.title}</strong></Link>
            <br /><span className="muted small">{t.counterpartName} · {new Date(t.updatedAt).toLocaleDateString()}</span></span>
            {t.unreadCount > 0 && <span className="badge green">{t.unreadCount} new</span>}</li>))}</ul>
      )}
    </section>
  )
}

/** s.16, s.17, s.20 in one card: headline performance, the buyers you follow, and enterprise readiness when it applies. */
export function OpportunitiesPanel() {
  const [insights, setInsights] = useState<Insights | null>(null)
  const [buyers, setBuyers] = useState<SavedBuyer[]>([])
  const [enterprise, setEnterprise] = useState<EnterpriseReadiness | null>(null)
  useEffect(() => {
    proApi.insights().then(setInsights).catch(() => {})
    proApi.savedBuyers().then(setBuyers).catch(() => {})
    proApi.enterprise().then(setEnterprise).catch(() => {})
  }, [])
  const metrics = (insights?.metrics ?? []).filter((m) => m.value !== null).slice(0, 2)
  // Contextual (s.16): shown once the professional is eligible to apply, applying, or enterprise-ready.
  const eligible = enterprise && (enterprise.status !== 'NONE' || enterprise.requirements.every((r) => r.met))
  const ENTERPRISE_TEXT: Record<EnterpriseReadiness['status'], string> = { NONE: 'You meet the requirements: apply to be shown to enterprise buyers',
    PENDING: 'Your application is being reviewed', READY: 'Enterprise-ready: shown to enterprise buyers', REJECTED: 'Not approved yet: see the reason',
    LAPSED: 'Lapsed: renew to stay visible to enterprise buyers' }
  return (
    <section className="card panel" id="opportunities">
      <div className="panel-head"><h2>Opportunities &amp; Performance</h2></div>
      <ul className="checklist">
        {metrics.map((m) => <li key={m.key}><span title={m.hint}>{m.label}</span><strong>{m.value}%</strong></li>)}
        {insights && metrics.length === 0 && <li><span className="muted small">Figures appear after {insights.minimumSample} proposals or engagements.</span><span /></li>}
        {insights?.averageRating != null && <li><span>Average rating</span><strong>{insights.averageRating.toFixed(1)} ({insights.reviewCount})</strong></li>}
      </ul>
      <Link className="small" to="/app/professional/insights">Performance insights →</Link>
      <h3 style={{ marginTop: 16 }}>Saved buyers</h3>
      {buyers.length === 0 ? <p className="muted small" style={{ margin: 0 }}>Save the organisations you work with to follow their new requests.</p> : (
        <ul className="pro-list">{buyers.slice(0, 3).map((b) => (
          <li key={b.id}><Icon name="building" /><span><strong>{b.name}</strong><br />
            <span className="muted small">{b.engagements} engagement{b.engagements === 1 ? '' : 's'} · {b.requests} request{b.requests === 1 ? '' : 's'}</span></span>
            {b.alerts && <span className="badge" title="You are told about their new requests"><Icon name="bell" /></span>}</li>))}</ul>
      )}
      <Link className="small" to="/app/professional/buyers">Manage saved buyers →</Link>
      {eligible && enterprise && <div className="protect-note" style={{ marginTop: 16 }}><Icon name="building" /><div>
        <strong>Enterprise readiness</strong><div className="small">{ENTERPRISE_TEXT[enterprise.status]}</div>
        <Link className="small" to="/app/professional/enterprise">{enterprise.status === 'NONE' ? 'Apply for enterprise readiness →' : 'View details →'}</Link></div></div>}
    </section>
  )
}
