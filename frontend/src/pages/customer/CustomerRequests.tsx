import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { formatMoney } from '../../api/orgs'
import { LABEL } from '../../api/professional'
import {
  budgetText, DURATION_LABEL, PROPOSAL_STATUS, proposalApi, requestStatus, type Proposal, type ProposalRequest,
} from '../../api/proposals'
import { Avatar, Icon } from '../../components/dashboard'
import { EmptyTable, PortalHeader, SidePanel, StatCard, Tabs, TierBadge } from '../../components/portal'
import { ErrorAlert } from '../../components/ui'

/* Customer side of Step 6: requests (one requirement sent to 1–3 professionals), the proposals that come back,
   side-by-side comparison, revision requests and acceptance. */

const fmtDate = (d: string | null) => (d ? new Date(d.length === 10 ? `${d}T00:00:00` : d).toLocaleDateString() : '—')

interface Group { id: string; first: ProposalRequest; members: ProposalRequest[] }

function groupRequests(list: ProposalRequest[]): Group[] {
  const map = new Map<string, Group>()
  for (const r of list) {
    const g = map.get(r.groupId)
    if (g) g.members.push(r)
    else map.set(r.groupId, { id: r.groupId, first: r, members: [r] })
  }
  return [...map.values()]
}

function groupState(g: Group): { key: 'draft' | 'open' | 'closed'; label: string; tone: '' | 'green' | 'warn'; next: string } {
  const m = g.members
  const accepted = m.find((r) => r.proposal?.status === 'ACCEPTED')
  const toReview = m.filter((r) => r.proposal && ['SUBMITTED', 'UNDER_REVIEW'].includes(r.proposal.status)).length
  if (m.every((r) => r.status === 'DRAFT')) return { key: 'draft', label: 'Draft', tone: '', next: 'Review and send' }
  if (accepted) return { key: 'closed', label: 'Proposal accepted', tone: 'green', next: `Contract with ${accepted.professional.displayName} (next step)` }
  if (m.some((r) => ['OPEN', 'PROPOSAL_RECEIVED'].includes(r.status))) {
    if (toReview) return { key: 'open', label: `${toReview} proposal${toReview > 1 ? 's' : ''} received`, tone: 'warn', next: `Review ${toReview > 1 ? 'and compare' : 'proposal'}` }
    if (m.some((r) => r.proposal?.status === 'REVISION_REQUESTED')) return { key: 'open', label: 'Revision requested', tone: '', next: 'Waiting for the revised proposal' }
    return { key: 'open', label: 'Awaiting proposals', tone: '', next: 'Waiting for professionals to respond' }
  }
  return { key: 'closed', label: m.every((r) => r.status === 'CANCELLED') ? 'Cancelled' : 'Closed', tone: '', next: '—' }
}

function useBuyerRequests() {
  const [list, setList] = useState<ProposalRequest[] | null>(null)
  const [error, setError] = useState<unknown>(null)
  const load = useCallback(() => proposalApi.list('buyer').then(setList).catch(setError), [])
  useEffect(() => { load() }, [load])
  return { list, error, load }
}

