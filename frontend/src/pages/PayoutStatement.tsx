import { useEffect, useState, type ReactNode } from 'react'
import { Link, useParams } from 'react-router-dom'
import { paymentsApi, type PayoutStatement } from '../api/escrow'
import { Icon, type IconName } from '../components/dashboard'
import { ErrorAlert } from '../components/ui'
import { saveBlob } from '../lib/exports'
import {
  feePercent, formatDateTime, formatDay, formatStatementMoney as money, humanize, STATUS_TONE, transactionLink, TRANSACTION_TYPE, workPeriod,
} from '../lib/payoutStatement'
import { COUNTRIES } from './Join'

/* Payout statement (professional): one payout in full - what the client paid into escrow, the platform fee, what was
   paid to the bank and when, the engagement it pays for, each step, related money movements and where it was paid.
   Real data only (GET /v1/payments/payouts/{id}); the client is shown as an organisation, never a person's contact details. */

const STEP_ICON: Record<PayoutStatement['steps'][number]['state'], IconName> = { DONE: 'check', CURRENT: 'clock', UPCOMING: 'clock', FAILED: 'alert' }

function Panel({ title, action, children, className = '' }: { title: string; action?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={`card panel ${className}`}>
      <div className="panel-head"><h2>{title}</h2>{action}</div>
      {children}
    </section>
  )
}

function Kpi({ icon, tone, label, value, note }: { icon: IconName; tone: string; label: string; value: ReactNode; note?: ReactNode }) {
  return (
    <div className="card kpi">
      <span className={`kpi-icon ${tone}`}><Icon name={icon} /></span>
      <div style={{ minWidth: 0 }}>
        <div className="label">{label}</div>
        <div className="value">{value}</div>
        {note && <div className="note">{note}</div>}
      </div>
    </div>
  )
}

const countryName = (code: string | null) => (code && COUNTRIES.find(([c]) => c === code)?.[1]) || code || '—'

