import { useCallback, useEffect, useState } from 'react'
import { useTwoStepReady } from '../auth/useTwoStep'
import { EngagementReview } from '../components/EngagementReview'
import { AIAssistance } from '../components/AIAssistance'
import { Link, useParams } from 'react-router-dom'
import { CONTRACT_STAGE, contractApi, MILESTONE_STATUS, stageOf, type PolicyState, type ActivityEntry, type ChangeOrder, type Contract, type ContractMilestone,
  type EngagementFile, type Verdict } from '../api/contracts'
import { DeliveryForm, ReviewPanel, SubmissionView } from '../components/Delivery'
import { disputableMilestones, disputeApi, OPEN_PHASES, paymentStuck, releaseAfterWindow, type Dispute } from '../api/disputes'
import { escrowApi, type Escrow } from '../api/escrow'
import { MeetingsPanel, TasksPanel } from '../components/Collaboration'
import { RaiseDisputeDialog } from './Disputes'
import { FundDialog, PaymentProtectionSetup, PaymentsPanel } from '../components/EscrowPanels'
import { formatMoney } from '../api/orgs'
import { SCOPE_CHANGE_LABEL, type ScopeChangeKind } from '../api/proposals'
import { LABEL } from '../api/professional'
import { FileLink } from '../components/FileLink'
import { messagingApi, type ConversationMessage } from '../api/messaging'
import { useAuth } from '../auth/AuthContext'
import { Icon } from '../components/dashboard'
import { EmptyTable, PortalHeader, SidePanel, StatCard, Tabs } from '../components/portal'
import { ErrorAlert, useStepUp, Loading } from '../components/ui'
import { saveBlob } from '../lib/exports'
import { formatCurrencies } from '../lib/money'

/* Engagements (Step 7) for both sides: the contract generated from an accepted proposal, signatures (buyer first,
   professional countersigns, each with a fresh two-step confirmation), and milestones (funded -> delivered -> reviewed). */

type Side = 'buyer' | 'professional'
const base = (side: Side) => (side === 'buyer' ? '/app/engagements' : '/app/professional/engagements')
const fmtDate = (d: string | null) => (d ? new Date(d.length === 10 ? `${d}T00:00:00` : d).toLocaleDateString() : '—')
const progress = (c: Contract) => {
  const done = c.milestones.filter((m) => m.status === 'ACCEPTED').length
  return { done, total: c.milestones.length, pct: c.milestones.length ? Math.round((done / c.milestones.length) * 100) : 0 }
}

export function EngagementsPage({ side }: { side: Side }) {
  const [list, setList] = useState<Contract[] | null>(null)
  const [error, setError] = useState<unknown>(null)
  const [tab, setTab] = useState<'all' | 'signing' | 'protection' | 'active' | 'completed'>('all')
  useEffect(() => { contractApi.list(side).then(setList).catch(setError) }, [side])
  const rows = list ?? []
  // "Active" means funded and under way; a signed engagement waits for payment protection (its first funding) first.
  const of = (t: string) => rows.filter((c) => t === 'all' || (t === 'signing' ? c.status === 'PENDING_SIGNATURE'
    : t === 'protection' ? stageOf(c) === 'AWAITING_PAYMENT_PROTECTION' : t === 'active' ? stageOf(c) === 'ACTIVE' : c.status === 'COMPLETED'))
  const activeValue = formatCurrencies(rows.filter((c) => stageOf(c) === 'ACTIVE').map(c => c.total))
  const other = (c: Contract) => c.parties.find((p) => p.role !== (side === 'buyer' ? 'BUYER' : 'PROFESSIONAL'))

  return (
    <>
      <PortalHeader eyebrow="Engagements" title={side === 'buyer' ? 'Your engagements' : 'Your engagements'}
        subtitle="Contracts, signatures and milestones for work you have agreed — every step on the record."
        actions={side === 'buyer' ? <Link className="btn btn-primary" to="/app/find"><Icon name="search" /> Find a Professional</Link> : undefined} />
      <ErrorAlert error={error} />
      <div className="stat-row four">
        <StatCard icon="contract" tone="amber" value={list ? of('signing').length + of('protection').length : '…'} label="Awaiting signatures or protection"
          sub={list && of('protection').length ? `${of('protection').length} awaiting payment protection` : 'Sign, then fund to activate'} />
        <StatCard icon="briefcase" tone="green" value={list ? of('active').length : '…'} label="Active" sub="In progress" />
        <StatCard icon="check" tone="blue" value={list ? of('completed').length : '…'} label="Completed" sub="All milestones accepted" />
        <StatCard icon="lock" tone="violet" value={list ? activeValue : '…'} label="Active value" sub="Totals by currency" />
      </div>
      <section className="card panel">
        <Tabs tabs={[{ key: 'all', label: 'All', count: rows.length }, { key: 'signing', label: 'Awaiting signatures', count: of('signing').length },
          { key: 'protection', label: 'Awaiting payment protection', count: of('protection').length }, { key: 'active', label: 'Active', count: of('active').length }, { key: 'completed', label: 'Completed', count: of('completed').length }]}
          value={tab} onChange={setTab} />
        {list && of(tab).length === 0 ? (
          <EmptyTable columns={['Engagement', side === 'buyer' ? 'Professional' : 'Buyer', 'Value', 'Status', 'Progress', 'Next action']}>
            <strong>No engagements here.</strong> An engagement starts when a proposal is accepted: the contract is generated
            automatically, then {side === 'buyer' ? 'you sign and the professional countersigns' : 'the buyer signs and you countersign'}.
          </EmptyTable>
        ) : (
          <div className="compare-scroll"><table className="data">
            <thead><tr><th>Engagement</th><th>{side === 'buyer' ? 'Professional' : 'Buyer'}</th><th>Value</th><th>Status</th><th>Progress</th><th>Next action</th></tr></thead>
            <tbody>{of(tab).map((c) => {
              const pr = progress(c)
              return (
                <tr key={c.id}>
                  <td><Link to={`${base(side)}/${c.id}`}><strong>{c.title}</strong></Link><div className="muted small">{c.reference}</div></td>
                  <td className="small">{other(c)?.name}</td>
                  <td><strong>{formatMoney(c.total)}</strong></td>
                  <td><span className={`badge ${CONTRACT_STAGE[stageOf(c)].tone}`}>{CONTRACT_STAGE[stageOf(c)].label}</span></td>
                  <td><div className="bar" title={`${pr.done} of ${pr.total} milestones accepted`}><span style={{ width: `${pr.pct}%` }} /></div>
                    <span className="muted small">{pr.done}/{pr.total} milestones</span></td>
                  <td className="small">{c.canSign ? <Link className="btn btn-primary btn-sm" to={`${base(side)}/${c.id}`}>Sign</Link> : c.nextAction}</td>
                </tr>
              )
            })}</tbody>
          </table></div>
        )}
      </section>
    </>
  )
}