/** Requests (management design 4), now with real data. */
export function RequestsPage() {
  const { list, error } = useBuyerRequests()
  const [tab, setTab] = useState<'all' | 'draft' | 'open' | 'closed'>('all')
  const groups = useMemo(() => groupRequests(list ?? []), [list])
  const count = (k: string) => groups.filter((g) => groupState(g).key === k).length
  const received = (list ?? []).filter((r) => r.proposal && ['SUBMITTED', 'UNDER_REVIEW'].includes(r.proposal.status)).length
  const accepted = (list ?? []).filter((r) => r.proposal?.status === 'ACCEPTED').length
  const shown = groups.filter((g) => tab === 'all' || groupState(g).key === tab)

  return (
    <>
      <PortalHeader eyebrow="Requests" title="Your requests"
        subtitle="Create, govern and progress professional requests from draft through selection."
        actions={<Link className="btn btn-primary" to="/app/find"><Icon name="search" /> Find a Professional</Link>} />
      <ErrorAlert error={error} />
      <div className="stat-row four">
        <StatCard icon="request" tone="amber" value={list ? count('draft') : '…'} label="Draft" sub="Complete and send" />
        <StatCard icon="proposal" tone="blue" value={list ? count('open') : '…'} label="Open" sub="Waiting for or receiving proposals" />
        <StatCard icon="message" tone="violet" value={list ? received : '…'} label="Proposals to review" sub="Compare and decide" to="/app/proposals" />
        <StatCard icon="check" tone="green" value={list ? accepted : '…'} label="Accepted" sub="Ready for contract" />
      </div>
      <div className="home-grid wide">
        <section className="card panel">
          <Tabs tabs={[{ key: 'all', label: 'All requests', count: groups.length }, { key: 'draft', label: 'Draft', count: count('draft') },
            { key: 'open', label: 'Open', count: count('open') }, { key: 'closed', label: 'Closed', count: count('closed') }]} value={tab} onChange={setTab} />
          {list && shown.length === 0 ? (
            <EmptyTable columns={['Request', 'Professionals', 'Status', 'Next action', 'Start']}>
              <strong>No requests here.</strong> Open a professional's profile, or select up to three in <Link to="/app/find">Find</Link> or
              {' '}<Link to="/app/saved">Saved</Link>, and choose <strong>Request proposal</strong>.
            </EmptyTable>
          ) : (
            <div className="compare-scroll"><table className="data">
              <thead><tr><th>Request</th><th>Professionals</th><th>Status</th><th>Next action</th><th>Start</th></tr></thead>
              <tbody>{shown.map((g) => {
                const s = groupState(g)
                return (
                  <tr key={g.id}>
                    <td><Link to={`/app/requests/${g.first.id}`}><strong>{g.first.service}</strong></Link>
                      <div className="muted small clamp">{g.first.objective}</div></td>
                    <td><div className="avatar-stack">{g.members.map((m) => <Avatar key={m.id} name={m.professional.displayName} photoUrl={m.professional.photoUrl} size={30} />)}</div>
                      <span className="muted small">{g.members.map((m) => m.professional.displayName).join(', ')}</span></td>
                    <td><span className={`badge ${s.tone}`}>{s.label}</span></td>
                    <td className="small">{s.next}</td>
                    <td className="small">{fmtDate(g.first.desiredStartDate)}</td>
                  </tr>
                )
              })}</tbody>
            </table></div>
          )}
        </section>
        <aside>
          <SidePanel title="How a request works">
            <ol className="side-steps">{[['Choose professionals', 'From a profile, search, your saved list or a comparison — up to three.'],
              ['Describe the need', 'Objective, scope, timing and an optional budget.'], ['Protect confidentiality', 'Require an NDA before they see the details.'],
              ['Compare and accept', 'Each replies with a structured proposal; accept one and the others close.']].map(([t, d], i) => (
              <li key={t}><span className="n">{i + 1}</span><span><strong>{t}</strong><br /><span className="muted small">{d}</span></span></li>))}</ol>
          </SidePanel>
        </aside>
      </div>
    </>
  )
}

