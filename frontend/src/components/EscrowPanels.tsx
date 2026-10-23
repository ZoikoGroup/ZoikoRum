import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import type { Contract } from '../api/contracts'
import { ALLOCATION_STATE, escrowApi, paymentsApi, RELEASE_MODELS, TEST_CARDS, type Escrow, type LedgerLine, type ReleaseModel } from '../api/escrow'
import { formatMoney, orgApi } from '../api/orgs'
import { saveBlob } from '../lib/exports'
import { Icon } from './dashboard'
import { StatCard } from './portal'
import { ErrorAlert, useDialog, useStepUp } from './ui'

/* Escrow UI for an engagement (Payments & Escrow doc s.7-14): funding confirmation and the payments tab. */

const feeText = (bps: number) => `${(bps / 100).toFixed(bps % 100 ? 2 : 0)}%`
const fmtDate = (d: string | null) => (d ? new Date(d).toLocaleDateString() : '—')

/** Funding confirmation: breakdown, payment method, and the "held until acceptance" notice. */
export function FundDialog({ escrow, preselect, onClose, onFunded }: {
  escrow: Escrow; preselect: string[]; onClose: () => void; onFunded: (e: Escrow) => void
}) {
  const dialog = useDialog(onClose)
  const open = escrow.allocations.filter((x) => x.state === 'UNFUNDED')
  // Fixed release: the whole fee is funded at once, so every open milestone is included and cannot be unticked.
  const fixedAll = escrow.protection?.releaseModel === 'FIXED' && escrow.funded.amountMinor === 0
  const [picked, setPicked] = useState<string[]>(fixedAll || !preselect.length ? open.map((x) => x.milestoneId) : preselect)
  const screening = escrow.buyerScreening
  const [token, setToken] = useState(TEST_CARDS[0][0])
  const [error, setError] = useState<unknown>(null)
  const [busy, setBusy] = useState(false)
  const [configuration, setConfiguration] = useState<Awaited<ReturnType<typeof paymentsApi.configuration>> | null>(null)
  useEffect(() => { paymentsApi.configuration().then(setConfiguration).catch(setError) }, [])
  const amount = open.filter((x) => picked.includes(x.milestoneId)).reduce((s, x) => s + x.amount.amountMinor, 0)
  const money = (m: number) => formatMoney({ amountMinor: m, currency: escrow.currency })
  const fee = Math.floor((amount * escrow.feeBps + 5000) / 10000)

  return (
    <div ref={dialog} className="modal-backdrop" role="dialog" aria-modal="true" aria-labelledby="fund-title" onClick={onClose}>
      <div className="card modal fund-modal" onClick={(e) => e.stopPropagation()}>
        <h2 id="fund-title">Fund protected payment</h2>
        <ErrorAlert error={error} />
        {error !== null && <div className="tip" style={{ marginBottom: 12 }}><Icon name="help" /><span>Nothing was taken and your choices are kept.
          Try again, choose another payment method below, or <Link to="/app/help?from=funding">ask us for help</Link>.</span></div>}
        <ScreeningNotice escrow={escrow} />
        {fixedAll && <p className="muted small">Fixed release: the whole fee is paid into escrow now and released milestone by milestone.</p>}
        <ul className="fund-list">{open.map((x) => (
          <li key={x.milestoneId}>
            <label className="checkbox"><input type="checkbox" checked={picked.includes(x.milestoneId)} disabled={fixedAll}
              onChange={() => setPicked(picked.includes(x.milestoneId) ? picked.filter((p) => p !== x.milestoneId) : [...picked, x.milestoneId])} />
              <span>M{x.sequence} {x.title}</span></label>
            <strong>{formatMoney(x.amount)}</strong>
          </li>))}</ul>
        <dl className="facts">
          <dt>You pay now</dt><dd><strong>{money(amount)}</strong></dd>
          <dt>Held until</dt><dd>You accept each milestone</dd>
          <dt>Professional receives</dt><dd>{money(amount - fee)} after the {feeText(escrow.feeBps)} platform fee</dd>
          <dt>Taxes</dt><dd>Included in the price where they apply (shown on the invoice)</dd>
        </dl>
        {configuration?.hostedCheckout ? <p>You will enter payment details on the partner’s secure checkout page. Funding is confirmed after payment completes.</p> :
          configuration?.configured ? <label className="filter-box" style={{ marginTop: 14 }}><span>Payment method (test mode: no real money moves)</span>
          <select value={token} onChange={(e) => setToken(e.target.value)}>{TEST_CARDS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select></label> :
          <p role="status">Payment integration is unavailable. No payment will be requested.</p>}
        <div className="protect-note" style={{ marginTop: 14 }}><Icon name="lock" /><div><strong>Funds will be held securely until acceptance.</strong>
          <div className="small">Neither side can withdraw them. If there is a dispute, they stay frozen until it is resolved.</div></div></div>
        <div className="row" style={{ marginTop: 16, justifyContent: 'flex-end' }}>
          <button className="btn btn-ghost" onClick={onClose}>Cancel</button>
          <button className="btn btn-primary" disabled={busy || amount === 0 || !configuration?.configured || screening?.status === 'FLAGGED'} onClick={async () => {
            setBusy(true)
            setError(null)
            try { onFunded(await escrowApi.fund(escrow.id, { milestoneIds: picked, paymentMethodToken: configuration?.hostedCheckout ? 'hosted_checkout' : token })) } catch (err) { setError(err) } finally { setBusy(false) }
          }}>{busy ? 'Processing…' : configuration?.hostedCheckout ? 'Prepare secure checkout' : `Pay ${money(amount)} into escrow`}</button>
        </div>
      </div>
    </div>
  )
}

/** Buyer organisation screening before funding: flagged blocks, pending warns. */
export function ScreeningNotice({ escrow }: { escrow: Escrow }) {
  const s = escrow.buyerScreening
  if (!s || !s.message || (s.status !== 'FLAGGED' && s.status !== 'PENDING')) return null
  return <div className={`alert ${s.status === 'FLAGGED' ? 'alert-error' : 'alert-warn'}`} role={s.status === 'FLAGGED' ? 'alert' : 'status'}>
    {s.status === 'FLAGGED' ? <strong>Funding blocked. </strong> : <strong>Screening in progress. </strong>}{s.message}</div>
}

const remaining = (due: string, now: number) => {
  const ms = new Date(due).getTime() - now
  if (ms <= 0) return 'overdue'
  const h = Math.floor(ms / 3_600_000), m = Math.floor((ms % 3_600_000) / 60_000), s = Math.floor((ms % 60_000) / 1000)
  return h >= 48 ? `${Math.floor(h / 24)}d ${h % 24}h left` : `${h}h ${String(m).padStart(2, '0')}m ${String(s).padStart(2, '0')}s left`
}

/** Live countdown to the buyer organisation's release-approval deadline (the SLA), updated every second. */
export function ApprovalCountdown({ due }: { due: string }) {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => { const t = setInterval(() => setNow(Date.now()), 1000); return () => clearInterval(t) }, [])
  const text = remaining(due, now)
  return <span className={`badge ${text === 'overdue' ? 'warn' : ''}`} role="timer" aria-live="off"
    title={`Approval due ${new Date(due).toLocaleString()}`}>Approval {text === 'overdue' ? 'overdue' : `due: ${text}`}</span>
}