export function EngagementDetail({ side }: { side: Side }) {
  const { id = '' } = useParams()
  const { user } = useAuth()
  const twoStepReady = useTwoStepReady()
  const [c, setC] = useState<Contract | null>(null)
  const [error, setError] = useState<unknown>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [tab, setTab] = useState<'overview' | 'agreement' | 'changes' | 'milestones' | 'tasks' | 'payments' | 'messages' | 'files' | 'activity'>('overview')
  const [doc, setDoc] = useState<string | null>(null)
  const [read, setRead] = useState(false)
  const [busy, setBusy] = useState(false)
  const { run, modal } = useStepUp(setError)

  const [escrow, setEscrow] = useState<Escrow | null>(null)
  const [fundFor, setFundFor] = useState<string[] | null>(null)
  const [disputes, setDisputes] = useState<Dispute[]>([])
  const [raising, setRaising] = useState(false)
  const load = useCallback(async () => {
    try {
      const k = await contractApi.get(id)
      setC(k)
      if (k.status !== 'PENDING_SIGNATURE') {
        setEscrow(await escrowApi.byContract(id).catch(() => null))
        setDisputes(await disputeApi.list(side, id).catch(() => []))
      }
    } catch (err) { setError(err) }
  }, [id, side])
  useEffect(() => { load() }, [load])
  // Payments are processed in the background (provider capture, then escrow hold): refresh a few times after funding.
  const refreshSoon = () => { for (const ms of [1200, 3000, 6000]) setTimeout(() => { load() }, ms) }
  useEffect(() => { if (tab === 'agreement' && doc === null) contractApi.document(id).then(setDoc).catch(setError) }, [tab, doc, id])
  // Live policy state (buyer): blocked actions are shown, and disabled, before anyone tries them.
  const [policy, setPolicy] = useState<PolicyState | null>(null)
  const policyKey = c && side === 'buyer' ? `${c.id}:${c.status}:${c.milestones.map((m) => m.status).join(',')}` : ''
  useEffect(() => { if (policyKey) contractApi.policyState(id).then(setPolicy).catch(() => setPolicy(null)) }, [policyKey, id])
  const blockedReason = (action: string, milestoneId?: string) => {
    const a = policy?.actions.find((x) => x.action === action && (!milestoneId || x.milestoneId === milestoneId))
    return a?.decision === 'BLOCK' ? a.reasons[0]?.message ?? 'Blocked by your organisation policy' : undefined
  }

  if (!c) return error ? <ErrorAlert error={error} /> : <Loading />
  const stage = stageOf(c)
  const st = CONTRACT_STAGE[stage]
  const awaitingProtection = stage === 'AWAITING_PAYMENT_PROTECTION'
  const signed = new Set(c.signatures.filter((s) => s.contractVersion === c.contractVersion).map((s) => s.party))
  const pr = progress(c)
  const act = async (fn: () => Promise<Contract>, msg: string) => {
    setBusy(true); setError(null); setNotice(null)
    try { setC(await fn()); setNotice(msg) } catch (err) { setError(err) } finally { setBusy(false) }
  }

  return (
    <>
      {modal}
      {raising && <RaiseDisputeDialog contract={c} escrow={escrow} onClose={() => setRaising(false)} />}
      <PortalHeader eyebrow={<Link to={base(side)}>← Engagements</Link>} title={c.title}
        subtitle={<><span className={`badge ${st.tone}`}>{st.label}</span> · {c.reference} · {formatMoney(c.total)} · version {c.contractVersion}</>}
        actions={<><Link className="btn btn-secondary" to={`/app/messages?contextType=CONTRACT&contextId=${c.id}`}><Icon name="message" /> Messages</Link>
          {(c.status === 'ACTIVE' || c.status === 'DISPUTED' || (c.status === 'COMPLETED' && paymentStuck(c, escrow).size > 0)) && disputableMilestones(c, escrow).length > 0 &&
            <button className="btn btn-ghost" onClick={() => setRaising(true)}><Icon name="help" /> Raise a dispute</button>}</>} />
      {notice && <div className="alert alert-success" role="status">{notice}</div>}
      <ErrorAlert error={error} />
      {disputes.filter((x) => OPEN_PHASES.includes(x.status)).map((x) => (
        <div key={x.id} className="attention-banner neutral"><span className="kpi-icon amber"><Icon name="lock" /></span>
          <div><strong>Dispute {x.reference} is open: {formatMoney(x.disputed)} frozen</strong>
            <div className="small">{x.nextStep}</div></div>
          <Link className="btn btn-secondary" to={`/app/disputes/${x.id}`}>Open dispute</Link></div>))}

      <div className={`attention-banner ${stage === 'ACTIVE' || c.status === 'COMPLETED' ? 'ok' : ''}`}>
        <span className={`kpi-icon ${c.canSign ? 'amber' : 'green'}`}><Icon name={c.canSign ? 'contract' : 'check'} /></span>
        <div><strong>{c.nextAction}</strong>
          {c.status === 'PENDING_SIGNATURE' && <div className="muted small">Sign by {fmtDate(c.signatureDeadline)}. The buyer signs first; the professional countersigns.</div>}
          {awaitingProtection && <div className="muted small">Signed {fmtDate(c.activatedAt)}. The engagement becomes active once the first funding is
            held in escrow{side === 'professional' ? ': do not start work before then.' : '.'}</div>}
          {stage === 'ACTIVE' && <div className="muted small">Activated {fmtDate(c.activatedAt)} · {pr.done} of {pr.total} milestones accepted</div>}</div>
        {c.canSign && <button className="btn btn-primary" onClick={() => setTab('agreement')}>Review &amp; sign</button>}
      </div>

      {c.terminationRequest?.status === 'PENDING' && <TerminationBanner c={c} busy={busy}
        onAnswer={(agree, note) => { setError(null); setNotice(null); run(async () => {
          setC(await contractApi.answerTermination(c.id, agree, note))
          setNotice(agree ? 'The engagement has ended. Money held for work not accepted goes back to the buyer.' : 'Declined. The engagement continues.')
          if (agree) refreshSoon()
        }) }}
        onWithdraw={() => act(() => contractApi.withdrawTermination(c.id), 'Request withdrawn. The engagement continues.')} />}

      {awaitingProtection && escrow && escrow.allocations.length > 0 && <div id="payment-protection">
        <PaymentProtectionSetup c={c} escrow={escrow} side={side} onSaved={(e) => { setEscrow(e); setNotice('Payment protection saved. Fund to activate the engagement.') }}
          onFund={(ids) => setFundFor(ids)} /></div>}
      {stage === 'ACTIVE' && pr.done === 0 && <ActivationPanel c={c} side={side} />}

      {c.status === 'COMPLETED' && <EngagementReview contractId={c.id} canReview={side === 'buyer'} reference={c.reference}
        professionalName={c.parties.find((p) => p.role === 'PROFESSIONAL')?.name} organizationName={c.parties.find((p) => p.role === 'BUYER')?.name} />}
      {tab === 'agreement' && <AIAssistance purpose="contract-summary" subjectId={c.id} />}
      <Tabs tabs={[{ key: 'overview', label: 'Overview' }, { key: 'agreement', label: 'Agreement' }, { key: 'milestones', label: 'Milestones', count: c.milestones.length },
        { key: 'tasks', label: 'Tasks' }, { key: 'changes', label: 'Change orders', count: c.changeOrders.length }, { key: 'payments', label: 'Payments' },
        { key: 'messages', label: 'Messages' }, { key: 'files', label: 'Files' }, { key: 'activity', label: 'Activity' }]} value={tab} onChange={setTab} />

      {tab === 'overview' && (
        <div className="home-grid wide">
          <div>
            <section className="card panel">
              <div className="panel-head"><h2>Key terms</h2></div>
              <dl className="facts">
                <dt>Objective</dt><dd>{c.terms.objective}</dd>
                {c.terms.successCriteria && <><dt>Success criteria</dt><dd><SuccessCriteriaView criteria={c.terms.successCriteria} /></dd></>}
                <dt>Engagement</dt><dd>{LABEL[c.engagementType] ?? c.engagementType}{c.pricingModel ? ` · ${LABEL[c.pricingModel] ?? c.pricingModel}` : ''}</dd>
                <dt>Timeline</dt><dd>{fmtDate(c.terms.startDate)} – {fmtDate(c.terms.endDate)}</dd>
                <dt>Total</dt><dd>{formatMoney(c.total)} · accepted so far {formatMoney(c.acceptedAmount)}</dd>
                <dt>Confidentiality</dt><dd>{c.ndaRequired ? 'NDA applies' : 'Standard'}</dd>
                <dt>Policy</dt><dd>{c.policyVersionLabel}</dd>
              </dl>
            </section>
            <section className="card panel">
              <div className="panel-head"><h2>Milestones</h2><button className="btn btn-ghost btn-sm" onClick={() => setTab('milestones')}>Open →</button></div>
              <div className="bar big"><span style={{ width: `${pr.pct}%` }} /></div>
              <ul className="milestone-mini">{c.milestones.map((m) => (
                <li key={m.id}><span className="n">M{m.sequence}</span><span>{m.title}</span><span className="small">{formatMoney(m.amount)}</span>
                  <span className={`badge ${MILESTONE_STATUS[m.status].tone}`}>{MILESTONE_STATUS[m.status].label}</span></li>))}</ul>
            </section>
          </div>
          <aside>
            <SidePanel title="Parties">
              <ul className="pro-list">{c.parties.map((p) => (
                <li key={p.role}><Icon name={p.role === 'BUYER' ? 'building' : 'user'} /><span><strong>{p.name}</strong><br /><span className="muted small">{p.detail}</span></span>
                  <span className={`badge ${signed.has(p.role) ? 'green' : ''}`}>{signed.has(p.role) ? 'Signed' : 'Not signed'}</span></li>))}</ul>
            </SidePanel>
            {(c.canEndNow || c.canRequestEnd) && <EndEngagement c={c} busy={busy} onEnd={(reason, mutual) => {
              setError(null); setNotice(null); run(async () => {
                setC(await contractApi.terminate(c.id, reason, mutual))
                setNotice(mutual ? 'Request sent. The other side can agree or decline; the engagement continues meanwhile.' : 'The engagement has ended.')
              }) }} />}
            <SidePanel title="What's protected">
              <ul className="assurance compact">{['Signed contract with locked terms', 'Escrow for every milestone',
                'Release only after acceptance', 'Dispute route with funds held', 'Audit-grade record'].map((t) => <li key={t}><Icon name="check" /><span>{t}</span></li>)}</ul>
            </SidePanel>
          </aside>
        </div>
      )}

      {tab === 'agreement' && (
        <div className="home-grid wide">
          <section className="card panel">
            <div className="panel-head"><h2>Agreement summary</h2>
              <span className="row" style={{ flexWrap: 'nowrap' }}><span className="muted small">Terms ref {c.termsHash.slice(0, 12)}…</span>
                <button className="btn btn-secondary btn-sm" onClick={() => contractApi.documentPdf(c.id)
                  .then((b) => saveBlob(`${c.reference}-v${c.contractVersion}.pdf`, b)).catch(setError)}>
                  <Icon name="download" /> Download PDF</button></span></div>
            <h3>Parties</h3>
            <ul className="pro-list">{c.parties.map((p) => (
              <li key={p.role}><Icon name={p.role === 'BUYER' ? 'building' : 'user'} /><span><strong>{p.name}</strong>
                <span className="muted small"> · {p.role === 'BUYER' ? 'Buyer' : 'Professional'}{p.detail ? ` · ${p.detail}` : ''}</span></span>
                <span className={`badge ${signed.has(p.role) ? 'green' : ''}`}>{signed.has(p.role) ? 'Signed' : 'Not signed'}</span></li>))}</ul>
            <h3>Deliverables &amp; acceptance criteria</h3>
            <ul className="why">{c.terms.deliverables.map((d) => <li key={d.key}><strong>{d.title}:</strong> {d.acceptanceCriteria}</li>)}</ul>
            {c.terms.successCriteria && <><h3>Success criteria</h3><SuccessCriteriaView criteria={c.terms.successCriteria} /></>}
            {(c.terms.scopeChanges ?? []).length > 0 && <><h3>Agreed scope changes</h3>
              <ul className="why">{c.terms.scopeChanges!.map((x, i) => <li key={i}><strong>{SCOPE_CHANGE_LABEL[x.kind as ScopeChangeKind] ?? x.kind}{x.target ? ` (${x.target})` : ''}:</strong> {x.proposed}</li>)}</ul></>}
            <h3>Payment schedule</h3>
            <table className="data"><thead><tr><th>#</th><th>Milestone</th><th>Due</th><th>Amount</th></tr></thead>
              <tbody>{c.milestones.map((m) => <tr key={m.id}><td>M{m.sequence}</td><td>{m.title}</td><td className="small">{fmtDate(m.dueDate)}</td><td>{formatMoney(m.amount)}</td></tr>)}</tbody></table>
            {(c.terms.assumptions.length > 0 || c.terms.exclusions.length > 0) && <div className="row" style={{ alignItems: 'flex-start', marginTop: 12 }}>
              {c.terms.assumptions.length > 0 && <div style={{ flex: 1 }}><h3>Assumptions</h3><ul className="why">{c.terms.assumptions.map((a) => <li key={a}>{a}</li>)}</ul></div>}
              {c.terms.exclusions.length > 0 && <div style={{ flex: 1 }}><h3>Exclusions</h3><ul className="why">{c.terms.exclusions.map((a) => <li key={a}>{a}</li>)}</ul></div>}
            </div>}
            <ul className="why"><li>Changes to scope, price or timeline need a change order accepted by both sides.</li>
              <li>Disputes go through Zoikorum's dispute process; funds for the milestone are held meanwhile.</li></ul>
            {c.status === 'PENDING_SIGNATURE' && !c.activatedAt && <p className="small">Something to change before signing?
              {' '}<button className="link-button" onClick={() => setTab('changes')}>Propose a change</button> (the other side approves; then both sign the new version).</p>}
            <details className="doc-full"><summary>Governing law</summary>
              <p className="small">{c.terms.governingLaw ?? 'As in the Zoikorum Terms of Service (no enterprise policy sets it for this engagement).'}</p></details>
            <details className="doc-full"><summary>Data handling</summary>
              <pre className="agreement">{section(doc, 'DATA HANDLING') ?? 'Loading…'}</pre></details>
            <details className="doc-full"><summary>Standard terms</summary>
              <pre className="agreement">{section(doc, 'STANDARD TERMS') ?? 'Loading…'}</pre></details>
            <details className="doc-full"><summary>Full agreement text</summary>
              <pre className="agreement">{doc ?? 'Loading…'}</pre>
              <p className="muted small">Document fingerprint (SHA-256): <code>{c.documentSha256}</code></p></details>
          </section>
          <aside>
            <section className="card panel sign-panel">
              <div className="panel-head"><h2>Signatures</h2></div>
              <ol className="side-steps">
                {(['BUYER', 'PROFESSIONAL'] as const).map((party, i) => {
                  const s = c.signatures.find((x) => x.party === party && x.contractVersion === c.contractVersion)
                  return <li key={party}><span className="n">{s ? '✓' : i + 1}</span><span><strong>{party === 'BUYER' ? 'Buyer signs' : 'Professional countersigns'}</strong><br />
                    <span className="muted small">{s ? `${s.signerName} · ${new Date(s.signedAt).toLocaleString()} · two-step confirmed` : 'Not signed yet'}</span></span></li>
                })}
              </ol>
              {c.canSign && (twoStepReady ? <>
                <label className="checkbox" style={{ marginTop: 12 }}><input type="checkbox" checked={read} onChange={(e) => setRead(e.target.checked)} />
                  <span>I have read the agreement and agree to its terms (version {c.contractVersion}).</span></label>
                <button className="btn btn-primary btn-lg" style={{ width: '100%', marginTop: 10 }} disabled={!read || busy}
                  onClick={() => { setError(null); setNotice(null); run(async () => {
                    // Errors propagate so the step-up dialog can ask for a code and retry.
                    setC(await contractApi.sign(c.id, c.termsHash))
                    setNotice(side === 'buyer' ? 'Signed. The professional will be asked to countersign.'
                      : 'Countersigned. The buyer now sets up payment protection; do not start work until the first milestone is funded.')
                  }) }}>
                  {side === 'buyer' ? 'Sign contract' : 'Countersign contract'}</button>
                <p className="muted small" style={{ margin: '8px 0 0' }}>{user?.mfaBypass ? 'Development mode: no authenticator code is asked.' : "You'll be asked to confirm with your authenticator app or a passkey."}</p>
              </> : <div className="tip" style={{ marginTop: 12 }}><Icon name="lock" /><span>Signing needs two-step verification: an authenticator
                app or a passkey. <Link to="/app/security">Set one up</Link>, then come back to sign.</span></div>)}
              {awaitingProtection && <div className="protect-note" style={{ marginTop: 12 }}><Icon name="check" /><div>
                <strong>Both parties have signed.</strong>
                <div className="small">{side === 'buyer' ? 'Next: choose how payments are protected and released, then fund.'
                  : 'Next: the buyer sets up payment protection and funds the first milestone. Do not start work before then.'}</div>
                {side === 'buyer' && <button className="btn btn-primary" style={{ marginTop: 8 }} onClick={() => {
                  setTab('overview'); setTimeout(() => document.getElementById('payment-protection')?.scrollIntoView({ behavior: 'smooth' }), 0)
                }}>Continue to payment protection setup</button>}</div></div>}
            </section>
          </aside>
        </div>
      )}

      {fundFor && escrow && <FundDialog escrow={escrow} preselect={fundFor} onClose={() => setFundFor(null)}
        onFunded={(e) => { setEscrow(e); setFundFor(null); setNotice('Payment submitted. The funds are held in escrow as soon as the payment is captured.'); refreshSoon() }} />}
      {tab === 'changes' && <ChangeOrdersPanel c={c} side={side} busy={busy}
        onPropose={(body) => act(() => contractApi.proposeChange(c.id, body), 'Change order proposed. The other party must review it.')}
        onApprove={(changeId) => {
          setError(null); setNotice(null)
          run(async () => {
            setBusy(true)
            try {
              setC(await contractApi.approveChange(changeId))
              setNotice('Change order approved. Material changes now need both parties to sign the new contract version.')
            } finally { setBusy(false) }
          })
        }}
        onReject={(changeId, reason) => {
          setError(null); setNotice(null)
          run(async () => {
            setBusy(true)
            try { setC(await contractApi.rejectChange(changeId, reason)); setNotice('Change order rejected.') }
            finally { setBusy(false) }
          })
        }} />}
      {tab === 'milestones' && (
        <>
          {c.status === 'PENDING_SIGNATURE' && <p className="muted">Milestones start after both parties sign and each milestone is funded.</p>}
          {(c.engagementType === 'RETAINER' || c.pricingModel === 'RETAINER') && <RetainerCycles c={c} side={side} busy={busy}
            onCancel={(reason) => act(() => contractApi.cancelRemainingCycles(c.id, reason), 'Remaining unfunded cycles cancelled.').then(refreshSoon)}
            onPause={(reason) => act(() => contractApi.pause(c.id, reason), 'Retainer paused. No new cycles are funded until you resume.')}
            onResume={() => act(() => contractApi.resume(c.id), 'Retainer resumed.')} />}
          {c.milestones.map((m) => <MilestoneCard key={m.id} m={m} c={c} side={side} busy={busy}
            canFund={!!escrow?.canFund && escrow.allocations.some((x) => x.milestoneId === m.id && x.state === 'UNFUNDED') && !blockedReason('ESCROW_FUND', m.id)}
            acceptBlocked={blockedReason('MILESTONE_ACCEPT', m.id)}
            funding={escrow?.allocations.find((x) => x.milestoneId === m.id)?.state === 'FUNDING'}
            paymentStuck={paymentStuck(c, escrow).has(m.id) && escrow?.allocations.find((x) => x.milestoneId === m.id)?.state === 'RELEASE_PENDING_APPROVAL'}
            onFund={() => setFundFor([m.id])}
            onSent={(k) => { setC(k); setError(null); setNotice('Work sent to the buyer for review.') }}
            onReview={(verdicts) => {
              const accepting = verdicts.every((v) => v.verdict === 'MET')
              act(() => contractApi.review(m.id, verdicts), accepting ? 'Milestone accepted. The funds are being released to the professional.'
                : 'Sent back to the professional with your comments.').then(() => { if (accepting) refreshSoon() })
            }}
            onOfferPartial={(amount, reason) => act(() => contractApi.offerPartial(m.id, amount, reason), 'Offer sent. The professional must agree before anything is released.')}
            onAnswerPartial={(agree) => act(() => contractApi.answerPartial(m.id, agree), agree ? 'Agreed. The agreed amount is being released and the rest refunded.' : 'Offer declined.').then(refreshSoon)} />)}
        </>
      )}

      {side === 'buyer' && ['overview', 'milestones', 'payments'].includes(tab) && <PolicyStatePanel state={policy} />}
      {tab === 'payments' && <PaymentsPanel c={c} escrow={escrow} side={side} onFund={(ids) => setFundFor(ids)}
        fundBlocked={blockedReason('ESCROW_FUND')} />}

      {tab === 'tasks' && <TasksPanel c={c} side={side} onError={setError} />}
      {tab === 'messages' && <MessagesPreview c={c} />}
      {tab === 'files' && <FilesPanel c={c} onError={setError} />}
      {tab === 'activity' && <ActivityPanel c={c} onError={setError} />}
    </>
  )
}

