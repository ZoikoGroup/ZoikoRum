import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { Link } from 'react-router-dom'
import { contractApi, type Contract } from '../api/contracts'
import { escrowApi, paymentsApi, PAYOUT_STATUS, type Charge, type Earnings, type Escrow, type Invoice } from '../api/escrow'
import { formatMoney, orgApi } from '../api/orgs'
import { CURRENCIES } from '../api/professional'
import { useAuth } from '../auth/AuthContext'
import { Icon } from '../components/dashboard'
import { EmptyTable, PortalHeader, SidePanel, StatCard, Tabs } from '../components/portal'
import { ErrorAlert, Field, useStepUp } from '../components/ui'
import { COUNTRIES } from './Join'

/* Money screens (Step 8): the professional's Earnings (payout account + payouts) and the customer's Payments
   & Protection (escrow across engagements, charges, invoices). Test mode: a fake payment provider, no real money. */

const sum = (xs: { amountMinor: number }[]) => xs.reduce((s, x) => s + x.amountMinor, 0)

export function EarningsPage() {
  const { user } = useAuth()
  const [data, setData] = useState<Earnings | null>(null)
  const [contracts, setContracts] = useState<Contract[]>([])
  const [error, setError] = useState<unknown>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [editing, setEditing] = useState(false)
  const [f, setF] = useState({ holderName: user?.displayName ?? '', country: user?.country ?? 'US', currency: 'USD', accountNumber: '' })
  const { run, modal } = useStepUp(setError)

  const load = useCallback(() => {
    paymentsApi.earnings().then(setData).catch(setError)
    contractApi.list('professional').then(setContracts).catch(() => {})
  }, [])
  useEffect(() => { load() }, [load])

  function save(e: FormEvent) {
    e.preventDefault()
    setError(null)
    run(async () => {
      await paymentsApi.setPayoutAccount(f)
      setEditing(false)
      setNotice('Payout account saved. Any waiting payouts have been sent.')
      setF({ ...f, accountNumber: '' })
      load()
    })
  }

  const title = (cid: string) => contracts.find((c) => c.id === cid)?.title ?? 'Engagement'
  const ms = (cid: string, mid: string | null) => contracts.find((c) => c.id === cid)?.milestones.find((m) => m.id === mid)
  const held = sum(contracts.filter((c) => c.status === 'ACTIVE').flatMap((c) => c.milestones.filter((m) => ['IN_PROGRESS', 'SUBMITTED', 'REVISION_REQUESTED'].includes(m.status)).map((m) => m.amount)))
  const ccy = data?.totals.settled.currency ?? 'USD'

  return (
    <>
      {modal}
      <PortalHeader eyebrow="Earnings" title="Your earnings" subtitle="Money released for accepted milestones, paid out to your bank account after the platform fee." />
      {notice && <div className="alert alert-success" role="status">{notice}</div>}
      <ErrorAlert error={error} />
      <div className="stat-row four">
        <StatCard icon="check" tone="green" value={data ? formatMoney(data.totals.settled) : '…'} label="Paid out" sub="Settled to your bank" />
        <StatCard icon="clock" tone="amber" value={data ? formatMoney(data.totals.pending) : '…'} label="Waiting" sub={data?.payoutAccount ? 'Being sent' : 'Add a payout account'} />
        <StatCard icon="lock" tone="blue" value={formatMoney({ amountMinor: held, currency: ccy })} label="Secured in escrow" sub="Funded, not yet accepted" />
        <StatCard icon="wallet" tone="violet" value={data ? formatMoney(data.totals.fees) : '…'} label="Platform fees" sub="Deducted from releases" />
      </div>
      <div className="home-grid wide">
        <section className="card panel">
          <div className="panel-head"><h2>Payouts</h2></div>
          {data && data.payouts.length === 0 ? (
            <EmptyTable columns={['Engagement', 'Milestone', 'Gross', 'Fee', 'Net', 'Status']}>
              <strong>No payouts yet.</strong> When a buyer accepts a funded milestone, the money is released and paid out here.
            </EmptyTable>
          ) : (
            <table className="data"><thead><tr><th>Engagement</th><th>Milestone</th><th>Gross</th><th>Fee</th><th>Net</th><th>Status</th><th>Date</th></tr></thead>
              <tbody>{(data?.payouts ?? []).map((p) => {
                const m = ms(p.contractId, p.milestoneId)
                return (
                  <tr key={p.id}>
                    <td><Link to={`/app/professional/engagements/${p.contractId}`}>{title(p.contractId)}</Link></td>
                    <td className="small">{m ? `M${m.sequence} ${m.title}` : '—'}</td>
                    <td>{formatMoney(p.gross)}</td><td className="small">−{formatMoney(p.fee)}</td><td><strong>{formatMoney(p.net)}</strong></td>
                    <td><span className={`badge ${PAYOUT_STATUS[p.status].tone}`}>{PAYOUT_STATUS[p.status].label}</span>
                      {p.failureMessage && <div className="muted small">{p.failureMessage}</div>}</td>
                    <td className="small">{new Date(p.settledAt ?? p.createdAt).toLocaleDateString()}</td>
                  </tr>
                )
              })}</tbody></table>
          )}
        </section>
        <aside>
          <SidePanel title="Payout account" action={data?.payoutAccount && !editing && <button className="btn btn-ghost btn-sm" onClick={() => setEditing(true)}>Change</button>}>
            {data?.payoutAccount && !editing ? (
              <dl className="facts">
                <dt>Account</dt><dd>{data.payoutAccount.label}</dd>
                <dt>Holder</dt><dd>{data.payoutAccount.holderName}</dd>
                <dt>Currency</dt><dd>{data.payoutAccount.currency} · {data.payoutAccount.country}</dd>
              </dl>
            ) : !user?.mfaEnabled ? (
              <div className="tip"><Icon name="lock" /><span>Adding a payout account needs two-step verification. <Link to="/app/security">Turn it on</Link>, then come back.</span></div>
            ) : (
              <form onSubmit={save}>
                <Field label="Account holder name" id="pa-name"><input id="pa-name" className="input" value={f.holderName} onChange={(e) => setF({ ...f, holderName: e.target.value })} required /></Field>
                <div className="row">
                  <Field label="Country" id="pa-country"><select id="pa-country" className="input" value={f.country} onChange={(e) => setF({ ...f, country: e.target.value })}>
                    {COUNTRIES.map(([c, n]) => <option key={c} value={c}>{n}</option>)}</select></Field>
                  <Field label="Currency" id="pa-ccy"><select id="pa-ccy" className="input" value={f.currency} onChange={(e) => setF({ ...f, currency: e.target.value })}>
                    {CURRENCIES.map((c) => <option key={c}>{c}</option>)}</select></Field>
                </div>
                <Field label="Account number / IBAN" id="pa-acct" hint="Test mode. Sent to the payment provider; Zoikorum keeps only the last 4 digits.">
                  <input id="pa-acct" className="input" value={f.accountNumber} onChange={(e) => setF({ ...f, accountNumber: e.target.value.replace(/[^A-Za-z0-9 ]/g, '') })} required minLength={6} /></Field>
                <div className="row">
                  {editing && <button type="button" className="btn btn-ghost" onClick={() => setEditing(false)}>Cancel</button>}
                  <button className="btn btn-primary">Save payout account</button>
                </div>
                <p className="muted small" style={{ marginBottom: 0 }}>You'll confirm with your authenticator code. Payouts need Trust Tier B.</p>
              </form>
            )}
          </SidePanel>
          <SidePanel title="How you get paid">
            <ol className="side-steps">{[['Buyer funds a milestone', 'The money is held in escrow; you see "Funds secured".'],
              ['You deliver and the buyer accepts', 'Acceptance releases the milestone amount.'],
              ['Platform fee is deducted', 'The net amount is paid to your payout account.']].map(([t, d], i) => (
              <li key={t}><span className="n">{i + 1}</span><span><strong>{t}</strong><br /><span className="muted small">{d}</span></span></li>))}</ol>
          </SidePanel>
        </aside>
      </div>
    </>
  )
}