export default function PayoutStatementPage() {
  const { id = '' } = useParams()
  const [loaded, setLoaded] = useState<{ id: string; data: PayoutStatement } | null>(null)
  const [error, setError] = useState<unknown>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const s = loaded?.id === id ? loaded.data : null  // never show the previous payout while the next one loads

  useEffect(() => { paymentsApi.payoutStatement(id).then((data) => setLoaded({ id, data })).catch(setError) }, [id])

  function download() {
    if (!s) return
    paymentsApi.payoutPdf(s.id).then((b) => saveBlob(`${s.reference}.pdf`, b)).catch(setError)
  }

  function copyReference(e: React.MouseEvent<HTMLButtonElement>) {
    e.currentTarget.closest('details')?.removeAttribute('open')
    if (!s) return
    navigator.clipboard?.writeText(s.reference).then(() => setNotice(`Copied ${s.reference}.`), () => setNotice(`Reference: ${s.reference}`))
  }

  const crumbs = (
    <nav className="breadcrumb small no-print" aria-label="Breadcrumb">
      <Link to="/app/professional/earnings">Earnings</Link> › <span>Payout statement</span>{s && <> › <span aria-current="page">{s.reference}</span></>}
    </nav>
  )

  if (!s) return <>{crumbs}<ErrorAlert error={error} />{!error && <p className="muted">Loading payout statement…</p>}</>

  const e = s.engagement
  const paidOn = s.settledAt ?? null
  const milestone = e.milestoneTitle ? `M${e.milestoneSequence} ${e.milestoneTitle}` : 'Whole engagement'
  const messages = `/app/messages?contextType=CONTRACT&contextId=${e.contractId}`

  return (
    <div className="payout-statement">
      {crumbs}
      <div className="portal-head">
        <div>
          <h1 className="payout-title">Payout Statement <span className={`badge ${STATUS_TONE[s.statusLabel]}`}>{s.statusLabel}</span></h1>
          <p className="muted" style={{ margin: 0 }}>
            <span className="mono">{s.reference}</span> · {formatDay(s.createdAt)} · For engagement{' '}
            <Link to={`/app/professional/engagements/${e.contractId}`}>{e.reference || e.title}</Link>
          </p>
        </div>
        <div className="row no-print">
          <button className="btn btn-secondary" onClick={download}><Icon name="download" /> Download PDF</button>
          <button className="btn btn-secondary" onClick={() => window.print()}>Print</button>
          <details className="more-menu">
            <summary aria-label="More actions">⋯</summary>
            <div className="menu card"><button onClick={copyReference}>Copy reference</button></div>
          </details>
        </div>
      </div>
      {notice && <div className="alert alert-success no-print" role="status">{notice}</div>}
      <ErrorAlert error={error} />
      {s.delayReason && <div className="alert alert-warn" role="status">{s.delayReason}</div>}

      <div className="kpi-row payout-kpis">
        <Kpi icon="lock" tone="blue" label="Gross amount" value={money(s.gross)} note="Released from escrow" />
        <Kpi icon="wallet" tone="violet" label={`Platform fee (${feePercent(s.feeBps)})`} value={`−${money(s.fee)}`} note="Zoikorum fee" />
        <Kpi icon="check" tone="green" label="Paid to you" value={<span className="payout-net">{money(s.net)}</span>} note={s.net.currency} />
        <Kpi icon="clock" tone="amber" label={paidOn ? 'Payment date' : 'Expected arrival'}
          value={formatDay(paidOn ?? s.expectedAt)} note={paidOn ? 'Arrived in your bank' : s.expectedAt ? 'Estimated' : 'Not sent yet'} />
      </div>

      <div className="payout-grid">
        <Panel title="Engagement details">
          <dl className="facts">
            <dt>Engagement</dt><dd>{e.reference || '—'}</dd>
            <dt>Service</dt><dd>{e.title}</dd>
            <dt>Milestone</dt><dd>{milestone}</dd>
            {e.specialization && <><dt>Specialization</dt><dd>{e.specialization}</dd></>}
            <dt>Contract type</dt><dd>{humanize(e.engagementType)}{e.pricingModel ? ` · ${humanize(e.pricingModel)}` : ''}</dd>
            <dt>Work period</dt><dd>{workPeriod(e.workStart, e.workEnd)}</dd>
            <dt>Accepted</dt><dd>{formatDay(e.acceptedAt)}</dd>
            <dt>Client invoice</dt><dd className="mono">{e.clientInvoiceNumber ?? '—'}</dd>
          </dl>
        </Panel>

        <Panel title="Client details" action={<Link className="btn btn-ghost btn-sm no-print" to={messages}><Icon name="message" /> Message client</Link>}>
          <dl className="facts">
            <dt>Company</dt><dd>{s.client.name}</dd>
            <dt>Country</dt><dd>{countryName(s.client.country)}</dd>
          </dl>
          <p className="muted small" style={{ marginBottom: 0 }}>Talk to the client in the engagement's conversation; contact details are not shared.</p>
        </Panel>

        <Panel title="Payment status">
          <ol className="payout-stepper" aria-label="Payment status">
            {s.steps.map((st) => (
              <li key={st.key} className={st.state.toLowerCase()} aria-current={st.state === 'CURRENT' ? 'step' : undefined}>
                <span className="dot"><Icon name={STEP_ICON[st.state]} /></span>
                <span className="txt"><strong>{st.label}</strong>
                  <span className="muted small">{st.at ? formatDay(st.at) : st.state === 'DONE' ? 'Done' : st.state === 'FAILED' ? 'Failed' : 'Pending'}</span></span>
              </li>
            ))}
          </ol>
        </Panel>

        <Panel title="Amount breakdown">
          <table className="payout-breakdown"><tbody>
            <tr><th scope="row">Gross amount (released from escrow)</th><td>{money(s.gross)}</td></tr>
            <tr><th scope="row">Platform fee ({feePercent(s.feeBps)})</th><td>−{money(s.fee)}</td></tr>
            <tr className="total"><th scope="row">Total paid to you</th><td>{money(s.net)}</td></tr>
          </tbody></table>
          <p className="muted small" style={{ marginBottom: 0 }}>All amounts in {s.net.currency}.</p>
        </Panel>

        <Panel title="Payout timeline">
          <ul className="payout-timeline">
            {s.steps.filter((st) => st.at || st.note).map((st) => (
              <li key={st.key} className={st.state.toLowerCase()}>
                <span className="when small muted">{st.at ? formatDateTime(st.at) : '—'}</span>
                <span><strong>{st.label}</strong>{st.note && <><br /><span className="muted small">{st.note}</span></>}</span>
              </li>
            ))}
          </ul>
        </Panel>

        <Panel title="Payout destination" action={<Link className="btn btn-ghost btn-sm no-print" to="/app/professional/earnings">Edit</Link>}>
          {s.destination ? (
            <dl className="facts">
              <dt>Bank account</dt><dd>•••• {s.destination.last4}</dd>
              <dt>Currency</dt><dd>{s.destination.currency} · {countryName(s.destination.country)}</dd>
              <dt>Paid through</dt><dd>{s.destination.provider}</dd>
              {s.destination.accountType && <><dt>Account type</dt><dd>{s.destination.accountType}</dd></>}
            </dl>
          ) : <p className="muted" style={{ margin: 0 }}>No payout account yet. Add one on the Earnings page to receive this payment.</p>}
          <h3 className="payout-sub">Transfer reference</h3>
          {s.transferReference
            ? <p className="mono" style={{ margin: 0 }}>{s.transferReference}</p>
            : <p className="muted small" style={{ margin: 0 }}>Available once the transfer is sent to your bank.</p>}
        </Panel>
      </div>

      <Panel title="Related transactions">
        <div className="table-scroll">
          <table className="data">
            <thead><tr><th>Date</th><th>Type</th><th>Description</th><th>Client / Project</th><th>Amount</th><th>Status</th><th><span className="sr-only">Open</span></th></tr></thead>
            <tbody>{s.transactions.map((t) => {
              const to = transactionLink(t.kind, e.contractId)
              return (
                <tr key={`${t.kind}-${t.at}`}>
                  <td className="small">{formatDay(t.at)}</td>
                  <td>{TRANSACTION_TYPE[t.kind]}</td>
                  <td className="small">{t.description}{t.reference && <div className="muted mono">{t.reference}</div>}</td>
                  <td className="small">{s.client.name}<div className="muted">{e.reference}</div></td>
                  <td>{money(t.amount)}</td>
                  <td><span className="badge">{t.status}</span></td>
                  <td className="no-print">{to ? <Link to={to}>View</Link> : null}</td>
                </tr>
              )
            })}</tbody>
          </table>
        </div>
      </Panel>

      <section className="card panel payout-help no-print">
        <span className="kpi-icon blue"><Icon name="help" /></span>
        <div style={{ flex: 1 }}><h2 style={{ margin: 0 }}>Need help?</h2>
          <p className="muted small" style={{ margin: 0 }}>Questions about this payout? Quote {s.reference} when you contact support.</p></div>
        <Link className="btn btn-secondary" to="/app/help">Contact support</Link>
      </section>
    </div>
  )
}