function ChangeOrdersPanel({ c, side, busy, onPropose, onApprove, onReject }: {
  c: Contract; side: Side; busy: boolean
  onPropose: (body: { type: ChangeOrder['type']; delta: Record<string, unknown>; impact: string }) => Promise<void>
  onApprove: (changeId: string) => void; onReject: (changeId: string, reason: string) => void
}) {
  const [type, setType] = useState<ChangeOrder['type']>('ADD_DELIVERABLE')
  const [milestoneId, setMilestoneId] = useState(c.milestones.find((m) => m.status === 'PENDING_FUNDING')?.id ?? '')
  const [deliverableKey, setDeliverableKey] = useState(c.terms.deliverables[0]?.key ?? '')
  const [title, setTitle] = useState('')
  const [description, setDescription] = useState('')
  const [criteria, setCriteria] = useState('')
  const [endDate, setEndDate] = useState(c.terms.endDate ?? '')
  const [newAmount, setNewAmount] = useState('')
  const [impact, setImpact] = useState('')
  const [rejectReason, setRejectReason] = useState('')
  const [formError, setFormError] = useState<string | null>(null)
  const pendingMilestones = c.milestones.filter((m) => m.status === 'PENDING_FUNDING')
  const party = side === 'buyer' ? 'BUYER' : 'PROFESSIONAL'
  const editableDeliverables = c.terms.deliverables.filter((d) =>
    c.milestones.some((m) => m.status === 'PENDING_FUNDING' && m.deliverableKeys.includes(d.key)))
  const delta = (): Record<string, unknown> => {
    if (type === 'ADD_DELIVERABLE') return {
      milestoneId,
      deliverable: { key: `co-${Date.now()}`, title: title.trim(), description: description.trim(), acceptanceCriteria: criteria.trim() },
    }
    if (type === 'MODIFY_DELIVERABLE') return {
      key: deliverableKey,
      changes: { ...(title.trim() ? { title: title.trim() } : {}), ...(description.trim() ? { description: description.trim() } : {}),
        ...(criteria.trim() ? { acceptanceCriteria: criteria.trim() } : {}) },
    }
    if (type === 'EXTEND_TIMELINE') return { endDate }
    const milestone = c.milestones.find((m) => m.id === milestoneId)
    const [whole = '0', fraction = ''] = newAmount.split('.')
    const amountMinor = Number(whole) * 100 + Number((fraction + '00').slice(0, 2))
    return { totalDeltaMinor: amountMinor - (milestone?.amount.amountMinor ?? 0), milestoneAmounts: [{ milestoneId, amountMinor }] }
  }
  const submit = async () => {
    const value = delta()
    if (type === 'ADD_DELIVERABLE' && (!milestoneId || !title.trim() || !criteria.trim())) return setFormError('Choose a milestone and provide a title and acceptance criteria.')
    if (type === 'MODIFY_DELIVERABLE' && (!deliverableKey || !Object.keys(value.changes as object).length)) return setFormError('Choose a deliverable and enter at least one updated field.')
    if (type === 'EXTEND_TIMELINE' && !/^\d{4}-\d{2}-\d{2}$/.test(endDate)) return setFormError('Enter the new contract end date.')
    if (type === 'PRICING_CHANGE' && (!milestoneId || !/^\d+(\.\d{1,2})?$/.test(newAmount) ||
      Number(newAmount) <= 0 || value.totalDeltaMinor === 0)) return setFormError('Choose an unfunded milestone and enter a different positive amount with at most two decimals.')
    if (impact.trim().length < 5) return setFormError('Describe the expected impact (at least 5 characters).')
    setFormError(null)
    await onPropose({ type, delta: value, impact: impact.trim() })
  }
  const draftPreview = (): { label: string; before: string; after: string }[] => {
    if (type === 'ADD_DELIVERABLE') {
      const milestone = c.milestones.find((m) => m.id === milestoneId)
      return [{ label: `M${milestone?.sequence ?? '—'} deliverables`, before: 'No such deliverable',
        after: `${title.trim() || 'New deliverable'} — ${criteria.trim() || 'Acceptance criteria not entered'}` }]
    }
    if (type === 'MODIFY_DELIVERABLE') {
      const deliverable = c.terms.deliverables.find((d) => d.key === deliverableKey)
      return [
        ...(title.trim() ? [{ label: 'Title', before: deliverable?.title ?? '—', after: title.trim() }] : []),
        ...(description.trim() ? [{ label: 'Description', before: deliverable?.description || '—', after: description.trim() }] : []),
        ...(criteria.trim() ? [{ label: 'Acceptance criteria', before: deliverable?.acceptanceCriteria ?? '—', after: criteria.trim() }] : []),
      ]
    }
    if (type === 'EXTEND_TIMELINE') {
      return [{ label: 'Contract end date', before: c.terms.endDate ?? 'Not set', after: endDate || 'Enter a date' }]
    }
    const milestone = c.milestones.find((m) => m.id === milestoneId)
    const parsedAmount = /^\d+(\.\d{1,2})?$/.test(newAmount) ? Math.round(Number(newAmount) * 100) : null
    const newTotal = parsedAmount !== null && milestone
      ? c.total.amountMinor + parsedAmount - milestone.amount.amountMinor
      : null
    return [
      { label: 'Contract total', before: formatMoney(c.total),
        after: newTotal !== null ? formatMoney({ amountMinor: newTotal, currency: c.total.currency }) : 'Enter a new amount' },
      { label: `M${milestone?.sequence ?? '—'} · ${milestone?.title ?? 'Milestone'}`,
        before: milestone ? formatMoney(milestone.amount) : '—',
        after: parsedAmount !== null ? formatMoney({ amountMinor: parsedAmount, currency: c.total.currency }) : 'Enter a new amount' },
    ]
  }
  return (
    <section className="card panel">
      <div className="panel-head"><h2>Change orders</h2><span className="muted small">Contract version {c.contractVersion}</span></div>
      <p className="muted">Changes are recorded against the signed agreement. The other party must approve or reject each proposal.
        Scope and price changes take effect only after both parties sign the new version; timeline changes apply after approval.</p>
      {((c.status === 'ACTIVE' && !c.pendingChangeOrderId) || (c.status === 'PENDING_SIGNATURE' && !c.activatedAt)) && <div className="revise-box">
        {c.status === 'PENDING_SIGNATURE' && <p className="muted small" style={{ marginTop: 0 }}>Not signed yet: an agreed change produces a new
          version that both sides then sign.</p>}
        <label className="filter-box"><span>Change type</span><select value={type} onChange={(e) => setType(e.target.value as ChangeOrder['type'])}>
          <option value="ADD_DELIVERABLE">Add deliverable</option><option value="MODIFY_DELIVERABLE">Modify deliverable</option>
          <option value="EXTEND_TIMELINE">Extend timeline</option><option value="PRICING_CHANGE">Change pricing</option>
        </select></label>
        {(type === 'ADD_DELIVERABLE' || type === 'PRICING_CHANGE') && <label className="filter-box"><span>Unfunded milestone</span>
          <select value={milestoneId} onChange={(e) => setMilestoneId(e.target.value)}>
            <option value="">Select milestone</option>{pendingMilestones.map((m) => <option key={m.id} value={m.id}>M{m.sequence} · {m.title}</option>)}
          </select></label>}
        {type === 'ADD_DELIVERABLE' && <>
          <label className="filter-box"><span>Deliverable title</span><input className="input" value={title} onChange={(e) => setTitle(e.target.value)} maxLength={200} /></label>
          <label className="filter-box"><span>Description</span><input className="input" value={description} onChange={(e) => setDescription(e.target.value)} maxLength={1000} /></label>
          <label className="filter-box"><span>Acceptance criteria</span><textarea rows={2} value={criteria} onChange={(e) => setCriteria(e.target.value)} maxLength={1000} /></label>
        </>}
        {type === 'MODIFY_DELIVERABLE' && <>
          <label className="filter-box"><span>Deliverable</span><select value={deliverableKey} onChange={(e) => setDeliverableKey(e.target.value)}>
            {editableDeliverables.map((d) => <option key={d.key} value={d.key}>{d.title}</option>)}</select></label>
          <label className="filter-box"><span>New title (optional)</span><input className="input" value={title} onChange={(e) => setTitle(e.target.value)} maxLength={200} /></label>
          <label className="filter-box"><span>New description (optional)</span><input className="input" value={description} onChange={(e) => setDescription(e.target.value)} maxLength={1000} /></label>
          <label className="filter-box"><span>New acceptance criteria (optional)</span><textarea rows={2} value={criteria} onChange={(e) => setCriteria(e.target.value)} maxLength={1000} /></label>
        </>}
        {type === 'EXTEND_TIMELINE' && <label className="filter-box"><span>New contract end date</span>
          <input className="input" type="date" value={endDate} onChange={(e) => setEndDate(e.target.value)} /></label>}
        {type === 'PRICING_CHANGE' && <>
          <label className="filter-box"><span>New milestone amount ({c.total.currency})</span>
            <input className="input" type="number" min="0.01" step="0.01" value={newAmount} onChange={(e) => setNewAmount(e.target.value)} />
          </label>
          {c.milestones.find((m) => m.id === milestoneId) &&
            <span className="muted small">Current amount: {formatMoney(c.milestones.find((m) => m.id === milestoneId)!.amount)}</span>}
        </>}
        <div className="tip" aria-live="polite">
          <Icon name="contract" /><span><strong>Before and after preview</strong>
            <ul className="change-preview">{draftPreview().map((item) => <li key={item.label}>
              <span>{item.label}</span><span>{item.before}</span><span aria-hidden="true">→</span><strong>{item.after}</strong>
            </li>)}</ul>
          </span>
        </div>
        <label className="filter-box"><span>Expected impact</span><textarea rows={2} maxLength={1000} value={impact} onChange={(e) => setImpact(e.target.value)}
          placeholder="Explain the effect on scope, price, or delivery." /></label>
        {formError && <p className="error-text" role="alert">{formError}</p>}
        <button className="btn btn-primary" disabled={busy} onClick={() => { void submit() }}>Propose change</button>
      </div>}
      {c.changeOrders.length === 0 ? <p className="muted">No change orders yet.</p> : <ul className="activity">
        {[...c.changeOrders].reverse().map((change) => {
          const canDecide = change.status === 'PROPOSED' && change.proposerParty !== party && c.status === 'ACTIVE'
          return <li key={change.id} style={{ alignItems: 'flex-start' }}><span className="dot" />
            <div style={{ flex: 1 }}><strong>{change.type.replaceAll('_', ' ')}</strong> · <span className={`badge ${change.status === 'APPROVED' ? 'green' : change.status === 'PROPOSED' ? 'warn' : ''}`}>{change.status}</span>
              <p style={{ margin: '4px 0' }}>{change.impact}</p><details><summary className="small">Change details</summary><pre className="agreement">{JSON.stringify(change.delta, null, 2)}</pre></details>
              {change.preview.length > 0 && <div className="change-preview-saved"><strong>Before and after</strong>
                <ul className="change-preview">{change.preview.map((item) => <li key={item.label}>
                  <span>{item.label}</span><span>{item.before}</span><span aria-hidden="true">→</span><strong>{item.after}</strong>
                </li>)}</ul>
              </div>}
              <span className="muted small">Proposed by {change.proposerParty === 'BUYER' ? 'buyer' : 'professional'} · base version {change.baseContractVersion}
                {change.appliedVersion ? ` · applied as version ${change.appliedVersion}` : ''}</span>
              {change.decisionReason && <p className="small">Decision note: {change.decisionReason}</p>}
              {canDecide && <div className="row card-actions">
                <button className="btn btn-primary btn-sm" disabled={busy} onClick={() => onApprove(change.id)}>Approve</button>
                <input className="input" style={{ maxWidth: 280 }} placeholder="Optional rejection reason" maxLength={1000} value={rejectReason}
                  onChange={(e) => setRejectReason(e.target.value)} />
                <button className="btn btn-secondary btn-sm" disabled={busy} onClick={() => onReject(change.id, rejectReason)}>Reject</button>
              </div>}
            </div><span className="muted small">{new Date(change.createdAt).toLocaleDateString()}</span>
          </li>
        })}
      </ul>}
      <div className="version-history">
        <h3>Contract version history</h3>
        {[...c.revisions].reverse().map((revision) => {
          const signedParties = new Set(c.signatures.filter((signature) => signature.contractVersion === revision.contractVersion).map((signature) => signature.party))
          const pendingSignature = revision.contractVersion === c.contractVersion && c.status === 'PENDING_SIGNATURE'
          const amendment = revision.changeOrderId
            ? c.changeOrders.find((change) => change.id === revision.changeOrderId)
            : undefined
          return <details key={revision.contractVersion} className="version-record">
            <summary><strong>Version {revision.contractVersion}</strong> · {formatMoney(revision.total)}
              {revision.contractVersion === c.contractVersion && <span className={`badge ${pendingSignature ? 'warn' : 'green'}`}>
                {pendingSignature ? 'Awaiting signatures' : 'Current'}
              </span>}
              <span className="muted small">{new Date(revision.createdAt).toLocaleString()}</span>
            </summary>
            {amendment?.type === 'EXTEND_TIMELINE' && amendment.appliedVersion === revision.contractVersion
              ? <p className="muted small">Timeline amendment approved by both parties; re-signing was not required.</p>
              : <p className="muted small">Signatures for this version: {(['BUYER', 'PROFESSIONAL'] as const)
                .map((partyName) => `${partyName === 'BUYER' ? 'Buyer' : 'Professional'} ${signedParties.has(partyName) ? 'signed' : 'not signed'}`)
                .join(' · ')}</p>}
            <h4>Deliverables</h4>
            <ul className="why">{revision.terms.deliverables.map((deliverable) => <li key={deliverable.key}>
              <strong>{deliverable.title}</strong> — {deliverable.acceptanceCriteria}
            </li>)}</ul>
            <h4>Milestones and pricing</h4>
            <ul className="why">{revision.milestones.map((milestone) => <li key={milestone.id}>
              M{milestone.sequence} · {milestone.title} · {formatMoney({ amountMinor: milestone.amountMinor, currency: milestone.currency })}
              {milestone.dueDate ? ` · due ${fmtDate(milestone.dueDate)}` : ''}
            </li>)}</ul>
            <p className="muted small">Terms SHA-256: <code>{revision.termsHash}</code><br />
              Agreement SHA-256: <code>{revision.documentSha256}</code></p>
          </details>
        })}
      </div>
      {c.status === 'PENDING_SIGNATURE' && c.pendingChangeOrderId && <p className="tip"><Icon name="contract" /><span>Approved material change: review and sign the updated agreement in the Agreement tab.</span></p>}
      <p className="muted small">Approving or rejecting requires a fresh two-step confirmation.</p>
    </section>
  )
}