/** Proposals (management design 5): every proposal received, across requests. */
export function ProposalsPage() {
  const { list, error } = useBuyerRequests()
  const [tab, setTab] = useState<'all' | 'review' | 'revision' | 'accepted' | 'closed'>('all')
  const rows = (list ?? []).filter((r) => r.proposal)
  const bucket = (r: ProposalRequest) => {
    const s = r.proposal!.status
    return ['SUBMITTED', 'UNDER_REVIEW'].includes(s) ? 'review' : s === 'REVISION_REQUESTED' ? 'revision' : s === 'ACCEPTED' ? 'accepted' : 'closed'
  }
  const n = (k: string) => rows.filter((r) => bucket(r) === k).length
  const shown = rows.filter((r) => tab === 'all' || bucket(r) === tab)
  return (
    <>
      <PortalHeader eyebrow="Proposals" title="Your proposals" subtitle="Review, compare and select proposals from verified professionals."
        actions={<Link className="btn btn-secondary" to="/app/requests"><Icon name="request" /> Your requests</Link>} />
      <ErrorAlert error={error} />
      <div className="stat-row four">
        <StatCard icon="request" tone="amber" value={list ? n('review') : '…'} label="Awaiting review" sub="New proposals to review" />
        <StatCard icon="message" tone="blue" value={list ? n('revision') : '…'} label="Revision requested" sub="Waiting for the professional" />
        <StatCard icon="check" tone="green" value={list ? n('accepted') : '…'} label="Accepted" sub="Ready for contract" />
        <StatCard icon="clock" tone="violet" value={list ? n('closed') : '…'} label="Not selected" sub="Declined, withdrawn or expired" />
      </div>
      <section className="card panel">
        <Tabs tabs={[{ key: 'all', label: 'All proposals', count: rows.length }, { key: 'review', label: 'Awaiting review', count: n('review') },
          { key: 'revision', label: 'Revision requested', count: n('revision') }, { key: 'accepted', label: 'Accepted', count: n('accepted') },
          { key: 'closed', label: 'Not selected', count: n('closed') }]} value={tab} onChange={setTab} />
        {list && shown.length === 0 ? (
          <EmptyTable columns={['Professional', 'Request', 'Price', 'Status', 'Received', 'Valid until']}>
            <strong>No proposals here.</strong> Proposals arrive in reply to your <Link to="/app/requests">requests</Link>.
          </EmptyTable>
        ) : (
          <div className="compare-scroll"><table className="data">
            <thead><tr><th>Professional</th><th>Request</th><th>Price</th><th>Status</th><th>Received</th><th>Valid until</th><th /></tr></thead>
            <tbody>{shown.map((r) => {
              const st = PROPOSAL_STATUS[r.proposal!.status]
              return (
                <tr key={r.id}>
                  <td><div className="name-row"><Avatar name={r.professional.displayName} photoUrl={r.professional.photoUrl} size={32} />
                    <span><strong>{r.professional.displayName}</strong><br /><TierBadge tier={r.professional.tier} /></span></div></td>
                  <td className="small">{r.service}</td>
                  <td><strong>{formatMoney(r.proposal!.total)}</strong></td>
                  <td><span className={`badge ${st.tone}`}>{st.label}</span></td>
                  <td className="small">{fmtDate(r.proposal!.submittedAt)}</td>
                  <td className="small">{fmtDate(r.proposal!.validUntil)}</td>
                  <td><Link className="btn btn-secondary btn-sm" to={`/app/requests/${r.id}`}>Review</Link></td>
                </tr>
              )
            })}</tbody>
          </table></div>
        )}
      </section>
    </>
  )
}