/** Payment protection setup, right after both signatures: release model, release approver, dispute hold, then fund. */
export function PaymentProtectionSetup({ c, escrow, side, onSaved, onFund }: {
  c: Contract; escrow: Escrow; side: 'buyer' | 'professional'; onSaved: (e: Escrow) => void; onFund: (ids: string[]) => void
}) {
  const retainer = c.engagementType === 'RETAINER' || c.pricingModel === 'RETAINER'
  const models = RELEASE_MODELS.filter(([m]) => (retainer ? m === 'RETAINER' : m !== 'RETAINER'))
  const prot = escrow.protection
  const [model, setModel] = useState<ReleaseModel>(prot?.releaseModel ?? models[0][0])
  const [approver, setApprover] = useState(prot?.approverIdentityId ?? '')
  const [ack, setAck] = useState(!!prot?.confirmedAt)
  const [members, setMembers] = useState<{ id: string; name: string }[]>([])
  const [error, setError] = useState<unknown>(null)
  const [busy, setBusy] = useState(false)
  useEffect(() => {
    if (side !== 'buyer') return
    orgApi.members(c.organizationId).then((ms) => setMembers(ms.filter((m) => m.roles.includes('APPROVER') || m.roles.includes('REQUESTER'))
      .map((m) => ({ id: m.identityId, name: m.displayName })))).catch(() => setMembers([]))
  }, [c.organizationId, side])
  const first = [...escrow.allocations].filter((x) => x.state === 'UNFUNDED').sort((a, b) => a.sequence - b.sequence)
  const toFund = prot?.firstFunding.length ? prot.firstFunding : first.slice(0, 1).map((x) => x.milestoneId)
  const amount = escrow.allocations.filter((x) => toFund.includes(x.milestoneId)).reduce((s, x) => s + x.amount.amountMinor, 0)
  if (side !== 'buyer') {
    return (
      <section className="card panel activation-panel">
        <div className="panel-head"><h2>Awaiting payment protection</h2><span className="badge warn">Do not start work yet</span></div>
        <p style={{ marginTop: 0 }}>Both of you have signed. The buyer is now setting up payment protection and funding
          {first[0] ? ` M${first[0].sequence} ${first[0].title}` : ' the first milestone'}. Work starts only once that money is held in escrow;
          you will be told as soon as it is.</p>
        {prot?.releaseModel && <p className="small muted">Release model: {RELEASE_MODELS.find(([m]) => m === prot.releaseModel)?.[1]}. {prot.explanation}</p>}
      </section>
    )
  }
  return (
    <section className="card panel activation-panel" aria-labelledby="protect-title">
      <div className="panel-head"><h2 id="protect-title">Set up payment protection</h2><span className="badge warn">Awaiting payment protection</span></div>
      <p className="muted small" style={{ marginTop: 0 }}>Both parties have signed. Choose how money is released, who approves releases, then fund.
        The engagement becomes active once the first funding is held in escrow. Escrow is required for every engagement.</p>
      <ErrorAlert error={error} />
      <ScreeningNotice escrow={escrow} />
      <fieldset className="field"><legend className="label">1. Release model</legend>
        <div className="choice-grid two">{models.map(([m, label, text]) => (
          <label key={m} className={`choice ${model === m ? 'on' : ''}`}><input type="radio" name="release-model" checked={model === m} onChange={() => setModel(m)} />
            <strong>{label}</strong><span className="muted small">{text}</span></label>))}</div></fieldset>
      <label className="filter-box"><span>2. Who approves releases</span>
        <select value={approver} onChange={(e) => setApprover(e.target.value)}>
          <option value="">Me</option>{members.map((m) => <option key={m.id} value={m.id}>{m.name}</option>)}</select></label>
      <p className="muted small">They accept the work (or approve releases where your policy asks). Nothing is released without acceptance.</p>
      <div className="protect-note"><Icon name="lock" /><div><strong>3. If there is a dispute</strong>
        <div className="small">{prot?.disputeHold ?? 'If either side raises a dispute, the money for the affected milestones is frozen in escrow until it is resolved.'}</div></div></div>
      <label className="checkbox" style={{ marginTop: 10 }}><input type="checkbox" checked={ack} onChange={(e) => setAck(e.target.checked)} />
        <span>I understand that a dispute freezes the affected money until it is resolved.</span></label>
      <div className="row card-actions">
        <button className="btn btn-secondary" disabled={busy || !ack} onClick={async () => {
          setBusy(true); setError(null)
          try { onSaved(await escrowApi.setProtection(escrow.id, { releaseModel: model, approverIdentityId: approver || null, disputeHoldAcknowledged: ack })) }
          catch (err) { setError(err) } finally { setBusy(false) }
        }}>{prot?.confirmedAt ? 'Update setup' : 'Save setup'}</button>
        <button className="btn btn-primary btn-lg" disabled={!prot?.confirmedAt || !escrow.canFund || escrow.buyerScreening?.status === 'FLAGGED'}
          title={!prot?.confirmedAt ? 'Save the setup first' : undefined} onClick={() => onFund(toFund)}>
          <Icon name="lock" /> 4. Fund {prot?.releaseModel === 'FIXED' ? 'the whole fee' : first[0] ? `M${first[0].sequence}` : ''}
          {amount ? ` (${formatMoney({ amountMinor: amount, currency: escrow.currency })})` : ''}</button>
      </div>
    </section>
  )
}