/** Retainer cycles as a calendar strip (Payments & Escrow s.15): funding and acceptance per cycle, cancel future cycles. */
/** Ending the engagement: at once while nothing is in escrow, otherwise by asking the other side to agree. */
function EndEngagement({ c, busy, onEnd }: { c: Contract; busy: boolean; onEnd: (reason: string, mutual: boolean) => void }) {
  const [open, setOpen] = useState(false)
  const [reason, setReason] = useState('')
  const mutual = !c.canEndNow
  return (
    <SidePanel title="End the engagement">
      {!open ? <>
        <p className="muted small" style={{ marginTop: 0 }}>{mutual
          ? 'Money is held in escrow, so ending needs the other side to agree. Accepted work is still paid; money held for other work goes back to the buyer.'
          : 'Nothing is held in escrow, so you can end it now. Both sides are told.'}</p>
        <button className="btn btn-ghost btn-sm" onClick={() => setOpen(true)}>{mutual ? 'Ask to end the engagement' : 'End the engagement'}</button>
      </> : <form onSubmit={(e) => { e.preventDefault(); onEnd(reason.trim(), mutual) }}>
        <label className="label" htmlFor="end-reason">Why? (both sides see this)</label>
        <textarea id="end-reason" className="input" rows={3} maxLength={1000} value={reason} onChange={(e) => setReason(e.target.value)} required />
        <p className="muted small">{mutual ? 'The other side gets a set time to answer (shown once sent). A dispute is the route if you disagree about the work itself.'
          : 'This cannot be undone. You will be asked to confirm with your authenticator app or a passkey.'}</p>
        <div className="row">
          <button className="btn btn-danger btn-sm" disabled={busy || reason.trim().length < 5}>{mutual ? 'Send request' : 'End now'}</button>
          <button type="button" className="btn btn-ghost btn-sm" onClick={() => { setOpen(false); setReason('') }}>Cancel</button>
        </div>
      </form>}
    </SidePanel>
  )
}