/** One requirement: its professionals, their proposals side by side, and the buyer's decisions. */
export function RequestDetailPage() {
  const { id = '' } = useParams()
  const [req, setReq] = useState<ProposalRequest | null>(null)
  const [members, setMembers] = useState<ProposalRequest[]>([])
  const [proposals, setProposals] = useState<Proposal[]>([])
  const [error, setError] = useState<unknown>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const load = useCallback(async () => {
    try {
      const r = await proposalApi.get(id)
      const [all, props] = await Promise.all([proposalApi.list('buyer'), proposalApi.proposals(id)])
      setReq(r)
      setMembers(all.filter((x) => x.groupId === r.groupId))
      setProposals(props)
    } catch (err) {
      setError(err)
    }
  }, [id])
  useEffect(() => { load() }, [load])

  async function act(fn: () => Promise<unknown>, msg: string) {
    setBusy(true)
    setError(null)
    try { await fn(); setNotice(msg); await load() } catch (err) { setError(err) } finally { setBusy(false) }
  }

  if (!req) return error ? <ErrorAlert error={error} /> : <p className="muted">Loading…</p>
  const group: Group = { id: req.groupId, first: req, members: members.length ? members : [req] }
  const state = groupState(group)
  const isDraft = group.members.every((m) => m.status === 'DRAFT')
  const openOnes = group.members.filter((m) => ['DRAFT', 'OPEN', 'PROPOSAL_RECEIVED'].includes(m.status))
  const accepted = proposals.find((p) => p.status === 'ACCEPTED')
  const byRequest = new Map(proposals.map((p) => [p.requestId, p]))

  return (
    <>
      <PortalHeader eyebrow={<Link to="/app/requests">← Requests</Link>} title={req.service}
        subtitle={<><span className={`badge ${state.tone}`}>{state.label}</span> · Sent to {group.members.length} professional{group.members.length > 1 ? 's' : ''}{req.sentAt ? ` on ${fmtDate(req.sentAt)}` : ''}</>}
        actions={<>
          {isDraft && <button className="btn btn-primary" disabled={busy} onClick={() => act(() => proposalApi.send(req.id), 'Request sent.')}>Send request</button>}
          {openOnes.length > 0 && !accepted && <button className="btn btn-secondary" disabled={busy} onClick={() => {
            if (confirm('Cancel this request? Professionals will be told it is no longer needed.')) act(() => Promise.all(openOnes.map((m) => proposalApi.cancel(m.id))), 'Request cancelled.')
          }}>Cancel request</button>}
        </>} />
      {notice && <div className="alert alert-success" role="status">{notice}</div>}
      <ErrorAlert error={error} />
      {accepted && <div className="attention-banner ok"><span className="kpi-icon green"><Icon name="check" /></span>
        <div><strong>You accepted {accepted.professional.displayName}'s proposal ({formatMoney(accepted.total)}).</strong>
          <div className="muted small">The terms are locked (reference {accepted.termsHash?.slice(0, 12)}…). Contract signing and escrow funding arrive in the next release.</div></div></div>}

      <div className="home-grid wide">
        <div>
          {proposals.length >= 2 && <CompareProposals proposals={proposals} />}
          {group.members.map((m) => {
            const p = byRequest.get(m.id)
            return p ? <ProposalCard key={m.id} p={p} busy={busy} canDecide={!accepted}
              onAccept={() => { if (confirm(`Accept ${p.professional.displayName}'s proposal for ${formatMoney(p.total)}?${group.members.length > 1 ? ' The other proposals for this request will be closed.' : ''}`)) act(() => proposalApi.accept(p.id), 'Proposal accepted.') }}
              onReject={(note) => act(() => proposalApi.reject(p.id, note), 'Proposal declined.')}
              onRevise={(changes, note) => act(() => proposalApi.requestRevision(p.id, changes, note), 'Revision requested. The professional has been notified.')} />
              : <section key={m.id} className="card panel waiting-card">
                <div className="name-row"><Avatar name={m.professional.displayName} photoUrl={m.professional.photoUrl} size={44} />
                  <span><strong>{m.professional.displayName}</strong> <TierBadge tier={m.professional.tier} /><br />
                    <span className="muted small">{m.professional.headline}</span></span>
                  <span className={`badge ${requestStatus(m).tone}`} style={{ marginLeft: 'auto' }}>{requestStatus(m).label}</span></div>
                {m.status === 'DECLINED' && <p className="muted small" style={{ margin: '10px 0 0' }}>Declined{m.reasonCode ? `: ${m.reasonCode.replace(/_/g, ' ').toLowerCase()}` : ''}{m.reasonNote ? ` — “${m.reasonNote}”` : ''}</p>}
                {['OPEN'].includes(m.status) && <p className="muted small" style={{ margin: '10px 0 0' }}>No proposal yet.{m.professional.tier === 'C' ? ' This professional must verify their identity before they can send one.' : ''}</p>}
              </section>
          })}
        </div>
        <aside>
          <SidePanel title="Your request">
            <dl className="facts">
              <dt>Objective</dt><dd>{req.objective}</dd>
              <dt>Engagement</dt><dd>{LABEL[req.engagementType]}</dd>
              <dt>Start</dt><dd>{fmtDate(req.desiredStartDate)} · {DURATION_LABEL[req.estimatedDuration]}</dd>
              <dt>Delivery</dt><dd>{LABEL[req.deliveryMode]}{req.location ? ` · ${req.location}` : ''}</dd>
              <dt>Budget</dt><dd>{budgetText(req.budget)}</dd>
              <dt>NDA</dt><dd>{req.ndaRequired ? 'Required before proposal' : 'Not required'}</dd>
              <dt>Organisation</dt><dd>{req.organizationName}</dd>
            </dl>
            {req.details && <p className="small" style={{ whiteSpace: 'pre-wrap', marginTop: 12 }}>{req.details}</p>}
            {req.attachments.length > 0 && <ul className="pro-list">{req.attachments.map((a) => <li key={a.sha256}><Icon name="request" /><span className="small">{a.name}</span><span /></li>)}</ul>}
          </SidePanel>
          <SidePanel title="After you accept">
            <ol className="side-steps">{[['Contract generated', 'From the accepted scope, milestones and price.'], ['Both parties sign', 'Terms are then locked.'],
              ['Fund the first milestone', 'Money is held in escrow until you accept the work.']].map(([t, d], i) => (
              <li key={t}><span className="n">{i + 1}</span><span><strong>{t}</strong><br /><span className="muted small">{d}</span></span></li>))}</ol>
          </SidePanel>
        </aside>
      </div>
    </>
  )
}

