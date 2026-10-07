import { useCallback, useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { CONTRACT_STATUS, contractApi, MILESTONE_STATUS, deliveredFileUrl, type Contract, type ContractMilestone } from '../api/contracts'
import { disputeApi, OPEN_PHASES, type Dispute } from '../api/disputes'
import { escrowApi, type Escrow } from '../api/escrow'
import { disputableMilestones, RaiseDisputeDialog } from './Disputes'
import { FundDialog, PaymentsPanel } from '../components/EscrowPanels'
import { formatMoney } from '../api/orgs'
import { LABEL } from '../api/professional'
import { DOC_ACCEPT, toUpload, type Upload } from '../api/files'
import { FileLinks } from '../components/FileLink'
import { useAuth } from '../auth/AuthContext'
import { Icon } from '../components/dashboard'
import { EmptyTable, PortalHeader, SidePanel, StatCard, Tabs } from '../components/portal'
import { ErrorAlert, useStepUp } from '../components/ui'
import { downloadFile } from '../lib/exports'

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
  const [tab, setTab] = useState<'all' | 'signing' | 'active' | 'completed'>('all')
  useEffect(() => { contractApi.list(side).then(setList).catch(setError) }, [side])
  const rows = list ?? []
  const of = (t: string) => rows.filter((c) => t === 'all' || (t === 'signing' ? c.status === 'PENDING_SIGNATURE' : t === 'active' ? c.status === 'ACTIVE' : c.status === 'COMPLETED'))
  const activeValue = rows.filter((c) => c.status === 'ACTIVE').reduce((s, c) => s + c.total.amountMinor, 0)
  const currency = rows.find((c) => c.status === 'ACTIVE')?.total.currency
  const other = (c: Contract) => c.parties.find((p) => p.role !== (side === 'buyer' ? 'BUYER' : 'PROFESSIONAL'))

  return (
    <>
      <PortalHeader eyebrow="Engagements" title={side === 'buyer' ? 'Your engagements' : 'Your engagements'}
        subtitle="Contracts, signatures and milestones for work you have agreed — every step on the record."
        actions={side === 'buyer' ? <Link className="btn btn-primary" to="/app/find"><Icon name="search" /> Find a Professional</Link> : undefined} />
      <ErrorAlert error={error} />
      <div className="stat-row four">
        <StatCard icon="contract" tone="amber" value={list ? of('signing').length : '…'} label="Awaiting signatures" sub="Sign to activate" />
        <StatCard icon="briefcase" tone="green" value={list ? of('active').length : '…'} label="Active" sub="In progress" />
        <StatCard icon="check" tone="blue" value={list ? of('completed').length : '…'} label="Completed" sub="All milestones accepted" />
        <StatCard icon="lock" tone="violet" value={list ? (currency ? formatMoney({ amountMinor: activeValue, currency }) : '—') : '…'} label="Active value" sub="Across active contracts" />
      </div>
      <section className="card panel">
        <Tabs tabs={[{ key: 'all', label: 'All', count: rows.length }, { key: 'signing', label: 'Awaiting signatures', count: of('signing').length },
          { key: 'active', label: 'Active', count: of('active').length }, { key: 'completed', label: 'Completed', count: of('completed').length }]}
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
                  <td><span className={`badge ${CONTRACT_STATUS[c.status].tone}`}>{CONTRACT_STATUS[c.status].label}</span></td>
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
  const [c, setC] = useState<Contract | null>(null)
  const [error, setError] = useState<unknown>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [tab, setTab] = useState<'overview' | 'agreement' | 'milestones' | 'payments' | 'activity'>('overview')
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

  if (!c) return error ? <ErrorAlert error={error} /> : <p className="muted">Loading…</p>
  const st = CONTRACT_STATUS[c.status]
  const signed = new Set(c.signatures.filter((s) => s.contractVersion === c.contractVersion).map((s) => s.party))
  const pr = progress(c)
  const act = async (fn: () => Promise<Contract>, msg: string) => {
    setBusy(true); setError(null); setNotice(null)
    try { setC(await fn()); setNotice(msg) } catch (err) { setError(err) } finally { setBusy(false) }
  }

  return (
    <>
      {modal}
      {raising && <RaiseDisputeDialog contract={c} onClose={() => setRaising(false)} />}
      <PortalHeader eyebrow={<Link to={base(side)}>← Engagements</Link>} title={c.title}
        subtitle={<><span className={`badge ${st.tone}`}>{st.label}</span> · {c.reference} · {formatMoney(c.total)} · version {c.contractVersion}</>}
        actions={(c.status === 'ACTIVE' || c.status === 'DISPUTED') && disputableMilestones(c).length > 0
          ? <button className="btn btn-ghost" onClick={() => setRaising(true)}><Icon name="help" /> Raise a dispute</button> : undefined} />
      {notice && <div className="alert alert-success" role="status">{notice}</div>}
      <ErrorAlert error={error} />
      {disputes.filter((x) => OPEN_PHASES.includes(x.status)).map((x) => (
        <div key={x.id} className="attention-banner neutral"><span className="kpi-icon amber"><Icon name="lock" /></span>
          <div><strong>Dispute {x.reference} is open: {formatMoney(x.disputed)} frozen</strong>
            <div className="small">{x.nextStep}</div></div>
          <Link className="btn btn-secondary" to={`/app/disputes/${x.id}`}>Open dispute</Link></div>))}

      <div className={`attention-banner ${c.status === 'ACTIVE' || c.status === 'COMPLETED' ? 'ok' : ''}`}>
        <span className={`kpi-icon ${c.canSign ? 'amber' : 'green'}`}><Icon name={c.canSign ? 'contract' : 'check'} /></span>
        <div><strong>{c.nextAction}</strong>
          {c.status === 'PENDING_SIGNATURE' && <div className="muted small">Sign by {fmtDate(c.signatureDeadline)}. The buyer signs first; the professional countersigns.</div>}
          {c.status === 'ACTIVE' && <div className="muted small">Activated {fmtDate(c.activatedAt)} · {pr.done} of {pr.total} milestones accepted</div>}</div>
        {c.canSign && <button className="btn btn-primary" onClick={() => setTab('agreement')}>Review &amp; sign</button>}
      </div>

      <Tabs tabs={[{ key: 'overview', label: 'Overview' }, { key: 'agreement', label: 'Agreement' }, { key: 'milestones', label: 'Milestones', count: c.milestones.length },
        { key: 'payments', label: 'Payments' }, { key: 'activity', label: 'Activity' }]} value={tab} onChange={setTab} />

      {tab === 'overview' && (
        <div className="home-grid wide">
          <div>
            <section className="card panel">
              <div className="panel-head"><h2>Key terms</h2></div>
              <dl className="facts">
                <dt>Objective</dt><dd>{c.terms.objective}</dd>
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
            <SidePanel title="What's protected">
              <ul className="assurance compact">{['Signed contract with locked terms', 'Escrow for every milestone (next release)',
                'Release only after acceptance', 'Dispute route with funds held', 'Audit-grade record'].map((t) => <li key={t}><Icon name="check" /><span>{t}</span></li>)}</ul>
            </SidePanel>
          </aside>
        </div>
      )}

      {tab === 'agreement' && (
        <div className="home-grid wide">
          <section className="card panel">
            <div className="panel-head"><h2>Agreement summary</h2><span className="muted small">Terms ref {c.termsHash.slice(0, 12)}…</span></div>
            <h3>Deliverables &amp; acceptance criteria</h3>
            <ul className="why">{c.terms.deliverables.map((d) => <li key={d.key}><strong>{d.title}:</strong> {d.acceptanceCriteria}</li>)}</ul>
            <h3>Payment schedule</h3>
            <table className="data"><thead><tr><th>#</th><th>Milestone</th><th>Due</th><th>Amount</th></tr></thead>
              <tbody>{c.milestones.map((m) => <tr key={m.id}><td>M{m.sequence}</td><td>{m.title}</td><td className="small">{fmtDate(m.dueDate)}</td><td>{formatMoney(m.amount)}</td></tr>)}</tbody></table>
            {(c.terms.assumptions.length > 0 || c.terms.exclusions.length > 0) && <div className="row" style={{ alignItems: 'flex-start', marginTop: 12 }}>
              {c.terms.assumptions.length > 0 && <div style={{ flex: 1 }}><h3>Assumptions</h3><ul className="why">{c.terms.assumptions.map((a) => <li key={a}>{a}</li>)}</ul></div>}
              {c.terms.exclusions.length > 0 && <div style={{ flex: 1 }}><h3>Exclusions</h3><ul className="why">{c.terms.exclusions.map((a) => <li key={a}>{a}</li>)}</ul></div>}
            </div>}
            <ul className="why"><li>Changes to scope, price or timeline need a change order accepted by both sides.</li>
              <li>Disputes go through Zoikorum's dispute process; funds for the milestone are held meanwhile.</li></ul>
            <details className="doc-full"><summary>Full agreement text (standard terms)</summary>
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
              {c.canSign && (user?.mfaEnabled ? <>
                <label className="checkbox" style={{ marginTop: 12 }}><input type="checkbox" checked={read} onChange={(e) => setRead(e.target.checked)} />
                  <span>I have read the agreement and agree to its terms (version {c.contractVersion}).</span></label>
                <button className="btn btn-primary btn-lg" style={{ width: '100%', marginTop: 10 }} disabled={!read || busy}
                  onClick={() => { setError(null); setNotice(null); run(async () => {
                    // Errors propagate so the step-up dialog can ask for a code and retry.
                    setC(await contractApi.sign(c.id, c.termsHash))
                    setNotice(side === 'buyer' ? 'Signed. The professional will be asked to countersign.' : 'Countersigned. The engagement is now active.')
                  }) }}>
                  {side === 'buyer' ? 'Sign contract' : 'Countersign contract'}</button>
                <p className="muted small" style={{ margin: '8px 0 0' }}>You'll be asked for a code from your authenticator app.</p>
              </> : <div className="tip" style={{ marginTop: 12 }}><Icon name="lock" /><span>Signing needs two-step verification.
                {' '}<Link to="/app/security">Turn it on</Link>, then come back to sign.</span></div>)}
            </section>
          </aside>
        </div>
      )}

      {fundFor && escrow && <FundDialog escrow={escrow} preselect={fundFor} onClose={() => setFundFor(null)}
        onFunded={(e) => { setEscrow(e); setFundFor(null); setNotice('Payment submitted. The funds are held in escrow as soon as the payment is captured.'); refreshSoon() }} />}
      {tab === 'milestones' && (
        <>
          {c.status === 'PENDING_SIGNATURE' && <p className="muted">Milestones start after both parties sign and each milestone is funded.</p>}
          {c.milestones.map((m) => <MilestoneCard key={m.id} m={m} c={c} side={side} busy={busy}
            canFund={!!escrow?.canFund && escrow.allocations.some((x) => x.milestoneId === m.id && x.state === 'UNFUNDED')}
            funding={escrow?.allocations.find((x) => x.milestoneId === m.id)?.state === 'FUNDING'}
            onFund={() => setFundFor([m.id])}
            onSubmit={(note, files) => act(() => contractApi.submit(m.id, note, files), 'Work submitted for review.')}
            onAccept={() => { if (confirm(`Accept M${m.sequence} "${m.title}"? This releases ${formatMoney(m.amount)} from escrow to the professional (minus the platform fee). It cannot be undone.`)) act(() => contractApi.accept(m.id), 'Milestone accepted. The funds are being released to the professional.').then(refreshSoon) }}
            onRevise={(reason) => act(() => contractApi.requestRevision(m.id, reason), 'Revision requested.')} />)}
        </>
      )}

      {tab === 'payments' && <PaymentsPanel c={c} escrow={escrow} side={side} onFund={(ids) => setFundFor(ids)} />}

      {tab === 'activity' && (
        <section className="card panel"><div className="panel-head"><h2>Activity</h2></div>
          <ul className="activity">
            <li><span className="dot" /><span>Contract generated from the accepted proposal ({c.reference})</span><span className="muted small">{new Date(c.createdAt).toLocaleString()}</span></li>
            {c.signatures.map((s) => <li key={s.party + s.signedAt}><span className="dot" /><span>{s.party === 'BUYER' ? 'Buyer' : 'Professional'} signed: {s.signerName} (two-step confirmed)</span>
              <span className="muted small">{new Date(s.signedAt).toLocaleString()}</span></li>)}
            {c.activatedAt && <li><span className="dot" /><span>Engagement activated</span><span className="muted small">{new Date(c.activatedAt).toLocaleString()}</span></li>}
            {c.milestones.flatMap((m) => m.submissions.map((s) => <li key={s.id}><span className="dot" /><span>M{m.sequence} submitted{s.files.length ? ` with ${s.files.length} file(s)` : ''}</span>
              <span className="muted small">{new Date(s.submittedAt).toLocaleString()}</span></li>))}
            {c.milestones.filter((m) => m.acceptedAt).map((m) => <li key={m.id + 'a'}><span className="dot" /><span>M{m.sequence} accepted</span><span className="muted small">{new Date(m.acceptedAt!).toLocaleString()}</span></li>)}
          </ul>
          <div className="row" style={{ justifyContent: 'space-between', alignItems: 'center' }}>
            <p className="muted small" style={{ margin: 0 }}>Every step is also recorded in the tamper-evident audit log.</p>
            <button className="btn btn-secondary btn-sm" onClick={async () => {
              const ledger = escrow ? await escrowApi.ledger(escrow.id).catch(() => []) : []
              downloadFile(`${c.reference || 'engagement'}-record.json`, JSON.stringify({
                exportedAt: new Date().toISOString(), contract: c, escrow, ledger, disputes }, null, 2), 'application/json')
            }}><Icon name="download" /> Export engagement record</button>
          </div></section>
      )}
    </>
  )
}

function MilestoneCard({ m, c, side, busy, canFund, funding, onFund, onSubmit, onAccept, onRevise }: {
  m: ContractMilestone; c: Contract; side: Side; busy: boolean; canFund: boolean; funding: boolean; onFund: () => void
  onSubmit: (note: string, files: Upload[]) => void; onAccept: () => void; onRevise: (reason: string) => void
}) {
  const [note, setNote] = useState('')
  const [files, setFiles] = useState<Upload[]>([])
  const [fileError, setFileError] = useState('')
  const [reason, setReason] = useState('')
  const [revising, setRevising] = useState(false)
  const st = MILESTONE_STATUS[m.status]
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

      {m.submissions.length > 0 && <ul className="submission-list">{m.submissions.map((s) => (
        <li key={s.id}><span className="muted small">{new Date(s.submittedAt).toLocaleString()}</span><span>{s.note || <em className="muted">No note</em>}</span>
          {s.files.length > 0 && <FileLinks files={s.files} url={(f) => deliveredFileUrl(c.id, f.sha256)} />}</li>))}</ul>}

      {canDeliver && <div className="revise-box">
        <label className="filter-box grow"><span>What did you deliver?</span>
          <textarea rows={3} maxLength={2000} value={note} onChange={(e) => setNote(e.target.value)} placeholder="Summary of the work and where to find it" /></label>
        <div style={{ marginTop: 8 }}>{files.map((f) => <div key={f.sha256} className="file-row"><Icon name="request" /><span>{f.name}</span></div>)}
          {files.length < 10 && <input type="file" multiple accept={DOC_ACCEPT} onChange={async (e) => {
            const picked = Array.from(e.target.files ?? []).slice(0, 10 - files.length)
            e.target.value = ''
            setFileError('')
            try { setFiles([...files, ...await Promise.all(picked.map((f) => toUpload(f)))]) } catch (err) { setFileError(err instanceof Error ? err.message : 'That file could not be read') }
          }} />}
          <p className="muted small" style={{ margin: '4px 0 0' }}>PDF, Word, Excel, CSV, JPG or PNG · up to 10 MB each, 25 MB together. The buyer can open them; every opening is logged.</p>
          {fileError && <p className="small" style={{ color: 'var(--zk-danger)', margin: '4px 0 0' }}>{fileError}</p>}</div>
        <button className="btn btn-primary" style={{ marginTop: 10 }} disabled={busy || (!note.trim() && files.length === 0)}
          onClick={() => { onSubmit(note.trim(), files); setNote(''); setFiles([]) }}>{m.status === 'REVISION_REQUESTED' ? 'Resubmit for review' : 'Submit for review'}</button>
      </div>}

      {canReview && <div className="row card-actions">
        {revising ? <>
          <input className="input" style={{ flex: 1 }} placeholder="What needs to change, against the acceptance criteria?" value={reason} maxLength={1000} onChange={(e) => setReason(e.target.value)} />
          <button className="btn btn-secondary btn-sm" disabled={busy || reason.trim().length < 5} onClick={() => { onRevise(reason.trim()); setRevising(false); setReason('') }}>Send</button>
          <button className="btn btn-ghost btn-sm" onClick={() => setRevising(false)}>Cancel</button>
        </> : <>
          <button className="btn btn-secondary btn-sm" disabled={busy} onClick={() => setRevising(true)}>Request revision</button>
          <button className="btn btn-primary" disabled={busy} onClick={onAccept}>Accept milestone</button>
        </>}
      </div>}
    </section>
  )
}