function TerminationBanner({ c, busy, onAnswer, onWithdraw }: {
  c: Contract; busy: boolean; onAnswer: (agree: boolean, note?: string) => void; onWithdraw: () => void
}) {
  const t = c.terminationRequest!
  const [note, setNote] = useState('')
  const who = t.requesterParty === 'BUYER' ? 'The buyer' : 'The professional'
  return (
    <div className="attention-banner neutral" role="status">
      <span className="kpi-icon amber"><Icon name="help" /></span>
      <div style={{ flex: 1 }}><strong>{t.canWithdraw ? 'You asked to end this engagement' : `${who} asked to end this engagement`}</strong>
        <div className="small">“{t.reason}” · answer by {fmtDate(t.expiresAt)}. If agreed, accepted work is still paid and money held for other work goes back to the buyer.</div>
        {t.canAnswer && <input className="input" style={{ marginTop: 8 }} aria-label="Note for the other side (optional)" placeholder="Note for the other side (optional)"
          maxLength={1000} value={note} onChange={(e) => setNote(e.target.value)} />}</div>
      {t.canAnswer && <span className="row" style={{ flexWrap: 'nowrap' }}>
        <button className="btn btn-danger" disabled={busy} onClick={() => onAnswer(true, note)}>Agree to end</button>
        <button className="btn btn-secondary" disabled={busy} onClick={() => onAnswer(false, note)}>Decline</button></span>}
      {t.canWithdraw && <button className="btn btn-secondary" disabled={busy} onClick={onWithdraw}>Withdraw request</button>}
    </div>
  )
}