function CompareProposals({ proposals }: { proposals: Proposal[] }) {
  const live = proposals.filter((p) => p.status !== 'WITHDRAWN')
  const rows: [string, (p: Proposal) => React.ReactNode][] = [
    ['Trust Tier', (p) => <TierBadge tier={p.professional.tier} />],
    ['Price', (p) => <strong>{formatMoney(p.total)}</strong>],
    ['Pricing model', (p) => LABEL[p.pricingModel] ?? p.pricingModel],
    ['Vs your budget', (p) => p.deltas.find((d) => d.field === 'price')?.status.toLowerCase() ?? '—'],
    ['Timeline', (p) => `${fmtDate(p.startDate)} – ${fmtDate(p.endDate)}`],
    ['Deliverables', (p) => p.deliverables.length],
    ['Milestones', (p) => p.milestones.length],
    ['Scope', (p) => (p.scopeAlignment === 'ADJUSTED' ? 'Adjusted' : 'As requested')],
    ['Valid until', (p) => fmtDate(p.validUntil)],
    ['Status', (p) => <span className={`badge ${PROPOSAL_STATUS[p.status].tone}`}>{PROPOSAL_STATUS[p.status].label}</span>],
  ]
  return (
    <section className="card panel">
      <div className="panel-head"><h2>Compare proposals</h2></div>
      <div className="compare-scroll"><table className="data compare-table">
        <thead><tr><th />{live.map((p) => <th key={p.id}>{p.professional.displayName}</th>)}</tr></thead>
        <tbody>{rows.map(([label, render]) => <tr key={label}><th scope="row">{label}</th>{live.map((p) => <td key={p.id}>{render(p)}</td>)}</tr>)}</tbody>
      </table></div>
    </section>
  )
}

