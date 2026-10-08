import { useCallback, useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import type { Contract } from '../api/contracts'
import {
  CATEGORIES, CATEGORY_LABEL, disputeApi, disputeFileUrl, EVIDENCE_TYPES, OPEN_PHASES, OUTCOME_LABEL, OUTCOMES, PHASE,
  type Dispute, type DisputeCategory, type DisputeOutcome, type EvidenceType, type RawAllocation,
} from '../api/disputes'
import { formatMoney } from '../api/orgs'
import { DOC_ACCEPT, toUpload, type Upload } from '../api/files'
import { FileLinks } from '../components/FileLink'
import { useAuth } from '../auth/AuthContext'
import { Icon } from '../components/dashboard'
import { EmptyTable, PortalHeader, SidePanel, StatCard } from '../components/portal'
import { ErrorAlert, useStepUp } from '../components/ui'
import { DisputeAppealPanel } from '../components/DisputeAppeal'
import { AIAssistance } from '../components/AIAssistance'
import { formatCurrencies } from '../lib/money'

/* Disputes (Dispute Resolution doc): neutral language, structured steps, the money frozen until a decision is executed. */

const DISPUTABLE = ['IN_PROGRESS', 'SUBMITTED', 'REVISION_REQUESTED']
const NO_MONEY: DisputeOutcome[] = ['REWORK', 'TIMELINE_EXTENSION']
const PARTIAL: DisputeOutcome[] = ['PARTIAL_RELEASE', 'PARTIAL_REFUND']
const PARTY: Record<string, string> = { BUYER: 'Buyer', PROFESSIONAL: 'Professional', PLATFORM: 'Platform' }

function timeLeft(iso: string | null): string {
  if (!iso) return ''
  const ms = new Date(iso).getTime() - Date.now()
  if (ms <= 0) return 'ending now'
  const h = Math.floor(ms / 3_600_000)
  return h >= 48 ? `${Math.floor(h / 24)} days left` : h >= 1 ? `${h} h left` : `${Math.max(1, Math.floor(ms / 60_000))} min left`
}

export function disputableMilestones(c: Contract) {
  return c.milestones.filter((m) => DISPUTABLE.includes(m.status))
}

/** Dispute intake (doc s.7): category, milestones, 300-character summary, desired outcome, confirmation. */
export function RaiseDisputeDialog({ contract, onClose }: { contract: Contract; onClose: () => void }) {
  const navigate = useNavigate()
  const options = disputableMilestones(contract)
  const [category, setCategory] = useState<DisputeCategory>('QUALITY_ACCEPTANCE')
  const [ids, setIds] = useState<string[]>(options.slice(0, 1).map((m) => m.id))
  const [summary, setSummary] = useState('')
  const [outcome, setOutcome] = useState<DisputeOutcome>('REWORK')
  const [context, setContext] = useState('')
  const [confirmed, setConfirmed] = useState(false)
  const [error, setError] = useState<unknown>(null)
  const [busy, setBusy] = useState(false)
  return (
    <div className="modal-backdrop" role="dialog" aria-modal="true" aria-labelledby="dispute-title" onClick={onClose}>
      <div className="card modal fund-modal" onClick={(e) => e.stopPropagation()}>
        <h2 id="dispute-title">Raise a dispute</h2>
        <p className="muted small">Use this when you cannot agree through revisions. Keep it factual: what was agreed, what happened, what you want.</p>
        <ErrorAlert error={error} />
        <label className="filter-box"><span>Category (cannot be changed later)</span>
          <select value={category} onChange={(e) => setCategory(e.target.value as DisputeCategory)}>{CATEGORIES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select></label>
        <div className="field" style={{ marginTop: 10 }}><span className="label">Affected milestones (funded, not yet accepted)</span>
          <ul className="fund-list">{options.map((m) => (
            <li key={m.id}><label className="checkbox"><input type="checkbox" checked={ids.includes(m.id)}
              onChange={() => setIds(ids.includes(m.id) ? ids.filter((x) => x !== m.id) : [...ids, m.id])} /><span>M{m.sequence} {m.title}</span></label>
              <strong>{formatMoney(m.amount)}</strong></li>))}</ul></div>
        <label className="filter-box grow"><span>Issue summary ({summary.length}/300)</span>
          <textarea rows={3} maxLength={300} value={summary} onChange={(e) => setSummary(e.target.value)} placeholder="e.g. The report misses the two sections listed in the acceptance criteria." /></label>
        <label className="filter-box" style={{ marginTop: 10 }}><span>Desired outcome</span>
          <select value={outcome} onChange={(e) => setOutcome(e.target.value as DisputeOutcome)}>{OUTCOMES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select></label>
        <details style={{ marginTop: 10 }}><summary className="small">Additional context (optional)</summary>
          <textarea className="input" rows={4} maxLength={1000} value={context} onChange={(e) => setContext(e.target.value)} style={{ marginTop: 8 }} /></details>
        <label className="checkbox" style={{ marginTop: 12 }}><input type="checkbox" checked={confirmed} onChange={(e) => setConfirmed(e.target.checked)} />
          <span>I understand the funds for these milestones will be frozen, acceptance and release pause, and both parties are notified.</span></label>
        <div className="row" style={{ marginTop: 14, justifyContent: 'flex-end' }}>
          <button className="btn btn-ghost" onClick={onClose}>Cancel</button>
          <button className="btn btn-primary" disabled={busy || !confirmed || ids.length === 0 || summary.trim().length < 10} onClick={async () => {
            setBusy(true); setError(null)
            try {
              const d = await disputeApi.open({ contractId: contract.id, milestoneIds: ids, category, summary: summary.trim(), desiredOutcome: outcome, context: context.trim() })
              navigate(`/app/disputes/${d.id}`)
            } catch (err) { setError(err) } finally { setBusy(false) }
          }}>Submit dispute</button>
        </div>
      </div>
    </div>
  )
}

export function DisputesPage({ role }: { role: 'buyer' | 'professional' | 'operator' }) {
  const [list, setList] = useState<Dispute[] | null>(null)
  const [error, setError] = useState<unknown>(null)
  useEffect(() => { disputeApi.list(role).then(setList).catch(setError) }, [role])
  const rows = list ?? []
  const open = rows.filter((d) => OPEN_PHASES.includes(d.status))
  return (
    <>
      <PortalHeader eyebrow="Disputes" title={role === 'operator' ? 'Dispute cases' : 'Your disputes'}
        subtitle="Structured, evidence-first resolution. Money stays frozen until a decision is executed." />
      <ErrorAlert error={error} />
      <div className="stat-row four">
        <StatCard icon="clock" tone="amber" value={list ? open.length : '…'} label="Open" sub="Evidence, negotiation or mediation" />
        <StatCard icon="team" tone="violet" value={list ? rows.filter((d) => d.status === 'MEDIATION').length : '…'} label="In mediation" sub={role === 'operator' ? 'Need a mediator or decision' : 'With a neutral mediator'} />
        <StatCard icon="check" tone="green" value={list ? rows.filter((d) => d.status === 'CLOSED').length : '…'} label="Closed" sub="Decided and executed" />
        <StatCard icon="lock" tone="blue" value={list ? formatCurrencies(open.map(d => d.disputed)) : '…'} label="Frozen" sub="Across open disputes, by currency" />
      </div>
      <section className="card panel">
        {list && rows.length === 0 ? (
          <EmptyTable columns={['Dispute', 'Engagement', 'Category', 'Phase', 'Amount', 'Opened']}>
            <strong>No disputes.</strong> {role === 'operator' ? 'Cases appear here when a party opens one.' : 'If something goes wrong on a funded milestone, raise a dispute from the engagement.'}
          </EmptyTable>
        ) : (
          <table className="data"><thead><tr><th>Dispute</th><th>Engagement</th><th>Category</th><th>Phase</th><th>Amount</th><th>Opened</th></tr></thead>
            <tbody>{rows.map((d) => (
              <tr key={d.id}>
                <td><Link to={`/app/disputes/${d.id}`}><strong>{d.reference}</strong></Link><div className="muted small clamp">{d.summary}</div></td>
                <td className="small">{d.contractReference}</td>
                <td className="small">{CATEGORY_LABEL[d.category]}</td>
                <td><span className={`badge ${PHASE[d.status].tone}`}>{PHASE[d.status].label}</span>
                  {role === 'operator' && d.status === 'MEDIATION' && !d.mediatorAssigned && <div className="small warn-text">Needs a mediator</div>}</td>
                <td>{formatMoney(d.disputed)}</td>
                <td className="small">{new Date(d.createdAt).toLocaleDateString()}</td>
              </tr>))}</tbody></table>
        )}
      </section>
    </>
  )
}

/** Allocation editor: money outcomes split each milestone fully into release + refund. */
function useAllocation(d: Dispute) {
  const [outcome, setOutcome] = useState<DisputeOutcome>(d.desiredOutcome)
  const [release, setRelease] = useState<Record<string, string>>(Object.fromEntries(d.milestones.map((m) => [m.id, String(m.amount.amountMinor / 200)])))
  const build = (): RawAllocation[] => {
    if (NO_MONEY.includes(outcome)) return []
    return d.milestones.map((m) => {
      const total = m.amount.amountMinor
      const r = outcome === 'FULL_RELEASE' ? total : outcome === 'FULL_REFUND' || outcome === 'TERMINATION' ? 0
        : Math.min(total, Math.max(0, Math.round(Number(release[m.id] || 0) * 100)))
      return { milestoneId: m.id, releaseMinor: r, refundMinor: total - r }
    })
  }
  const editor = (
    <>
      <label className="filter-box"><span>Outcome</span>
        <select value={outcome} onChange={(e) => setOutcome(e.target.value as DisputeOutcome)}>{OUTCOMES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select></label>
      {NO_MONEY.includes(outcome) ? <p className="muted small">The money stays held in escrow and work continues.</p> : (
        <table className="data" style={{ marginTop: 8 }}><thead><tr><th>Milestone</th><th>Release to professional</th><th>Refund to buyer</th></tr></thead>
          <tbody>{build().map((a) => {
            const m = d.milestones.find((x) => x.id === a.milestoneId)!
            return <tr key={a.milestoneId}><td className="small">M{m.sequence} {m.title}<br /><span className="muted">{formatMoney(m.amount)}</span></td>
              <td>{PARTIAL.includes(outcome) ? <input className="input amount" inputMode="decimal" value={release[m.id] ?? ''}
                onChange={(e) => setRelease({ ...release, [m.id]: e.target.value.replace(/[^0-9.]/g, '') })} />
                : formatMoney({ amountMinor: a.releaseMinor, currency: m.amount.currency })}</td>
              <td>{formatMoney({ amountMinor: a.refundMinor, currency: m.amount.currency })}</td></tr>
          })}</tbody></table>
      )}
    </>
  )
  return { outcome, build, editor }
}

export function DisputeDetail() {
  const { id = '' } = useParams()
  const { user } = useAuth()
  const [d, setD] = useState<Dispute | null>(null)
  const [error, setError] = useState<unknown>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const { run, modal } = useStepUp(setError)
  const load = useCallback(() => disputeApi.get(id).then(setD).catch(setError), [id])
  useEffect(() => { load() }, [load])

  if (!d) return error ? <ErrorAlert error={error} /> : <p className="muted">Loading…</p>
  const party = d.viewerRole === 'BUYER' || d.viewerRole === 'PROFESSIONAL'
  const ph = PHASE[d.status]
  const act = async (fn: () => Promise<Dispute>, msg: string) => {
    setBusy(true); setError(null); setNotice(null)
    try { setD(await fn()); setNotice(msg) } catch (err) { setError(err) } finally { setBusy(false) }
  }
  const stepUp = (fn: () => Promise<Dispute>, msg: string) => { setError(null); setNotice(null); run(async () => { setD(await fn()); setNotice(msg) }) }
  const deadline = d.status === 'EVIDENCE_COLLECTION' ? d.evidenceDeadline : d.status === 'DIRECT_RESOLUTION' ? d.directDeadline : null

  return (
    <>
      {modal}
      <PortalHeader eyebrow={<Link to={party ? (d.viewerRole === 'BUYER' ? '/app/disputes' : '/app/professional/disputes') : '/app/ops/disputes'}>← Disputes</Link>}
        title={`Dispute ${d.reference}`}
        subtitle={<>Engagement {d.contractReference} · <span className="badge">{CATEGORY_LABEL[d.category]}</span> <span className={`badge ${ph.tone}`}>{ph.label}</span>
          {deadline && <> · <Icon name="clock" /> {timeLeft(deadline)}</>}</>} />
      {notice && <div className="alert alert-success" role="status">{notice}</div>}
      <ErrorAlert error={error} />
      <div className="attention-banner neutral"><span className="kpi-icon blue"><Icon name="help" /></span>
        <div><strong>What happens next</strong><div className="small">{d.nextStep}</div></div></div>

      <div className="home-grid wide">
        <div>
          <section className="card panel">
            <div className="panel-head"><h2>The issue</h2><span className="muted small">Raised by the {PARTY[d.initiatorParty].toLowerCase()}</span></div>
            <p style={{ margin: 0 }}>{d.summary}</p>
            {d.context && <p className="muted small" style={{ marginTop: 8 }}>{d.context}</p>}
            <dl className="facts" style={{ marginTop: 12 }}>
              <dt>Desired outcome</dt><dd>{OUTCOME_LABEL[d.desiredOutcome]}</dd>
              <dt>Milestones</dt><dd>{d.milestones.map((m) => `M${m.sequence} ${m.title} (${formatMoney(m.amount)})`).join(', ')}</dd>
              <dt>Frozen in escrow</dt><dd>{formatMoney(d.disputed)}</dd>
            </dl>
          </section>

          {d.decision && <DecisionCard d={d} />}
          {d.viewerRole === 'MEDIATOR' && <AIAssistance purpose="dispute-summary" subjectId={d.id} />}
          {d.decision?.decisionPath === 'PLATFORM' && <DisputeAppealPanel caseId={d.id} canFile={party} canReview={!!user?.platformRoles.includes('LEGAL')} />}

          {d.status === 'MEDIATION' && <MediationPanel d={d} busy={busy} party={party}
            onAnswer={(accept) => act(() => disputeApi.answerRecommendation(d.id, accept), accept ? 'You accepted the recommendation.' : 'You declined the recommendation.')}
            onAssignSelf={() => user && stepUp(() => disputeApi.assignMediator(d.id, user.id), 'You are the mediator for this case.')}
            onRecommend={(body) => stepUp(() => disputeApi.recommend(d.id, body), 'Recommendation issued to both parties.')}
            onDecide={(body) => stepUp(() => disputeApi.proposeDecision(d.id, body), 'Platform decision proposed; a Legal reviewer must approve it.')}
            onApprove={() => stepUp(() => disputeApi.approveDecision(d.id), 'Decision approved and issued.')}
            canApprove={!!user?.platformRoles.includes('LEGAL')} isMediatorRole={!!user?.platformRoles.includes('MEDIATOR')} />}

          {(d.status === 'DIRECT_RESOLUTION' || d.proposals.length > 0) && <ProposalsPanel d={d} busy={busy} party={party}
            onPropose={(body) => act(() => disputeApi.propose(d.id, body), 'Proposal sent. The other party can accept it or decline.')}
            onAnswer={(pid, accept) => act(() => accept ? disputeApi.acceptProposal(pid) : disputeApi.rejectProposal(pid), accept ? 'Agreed. The decision is being executed.' : 'Proposal declined. You can now escalate to a mediator.')}
            onEscalate={() => { if (confirm('Escalate to a neutral mediator? Escalation cannot be undone.')) act(() => disputeApi.escalate(d.id), 'Escalated to mediation.') }} />}

          <EvidencePanel d={d} busy={busy} party={party}
            onAdd={(body) => act(() => disputeApi.addEvidence(d.id, body), 'Evidence added. It is fingerprinted and cannot be edited.')}
            onComplete={() => act(() => disputeApi.evidenceComplete(d.id), 'Marked your evidence as complete.')} />
        </div>
        <aside>
          <SidePanel title="Timeline">
            <ul className="activity dispute-timeline">{d.timeline.map((t, i) => (
              <li key={i}><span className="dot" /><span><strong>{t.actor}</strong><br /><span className="small">{t.text}</span></span>
                <span className="muted small">{new Date(t.at).toLocaleString()}</span></li>))}</ul>
          </SidePanel>
          <SidePanel title="Rules">
            <ul className="assurance compact">{['Funds stay frozen until a decision is executed', 'No direct messaging during a dispute',
              'Evidence is fingerprinted and cannot be edited', 'A mediator recommendation binds only if both accept',
              'Platform decisions need two different reviewers', 'AI never decides'].map((t) => <li key={t}><Icon name="check" /><span>{t}</span></li>)}</ul>
          </SidePanel>
        </aside>
      </div>
    </>
  )
}

function DecisionCard({ d }: { d: Dispute }) {
  const dec = d.decision!
  const ms = (mid: string) => d.milestones.find((m) => m.id === mid)
  return (
    <section className="card panel decision-card">
      <div className="panel-head"><h2>Decision</h2><span className="badge green">{{ DIRECT: 'Agreed by both parties', MEDIATION: 'Mediated agreement', PLATFORM: 'Platform decision' }[dec.decisionPath]}</span></div>
      <p>{dec.plainSummary}</p>
      {dec.allocations.length > 0 && <table className="data"><thead><tr><th>Milestone</th><th>Released</th><th>Refunded</th></tr></thead>
        <tbody>{dec.allocations.map((a) => <tr key={a.milestoneId}><td className="small">M{ms(a.milestoneId)?.sequence} {ms(a.milestoneId)?.title}</td>
          <td>{formatMoney({ amountMinor: a.releaseMinor, currency: d.disputed.currency })}</td><td>{formatMoney({ amountMinor: a.refundMinor, currency: d.disputed.currency })}</td></tr>)}</tbody></table>}
      <p className="muted small" style={{ marginBottom: 0 }}>Evidence referenced: {dec.evidenceReferences.length} item(s) · Policy: {dec.policyCitations.join('; ')} · {dec.appealNote}</p>
    </section>
  )
}

function EvidencePanel({ d, busy, party, onAdd, onComplete }: {
  d: Dispute; busy: boolean; party: boolean; onAdd: (b: { evidenceType: EvidenceType; description: string; items: Upload[] }) => void; onComplete: () => void
}) {
  const [type, setType] = useState<EvidenceType>('DELIVERABLE')
  const [desc, setDesc] = useState('')
  const [files, setFiles] = useState<Upload[]>([])
  const [fileError, setFileError] = useState('')
  const open = d.status === 'EVIDENCE_COLLECTION' && party
  const done = d.evidenceComplete.includes(d.viewerRole)
  return (
    <section className="card panel">
      <div className="panel-head"><h2>Evidence</h2><span className="muted small">{d.evidence.length} item(s) · both parties see everything</span></div>
      {d.evidence.length === 0 ? <p className="muted small">No evidence yet.</p> : (
        <ul className="submission-list">{d.evidence.map((e) => (
          <li key={e.id}><span className="muted small">{PARTY[e.party]} · {EVIDENCE_TYPES.find(([v]) => v === e.evidenceType)?.[1]} · {new Date(e.submittedAt).toLocaleString()}</span>
            <span>{e.description}</span>{e.items.length > 0 && <FileLinks files={e.items} url={(f) => disputeFileUrl(d.id, f.sha256)} />}</li>))}</ul>
      )}
      {open && !done && <div className="revise-box">
        <div className="row">
          <label className="filter-box"><span>Type</span><select value={type} onChange={(e) => setType(e.target.value as EvidenceType)}>
            {EVIDENCE_TYPES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select></label>
          <label className="filter-box grow"><span>What does it show?</span><input value={desc} maxLength={1000} onChange={(e) => setDesc(e.target.value)} /></label>
        </div>
        <div style={{ marginTop: 8 }}>{files.map((f) => <div key={f.sha256} className="file-row"><Icon name="request" /><span>{f.name}</span></div>)}
          {files.length < 10 && <input type="file" multiple accept={DOC_ACCEPT} onChange={async (e) => {
            const picked = Array.from(e.target.files ?? []).slice(0, 10 - files.length)
            e.target.value = ''
            setFileError('')
            try { setFiles([...files, ...await Promise.all(picked.map((f) => toUpload(f)))]) } catch (err) { setFileError(err instanceof Error ? err.message : 'That file could not be read') }
          }} />}
          <p className="muted small" style={{ margin: '4px 0 0' }}>PDF, Word, Excel, CSV, JPG or PNG · up to 10 MB each, 25 MB together. Both parties and the mediator can open them.</p>
          {fileError && <p className="small" style={{ color: 'var(--zk-danger)', margin: '4px 0 0' }}>{fileError}</p>}</div>
        <div className="row" style={{ marginTop: 10 }}>
          <button className="btn btn-secondary" disabled={busy || desc.trim().length < 5} onClick={() => { onAdd({ evidenceType: type, description: desc.trim(), items: files }); setDesc(''); setFiles([]) }}>Add evidence</button>
          <button className="btn btn-primary" disabled={busy} onClick={onComplete}>My evidence is complete</button>
        </div>
      </div>}
      {d.status === 'EVIDENCE_COLLECTION' && <p className="muted small" style={{ marginBottom: 0 }}>Completed: {d.evidenceComplete.map((p) => PARTY[p]).join(', ') || 'nobody yet'}.
        The next phase starts when both are done or the deadline passes.</p>}
    </section>
  )
}

function ProposalsPanel({ d, busy, party, onPropose, onAnswer, onEscalate }: {
  d: Dispute; busy: boolean; party: boolean; onPropose: (b: { outcome: DisputeOutcome; allocations: RawAllocation[]; note: string }) => void
  onAnswer: (pid: string, accept: boolean) => void; onEscalate: () => void
}) {
  const alloc = useAllocation(d)
  const [note, setNote] = useState('')
  const canPropose = party && d.status === 'DIRECT_RESOLUTION'
  return (
    <section className="card panel">
      <div className="panel-head"><h2>Resolution proposals</h2>{d.canEscalate && <button className="btn btn-secondary btn-sm" disabled={busy} onClick={onEscalate}>Escalate to a mediator</button>}</div>
      {d.proposals.length === 0 && <p className="muted small">No proposals yet. Proposals are structured; there is no free-form chat during a dispute.</p>}
      {d.proposals.map((p) => (
        <div key={p.id} className={`proposal-mini ${p.status === 'OPEN' ? 'open' : ''}`}>
          <div className="panel-head"><strong>{PARTY[p.party]} proposed: {OUTCOME_LABEL[p.outcome]}</strong>
            <span className={`badge ${p.status === 'ACCEPTED' ? 'green' : p.status === 'OPEN' ? 'warn' : ''}`}>{p.status.toLowerCase()}</span></div>
          {p.allocations.some((a) => a.release.amountMinor || a.refund.amountMinor) && <ul className="why">{p.allocations.map((a) => (
            <li key={a.milestoneId}>M{a.sequence}: {formatMoney(a.release)} released, {formatMoney(a.refund)} refunded</li>))}</ul>}
          {p.note && <p className="muted small">“{p.note}”</p>}
          {party && !p.mine && p.status === 'OPEN' && d.status === 'DIRECT_RESOLUTION' && <div className="row">
            <button className="btn btn-primary btn-sm" disabled={busy} onClick={() => { if (confirm('Accept this proposal? It becomes the binding decision and the money moves accordingly.')) onAnswer(p.id, true) }}>Accept</button>
            <button className="btn btn-ghost btn-sm" disabled={busy} onClick={() => onAnswer(p.id, false)}>Decline</button></div>}
        </div>))}
      {canPropose && <div className="revise-box">
        <h3 style={{ marginTop: 0 }}>{d.proposals.some((p) => !p.mine && p.status === 'OPEN') ? 'Make a counterproposal' : 'Make a proposal'}</h3>
        {alloc.editor}
        <label className="filter-box grow" style={{ marginTop: 8 }}><span>Note (optional)</span><input value={note} maxLength={1000} onChange={(e) => setNote(e.target.value)} /></label>
        <button className="btn btn-primary" style={{ marginTop: 10 }} disabled={busy} onClick={() => { onPropose({ outcome: alloc.outcome, allocations: alloc.build(), note: note.trim() }); setNote('') }}>Send proposal</button>
      </div>}
    </section>
  )
}

function MediationPanel({ d, busy, party, onAnswer, onAssignSelf, onRecommend, onDecide, onApprove, canApprove, isMediatorRole }: {
  d: Dispute; busy: boolean; party: boolean; onAnswer: (accept: boolean) => void; onAssignSelf: () => void
  onRecommend: (b: { outcome: DisputeOutcome; allocations: RawAllocation[]; summary: string; citations: string[] }) => void
  onDecide: (b: { outcome: DisputeOutcome; allocations: RawAllocation[]; summary: string; citations: string[] }) => void
  onApprove: () => void; canApprove: boolean; isMediatorRole: boolean
}) {
  const alloc = useAllocation(d)
  const [summary, setSummary] = useState('')
  const [citations, setCitations] = useState('')
  const r = d.recommendation
  const answered = r && (r.acceptedBy?.includes(d.viewerRole) || r.rejectedBy?.includes(d.viewerRole))
  const body = () => ({ outcome: alloc.outcome, allocations: alloc.build(), summary: summary.trim(), citations: citations.split('\n').map((c) => c.trim()).filter(Boolean) })
  return (
    <section className="card panel">
      <div className="panel-head"><h2>Mediation</h2><span className="muted small">{d.mediatorAssigned ? 'Mediator assigned' : 'Waiting for a mediator'}</span></div>
      {!d.mediatorAssigned && isMediatorRole && <button className="btn btn-primary" disabled={busy} onClick={onAssignSelf}>Take this case as mediator</button>}
      {r && <div className="proposal-mini open">
        <strong>Recommendation: {OUTCOME_LABEL[r.outcome]}</strong>
        <p className="small" style={{ whiteSpace: 'pre-wrap' }}>{r.summary}</p>
        {r.citations.length > 0 && <p className="muted small">Cites: {r.citations.join('; ')}</p>}
        <p className="muted small">Accepted by: {r.acceptedBy?.map((p) => PARTY[p]).join(', ') || 'nobody yet'}{r.rejectedBy?.length ? ` · Declined by: ${r.rejectedBy.map((p) => PARTY[p]).join(', ')}` : ''}</p>
        {party && !answered && <div className="row">
          <button className="btn btn-primary btn-sm" disabled={busy} onClick={() => onAnswer(true)}>Accept recommendation</button>
          <button className="btn btn-ghost btn-sm" disabled={busy} onClick={() => onAnswer(false)}>Decline</button></div>}
      </div>}
      {d.pendingDecision && <div className="proposal-mini open">
        <strong>Platform decision awaiting approval: {OUTCOME_LABEL[d.pendingDecision.outcome]}</strong>
        <p className="small">{d.pendingDecision.summary}</p>
        {canApprove && d.viewerRole !== 'MEDIATOR' && <button className="btn btn-primary btn-sm" disabled={busy} onClick={onApprove}>Approve as second reviewer (Legal)</button>}
      </div>}
      {d.viewerRole === 'MEDIATOR' && !d.pendingDecision && (!r || r.rejectedBy?.length) && <div className="revise-box">
        <h3 style={{ marginTop: 0 }}>{r ? 'Propose a platform decision' : 'Issue a recommendation'}</h3>
        {alloc.editor}
        <label className="filter-box grow" style={{ marginTop: 8 }}><span>Plain-language reasoning (min 20 characters)</span>
          <textarea rows={4} maxLength={2000} value={summary} onChange={(e) => setSummary(e.target.value)} /></label>
        <label className="filter-box grow" style={{ marginTop: 8 }}><span>Evidence and policy citations (one per line)</span>
          <textarea rows={3} value={citations} onChange={(e) => setCitations(e.target.value)} /></label>
        <button className="btn btn-primary" style={{ marginTop: 10 }} disabled={busy || summary.trim().length < 20}
          onClick={() => (r ? onDecide(body()) : onRecommend(body()))}>{r ? 'Propose decision for Legal approval' : 'Issue recommendation'}</button>
        <p className="muted small" style={{ marginBottom: 0 }}>You will confirm with your authenticator code.</p>
      </div>}
    </section>
  )
}