function RetainerCycles({ c, side, busy, onCancel, onPause, onResume }: { c: Contract; side: Side; busy: boolean; onCancel: (reason: string) => void
  onPause: (reason?: string) => void; onResume: () => void }) {
  const future = c.milestones.filter((m) => m.status === 'PENDING_FUNDING').length
  return (
    <section className="card panel">
      <div className="panel-head"><h2>Retainer cycles</h2>
        {side === 'buyer' && c.status === 'ACTIVE' && future > 0 && <button className="btn btn-ghost btn-sm" disabled={busy} onClick={() => {
          const reason = prompt(`Cancel the ${future} cycle(s) not funded yet? Funded cycles continue. Reason:`)
          if (reason && reason.trim().length >= 5) onCancel(reason.trim())
        }}>Cancel remaining cycles</button>}
        {side === 'buyer' && c.status === 'ACTIVE' && (c.pausedAt
          ? <button className="btn btn-secondary btn-sm" disabled={busy} onClick={onResume}>Resume</button>
          : <button className="btn btn-ghost btn-sm" disabled={busy} onClick={() => onPause(prompt('Why pause? (optional, the professional sees it)') ?? undefined)}>Pause</button>)}</div>
      {c.pausedAt && <div className="tip" style={{ marginBottom: 8 }}><Icon name="clock" /><span>Paused since {new Date(c.pausedAt).toLocaleDateString()}
        {c.pauseReason ? `: ${c.pauseReason}` : ''}. Funded cycles continue; nothing new is funded or reminded until it resumes.</span></div>}
      <ol className="cycle-strip">{c.milestones.map((m) => (
        <li key={m.id} className={`cycle ${m.status.toLowerCase()}`}>
          <strong>{m.dueDate ? new Date(`${m.dueDate}T00:00:00`).toLocaleDateString(undefined, { month: 'short', year: 'numeric' }) : `Cycle ${m.sequence}`}</strong>
          <span className="small">{formatMoney(m.amount)}</span>
          <span className={`badge ${MILESTONE_STATUS[m.status].tone}`}>{MILESTONE_STATUS[m.status].label}</span>
        </li>))}</ol>
      <p className="muted small" style={{ margin: 0 }}>Each cycle is funded and accepted on its own. You get a reminder before an unfunded cycle is due;
        not funding the next cycle pauses the work. Automatic funding needs a saved payment method from the live payment provider.</p>
    </section>
  )
}