export function PaymentsPanel({ c, escrow, side, onFund, fundBlocked }: { c: Contract; escrow: Escrow | null; side: 'buyer' | 'professional'
  onFund: (ids: string[]) => void; fundBlocked?: string }) {
  const [ledger, setLedger] = useState<LedgerLine[] | null>(null)
  const [ledgerCursor, setLedgerCursor] = useState<string | null>(null)
  const [ledgerBusy, setLedgerBusy] = useState(false)
  const [paymentError, setPaymentError] = useState<unknown>(null)
  const loadLedger = (cursor: string | null) => {
    if (!escrow) return
    setLedgerBusy(true)
    escrowApi.ledger(escrow.id, cursor).then((page) => { setLedger((prev) => [...(cursor ? prev ?? [] : []), ...page.items]); setLedgerCursor(page.nextCursor) })
      .catch((err) => { setPaymentError(err); setLedger((prev) => prev ?? []) }).finally(() => setLedgerBusy(false))
  }
  const [hosted, setHosted] = useState(false)
  useEffect(() => { paymentsApi.configuration().then(config => setHosted(config.hostedCheckout)).catch(setPaymentError) }, [])
  if (c.status === 'PENDING_SIGNATURE' || !escrow) {
    return <section className="card panel"><div className="panel-head"><h2>Payments &amp; protection</h2></div>
      <p className="muted" style={{ margin: 0 }}>The escrow account opens when both parties have signed the contract.</p></section>
  }
  const pending = escrow.fundings.filter((f) => f.status === 'REQUESTED')
  const seq = (mid: string) => escrow.allocations.find((x) => x.milestoneId === mid)?.sequence
  return (
    <>
      <div className="stat-row four">
        <StatCard icon="lock" tone="amber" value={formatMoney(escrow.held)} label="Held in escrow" sub="Protected until acceptance" />
        <StatCard icon="check" tone="green" value={formatMoney(escrow.released)} label="Released to professional" sub={`After ${formatMoney(escrow.fees)} platform fees`} />
        <StatCard icon="wallet" tone="blue" value={formatMoney(escrow.unfunded)} label="Not yet funded" sub={`of ${formatMoney(escrow.total)} total`} />
        <StatCard icon="clock" tone="violet" value={escrow.status.replace(/_/g, ' ').toLowerCase()} label="Escrow status" sub={`Platform fee ${feeText(escrow.feeBps)}`} />
      </div>
      {pending.length > 0 && <div className="tip" style={{ marginBottom: 16 }}><Icon name="clock" /><span>A payment of {formatMoney(pending[0].amount)} is being processed.</span></div>}
      {side === 'buyer' && <ScreeningNotice escrow={escrow} />}
      {escrow.status === 'EXPIRED' && <div className="alert alert-warn" role="status">This engagement was never funded within the funding window, so it
        expired. No money was taken. Request a new proposal to start again.</div>}
      {side === 'buyer' && (c.engagementType === 'RETAINER' || c.pricingModel === 'RETAINER') && c.status === 'ACTIVE' &&
        <AutoFunding escrow={escrow} hosted={hosted} />}
      <section className="card panel">
        <div className="panel-head"><h2>Milestones in escrow</h2>
          {escrow.canFund && <button className="btn btn-primary btn-sm" disabled={!!fundBlocked} title={fundBlocked} onClick={() => onFund([])}><Icon name="lock" /> Fund remaining</button>}</div>
        {fundBlocked && <p className="small warn-text" role="note">{fundBlocked}</p>}
        <div className="payment-frame small">
          <span><Icon name="shield" /> <strong>Who releases:</strong> {escrow.protection?.approverName
            ? `${escrow.protection.approverName} accepts the work for the buyer; their organisation's approvers agree where its policy asks.`
            : "the buyer accepts each milestone; their organisation's approvers agree where its policy asks."}</span>
          {escrow.protection?.releaseModel && <span><Icon name="lock" /> <strong>{RELEASE_MODELS.find(([m]) => m === escrow.protection?.releaseModel)?.[1]}:</strong> {escrow.protection.explanation}</span>}
          <span><Icon name="clock" /> <strong>What happens next:</strong> {escrow.held.amountMinor > 0 ? 'money held now is released when its milestone is accepted, or stays frozen if a dispute is opened.'
            : escrow.unfunded.amountMinor > 0 ? 'the next milestone is funded before its work starts.' : 'nothing is waiting: every milestone is settled.'}</span>
        </div>
        <table className="data"><thead><tr><th>Milestone</th><th>Amount</th><th>Status</th><th>Funded</th><th>Released (net)</th><th>Fee</th><th>Release reference</th></tr></thead>
          <tbody>{escrow.allocations.map((x) => (
            <tr key={x.milestoneId}>
              <td>M{x.sequence} {x.title}</td><td>{formatMoney(x.amount)}</td>
              <td><span className={`badge ${ALLOCATION_STATE[x.state]?.tone ?? ''}`}>{ALLOCATION_STATE[x.state]?.label ?? x.state}</span>
                {side === 'buyer' && x.state === 'RELEASE_PENDING_APPROVAL' && x.releaseApprovalDueAt && <><br /><ApprovalCountdown due={x.releaseApprovalDueAt} /></>}</td>
              <td className="small">{fmtDate(x.fundedAt)}</td>
              <td>{x.state === 'RELEASED' ? formatMoney(x.released) : '—'}</td>
              <td className="small">{x.state === 'RELEASED' ? formatMoney(x.fee) : '—'}</td>
              <td className="small">{x.releaseReference ? <><code>{x.releaseReference}</code><br /><span className="muted">{fmtDate(x.releasedAt)}</span>
                {x.releaseId && <><br /><button className="link-button" onClick={() => escrowApi.releaseReceipt(x.releaseId!)
                  .then((b) => saveBlob(`${x.releaseReference}.pdf`, b)).catch(setPaymentError)}><Icon name="download" /> Receipt (PDF)</button></>}</> : '—'}</td>
            </tr>))}</tbody></table>
        {side === 'professional' && <p className="muted small" style={{ marginBottom: 0 }}>Released money is paid out to your bank account. See <Link to="/app/professional/earnings">Earnings</Link>.</p>}
      </section>
      {escrow.fundings.length > 0 && <section className="card panel">
        <div className="panel-head"><h2>Payments</h2></div><ErrorAlert error={paymentError} />
        <table className="data"><thead><tr><th>Date</th><th>Amount</th><th>Milestones</th><th>Status</th></tr></thead>
          <tbody>{escrow.fundings.map((f) => (
            <tr key={f.id}><td className="small">{new Date(f.createdAt).toLocaleString()}</td><td>{formatMoney(f.amount)}</td>
              <td className="small">{f.milestoneIds.map((mid) => `M${seq(mid)}`).join(', ')}</td>
              <td><span className={`badge ${f.status === 'CAPTURED' ? 'green' : f.status === 'FAILED' ? '' : 'warn'}`}>
                {f.status === 'CAPTURED' ? 'Captured' : f.status === 'FAILED' ? `Failed: ${f.failureMessage}` : 'Processing'}</span>
                {side === 'buyer' && hosted && f.status === 'REQUESTED' && <button className="btn btn-secondary btn-sm" onClick={async () => {
                  try { const result = await paymentsApi.checkout(f.id); if (result.url) window.location.assign(result.url); else setPaymentError(new Error('Checkout is being prepared. Try again shortly.')) } catch (err) { setPaymentError(err) }
                }}>Continue payment</button>}</td></tr>))}</tbody></table>
      </section>}
      <section className="card panel">
        <div className="panel-head"><h2>Ledger</h2>
          {ledger === null && <button className="btn btn-ghost btn-sm" disabled={ledgerBusy} onClick={() => loadLedger(null)}>Show entries</button>}</div>
        {escrow.fundings.length === 0 && <ErrorAlert error={paymentError} />}
        {ledger === null ? <p className="muted small" style={{ margin: 0 }}>Every movement is recorded as balanced, permanent double-entry lines.</p> : (
          <table className="data"><thead><tr><th>When</th><th>Type</th><th>Account</th><th>Debit</th><th>Credit</th><th>Memo</th></tr></thead>
            <tbody>{ledger.map((l) => (
              <tr key={l.id}><td className="small">{new Date(l.createdAt).toLocaleString()}</td><td className="small">{l.entryType.replace(/_/g, ' ')}</td>
                <td className="small">{l.ledgerAccount.replace(/_/g, ' ')}</td><td>{l.debit.amountMinor ? formatMoney(l.debit) : ''}</td>
                <td>{l.credit.amountMinor ? formatMoney(l.credit) : ''}</td><td className="small">{l.memo}</td></tr>))}</tbody></table>
        )}
        {ledger !== null && ledgerCursor && <div className="row" style={{ justifyContent: 'center', marginTop: 8 }}>
          <button className="btn btn-secondary btn-sm" disabled={ledgerBusy} onClick={() => loadLedger(ledgerCursor)}>{ledgerBusy ? 'Loading…' : 'Load more'}</button></div>}
      </section>
    </>
  )
}


