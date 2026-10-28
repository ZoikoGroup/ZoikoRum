import { useCallback, useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import type { Contract } from '../api/contracts'
import type { Escrow } from '../api/escrow'
import {
  CATEGORIES, CATEGORY_LABEL, disputableMilestones, disputeApi, disputeFileUrl, EVIDENCE_TYPES, OPEN_PHASES, OUTCOME_LABEL, OUTCOMES,
  paymentStuck, PHASE, releaseAfterWindow,
  type AccountRestriction, type AgreementKind, type Dispute, type DisputeCategory, type DisputeDashboard, type DisputeOutcome, type EvidenceType,
  type RawAllocation, type ReportSubscription,
} from '../api/disputes'
import { formatMoney, orgApi, type Organization } from '../api/orgs'
import { DOC_ACCEPT, toUpload, type Upload } from '../api/files'
import { FileLinks } from '../components/FileLink'
import { useAuth } from '../auth/AuthContext'
import { useCapabilities } from '../auth/capabilities'
import { ExportPack } from '../components/ExportPack'
import { saveBlob } from '../lib/exports'
import { Icon } from '../components/dashboard'
import { EmptyTable, PortalHeader, SidePanel, StatCard } from '../components/portal'
import { ErrorAlert, useDialog, useStepUp, Loading } from '../components/ui'
import { DisputeAppealPanel } from '../components/DisputeAppeal'
import { AIAssistance } from '../components/AIAssistance'
import { formatCurrencies } from '../lib/money'

/* Disputes (Dispute Resolution doc): neutral language, structured steps, the money frozen until a decision is executed. */

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

/** Dispute intake (doc s.7): category, milestones, 300-character summary, desired outcome, confirmation. */
export function RaiseDisputeDialog({ contract, escrow, onClose }: { contract: Contract; escrow?: Escrow | null; onClose: () => void }) {
  const dialog = useDialog(onClose)
  const navigate = useNavigate()
  const options = disputableMilestones(contract, escrow)
  const stuck = paymentStuck(contract, escrow)
  const [chosenCategory, setCategory] = useState<DisputeCategory>('QUALITY_ACCEPTANCE')
  const [ids, setIds] = useState<string[]>(options.slice(0, 1).map((m) => m.id))
  // Accepted work can only be disputed about its payment, except inside its challenge window (a defect found after acceptance).
  const paymentOnly = ids.some((id) => stuck.has(id) && !releaseAfterWindow(contract, id))
  const category: DisputeCategory = paymentOnly ? 'PAYMENT_RELEASE' : chosenCategory
  const [summary, setSummary] = useState('')
  const [outcome, setOutcome] = useState<DisputeOutcome>('REWORK')
  const [context, setContext] = useState('')
  const [confirmed, setConfirmed] = useState(false)
  const [early, setEarly] = useState(false)
  const draftKey = `zk.disputeDraft.${contract.id}`
  useEffect(() => {  // a draft of what was typed survives closing the dialog (kept only in this browser)
    try { const saved = JSON.parse(localStorage.getItem(draftKey) ?? 'null'); if (saved) { setSummary(saved.summary ?? ''); setContext(saved.context ?? '') } } catch { /* none */ }
  }, [draftKey])
  useEffect(() => {
    try { if (summary || context) localStorage.setItem(draftKey, JSON.stringify({ summary, context })) } catch { /* storage off */ }
  }, [draftKey, summary, context])
  const [error, setError] = useState<unknown>(null)
  const [busy, setBusy] = useState(false)
  return (
    <div ref={dialog} className="modal-backdrop" role="dialog" aria-modal="true" aria-labelledby="dispute-title" onClick={onClose}>
      <div className="card modal fund-modal" onClick={(e) => e.stopPropagation()}>
        <h2 id="dispute-title">Raise a dispute</h2>
        <p className="muted small">Use this when you cannot agree through revisions. Keep it factual: what was agreed, what happened, what you want.</p>
        <ErrorAlert error={error} />
        <label className="filter-box"><span>Category (cannot be changed later)</span>
          <select value={category} disabled={paymentOnly} onChange={(e) => setCategory(e.target.value as DisputeCategory)}>{CATEGORIES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select></label>
        {paymentOnly && <p className="muted small" style={{ margin: '6px 0 0' }}>Accepted work is disputed only about its payment, which the buyer's organisation has not approved.</p>}
        <div className="field" style={{ marginTop: 10 }}><span className="label">Affected milestones (funded, not yet accepted, or accepted but unpaid)</span>
          <ul className="fund-list">{options.map((m) => (
            <li key={m.id}><label className="checkbox"><input type="checkbox" checked={ids.includes(m.id)}
              onChange={() => setIds(ids.includes(m.id) ? ids.filter((x) => x !== m.id) : [...ids, m.id])} /><span>M{m.sequence} {m.title}{stuck.has(m.id) && <span className="muted"> · accepted, payment not released{releaseAfterWindow(contract, m.id) ? ' (within the check period)' : ''}</span>}</span></label>
              <strong>{formatMoney(m.amount)}</strong></li>))}</ul></div>
        <label className="filter-box grow"><span>Issue summary ({summary.length}/300)</span>
          <textarea rows={3} maxLength={300} value={summary} onChange={(e) => setSummary(e.target.value)} placeholder="e.g. The report misses the two sections listed in the acceptance criteria." /></label>
        <label className="filter-box" style={{ marginTop: 10 }}><span>Desired outcome</span>
          <select value={outcome} onChange={(e) => setOutcome(e.target.value as DisputeOutcome)}>{OUTCOMES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select></label>
        <details style={{ marginTop: 10 }}><summary className="small">Additional context (optional)</summary>
          <textarea className="input" rows={4} maxLength={1000} value={context} onChange={(e) => setContext(e.target.value)} style={{ marginTop: 8 }} /></details>
        <label className="checkbox" style={{ marginTop: 12 }}><input type="checkbox" checked={confirmed} onChange={(e) => setConfirmed(e.target.checked)} />
          <span>I understand the funds for these milestones will be frozen, acceptance and release pause, and both parties are notified.</span></label>
        <label className="checkbox" style={{ marginTop: 6 }}><input type="checkbox" checked={early} onChange={(e) => setEarly(e.target.checked)} />
          <span>I would prefer to settle this directly with the other side first.</span></label>
        <p className="muted small" style={{ margin: '6px 0 0' }}>What you type is kept as a draft in this browser until you submit.</p>
        <div className="row" style={{ marginTop: 14, justifyContent: 'flex-end' }}>
          <button className="btn btn-ghost" onClick={onClose}>Cancel</button>
          <button className="btn btn-primary" disabled={busy || !confirmed || ids.length === 0 || summary.trim().length < 10} onClick={async () => {
            setBusy(true); setError(null)
            try {
              const d = await disputeApi.open({ contractId: contract.id, milestoneIds: ids, category, summary: summary.trim(), desiredOutcome: outcome,
                context: context.trim(), prefersEarlyResolution: early })
              try { localStorage.removeItem(draftKey) } catch { /* storage off */ }
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
      {role === 'buyer' && <OrgDisputeDashboard />}
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
  const [extendDays, setExtendDays] = useState('14')
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
      {outcome === 'TIMELINE_EXTENSION' && <label className="filter-box"><span>Extra days to deliver</span>
        <input className="input" inputMode="numeric" value={extendDays} onChange={(e) => setExtendDays(e.target.value.replace(/[^0-9]/g, ''))} /></label>}
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
  const extra = () => (outcome === 'TIMELINE_EXTENSION' ? Number(extendDays) || null : null)
  return { outcome, build, editor, extra }
}

export function DisputeDetail() {
  const { id = '' } = useParams()
  const { user } = useAuth()
  const { has: can } = useCapabilities()  // Legal / Mediator actions (staff sign-in)
  const [d, setD] = useState<Dispute | null>(null)
  const [error, setError] = useState<unknown>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const { run, modal } = useStepUp(setError)
  const load = useCallback(() => disputeApi.get(id).then(setD).catch(setError), [id])
  useEffect(() => { load() }, [load])

  if (!d) return error ? <ErrorAlert error={error} /> : <Loading />
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
      <PortalHeader eyebrow={<Link to={party ? (d.viewerRole === 'BUYER' ? '/app/disputes' : '/app/professional/disputes') : '/platform-admin/dispute-resolution'}>← Disputes</Link>}
        title={`Dispute ${d.reference}`}
        subtitle={<>Engagement {d.contractReference} · <span className="badge">{CATEGORY_LABEL[d.category]}</span> <span className={`badge ${ph.tone}`}>{ph.label}</span>
          {deadline && <> · <Icon name="clock" /> {timeLeft(deadline)}</>}</>}
        actions={<ExportPack label="Case record" fileStem={`${d.reference}-record`} fetchPack={(f) => disputeApi.record(d.id, f === 'csv' ? 'json' : f)} onError={setError} formats={['pdf', 'json']} />} />
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
          {d.retainUntil && <section className="card panel small">
            <strong>Record retention:</strong> kept until at least {new Date(d.retainUntil).toLocaleDateString()} ({d.retentionBasis}).
            {d.legalHold && <span className="badge warn" style={{ marginLeft: 8 }}>Legal hold</span>}
            {can('disputes.adjudicate') && <button className="btn btn-ghost btn-sm" style={{ marginLeft: 8 }} onClick={() => {
              const reason = prompt(d.legalHold ? 'Why lift the hold?' : 'Why hold this record? (e.g. litigation, a request from a regulator)')
              if (reason && reason.trim().length >= 10) stepUp(() => disputeApi.legalHold(d.id, !d.legalHold, reason.trim()), d.legalHold ? 'Hold lifted.' : 'Legal hold placed.')
            }}>{d.legalHold ? 'Lift legal hold' : 'Place legal hold'}</button>}
          </section>}
          {d.viewerRole === 'MEDIATOR' && <AIAssistance purpose="dispute-summary" subjectId={d.id} />}
          {d.provisionalDecision && <ProvisionalCard d={d} />}
          {(d.decision?.decisionPath === 'PLATFORM' || d.provisionalDecision || (d.decision?.binding && d.decision.decisionPath !== 'DIRECT')) &&
            <DisputeAppealPanel caseId={d.id} canFile={party && (!d.provisionalDecision || !d.provisionalDecision.appealed)} canReview={can('disputes.adjudicate')} />}
          {party && (d.status === 'EVIDENCE_COLLECTION' || d.status === 'DIRECT_RESOLUTION' || d.status === 'MEDIATION') && !d.arbitration &&
            <DecisionPathsPanel d={d} busy={busy} onSet={(kind, consent) => act(() => disputeApi.setAgreement(d.id, kind, consent),
              consent ? 'Your agreement is recorded. It applies once both parties agree.' : 'Your agreement was withdrawn.')} />}
          {d.canDecideAsEnterpriseAdmin && <EnterpriseDecisionPanel d={d} busy={busy}
            onDecide={(body) => stepUp(() => disputeApi.enterpriseDecision(d.id, body), 'Decision issued. It takes effect after the challenge period unless a party appeals.')} />}

          {(d.mediationRequired || d.legalReviewRequired) && d.status !== 'DECIDED' && d.status !== 'ENFORCED' && d.status !== 'CLOSED' &&
            <div className="tip"><Icon name="shield" /><span>The buyer organisation's policy applies to this dispute:
              {d.mediationRequired ? ' a mediator handles any settlement of this size;' : ''}
              {d.legalReviewRequired ? " the organisation's Legal Reviewer must agree to its settlement." : ''}</span></div>}

          {d.status === 'MEDIATION' && <ArbitrationPanel d={d} busy={busy} isLegal={can('disputes.adjudicate')}
            onRefer={(forum, reason) => stepUp(() => disputeApi.referToArbitration(d.id, forum, reason), 'Referred to external arbitration. The money stays frozen.')}
            onAward={(body) => stepUp(() => disputeApi.recordAward(d.id, body), 'Award recorded. The money moves as awarded.')} />}

          {d.status === 'MEDIATION' && !d.arbitration && <MediationPanel d={d} busy={busy} party={party}
            onAnswer={(accept) => act(() => disputeApi.answerRecommendation(d.id, accept), accept ? 'You accepted the recommendation.' : 'You declined the recommendation.')}
            onAssignSelf={() => user && stepUp(() => disputeApi.assignMediator(d.id, user.id), 'You are the mediator for this case.')}
            onRecommend={(body) => stepUp(() => disputeApi.recommend(d.id, body), 'Recommendation issued to both parties.')}
            onDecide={(body, restriction) => stepUp(() => disputeApi.proposeDecision(d.id, { ...body, accountRestriction: restriction }), 'Platform decision proposed; a Legal reviewer must approve it.')}
            onApprove={() => stepUp(() => disputeApi.approveDecision(d.id), 'Decision approved and issued.')}
            canApprove={can('disputes.adjudicate')} isMediatorRole={can('disputes.mediate')} />}

          {(d.status === 'DIRECT_RESOLUTION' || d.proposals.length > 0) && <ProposalsPanel d={d} busy={busy} party={party}
            onPropose={(body) => act(() => disputeApi.propose(d.id, body), 'Proposal sent. The other party can accept it or decline.')}
            onAnswer={(pid, accept) => act(() => accept ? disputeApi.acceptProposal(pid) : disputeApi.rejectProposal(pid), accept ? 'Agreed. The decision is being executed.' : 'Proposal declined. You can now escalate to a mediator.')}
            onEscalate={() => { if (confirm('Escalate to a neutral mediator? Escalation cannot be undone.')) act(() => disputeApi.escalate(d.id), 'Escalated to mediation.') }} />}

          <DisputeTools d={d} busy={busy} party={party} act={act} />
          <EvidencePanel d={d} busy={busy} party={party}
            onAdd={(body) => act(() => disputeApi.addEvidence(d.id, body), 'Evidence added. It is fingerprinted and cannot be edited.')}
            onComplete={() => act(() => disputeApi.evidenceComplete(d.id), 'Marked your evidence as complete.')} />
        </div>
        <aside>
          <SidePanel title="Timeline">
            <ul className="activity dispute-timeline">{d.timeline.map((t, i) => (
              <li key={i}><span className="dot" /><span><strong>{t.actor}</strong><br /><span className="small">{t.text}</span>
                {t.ref?.startsWith('evidence:') && <> · <a className="small" href={`#evidence-${t.ref.slice(9)}`}>view</a></>}</span>
                <span className="muted small">{new Date(t.at).toLocaleString()}</span></li>))}</ul>
          </SidePanel>
          <SidePanel title="Rules">
            <ul className="assurance compact">{['Funds stay frozen until a decision is executed', 'No direct messaging during a dispute',
              'Evidence is fingerprinted and cannot be edited', 'A mediator recommendation binds only if both accept, or both agreed in advance',
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
      <div className="panel-head"><h2>Decision</h2><span className="badge green">{dec.decisionPath === 'MEDIATION' && dec.binding ? 'Binding mediator recommendation'
        : { DIRECT: 'Agreed by both parties', MEDIATION: 'Mediated agreement', PLATFORM: 'Platform decision', ARBITRATION: 'Arbitration award',
          ENTERPRISE_ADMIN: 'Enterprise admin decision' }[dec.decisionPath]}</span></div>
      <p>{dec.plainSummary}</p>
      {dec.accountRestriction && <div className="tip"><Icon name="shield" /><span>The decision referred the {PARTY[dec.accountRestriction.party].toLowerCase()}'s
        account to Trust &amp; Safety: {dec.accountRestriction.reason} Any restriction is decided there, with its own notice and appeal.</span></div>}
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
          <li key={e.id} id={`evidence-${e.id}`}><span className="muted small">{PARTY[e.party]} · {EVIDENCE_TYPES.find(([v]) => v === e.evidenceType)?.[1]} · {new Date(e.submittedAt).toLocaleString()}</span>
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
  d: Dispute; busy: boolean; party: boolean; onPropose: (b: { outcome: DisputeOutcome; allocations: RawAllocation[]; note: string; extendDays?: number | null }) => void
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
        <button className="btn btn-primary" style={{ marginTop: 10 }} disabled={busy} onClick={() => { onPropose({ outcome: alloc.outcome, allocations: alloc.build(), note: note.trim(), extendDays: alloc.extra() }); setNote('') }}>Send proposal</button>
      </div>}
    </section>
  )
}

function MediationPanel({ d, busy, party, onAnswer, onAssignSelf, onRecommend, onDecide, onApprove, canApprove, isMediatorRole }: {
  d: Dispute; busy: boolean; party: boolean; onAnswer: (accept: boolean) => void; onAssignSelf: () => void
  onRecommend: (b: { outcome: DisputeOutcome; allocations: RawAllocation[]; summary: string; citations: string[]; extendDays?: number | null }) => void
  onDecide: (b: { outcome: DisputeOutcome; allocations: RawAllocation[]; summary: string; citations: string[]; extendDays?: number | null },
    restriction: AccountRestriction | null) => void
  onApprove: () => void; canApprove: boolean; isMediatorRole: boolean
}) {
  const alloc = useAllocation(d)
  const restriction = useRestriction()
  const [summary, setSummary] = useState('')
  const [citations, setCitations] = useState('')
  const r = d.recommendation
  const answered = r && (r.acceptedBy?.includes(d.viewerRole) || r.rejectedBy?.includes(d.viewerRole))
  const body = () => ({ outcome: alloc.outcome, allocations: alloc.build(), summary: summary.trim(), extendDays: alloc.extra(),
    citations: citations.split('\n').map((c) => c.trim()).filter(Boolean) })
  return (
    <section className="card panel">
      <div className="panel-head"><h2>Mediation</h2><span className="muted small">{d.mediatorAssigned ? 'Mediator assigned' : 'Waiting for a mediator'}</span></div>
      {!d.mediatorAssigned && isMediatorRole && <button className="btn btn-primary" disabled={busy} onClick={onAssignSelf}>Take this case as mediator</button>}
      {r && <div className="proposal-mini open">
        <strong>Recommendation: {OUTCOME_LABEL[r.outcome]}</strong>
        <p className="small" style={{ whiteSpace: 'pre-wrap' }}>{r.summary}</p>
        {r.citations.length > 0 && <p className="muted small">Cites: {r.citations.join('; ')}</p>}
        <p className="muted small">Accepted by: {r.acceptedBy?.map((p) => PARTY[p]).join(', ') || 'nobody yet'}{r.rejectedBy?.length ? ` · Declined by: ${r.rejectedBy.map((p) => PARTY[p]).join(', ')}` : ''}</p>
        {r.binding && <p className="small"><span className="badge warn">Binding</span> Becomes the decision on {r.challengeEndsAt ? new Date(r.challengeEndsAt).toLocaleDateString() : '—'} unless a party appeals.</p>}
        {r.setAside && <p className="small"><span className="badge">Set aside on appeal</span></p>}
        {party && !answered && !r.setAside && <div className="row">
          <button className="btn btn-primary btn-sm" disabled={busy} onClick={() => onAnswer(true)}>Accept recommendation</button>
          {!r.binding && <button className="btn btn-ghost btn-sm" disabled={busy} onClick={() => onAnswer(false)}>Decline</button>}</div>}
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
        {r && restriction.editor}
        {!r && d.bindingRecommendation && <p className="small warn-text">Both parties agreed in advance: this recommendation becomes the decision
          after a 7-day challenge period unless a party appeals.</p>}
        <button className="btn btn-primary" style={{ marginTop: 10 }} disabled={busy || summary.trim().length < 20 || !restriction.valid}
          onClick={() => (r ? onDecide(body(), restriction.value()) : onRecommend(body()))}>{r ? 'Propose decision for Legal approval' : 'Issue recommendation'}</button>
        <p className="muted small" style={{ marginBottom: 0 }}>You will confirm with your authenticator code.</p>
      </div>}
    </section>
  )
}


/** Conversation as evidence, the once-per-side 24-hour pause, and the mediator's clarifying questions. */
function DisputeTools({ d, busy, party, act }: { d: Dispute; busy: boolean; party: boolean
  act: (fn: () => Promise<Dispute>, msg: string) => void }) {
  const [to, setTo] = useState<'BUYER' | 'PROFESSIONAL'>('BUYER')
  const [question, setQuestion] = useState('')
  const mediator = d.viewerRole === 'MEDIATOR'
  const mine = d.clarifications.filter((c) => c.to === d.viewerRole)
  if (!party && !mediator && d.clarifications.length === 0) return null
  return (
    <section className="card panel">
      <div className="panel-head"><h2>Tools</h2>{d.prefersEarlyResolution && <span className="badge green">Open to settling directly</span>}</div>
      {mine.length > 0 && <div className="tip" style={{ marginBottom: 10 }}><span><strong>The mediator asks you:</strong>
        <ul className="why">{mine.map((c, i) => <li key={i}>{c.question}</li>)}</ul>Answer by adding evidence below.</span></div>}
      {party && <div className="row">
        {d.status === 'EVIDENCE_COLLECTION' && <button className="btn btn-secondary btn-sm" disabled={busy}
          onClick={() => act(() => disputeApi.importMessages(d.id), 'The conversation was added as evidence, with fingerprints.')}>Add our conversation as evidence</button>}
        {d.canCooldown && <button className="btn btn-ghost btn-sm" disabled={busy} onClick={() => {
          if (confirm('Pause the current deadline for 24 hours? Each side can do this once.')) act(() => disputeApi.cooldown(d.id), 'Deadline paused for 24 hours.')
        }}>Pause 24 hours</button>}
      </div>}
      {mediator && <form style={{ marginTop: 10 }} onSubmit={(e) => { e.preventDefault(); act(() => disputeApi.clarify(d.id, to, question.trim()), 'Question sent.'); setQuestion('') }}>
        <label className="filter-box"><span>Ask for clarification ({d.clarifications.length}/3)</span>
          <select value={to} onChange={(e) => setTo(e.target.value as 'BUYER' | 'PROFESSIONAL')}><option value="BUYER">Buyer</option><option value="PROFESSIONAL">Professional</option></select></label>
        <input className="input" aria-label="Question" maxLength={500} value={question} onChange={(e) => setQuestion(e.target.value)} placeholder="One focused question" />
        <button className="btn btn-secondary btn-sm" style={{ marginTop: 6 }} disabled={busy || question.trim().length < 10 || d.clarifications.length >= 3}>Send question</button>
      </form>}
    </section>
  )
}


function ArbitrationPanel({ d, busy, isLegal, onRefer, onAward }: { d: Dispute; busy: boolean; isLegal: boolean
  onRefer: (forum: string, reason: string) => void
  onAward: (body: { outcome: DisputeOutcome; allocations: RawAllocation[]; summary: string; citations: string[]; awardReference: string
    accountRestriction?: AccountRestriction | null }) => void }) {
  const restriction = useRestriction()
  const [forum, setForum] = useState('')
  const [reason, setReason] = useState('')
  const [outcome, setOutcome] = useState<DisputeOutcome>('FULL_RELEASE')
  const [summary, setSummary] = useState('')
  const [ref, setRef] = useState('')
  const mediator = d.viewerRole === 'MEDIATOR' && d.mediatorAssigned
  if (!d.arbitration && !mediator) return null
  return (
    <section className="card panel">
      <div className="panel-head"><h2>External arbitration</h2>{d.arbitration && <span className="badge amber">Referred</span>}</div>
      {d.arbitration ? <>
        <p><strong>{d.arbitration.forum}</strong> · referred {new Date(d.arbitration.referredAt).toLocaleDateString()}</p>
        <p className="muted">{d.arbitration.reason}</p>
        <p className="small">The money stays frozen in escrow until the platform's Legal team records the arbitrator's award.</p>
        {isLegal && <div className="form-grid">
          <label>Award reference<input className="input" value={ref} onChange={(e) => setRef(e.target.value)} placeholder="e.g. ICC-2026-0412" /></label>
          <label>Outcome<select className="input" value={outcome} onChange={(e) => setOutcome(e.target.value as DisputeOutcome)}>
            {(['FULL_RELEASE', 'FULL_REFUND', 'TERMINATION'] as DisputeOutcome[]).map((o) => <option key={o} value={o}>{OUTCOME_LABEL[o]}</option>)}</select></label>
          <label>What the award says (plain language)<textarea className="input" rows={3} value={summary} onChange={(e) => setSummary(e.target.value)} /></label>
          {restriction.editor}
          <button className="btn btn-primary" disabled={busy || ref.trim().length < 3 || summary.trim().length < 20 || !restriction.valid}
            onClick={() => onAward({ outcome, allocations: [], summary, citations: [], awardReference: ref, accountRestriction: restriction.value() })}>Record award</button>
        </div>}
      </> : <div className="form-grid">
        <p className="muted">Refer a case the platform should not decide (its size, legal complexity, or a clause naming an arbitration forum).
          Platform mediation stops; nothing is released or refunded until the award is recorded.</p>
        <label>Forum<input className="input" value={forum} onChange={(e) => setForum(e.target.value)} placeholder="e.g. ICC, AAA, LCIA" /></label>
        <label>Reason<textarea className="input" rows={2} value={reason} onChange={(e) => setReason(e.target.value)} /></label>
        <button className="btn btn-secondary" disabled={busy || forum.trim().length < 3 || reason.trim().length < 20}
          onClick={() => { if (confirm('Refer this case to external arbitration? Platform mediation stops.')) onRefer(forum, reason) }}>Refer to arbitration</button>
      </div>}
    </section>
  )
}


/** Optional "account restriction" outcome: it hands the account to Trust & Safety (a linked case), never restricts directly. */
function useRestriction() {
  const [party, setParty] = useState<'' | 'BUYER' | 'PROFESSIONAL'>('')
  const [reason, setReason] = useState('')
  const valid = !party || reason.trim().length >= 20
  const editor = (
    <div className="revise-box" style={{ marginTop: 8 }}>
      <label className="filter-box"><span>Account restriction (optional)</span>
        <select value={party} onChange={(e) => setParty(e.target.value as '' | 'BUYER' | 'PROFESSIONAL')}>
          <option value="">No referral</option><option value="BUYER">Refer the buyer to Trust &amp; Safety</option>
          <option value="PROFESSIONAL">Refer the professional to Trust &amp; Safety</option></select></label>
      {party && <label className="filter-box grow" style={{ marginTop: 6 }}><span>Why (min 20 characters)</span>
        <textarea rows={2} maxLength={2000} value={reason} onChange={(e) => setReason(e.target.value)} /></label>}
      <p className="muted small" style={{ marginBottom: 0 }}>Trust &amp; Safety opens a linked case and decides any restriction itself.</p>
    </div>
  )
  const value = (): AccountRestriction | null => (party ? { party, reason: reason.trim() } : null)
  return { editor, valid, value }
}

function ProvisionalCard({ d }: { d: Dispute }) {
  const p = d.provisionalDecision!
  return (
    <section className="card panel decision-card">
      <div className="panel-head"><h2>{p.path === 'MEDIATION' ? 'Binding recommendation' : 'Enterprise admin decision'}</h2>
        <span className={`badge ${p.appealed ? '' : 'warn'}`}>{p.appealed ? 'Under appeal' : `Takes effect ${new Date(p.challengeEndsAt).toLocaleDateString()}`}</span></div>
      <p><strong>{OUTCOME_LABEL[p.outcome]}.</strong> {p.summary}</p>
      {p.allocations.some((a) => a.releaseMinor || a.refundMinor) && <ul className="why">{p.allocations.map((a) => {
        const m = d.milestones.find((x) => x.id === a.milestoneId)
        return <li key={a.milestoneId}>M{m?.sequence}: {formatMoney({ amountMinor: a.releaseMinor, currency: d.disputed.currency })} released,{' '}
          {formatMoney({ amountMinor: a.refundMinor, currency: d.disputed.currency })} refunded</li>
      })}</ul>}
      <p className="muted small" style={{ marginBottom: 0 }}>Nothing moves until it takes effect. Either party may appeal before then for new
        material evidence or a procedural error; an independent reviewer then decides whether it stands.</p>
    </section>
  )
}

const PATHS: { kind: AgreementKind; title: string; text: string }[] = [
  { kind: 'BINDING_RECOMMENDATION', title: 'Binding mediator recommendation',
    text: "The mediator's recommendation becomes the decision after a 7-day challenge period, unless either side appeals." },
  { kind: 'ENTERPRISE_ADMIN', title: "Decision by the buyer enterprise's admin",
    text: "An Organisation Admin of the buyer enterprise (not the person who opened the dispute) decides, equally open to appeal for 7 days." },
]

function DecisionPathsPanel({ d, busy, onSet }: { d: Dispute; busy: boolean; onSet: (kind: AgreementKind, consent: boolean) => void }) {
  const paths = PATHS.filter((p) => p.kind === 'BINDING_RECOMMENDATION' || d.enterpriseEngagement)
  const applies = (k: AgreementKind) => (k === 'BINDING_RECOMMENDATION' ? d.bindingRecommendation : d.enterpriseAdminPath)
  const locked = !!d.provisionalDecision || !!d.pendingDecision
  return (
    <section className="card panel">
      <div className="panel-head"><h2>Optional decision paths</h2><span className="muted small">Both parties must agree</span></div>
      {paths.map((p) => {
        const agreed = d.agreements?.[p.kind] ?? []
        const mine = agreed.includes(d.viewerRole)
        const lockedHere = locked || (p.kind === 'BINDING_RECOMMENDATION' && !!d.recommendation)
        return (
          <div key={p.kind} className="proposal-mini">
            <div className="panel-head"><strong>{p.title}</strong>
              <span className={`badge ${applies(p.kind) ? 'green' : ''}`}>{applies(p.kind) ? 'Applies' : `${agreed.length}/2 agreed`}</span></div>
            <p className="muted small">{p.text}</p>
            {!applies(p.kind) || mine ? !lockedHere && <button className={`btn btn-sm ${mine ? 'btn-ghost' : 'btn-secondary'}`} disabled={busy}
              onClick={() => onSet(p.kind, !mine)}>{mine ? 'Withdraw my agreement' : 'I agree'}</button> : null}
          </div>
        )
      })}
    </section>
  )
}

function EnterpriseDecisionPanel({ d, busy, onDecide }: { d: Dispute; busy: boolean
  onDecide: (b: { outcome: DisputeOutcome; allocations: RawAllocation[]; summary: string; citations: string[]; extendDays?: number | null }) => void }) {
  const alloc = useAllocation(d)
  const [summary, setSummary] = useState('')
  return (
    <section className="card panel">
      <div className="panel-head"><h2>Decide as enterprise admin</h2><span className="badge">Agreed by both parties</span></div>
      <p className="muted small">Your decision takes effect after a 7-day challenge period unless a party appeals. Money then moves through the
        usual escrow release and refund; you never move it directly.</p>
      {alloc.editor}
      <label className="filter-box grow" style={{ marginTop: 8 }}><span>Plain-language reasoning (min 20 characters)</span>
        <textarea rows={4} maxLength={2000} value={summary} onChange={(e) => setSummary(e.target.value)} /></label>
      <button className="btn btn-primary" style={{ marginTop: 10 }} disabled={busy || summary.trim().length < 20}
        onClick={() => { if (confirm('Issue this decision? Both parties are notified and may appeal within 7 days.'))
          onDecide({ outcome: alloc.outcome, allocations: alloc.build(), summary: summary.trim(), citations: [], extendDays: alloc.extra() }) }}>Issue decision</button>
    </section>
  )
}

/** Buyer organisation dispute dashboard: open / closed, time to resolution, repeat patterns, money frozen, scheduled reports. */
function OrgDisputeDashboard() {
  const [orgs, setOrgs] = useState<Organization[]>([])
  const [orgId, setOrgId] = useState<string | null>(null)
  const [dash, setDash] = useState<DisputeDashboard | null>(null)
  const [sub, setSub] = useState<ReportSubscription | null | undefined>(undefined)
  const [error, setError] = useState<unknown>(null)
  const [notice, setNotice] = useState<string | null>(null)
  useEffect(() => { orgApi.mine().then((os) => { setOrgs(os); setOrgId(os[0]?.id ?? null) }).catch(setError) }, [])
  const org = orgs.find((o) => o.id === orgId)
  const admin = !!org?.myRoles.includes('ORG_ADMIN')
  const canExport = admin || !!org?.myRoles.includes('LEGAL_REVIEWER')
  useEffect(() => {
    if (!orgId) return
    disputeApi.dashboard(orgId).then(setDash).catch(setError)
    if (admin) disputeApi.reportSubscription(orgId).then(setSub).catch(setError)
  }, [orgId, admin])
  if (!orgId) return error ? <ErrorAlert error={error} /> : null
  const label = (r: Record<string, number>) => Object.entries(r).map(([k, v]) => `${k.replaceAll('_', ' ').toLowerCase()} ${v}`).join(' · ') || '—'
  return (
    <section className="card panel">
      <div className="panel-head"><h2>Organisation dashboard</h2>
        {orgs.length > 1 && <select aria-label="Organisation" value={orgId} onChange={(e) => setOrgId(e.target.value)}>
          {orgs.map((o) => <option key={o.id} value={o.id}>{o.name}</option>)}</select>}</div>
      <ErrorAlert error={error} />
      {notice && <div className="alert alert-success" role="status">{notice}</div>}
      {!dash ? <Loading /> : <>
        <dl className="facts">
          <dt>Open / decided / closed</dt><dd>{dash.open} / {dash.decided} / {dash.closed} (of {dash.total})</dd>
          <dt>Time to resolution</dt><dd>{dash.medianDaysToResolution == null ? '—' : `median ${dash.medianDaysToResolution} days · average ${dash.averageDaysToResolution} days`}</dd>
          <dt>Money frozen now</dt><dd>{dash.frozen.length ? dash.frozen.map((f) => `${formatMoney({ amountMinor: f.amountMinor, currency: f.currency })} (${f.cases})`).join(', ') : 'None'}</dd>
          <dt>By category</dt><dd className="small">{label(dash.byCategory)}</dd>
          <dt>By outcome</dt><dd className="small">{label(dash.byOutcome)}</dd>
          <dt>How decided</dt><dd className="small">{label(dash.byDecisionPath)}</dd>
        </dl>
        <h3>Repeat disputes per professional</h3>
        {dash.repeatProfessionals.length === 0 ? <p className="muted small">No professional has more than one dispute with your organisation.</p> : (
          <table className="data"><thead><tr><th>Professional</th><th>Disputes</th><th>Open</th><th>Engagements</th><th>Categories</th><th>Last opened</th></tr></thead>
            <tbody>{dash.repeatProfessionals.map((p) => <tr key={p.professionalId}><td>{p.name}</td><td>{p.disputes}</td><td>{p.open}</td>
              <td>{p.engagements}</td><td className="small">{p.categories.map((c) => CATEGORY_LABEL[c as DisputeCategory] ?? c).join(', ')}</td>
              <td className="small">{new Date(p.lastOpenedAt).toLocaleDateString()}</td></tr>)}</tbody></table>)}
      </>}
      {(admin || canExport) && <div className="row" style={{ marginTop: 12, alignItems: 'flex-end' }}>
        {admin && <label className="filter-box"><span>Scheduled report (CSV link by notification)</span>
          <select value={sub === undefined ? '' : sub?.frequency ?? 'OFF'} disabled={sub === undefined} onChange={async (e) => {
            const v = e.target.value === 'OFF' ? null : (e.target.value as 'WEEKLY' | 'MONTHLY')
            setError(null); setNotice(null)
            try { setSub(await disputeApi.setReportSubscription(orgId, v)); setNotice(v ? `You will receive a ${v.toLowerCase()} dispute report.` : 'Scheduled reports stopped.') }
            catch (err) { setError(err) }
          }}><option value="OFF">Off</option><option value="WEEKLY">Weekly (Mondays)</option><option value="MONTHLY">Monthly (the 1st)</option></select></label>}
        {sub && <span className="muted small">Next: {new Date(sub.nextRunAt).toLocaleDateString()}{sub.lastSentAt ? ` · last sent ${new Date(sub.lastSentAt).toLocaleDateString()}` : ''}</span>}
        {canExport && <button className="btn btn-secondary btn-sm" onClick={() => disputeApi.exportReport(orgId)
          .then((b) => saveBlob('disputes-last-30-days.csv', b)).catch(setError)}><Icon name="download" /> Export last 30 days (CSV)</button>}
      </div>}
    </section>
  )
}