function MilestoneCard({ m, c, side, busy, canFund, funding, onFund, onSent, onReview, onOfferPartial, onAnswerPartial, acceptBlocked, paymentStuck }: {
  acceptBlocked?: string; paymentStuck?: boolean
  m: ContractMilestone; c: Contract; side: Side; busy: boolean; canFund: boolean; funding: boolean; onFund: () => void
  onSent: (c: Contract) => void; onReview: (verdicts: { deliverableKey: string; verdict: Verdict; comment: string }[]) => void
  onOfferPartial: (amountMinor: number, reason: string) => void; onAnswerPartial: (agree: boolean) => void
}) {
  const [partial, setPartial] = useState(false)
  const [partialAmount, setPartialAmount] = useState('')
  const [partialReason, setPartialReason] = useState('')
  const partialMinor = Math.round(Number(partialAmount || 0) * 100)
  const st = MILESTONE_STATUS[m.status]
  const [latest, ...earlier] = m.submissions
  const delivers = m.deliverableKeys.map((k) => c.terms.deliverables.find((d) => d.key === k)?.title ?? k)
  const canDeliver = side === 'professional' && c.status === 'ACTIVE' && ['IN_PROGRESS', 'REVISION_REQUESTED'].includes(m.status)
  const canReview = side === 'buyer' && c.status === 'ACTIVE' && m.status === 'SUBMITTED'

  return (
    <section className={`card panel milestone-card ${m.status === 'ACCEPTED' ? 'done' : ''}`}>
      <div className="panel-head">
        <h2>M{m.sequence} · {m.title}</h2>
        <span><strong>{formatMoney(m.amount)}</strong> <span className={`badge ${st.tone}`}>{st.label}</span></span>
      </div>
      <p className="muted small" style={{ margin: 0 }}>Delivers: {delivers.join(', ') || '—'} · Due {fmtDate(m.dueDate)}
        {m.acceptanceDueAt && m.status === 'SUBMITTED' && ` · Review by ${fmtDate(m.acceptanceDueAt)}`}</p>
      {m.reviewOverdue && <div className="alert alert-warn" style={{ marginTop: 10 }}>{side === 'buyer'
        ? 'The review window has passed. Please accept the work or request a revision. The payment stays in escrow until you decide.'
        : 'The buyer has not reviewed this yet and the review window has passed. They have been reminded; your payment stays protected in escrow.'}</div>}
      {m.status === 'PENDING_FUNDING' && <div className="row card-actions" style={{ justifyContent: 'space-between' }}>
        <span className="small">{funding ? 'Payment processing…' : side === 'buyer' ? 'Fund this milestone to let work start. The money is held in escrow until you accept the work.'
          : 'Waiting for the buyer to fund this milestone. Do not start work before it is funded.'}</span>
        {canFund && !funding && <button className="btn btn-primary" onClick={onFund}><Icon name="lock" /> Fund M{m.sequence}</button>}
      </div>}
      {m.status === 'IN_PROGRESS' && side === 'professional' && <p className="ok-text small" style={{ margin: '8px 0 0' }}>✓ Funds secured in escrow — you can start work.</p>}
      {m.status === 'REVISION_REQUESTED' && m.lastRevisionReason && <div className="tip" style={{ marginTop: 10 }}><Icon name="message" /><span><strong>Revision requested:</strong> {m.lastRevisionReason}</span></div>}

      {latest && !canReview && <SubmissionView s={latest} c={c} />}
      {earlier.length > 0 && <details className="earlier-deliveries"><summary className="small">{earlier.length} earlier deliver{earlier.length > 1 ? 'ies' : 'y'}</summary>
        {earlier.map((s) => <SubmissionView key={s.id} s={s} c={c} />)}</details>}

      {canDeliver && <DeliveryForm m={m} onSent={onSent} />}

      {m.status === 'ACCEPTED' && !paymentStuck && (() => { const end = releaseAfterWindow(c, m.id); return end && <div className="tip" style={{ marginTop: 10 }}>
        <Icon name="lock" /><span><strong>Payment is released on {end.toLocaleDateString()}.</strong>{' '}{side === 'buyer'
          ? 'Until then you can still raise a problem with this work; after that date it is paid out.'
          : 'The agreement gives the buyer this period to raise a problem after accepting; the money is held in escrow until then.'}</span></div> })()}
      {paymentStuck && <div className="tip" style={{ marginTop: 10 }}><Icon name="wallet" /><span><strong>Payment waiting for the buyer's approval.</strong>{' '}
        {side === 'buyer' ? 'Your organisation has not approved releasing this payment yet. Ask your approver again, or raise a payment-release dispute so a mediator decides.'
          : 'The work is accepted, but the buyer\'s organisation has not approved the payment yet. The money stays protected in escrow; if it is not released, raise a payment-release dispute.'}</span></div>}
      {m.acceptedRelease && <p className="small muted" style={{ margin: '8px 0 0' }}>Accepted for {formatMoney(m.acceptedRelease)} by agreement;
        {' '}{formatMoney({ amountMinor: m.amount.amountMinor - m.acceptedRelease.amountMinor, currency: m.amount.currency })} was refunded to the buyer.</p>}
      {m.partialOffer && m.status === 'SUBMITTED' && <div className="tip" style={{ marginTop: 10 }}><Icon name="wallet" /><span>
        <strong>Offer to accept for {formatMoney(m.partialOffer.amount)}</strong> ({formatMoney(m.partialOffer.refund)} back to the buyer): {m.partialOffer.reason}
        {side === 'buyer' ? <span className="muted"> Waiting for the professional to agree. Nothing moves until they do.</span> : <span className="row" style={{ marginTop: 8 }}>
          <button className="btn btn-primary btn-sm" disabled={busy} onClick={() => { if (confirm(`Agree to ${formatMoney(m.partialOffer!.amount)} for M${m.sequence}? That amount is released to you (minus the platform fee) and the rest is refunded. It cannot be undone.`)) onAnswerPartial(true) }}>Agree</button>
          <button className="btn btn-secondary btn-sm" disabled={busy} onClick={() => onAnswerPartial(false)}>Decline</button></span>}
      </span></div>}
      {canReview && partial && <div className="revise-box">
        <div className="row">
          <label className="filter-box"><span>Release ({m.amount.currency})</span>
            <input inputMode="decimal" value={partialAmount} onChange={(e) => setPartialAmount(e.target.value.replace(/[^0-9.]/g, ''))} placeholder={`less than ${m.amount.amountMinor / 100}`} /></label>
          <label className="filter-box grow"><span>Why, against the acceptance criteria?</span>
            <input value={partialReason} maxLength={1000} onChange={(e) => setPartialReason(e.target.value)} /></label>
        </div>
        <p className="muted small">The professional must agree. If they do, {formatMoney({ amountMinor: Math.min(partialMinor, m.amount.amountMinor), currency: m.amount.currency })} is released
          and {formatMoney({ amountMinor: Math.max(m.amount.amountMinor - partialMinor, 0), currency: m.amount.currency })} is refunded to you.</p>
        <div className="row"><button className="btn btn-primary btn-sm" disabled={busy || partialMinor <= 0 || partialMinor >= m.amount.amountMinor || partialReason.trim().length < 10}
          onClick={() => { onOfferPartial(partialMinor, partialReason.trim()); setPartial(false) }}>Send offer</button>
          <button className="btn btn-ghost btn-sm" onClick={() => setPartial(false)}>Cancel</button></div>
      </div>}
      {canReview && !partial && <ReviewPanel key={latest?.id} m={m} c={c} busy={busy} onDecide={onReview} onPartial={() => setPartial(true)} acceptBlocked={acceptBlocked} />}
    </section>
  )
}

/** One titled section of the agreement text (titles are lines in capitals), or the whole text when it has none. */
function section(doc: string | null, title: string): string | null {
  if (doc === null) return null
  const start = doc.indexOf(`\n${title}\n`)
  if (start < 0) return title === 'DATA HANDLING' ? 'This agreement predates the separate data handling section; see the full text.' : doc
  const rest = doc.slice(start + title.length + 2)
  const next = rest.search(/\n\n[A-Z][A-Z ()—-]{3,}\n/)
  return next < 0 ? rest : rest.slice(0, next)
}

function SuccessCriteriaView({ criteria }: { criteria: { definition: string | null; measures: string[] } }) {
  return <>{criteria.definition && <p className="small" style={{ margin: '0 0 4px' }}><strong>Done looks like:</strong> {criteria.definition}</p>}
    {criteria.measures.length > 0 && <ul className="why" style={{ margin: 0 }}>{criteria.measures.map((m) => <li key={m}>Measured by: {m}</li>)}</ul>}</>
}

/** Once the first funding is held (the engagement is active): what was agreed, the next milestone and its due date, and
    where to go next. Shown until the first milestone is accepted. */
function ActivationPanel({ c, side }: { c: Contract; side: Side }) {
  const next = [...c.milestones].sort((a, b) => a.sequence - b.sequence).find((m) => !['ACCEPTED', 'CANCELLED'].includes(m.status))
  return (
    <section className="card panel activation-panel">
      <div className="panel-head"><h2>Engagement active</h2><code>{c.reference}</code></div>
      <div className="row" style={{ alignItems: 'flex-start', gap: 24 }}>
        <dl className="facts" style={{ flex: 1 }}>
          {next && <><dt>Next milestone</dt><dd>M{next.sequence} {next.title} · <strong>{formatMoney(next.amount)}</strong>
            {' '}<span className={`badge ${MILESTONE_STATUS[next.status].tone}`}>{MILESTONE_STATUS[next.status].label}</span></dd>
            <dt>Due</dt><dd>{next.dueDate ? fmtDate(next.dueDate) : 'No date set'}</dd></>}
          <dt>Payment protection</dt><dd>Funded milestones are held in escrow and released only when the buyer accepts the work.</dd>
          <dt>If something goes wrong</dt><dd>Raise a dispute: the milestone’s money stays frozen until it is resolved.</dd>
        </dl>
        <div style={{ minWidth: 220, display: 'grid', gap: 8 }}>
          {side === 'buyer' ? <>
            <Link className="btn btn-primary" to="/app/buyer">Go to buyer dashboard</Link>
            <Link className="btn btn-secondary" to="/app/find">Request additional proposals</Link>
          </> : <p className="small" style={{ margin: 0 }}><strong>Funds are secured.</strong> You can start work on the funded milestone.</p>}
          <Link className="btn btn-ghost btn-sm" to={`/app/messages?contextType=CONTRACT&contextId=${c.id}`}><Icon name="message" /> Messages</Link>
        </div>
      </div>
    </section>
  )
}

