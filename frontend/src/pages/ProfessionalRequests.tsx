import { useCallback, useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { formatMoney } from '../api/orgs'
import { CURRENCIES, LABEL, toMinor } from '../api/professional'
import {
  budgetText, DECLINE_REASONS, DURATION_LABEL, PROPOSAL_STATUS, proposalApi, requestStatus,
  type DeclineReason, type Deliverable, type Proposal, type ProposalInput, type ProposalRequest,
} from '../api/proposals'
import { Avatar, Icon } from '../components/dashboard'
import { EmptyTable, PortalHeader, SidePanel, StatCard, Tabs } from '../components/portal'
import { ErrorAlert, Field } from '../components/ui'

/* Professional side of Step 6 (Professional Dashboard doc s.7–8): incoming requests, NDA, the structured proposal
   builder, revisions, decline with a reason. Professionals do not browse jobs: buyers choose them and send requests. */

const fmtDate = (d: string | null) => (d ? new Date(d.length === 10 ? `${d}T00:00:00` : d).toLocaleDateString() : '—')
const plusDays = (n: number) => new Date(Date.now() + n * 86_400_000).toISOString().slice(0, 10)
type Bucket = 'new' | 'sent' | 'revision' | 'closed'

function bucket(r: ProposalRequest): Bucket {
  const s = r.proposal?.status
  if (r.status === 'OPEN') return 'new'
  if (s === 'REVISION_REQUESTED') return 'revision'
  if (r.status === 'PROPOSAL_RECEIVED') return 'sent'
  return 'closed'
}

export function ProfessionalRequestsPage() {
  const [list, setList] = useState<ProposalRequest[] | null>(null)
  const [error, setError] = useState<unknown>(null)
  const [tab, setTab] = useState<Bucket | 'all'>('new')
  useEffect(() => { proposalApi.list('professional').then(setList).catch(setError) }, [])
  const rows = list ?? []
  const n = (b: Bucket) => rows.filter((r) => bucket(r) === b).length
  const shown = rows.filter((r) => tab === 'all' || bucket(r) === tab)
  const won = rows.filter((r) => r.proposal?.status === 'ACCEPTED').length

  return (
    <>
      <PortalHeader eyebrow="Requests" title="Incoming requests" subtitle="Buyers who chose you. Reply with a structured proposal, or decline with a reason." />
      <ErrorAlert error={error} />
      <div className="stat-row four">
        <StatCard icon="proposal" tone="amber" value={list ? n('new') : '…'} label="New requests" sub="Waiting for your proposal" />
        <StatCard icon="message" tone="violet" value={list ? n('revision') : '…'} label="Revision requested" sub="The buyer asked for changes" />
        <StatCard icon="request" tone="blue" value={list ? n('sent') : '…'} label="Proposals sent" sub="Waiting for the buyer" />
        <StatCard icon="check" tone="green" value={list ? won : '…'} label="Accepted" sub="Ready for contract" />
      </div>
      <section className="card panel">
        <Tabs tabs={[{ key: 'new', label: 'New', count: n('new') }, { key: 'revision', label: 'Revision requested', count: n('revision') },
          { key: 'sent', label: 'Sent', count: n('sent') }, { key: 'closed', label: 'Closed', count: n('closed') }, { key: 'all', label: 'All', count: rows.length }]}
          value={tab} onChange={setTab} />
        {list && shown.length === 0 ? (
          <EmptyTable columns={['Buyer', 'Service', 'Type', 'Budget', 'Start', 'Status']}>
            <strong>Nothing here yet.</strong> Buyers find you through search and send requests. A complete, verified profile with clear
            {' '}<Link to="/app/professional/offerings">service offerings</Link> gets found more often.
          </EmptyTable>
        ) : (
          <div className="compare-scroll"><table className="data">
            <thead><tr><th>Buyer</th><th>Service</th><th>Type</th><th>Budget</th><th>Start</th><th>Status</th><th /></tr></thead>
            <tbody>{shown.map((r) => {
              const st = requestStatus(r)
              return (
                <tr key={r.id}>
                  <td><strong>{r.organizationName ?? r.buyerName}</strong><div className="muted small">{r.buyerName}</div></td>
                  <td className="small">{r.service}{r.ndaRequired && <> <span className="badge">NDA</span></>}</td>
                  <td className="small">{LABEL[r.engagementType]}</td>
                  <td className="small">{budgetText(r.budget)}</td>
                  <td className="small">{fmtDate(r.desiredStartDate)}</td>
                  <td><span className={`badge ${st.tone}`}>{st.label}</span></td>
                  <td><Link className={`btn btn-sm ${bucket(r) === 'new' || bucket(r) === 'revision' ? 'btn-primary' : 'btn-secondary'}`}
                    to={`/app/professional/requests/${r.id}`}>{bucket(r) === 'new' ? 'Respond' : bucket(r) === 'revision' ? 'Revise' : 'View'}</Link></td>
                </tr>
              )
            })}</tbody>
          </table></div>
        )}
      </section>
    </>
  )
}

const EMPTY = (currency: string): ProposalInput => ({
  summary: '', scopeAlignment: 'CONFIRMED', scopeNotes: null,
  deliverables: [{ key: 'd1', title: '', description: '', acceptanceCriteria: '' }],
  milestones: [{ title: '', description: '', amountMinor: 0, dueDate: null, deliverableKeys: ['d1'] }],
  pricingModel: 'FIXED', currency, startDate: null, endDate: null, assumptions: [], exclusions: [], validUntil: plusDays(14),
})

const fromProposal = (p: Proposal): ProposalInput => ({
  summary: p.summary, scopeAlignment: p.scopeAlignment, scopeNotes: p.scopeNotes, deliverables: p.deliverables, milestones: p.milestones,
  pricingModel: p.pricingModel, currency: p.currency, startDate: p.startDate, endDate: p.endDate, assumptions: p.assumptions,
  exclusions: p.exclusions, validUntil: p.validUntil,
})

export function ProfessionalRequestDetail() {
  const { id = '' } = useParams()
  const [req, setReq] = useState<ProposalRequest | null>(null)
  const [proposal, setProposal] = useState<Proposal | null>(null)
  const [form, setForm] = useState<ProposalInput | null>(null)
  const [amounts, setAmounts] = useState<string[]>([])
  const [error, setError] = useState<unknown>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [declining, setDeclining] = useState(false)

  const load = useCallback(async () => {
    try {
      const r = await proposalApi.get(id)
      const mine = (await proposalApi.proposals(id))[0] ?? null
      setReq(r)
      setProposal(mine)
      const f = mine ? fromProposal(mine) : EMPTY(r.budget?.currency ?? 'USD')
      setForm(f)
      setAmounts(f.milestones.map((m) => (m.amountMinor ? String(m.amountMinor / 100) : '')))
    } catch (err) {
      setError(err)
    }
  }, [id])
  useEffect(() => { load() }, [load])

  if (!req || !form) return error ? <ErrorAlert error={error} /> : <p className="muted">Loading…</p>
  const editable = (req.status === 'OPEN' && (!proposal || proposal.status === 'DRAFT')) || proposal?.status === 'REVISION_REQUESTED'
  const set = <K extends keyof ProposalInput>(k: K, v: ProposalInput[K]) => setForm({ ...form, [k]: v })
  const body = (): ProposalInput => ({ ...form, milestones: form.milestones.map((m, i) => ({ ...m, amountMinor: amounts[i] ? toMinor(amounts[i]) : 0 })) })
  const total = form.milestones.reduce((s, _, i) => s + (amounts[i] ? toMinor(amounts[i]) : 0), 0)

  async function run(fn: () => Promise<unknown>, msg: string) {
    setBusy(true)
    setError(null)
    setNotice(null)
    try { await fn(); setNotice(msg); await load() } catch (err) { setError(err) } finally { setBusy(false) }
  }
  const save = async (): Promise<Proposal> => (proposal ? proposalApi.updateProposal(proposal.id, body()) : proposalApi.createProposal(req.id, body()))
  const nextKey = () => `d${Math.max(0, ...form.deliverables.map((d) => Number(d.key.slice(1)) || 0)) + 1}`
  const setDeliverable = (i: number, patch: Partial<Deliverable>) => set('deliverables', form.deliverables.map((d, j) => (j === i ? { ...d, ...patch } : d)))
  const lastRevision = proposal?.revisionRequests[proposal.revisionRequests.length - 1]

  return (
    <>
      <PortalHeader eyebrow={<Link to="/app/professional/requests">← Incoming requests</Link>} title={req.service}
        subtitle={<>From <strong>{req.organizationName ?? req.buyerName}</strong> · <span className={`badge ${requestStatus(req).tone}`}>{requestStatus(req).label}</span></>}
        actions={req.status === 'OPEN' && (!proposal || proposal.status === 'DRAFT')
          ? <button className="btn btn-secondary" onClick={() => setDeclining(true)}>Decline request</button> : undefined} />
      {notice && <div className="alert alert-success" role="status">{notice}</div>}
      <ErrorAlert error={error} />

      {declining && <DeclineForm busy={busy} onCancel={() => setDeclining(false)}
        onDecline={(reason, note) => run(() => proposalApi.decline(req.id, reason, note), 'Request declined. The buyer has been told, with your reason.').then(() => setDeclining(false))} />}

      {proposal?.status === 'REVISION_REQUESTED' && lastRevision && <div className="attention-banner"><span className="kpi-icon amber"><Icon name="message" /></span>
        <div><strong>The buyer asked for changes</strong>
          <ul className="why" style={{ margin: '4px 0 0' }}>{lastRevision.changes.map((c, i) => <li key={i}><strong>{c.field}:</strong> {c.requested}</li>)}</ul>
          {lastRevision.note && <div className="muted small">“{lastRevision.note}”</div>}</div></div>}

      <div className="home-grid wide">
        <div>
          {req.detailsHidden ? (
            <section className="card panel nda-gate">
              <span className="kpi-icon violet big"><Icon name="lock" /></span>
              <h2>This buyer requires an NDA</h2>
              <p className="muted">Accept the non-disclosure agreement to see the objective, details and files. Accepting is recorded in the audit log.</p>
              <button className="btn btn-primary" disabled={busy} onClick={() => run(() => proposalApi.acceptNda(req.id), 'NDA accepted.')}>Accept NDA and view details</button>
            </section>
          ) : proposal && !editable ? (
            <SentProposal p={proposal} busy={busy} onWithdraw={() => {
              if (confirm('Withdraw this proposal? The request will close for you.')) run(() => proposalApi.withdraw(proposal.id), 'Proposal withdrawn.')
            }} />
          ) : editable ? (
            <section className="card panel builder">
              <div className="panel-head"><h2>{proposal?.status === 'REVISION_REQUESTED' ? 'Revise your proposal' : 'Your proposal'}</h2>
                {proposal && <span className={`badge ${PROPOSAL_STATUS[proposal.status].tone}`}>{PROPOSAL_STATUS[proposal.status].label}</span>}</div>
              <Field label="Summary for the buyer" id="p-sum" hint={`${form.summary.length}/500`}>
                <textarea id="p-sum" className="input" rows={3} maxLength={500} value={form.summary} onChange={(e) => set('summary', e.target.value)} /></Field>
              <div className="field"><span className="label">Scope</span>
                <div className="choice-grid two">
                  <label className={`choice ${form.scopeAlignment === 'CONFIRMED' ? 'on' : ''}`}><input type="radio" checked={form.scopeAlignment === 'CONFIRMED'} onChange={() => set('scopeAlignment', 'CONFIRMED')} /><strong>Confirm the scope as requested</strong></label>
                  <label className={`choice ${form.scopeAlignment === 'ADJUSTED' ? 'on' : ''}`}><input type="radio" checked={form.scopeAlignment === 'ADJUSTED'} onChange={() => set('scopeAlignment', 'ADJUSTED')} /><strong>Propose changes</strong></label>
                </div>
                {form.scopeAlignment === 'ADJUSTED' && <textarea className="input" rows={2} maxLength={1000} aria-label="Scope changes" placeholder="What you would change, and why"
                  value={form.scopeNotes ?? ''} onChange={(e) => set('scopeNotes', e.target.value)} style={{ marginTop: 8 }} />}</div>

              <h3>Deliverables</h3>
              {form.deliverables.map((d, i) => (
                <div key={d.key} className="builder-row">
                  <span className="n">{i + 1}</span>
                  <div className="builder-fields">
                    <input className="input" aria-label="Deliverable" placeholder="Deliverable (e.g. Master file)" value={d.title} maxLength={200} onChange={(e) => setDeliverable(i, { title: e.target.value })} />
                    <input className="input" aria-label="Acceptance criteria" placeholder="Acceptance criteria — what “done” means" value={d.acceptanceCriteria} maxLength={1000} onChange={(e) => setDeliverable(i, { acceptanceCriteria: e.target.value })} />
                  </div>
                  {form.deliverables.length > 1 && <button className="icon-btn" aria-label="Remove deliverable" onClick={() => setForm({ ...form,
                    deliverables: form.deliverables.filter((_, j) => j !== i),
                    milestones: form.milestones.map((m) => ({ ...m, deliverableKeys: m.deliverableKeys.filter((k) => k !== d.key) })) })}>×</button>}
                </div>))}
              {form.deliverables.length < 20 && <button className="btn btn-ghost btn-sm" onClick={() => set('deliverables', [...form.deliverables, { key: nextKey(), title: '', description: '', acceptanceCriteria: '' }])}>
                <Icon name="plus" /> Add deliverable</button>}

              <h3>Milestones &amp; price</h3>
              <div className="row">
                <Field label="Pricing model" id="p-model"><select id="p-model" className="input" value={form.pricingModel} onChange={(e) => set('pricingModel', e.target.value as ProposalInput['pricingModel'])}>
                  <option value="FIXED">Fixed fee</option><option value="HOURLY">Hourly (estimate)</option><option value="RETAINER">Retainer</option></select></Field>
                <Field label="Currency" id="p-cur"><select id="p-cur" className="input" value={form.currency} onChange={(e) => set('currency', e.target.value)}>
                  {CURRENCIES.map((c) => <option key={c}>{c}</option>)}</select></Field>
              </div>
              {form.milestones.map((m, i) => (
                <div key={i} className="builder-row">
                  <span className="n">{i + 1}</span>
                  <div className="builder-fields">
                    <div className="row">
                      <input className="input grow" aria-label="Milestone" placeholder="Milestone title" value={m.title} maxLength={200}
                        onChange={(e) => set('milestones', form.milestones.map((x, j) => (j === i ? { ...x, title: e.target.value } : x)))} />
                      <input className="input amount" aria-label="Amount" inputMode="decimal" placeholder="Amount" value={amounts[i] ?? ''}
                        onChange={(e) => setAmounts(amounts.map((a, j) => (j === i ? e.target.value.replace(/[^0-9.]/g, '') : a)))} />
                      <input className="input date" type="date" aria-label="Due date" value={m.dueDate ?? ''}
                        onChange={(e) => set('milestones', form.milestones.map((x, j) => (j === i ? { ...x, dueDate: e.target.value || null } : x)))} />
                    </div>
                    <div className="chips">{form.deliverables.map((d, k) => (
                      <label key={d.key} className={`chip pick ${m.deliverableKeys.includes(d.key) ? 'on' : ''}`}><input type="checkbox" checked={m.deliverableKeys.includes(d.key)}
                        onChange={() => set('milestones', form.milestones.map((x, j) => (j === i ? { ...x, deliverableKeys: x.deliverableKeys.includes(d.key)
                          ? x.deliverableKeys.filter((y) => y !== d.key) : [...x.deliverableKeys, d.key] } : x)))} />{d.title || `Deliverable ${k + 1}`}</label>))}</div>
                  </div>
                  {form.milestones.length > 1 && <button className="icon-btn" aria-label="Remove milestone" onClick={() => {
                    set('milestones', form.milestones.filter((_, j) => j !== i)); setAmounts(amounts.filter((_, j) => j !== i)) }}>×</button>}
                </div>))}
              <div className="row" style={{ justifyContent: 'space-between', alignItems: 'center' }}>
                {form.milestones.length < 20 && <button className="btn btn-ghost btn-sm" onClick={() => { set('milestones', [...form.milestones,
                  { title: '', description: '', amountMinor: 0, dueDate: null, deliverableKeys: [] }]); setAmounts([...amounts, '']) }}><Icon name="plus" /> Add milestone</button>}
                <strong>Total {formatMoney({ amountMinor: total, currency: form.currency })}</strong>
              </div>

              <h3>Timeline &amp; terms</h3>
              <div className="row">
                <Field label="Start date" id="p-start"><input id="p-start" type="date" className="input" value={form.startDate ?? ''} onChange={(e) => set('startDate', e.target.value || null)} /></Field>
                <Field label="Completion date" id="p-end"><input id="p-end" type="date" className="input" value={form.endDate ?? ''} onChange={(e) => set('endDate', e.target.value || null)} /></Field>
                <Field label="Proposal valid until" id="p-valid"><input id="p-valid" type="date" className="input" value={form.validUntil ?? ''} onChange={(e) => set('validUntil', e.target.value || null)} /></Field>
              </div>
              <div className="row" style={{ alignItems: 'flex-start' }}>
                <Field label="Assumptions (one per line)" id="p-ass"><textarea id="p-ass" className="input" rows={3} value={form.assumptions.join('\n')}
                  onChange={(e) => set('assumptions', e.target.value.split('\n').filter((l) => l.trim()).slice(0, 20))} /></Field>
                <Field label="Exclusions (one per line)" id="p-exc"><textarea id="p-exc" className="input" rows={3} value={form.exclusions.join('\n')}
                  onChange={(e) => set('exclusions', e.target.value.split('\n').filter((l) => l.trim()).slice(0, 20))} /></Field>
              </div>
              <ul className="assurance compact governance-note">
                <li><Icon name="contract" /><span>The contract will be generated from the accepted proposal.</span></li>
                <li><Icon name="lock" /><span>The buyer funds each milestone into escrow; you are paid when they accept the work.</span></li>
              </ul>
              <div className="wizard-nav">
                <div style={{ flex: 1 }} />
                <button className="btn btn-secondary" disabled={busy} onClick={() => run(save, 'Draft saved.')}>Save draft</button>
                <button className="btn btn-primary btn-lg" disabled={busy} onClick={() => run(async () => { const p = await save(); await proposalApi.submit(p.id) },
                  proposal?.status === 'REVISION_REQUESTED' ? 'Revised proposal sent to the buyer.' : 'Proposal sent to the buyer.')}>
                  {proposal?.status === 'REVISION_REQUESTED' ? 'Send revised proposal' : 'Submit proposal'}</button>
              </div>
            </section>
          ) : (
            <section className="card panel"><p style={{ margin: 0 }}>This request is {requestStatus(req).label.toLowerCase()}.
              {req.reasonCode && <span className="muted"> ({req.reasonCode.replace(/_/g, ' ').toLowerCase()})</span>}</p></section>
          )}
        </div>

        <aside>
          <SidePanel title="Buyer requirements">
            <div className="name-row" style={{ marginBottom: 12 }}><Avatar name={req.organizationName ?? 'Buyer'} size={36} />
              <span><strong>{req.organizationName}</strong><br /><span className="muted small">{req.buyerName}{req.businessContext ? ` · ${LABEL[req.businessContext] ?? req.businessContext.replace('_', '-').toLowerCase()}` : ''}</span></span></div>
            <dl className="facts">
              <dt>Objective</dt><dd>{req.detailsHidden ? <span className="muted">Hidden until NDA</span> : req.objective}</dd>
              <dt>Engagement</dt><dd>{LABEL[req.engagementType]}</dd>
              <dt>Start</dt><dd>{fmtDate(req.desiredStartDate)} · {DURATION_LABEL[req.estimatedDuration]}</dd>
              <dt>Delivery</dt><dd>{LABEL[req.deliveryMode]}{req.location ? ` · ${req.location}` : ''}</dd>
              <dt>Budget</dt><dd>{budgetText(req.budget)}</dd>
              {req.groupSize > 1 && <><dt>Competition</dt><dd>Sent to {req.groupSize} professionals</dd></>}
            </dl>
            {!req.detailsHidden && req.details && <p className="small" style={{ whiteSpace: 'pre-wrap', marginTop: 12 }}>{req.details}</p>}
            {req.attachments.length > 0 && <ul className="pro-list">{req.attachments.map((a) => <li key={a.sha256}><Icon name="request" /><span className="small">{a.name}</span><span /></li>)}</ul>}
          </SidePanel>
          <SidePanel title="Good proposals">
            <ul className="assurance compact">{['Map every deliverable to a milestone', 'Write acceptance criteria the buyer can check',
              'Say what is excluded, to avoid scope creep', 'You need Trust Tier B or higher to submit'].map((t) => <li key={t}><Icon name="check" /><span>{t}</span></li>)}</ul>
          </SidePanel>
        </aside>
      </div>
    </>
  )
}

function SentProposal({ p, busy, onWithdraw }: { p: Proposal; busy: boolean; onWithdraw: () => void }) {
  const st = PROPOSAL_STATUS[p.status]
  return (
    <section className="card panel">
      <div className="panel-head"><h2>Your proposal</h2><span className={`badge ${st.tone}`}>{st.label}</span></div>
      <p>{p.summary}</p>
      <table className="data"><thead><tr><th>Milestone</th><th>Due</th><th>Amount</th></tr></thead>
        <tbody>{p.milestones.map((m, i) => <tr key={i}><td>{m.title}</td><td className="small">{fmtDate(m.dueDate)}</td>
          <td>{formatMoney({ amountMinor: m.amountMinor, currency: p.currency })}</td></tr>)}</tbody></table>
      <p style={{ marginTop: 12 }}><strong>Total {formatMoney(p.total)}</strong> · {fmtDate(p.startDate)} – {fmtDate(p.endDate)} · valid until {fmtDate(p.validUntil)}</p>
      {p.status === 'ACCEPTED' && <div className="protect-note"><Icon name="check" /><div><strong>Accepted by the buyer.</strong>
        <div className="small">Contract signing and escrow funding arrive in the next release.</div></div></div>}
      {['SUBMITTED', 'UNDER_REVIEW'].includes(p.status) && <div className="row"><button className="btn btn-ghost btn-sm danger-text" disabled={busy} onClick={onWithdraw}>Withdraw proposal</button></div>}
    </section>
  )
}

function DeclineForm({ busy, onCancel, onDecline }: { busy: boolean; onCancel: () => void; onDecline: (r: DeclineReason, note: string) => void }) {
  const [reason, setReason] = useState<DeclineReason>('NO_CAPACITY')
  const [note, setNote] = useState('')
  return (
    <section className="card panel">
      <div className="panel-head"><h2>Decline this request</h2></div>
      <p className="muted small">Declining is not held against you. Your reason helps the buyer and improves matching.</p>
      <div className="row">
        <Field label="Reason" id="d-reason"><select id="d-reason" className="input" value={reason} onChange={(e) => setReason(e.target.value as DeclineReason)}>
          {DECLINE_REASONS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select></Field>
        <Field label="Note to the buyer (optional)" id="d-note"><input id="d-note" className="input" maxLength={500} value={note} onChange={(e) => setNote(e.target.value)} /></Field>
      </div>
      <div className="row" style={{ marginTop: 8 }}><button className="btn btn-danger" disabled={busy} onClick={() => onDecline(reason, note)}>Decline request</button>
        <button className="btn btn-ghost" onClick={onCancel}>Cancel</button></div>
    </section>
  )
}