/** Payments & Protection (management design 7), now with real escrow data. */
export function CustomerPaymentsPage() {
  const [contracts, setContracts] = useState<Contract[] | null>(null)
  const [escrows, setEscrows] = useState<Escrow[]>([])
  const [charges, setCharges] = useState<Charge[]>([])
  const [invoices, setInvoices] = useState<Invoice[]>([])
  const [error, setError] = useState<unknown>(null)
  const [tab, setTab] = useState<'escrow' | 'transactions' | 'invoices'>('escrow')

  useEffect(() => {
    (async () => {
      try {
        const cs = await contractApi.list('buyer')
        setContracts(cs)
        setEscrows((await Promise.all(cs.filter((c) => c.status !== 'PENDING_SIGNATURE').map((c) => escrowApi.byContract(c.id).catch(() => null))))
          .filter((e): e is Escrow => e !== null))
        const orgIds = [...new Set([...cs.map((c) => c.organizationId), ...(await orgApi.mine()).map((o) => o.id)])]
        setCharges((await Promise.all(orgIds.map((o) => paymentsApi.charges(o).catch(() => [])))).flat())
        setInvoices((await Promise.all(orgIds.map((o) => paymentsApi.invoices(o).catch(() => [])))).flat())
      } catch (err) { setError(err) }
    })()
  }, [])

  const ccy = escrows[0]?.currency ?? 'USD'
  const m = (n: number) => formatMoney({ amountMinor: n, currency: ccy })
  const title = (cid: string) => contracts?.find((c) => c.id === cid)?.title ?? 'Engagement'
  const paid = charges.filter((c) => c.status === 'CAPTURED').reduce((s, c) => s + c.amount.amountMinor, 0)

  return (
    <>
      <PortalHeader eyebrow="Payments & protection" title="Secure payments. Protected work."
        subtitle="Money is held in escrow per milestone and released to the professional only when you accept the work."
        actions={<Link className="btn btn-secondary" to="/app/engagements"><Icon name="briefcase" /> Engagements</Link>} />
      <ErrorAlert error={error} />
      <div className="tip" style={{ marginBottom: 16 }}><Icon name="help" /><span>Test mode: payments use a test provider and test cards. No real money moves.</span></div>
      <div className="stat-row four">
        <StatCard icon="lock" tone="amber" value={m(escrows.reduce((s, e) => s + e.held.amountMinor, 0))} label="In escrow" sub="Held until you accept" />
        <StatCard icon="check" tone="green" value={m(escrows.reduce((s, e) => s + e.released.amountMinor + e.fees.amountMinor, 0))} label="Released" sub="Paid for accepted work" />
        <StatCard icon="wallet" tone="blue" value={m(paid)} label="Total paid" sub={`${charges.filter((c) => c.status === 'CAPTURED').length} payment(s)`} />
        <StatCard icon="download" tone="violet" value={m(escrows.reduce((s, e) => s + e.refunded.amountMinor, 0))} label="Refunded" sub="Returned to you" />
      </div>
      <section className="card panel">
        <Tabs tabs={[{ key: 'escrow', label: 'Escrow by engagement', count: escrows.length }, { key: 'transactions', label: 'Payments', count: charges.length },
          { key: 'invoices', label: 'Invoices', count: invoices.length }]} value={tab} onChange={setTab} />
        {tab === 'escrow' && (escrows.length === 0 ? (
          <EmptyTable columns={['Engagement', 'Total', 'In escrow', 'Released', 'Not funded', 'Status']}>
            <strong>Nothing in escrow yet.</strong> After both parties sign a contract, fund its milestones from the engagement.</EmptyTable>
        ) : (
          <table className="data"><thead><tr><th>Engagement</th><th>Total</th><th>In escrow</th><th>Released</th><th>Not funded</th><th>Status</th></tr></thead>
            <tbody>{escrows.map((e) => <tr key={e.id}><td><Link to={`/app/engagements/${e.contractId}`}><strong>{title(e.contractId)}</strong></Link></td>
              <td>{formatMoney(e.total)}</td><td>{formatMoney(e.held)}</td><td>{formatMoney({ amountMinor: e.released.amountMinor + e.fees.amountMinor, currency: e.currency })}</td>
              <td>{formatMoney(e.unfunded)}</td><td className="small">{e.status.replace(/_/g, ' ').toLowerCase()}</td></tr>)}</tbody></table>
        ))}
        {tab === 'transactions' && (charges.length === 0 ? (
          <EmptyTable columns={['Date', 'Engagement', 'Amount', 'Method', 'Status']}><strong>No payments yet.</strong></EmptyTable>
        ) : (
          <table className="data"><thead><tr><th>Date</th><th>Engagement</th><th>Amount</th><th>Method</th><th>Status</th></tr></thead>
            <tbody>{charges.map((c) => <tr key={c.id}><td className="small">{new Date(c.createdAt).toLocaleString()}</td><td className="small">{title(c.contractId)}</td>
              <td>{formatMoney(c.amount)}</td><td className="small">{c.methodLabel}</td>
              <td><span className={`badge ${c.status === 'CAPTURED' ? 'green' : ''}`}>{c.status === 'CAPTURED' ? 'Paid into escrow' : c.status === 'FAILED' ? `Failed: ${c.failureMessage}` : 'Processing'}</span></td></tr>)}</tbody></table>
        ))}
        {tab === 'invoices' && (invoices.length === 0 ? (
          <EmptyTable columns={['Invoice', 'Engagement', 'Description', 'Amount', 'Issued']}><strong>No invoices yet.</strong> An invoice is issued each time you accept a milestone.</EmptyTable>
        ) : (
          <table className="data"><thead><tr><th>Invoice</th><th>Engagement</th><th>Description</th><th>Amount</th><th>Issued</th></tr></thead>
            <tbody>{invoices.map((i) => <tr key={i.id}><td><code>{i.number}</code></td><td className="small">{title(i.contractId)}</td>
              <td className="small">{i.lines.map((l) => l.description).join(', ')}</td><td>{formatMoney(i.total)}</td>
              <td className="small">{new Date(i.issuedAt).toLocaleDateString()}</td></tr>)}</tbody></table>
        ))}
      </section>
    </>
  )
}