/** The latest messages of the engagement's conversation, with a link to the full thread. */
function MessagesPreview({ c }: { c: Contract }) {
  const [messages, setMessages] = useState<ConversationMessage[] | null>(null)
  const [threadId, setThreadId] = useState<string | null>(null)
  const load = useCallback(() => {
    messagingApi.open('CONTRACT', c.id).then(async (t) => { setThreadId(t.id); setMessages((await messagingApi.messages(t.id)).items.slice(-8)) })
      .catch(() => setMessages([]))
  }, [c.id])
  useEffect(() => { load() }, [load])
  return (
    <>
    <section className="card panel">
      <div className="panel-head"><h2>Messages</h2>
        <Link className="btn btn-secondary btn-sm" to={`/app/messages?contextType=CONTRACT&contextId=${c.id}`}><Icon name="message" /> Open conversation</Link></div>
      {messages === null ? <Loading /> : messages.length === 0 ? <p className="muted">No messages yet.{threadId ? '' : ''}</p> : (
        <ol className="support-thread">{messages.map((m) => <li key={m.id} className={m.senderIdentityId === null ? 'staff' : ''}>
          <strong>{m.senderIdentityId === null ? 'Zoikorum' : m.senderName}</strong> <span className="muted small">{new Date(m.sentAt).toLocaleString()}</span>
          {m.body && <p style={{ margin: '4px 0 0', whiteSpace: 'pre-wrap' }}>{m.body}</p>}
          {m.attachments.length > 0 && <p className="muted small" style={{ margin: '4px 0 0' }}>{m.attachments.length} file(s)</p>}</li>)}</ol>
      )}
      <p className="muted small" style={{ margin: 0 }}>Messages are part of the engagement record and cannot be edited or deleted.</p>
    </section>
    {threadId && <MeetingsPanel threadId={threadId} onChange={load} />}
    </>
  )
}

/** Every file of the engagement in one list: request, proposal, delivered work, messages, dispute evidence. */
/** Files with the same name and source are versions of one document: newest first, earlier versions on request. */
function fileVersions(files: EngagementFile[]): EngagementFile[][] {
  const groups = new Map<string, EngagementFile[]>()
  for (const f of files) {
    const key = `${f.source}::${f.name.toLowerCase()}`
    groups.set(key, [...(groups.get(key) ?? []), f])
  }
  const when = (f: EngagementFile) => (f.uploadedAt ? new Date(f.uploadedAt).getTime() : 0)
  return [...groups.values()].map((g) => [...g].sort((a, b) => when(b) - when(a)))
}

function FilesPanel({ c, onError }: { c: Contract; onError: (e: unknown) => void }) {
  const [files, setFiles] = useState<EngagementFile[] | null>(null)
  useEffect(() => { contractApi.files(c.id).then(setFiles).catch(onError) }, [c.id, onError])
  const groups = fileVersions(files ?? [])
  return (
    <section className="card panel">
      <div className="panel-head"><h2>Files</h2><span className="muted small">{groups.length} document(s) · {files?.length ?? 0} version(s)</span></div>
      <div className="tip" style={{ marginBottom: 12 }}><Icon name="lock" /><span><strong>Who can open these:</strong> members of the buyer organisation
        and the professional on this engagement. Zoikorum staff open them only to handle a dispute or a support request you raise. Every opening is
        recorded in the audit log, and each version keeps its fingerprint so a copy can be checked.</span></div>
      {files && files.length === 0 ? <p className="muted">No files yet.</p> : (
        <table className="data"><thead><tr><th>File</th><th>From</th><th>Added</th><th>Fingerprint (SHA-256)</th></tr></thead>
          <tbody>{groups.map(([latest, ...earlier]) => <tr key={latest.url}>
            <td><FileLink file={{ name: latest.name, hasFile: true }} url={latest.url} />
              <div className="muted small">{(latest.size / 1024).toFixed(0)} KB{earlier.length > 0 ? ` · version ${earlier.length + 1} (latest)` : ''}</div>
              {earlier.length > 0 && <details className="small"><summary>Version history ({earlier.length} earlier)</summary>
                <ol className="why" style={{ margin: '4px 0 0' }}>{earlier.map((f, i) => <li key={f.url}>
                  <FileLink file={{ name: `Version ${earlier.length - i}`, hasFile: true }} url={f.url} />
                  {' '}<span className="muted">{f.uploadedAt ? new Date(f.uploadedAt).toLocaleString() : '—'} · <code>{f.sha256.slice(0, 12)}…</code></span></li>)}</ol>
              </details>}</td>
            <td className="small">{latest.source}</td><td className="small">{latest.uploadedAt ? new Date(latest.uploadedAt).toLocaleString() : '—'}</td>
            <td><code className="small">{latest.sha256.slice(0, 16)}…</code></td></tr>)}</tbody></table>
      )}
    </section>
  )
}

/** The engagement's history from the tamper-evident audit trail, and the evidence pack to download. */
function ActivityPanel({ c, onError }: { c: Contract; onError: (e: unknown) => void }) {
  const [rows, setRows] = useState<ActivityEntry[] | null>(null)
  useEffect(() => { contractApi.activity(c.id).then(setRows).catch(onError) }, [c.id, onError])
  const download = (format: 'pdf' | 'json') => contractApi.evidencePack(c.id, format)
    .then((b) => saveBlob(`${c.reference}-evidence-pack.${format}`, b)).catch(onError)
  return (
    <section className="card panel">
      <div className="panel-head"><h2>Activity</h2>
        <span className="row" style={{ flexWrap: 'nowrap' }}>
          <button className="btn btn-secondary btn-sm" onClick={() => download('pdf')}><Icon name="download" /> Evidence pack (PDF)</button>
          <button className="btn btn-ghost btn-sm" onClick={() => download('json')}>JSON</button></span></div>
      {rows === null ? <Loading /> : (
        <ul className="activity">{rows.map((a, i) => <li key={a.hash + i}><span className="dot" /><span>{a.what}<span className="muted small"> · {a.by}</span></span>
          <span className="muted small" title={`Audit record hash ${a.hash}`}>{new Date(a.at).toLocaleString()}</span></li>)}</ul>
      )}
      <p className="muted small" style={{ margin: 0 }}>From the append-only, hash-chained audit trail. The evidence pack carries a fingerprint that is
        recorded with each download, so a copy can be checked later.</p>
    </section>
  )
}


const POLICY_BADGE: Record<string, [string, string]> = {
  ALLOW: ['green', 'Allowed'], REQUIRE_APPROVAL: ['', 'Needs approval'], REQUIRE_EXCEPTION: ['warn', 'Needs an exception'], BLOCK: ['warn', 'Blocked'],
}

/** What the agreed policy will decide for the next money actions on this engagement. */
function PolicyStatePanel({ state }: { state: PolicyState | null }) {
  if (!state || state.actions.length === 0) return null
  return (
    <section className="card panel">
      <div className="panel-head"><h2>Your policy on this engagement</h2><span className="badge">{state.policyVersion}</span></div>
      <ul className="checklist">{state.actions.map((a) => {
        const [tone, label] = POLICY_BADGE[a.decision] ?? ['', a.decision]
        return <li key={`${a.action}-${a.milestoneId}`}><span><strong>{a.label}</strong> · {a.milestone}
          {a.decision !== 'ALLOW' && a.reasons[0] && <><br /><span className="muted small">{a.reasons[0].message}</span></>}
          {a.decision === 'REQUIRE_EXCEPTION' && <><br /><Link className="small" to={`/app/policies?${new URLSearchParams({ tab: 'exceptions',
            subjectType: a.action === 'ESCROW_FUND' ? 'EscrowAccount' : 'Milestone', subjectId: a.milestoneId, action: a.action })}`}>Request an exception</Link></>}</span>
          <span className={`badge ${tone}`}>{label}</span></li>
      })}</ul>
      <p className="muted small">Checked against the policy version agreed for this engagement. Approvals are requested when you take the action.</p>
    </section>
  )
}