/** Retainer auto-funding: each new cycle is funded from a saved payment method before it is due, with the same role,
    spend-limit and policy checks as funding by hand. */
function AutoFunding({ escrow, hosted }: { escrow: Escrow; hosted: boolean }) {
  const [state, setState] = useState(escrow.autoFundingEnabledAt ?? null)
  const [token, setToken] = useState(hosted ? '' : TEST_CARDS[0][0])
  const [error, setError] = useState<unknown>(null)
  const { run, modal } = useStepUp(setError)
  const save = (value: string | null) => run(async () => setState((await escrowApi.autoFunding(escrow.id, value)).autoFundingEnabledAt ?? null))
  return (
    <section className="card panel">
      {modal}
      <div className="panel-head"><h2>Automatic funding</h2>
        <span className={`badge ${state ? 'green' : ''}`}>{state ? `On since ${new Date(state).toLocaleDateString()}` : 'Off'}</span></div>
      <ErrorAlert error={error} />
      <p className="small muted">Each new cycle is funded a few days before it is due. Your role, your spend limit and your organisation's
        policy are checked every time; if a check fails you are told and the cycle waits for you to fund it.</p>
      {state ? <button className="btn btn-ghost btn-sm" onClick={() => save(null)}>Turn off</button> : <div className="row">
        {hosted ? <input className="input" aria-label="Saved payment method" placeholder="Saved payment method ID (pm_…)" value={token} onChange={(e) => setToken(e.target.value.trim())} />
          : <select className="input" aria-label="Payment method" value={token} onChange={(e) => setToken(e.target.value)}>
            {TEST_CARDS.map(([t, l]) => <option key={t} value={t}>{l}</option>)}</select>}
        <button className="btn btn-secondary btn-sm" disabled={token.length < 3} onClick={() => save(token)}>Turn on</button>
      </div>}
    </section>
  )
}