function ProposalCard({ p, busy, canDecide, onAccept, onReject, onRevise }: {
  p: Proposal; busy: boolean; canDecide: boolean; onAccept: () => void; onReject: (note?: string) => void
  onRevise: (changes: { field: string; requested: string }[], note?: string) => void
}) {
  const [open, setOpen] = useState(false)
  const [revising, setRevising] = useState(false)
  const [field, setField] = useState('price')
  const [text, setText] = useState('')
  const st = PROPOSAL_STATUS[p.status]
  const decidable = canDecide && ['SUBMITTED', 'UNDER_REVIEW'].includes(p.status) && !p.expired
  return (
    <section className="card panel proposal-card">
      <div className="name-row"><Avatar name={p.professional.displayName} photoUrl={p.professional.photoUrl} size={44} />
        <span><strong>{p.professional.displayName}</strong> <TierBadge tier={p.professional.tier} /><br /><span className="muted small">{p.professional.headline}</span></span>
        <span style={{ marginLeft: 'auto', textAlign: 'right' }}><strong className="big-price">{formatMoney(p.total)}</strong><br />
          <span className={`badge ${st.tone}`}>{st.label}</span></span></div>
      <p style={{ margin: '14px 0 10px' }}>{p.summary}</p>
      <div className="delta-row">{p.deltas.map((d) => (
        <span key={d.field} className={`delta ${['MATCH', 'WITHIN'].includes(d.status) ? 'ok' : 'diff'}`} title={`You asked: ${d.requested}`}>
          {d.label}: <strong>{d.proposed}</strong></span>))}</div>
      <div className="small"><strong>Deliverables:</strong> {p.deliverables.slice(0, 3).map((d) => d.title).join(' · ')}{p.deliverables.length > 3 ? ` +${p.deliverables.length - 3} more` : ''}</div>
      {open && <div className="proposal-detail">
        <table className="data"><thead><tr><th>#</th><th>Milestone</th><th>Delivers</th><th>Due</th><th>Amount</th></tr></thead>
          <tbody>{p.milestones.map((m, i) => <tr key={i}><td>{i + 1}</td><td><strong>{m.title}</strong>{m.description && <div className="muted small">{m.description}</div>}</td>
            <td className="small">{m.deliverableKeys.map((k) => p.deliverables.find((d) => d.key === k)?.title ?? k).join(', ')}</td>
            <td className="small">{fmtDate(m.dueDate)}</td><td>{formatMoney({ amountMinor: m.amountMinor, currency: p.currency })}</td></tr>)}</tbody></table>
        <h3 style={{ marginTop: 16 }}>Acceptance criteria</h3>
        <ul className="why">{p.deliverables.map((d) => <li key={d.key}><strong>{d.title}:</strong> {d.acceptanceCriteria}</li>)}</ul>
        {p.scopeNotes && <><h3>Scope notes</h3><p className="small">{p.scopeNotes}</p></>}
        <div className="row" style={{ alignItems: 'flex-start' }}>
          {p.assumptions.length > 0 && <div style={{ flex: 1 }}><h3>Assumptions</h3><ul className="why">{p.assumptions.map((a) => <li key={a}>{a}</li>)}</ul></div>}
          {p.exclusions.length > 0 && <div style={{ flex: 1 }}><h3>Exclusions</h3><ul className="why">{p.exclusions.map((a) => <li key={a}>{a}</li>)}</ul></div>}
        </div>
        {p.revisionRequests.length > 0 && <p className="muted small">You requested {p.revisionRequests.length} revision{p.revisionRequests.length > 1 ? 's' : ''}; this is the latest version.</p>}
      </div>}
      {revising && <div className="revise-box">
        <div className="row">
          <label className="filter-box"><span>What should change?</span><select value={field} onChange={(e) => setField(e.target.value)}>
            {['price', 'timeline', 'scope', 'deliverables', 'milestones', 'assumptions', 'exclusions', 'other'].map((x) => <option key={x} value={x}>{x[0].toUpperCase() + x.slice(1)}</option>)}</select></label>
          <label className="filter-box grow"><span>Your request</span><input value={text} maxLength={500} onChange={(e) => setText(e.target.value)} placeholder="e.g. Can milestone 2 finish a week earlier?" /></label>
        </div>
        <div className="row" style={{ marginTop: 8 }}><button className="btn btn-primary btn-sm" disabled={busy || text.trim().length < 2}
          onClick={() => { onRevise([{ field, requested: text.trim() }]); setRevising(false); setText('') }}>Send revision request</button>
          <button className="btn btn-ghost btn-sm" onClick={() => setRevising(false)}>Cancel</button></div>
      </div>}
      <div className="row card-actions">
        <button className="btn btn-ghost btn-sm" onClick={() => setOpen(!open)}>{open ? 'Hide details' : 'View details'}</button>
        {decidable && <>
          <button className="btn btn-secondary btn-sm" disabled={busy} onClick={() => setRevising(true)}>Request revision</button>
          <button className="btn btn-ghost btn-sm danger-text" disabled={busy} onClick={() => { const note = prompt('Optional: tell them why (kept respectful and private)') ?? undefined; onReject(note) }}>Decline</button>
          <button className="btn btn-primary" disabled={busy} onClick={onAccept}>Accept proposal</button>
        </>}
        {p.expired && <span className="muted small">This proposal expired on {fmtDate(p.validUntil)}.</span>}
      </div>
    </section>
  )
}
