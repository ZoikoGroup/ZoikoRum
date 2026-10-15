import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import type { Contract } from '../api/contracts'
import { ALLOCATION_STATE, escrowApi, paymentsApi, TEST_CARDS, type Escrow, type LedgerLine } from '../api/escrow'
import { formatMoney } from '../api/orgs'
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
  const [picked, setPicked] = useState<string[]>(preselect.length ? preselect : open.map((x) => x.milestoneId))
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
        <ul className="fund-list">{open.map((x) => (
          <li key={x.milestoneId}>
            <label className="checkbox"><input type="checkbox" checked={picked.includes(x.milestoneId)}
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
          <button className="btn btn-primary" disabled={busy || amount === 0 || !configuration?.configured} onClick={async () => {
            setBusy(true)
            setError(null)
            try { onFunded(await escrowApi.fund(escrow.id, { milestoneIds: picked, paymentMethodToken: configuration?.hostedCheckout ? 'hosted_checkout' : token })) } catch (err) { setError(err) } finally { setBusy(false) }
          }}>{busy ? 'Processing…' : configuration?.hostedCheckout ? 'Prepare secure checkout' : `Pay ${money(amount)} into escrow`}</button>
        </div>
      </div>
    </div>
  )
}

export function PaymentsPanel({ c, escrow, side, onFund, fundBlocked }: { c: Contract; escrow: Escrow | null; side: 'buyer' | 'professional'
  onFund: (ids: string[]) => void; fundBlocked?: string }) {
  const [ledger, setLedger] = useState<LedgerLine[] | null>(null)
  const [paymentError, setPaymentError] = useState<unknown>(null)
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
      {side === 'buyer' && (c.engagementType === 'RETAINER' || c.pricingModel === 'RETAINER') && c.status === 'ACTIVE' &&
        <AutoFunding escrow={escrow} hosted={hosted} />}
      <section className="card panel">
        <div className="panel-head"><h2>Milestones in escrow</h2>
          {escrow.canFund && <button className="btn btn-primary btn-sm" disabled={!!fundBlocked} title={fundBlocked} onClick={() => onFund([])}><Icon name="lock" /> Fund remaining</button>}</div>
        {fundBlocked && <p className="small warn-text" role="note">{fundBlocked}</p>}
        <div className="payment-frame small">
          <span><Icon name="shield" /> <strong>Who releases:</strong> the buyer accepts each milestone; their organisation's approvers agree where its policy asks.</span>
          <span><Icon name="clock" /> <strong>What happens next:</strong> {escrow.held.amountMinor > 0 ? 'money held now is released when its milestone is accepted, or stays frozen if a dispute is opened.'
            : escrow.unfunded.amountMinor > 0 ? 'the next milestone is funded before its work starts.' : 'nothing is waiting: every milestone is settled.'}</span>
        </div>
        <table className="data"><thead><tr><th>Milestone</th><th>Amount</th><th>Status</th><th>Funded</th><th>Released (net)</th><th>Fee</th><th>Release reference</th></tr></thead>
          <tbody>{escrow.allocations.map((x) => (
            <tr key={x.milestoneId}>
              <td>M{x.sequence} {x.title}</td><td>{formatMoney(x.amount)}</td>
              <td><span className={`badge ${ALLOCATION_STATE[x.state].tone}`}>{ALLOCATION_STATE[x.state].label}</span></td>
              <td className="small">{fmtDate(x.fundedAt)}</td>
              <td>{x.state === 'RELEASED' ? formatMoney(x.released) : '—'}</td>
              <td className="small">{x.state === 'RELEASED' ? formatMoney(x.fee) : '—'}</td>
              <td className="small">{x.releaseReference ? <><code>{x.releaseReference}</code><br /><span className="muted">{fmtDate(x.releasedAt)}</span></> : '—'}</td>
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
          {ledger === null && <button className="btn btn-ghost btn-sm" onClick={() => escrowApi.ledger(escrow.id).then(setLedger).catch(() => setLedger([]))}>Show entries</button>}</div>
        {ledger === null ? <p className="muted small" style={{ margin: 0 }}>Every movement is recorded as balanced, permanent double-entry lines.</p> : (
          <table className="data"><thead><tr><th>When</th><th>Type</th><th>Account</th><th>Debit</th><th>Credit</th><th>Memo</th></tr></thead>
            <tbody>{ledger.map((l) => (
              <tr key={l.id}><td className="small">{new Date(l.createdAt).toLocaleString()}</td><td className="small">{l.entryType.replace(/_/g, ' ')}</td>
                <td className="small">{l.ledgerAccount.replace(/_/g, ' ')}</td><td>{l.debit.amountMinor ? formatMoney(l.debit) : ''}</td>
                <td>{l.credit.amountMinor ? formatMoney(l.credit) : ''}</td><td className="small">{l.memo}</td></tr>))}</tbody></table>
        )}
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
