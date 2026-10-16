import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { escrowApi, TEST_CARDS, type PaymentsOverview as Overview } from '../api/escrow'
import { formatMoney } from '../api/orgs'
import { ErrorAlert } from './ui'

const money = (amountMinor: number, currency: string) => formatMoney({ amountMinor, currency })

/** Enterprise payments dashboard (Payments & Escrow): exposure by vendor, the release timeline, and funding several
    milestones across engagements at once. */
export function PaymentsOverview({ organizationId, hostedCheckout, onFunded }: { organizationId: string; hostedCheckout: boolean; onFunded: () => void }) {
  const [data, setData] = useState<Overview | null>(null)
  const [error, setError] = useState<unknown>(null)
  const [picked, setPicked] = useState<string[]>([])
  const [token, setToken] = useState(TEST_CARDS[0][0])
  const [busy, setBusy] = useState(false)
  const [result, setResult] = useState<string | null>(null)
  const load = useCallback(() => { escrowApi.overview(organizationId).then(setData).catch(setError) }, [organizationId])
  useEffect(() => { load() }, [load])

  async function fundPicked() {
    if (!data) return
    const byAccount = new Map<string, string[]>()
    for (const m of data.awaitingFunding.filter((x) => picked.includes(x.milestoneId))) byAccount.set(m.accountId, [...(byAccount.get(m.accountId) ?? []), m.milestoneId])
    setBusy(true); setError(null); setResult(null)
    try {
      const r = await escrowApi.bulkFund([...byAccount].map(([accountId, milestoneIds]) => ({ accountId, milestoneIds })), token)
      setResult(`${r.funded} engagement${r.funded === 1 ? '' : 's'} funded.` + (r.failed ? ` ${r.failed} not funded: ${r.results.filter((x) => !x.ok).map((x) => x.detail).join('; ')}` : ''))
      setPicked([])
      load(); onFunded()
    } catch (err) { setError(err) } finally { setBusy(false) }
  }

  if (!data) return error ? <ErrorAlert error={error} /> : <div className="card panel skeleton" style={{ height: 120 }} aria-busy="true" />
  const pickedTotal = data.awaitingFunding.filter((m) => picked.includes(m.milestoneId))
  return (
    <section className="card panel">
      <div className="panel-head"><h2>Exposure by vendor</h2></div>
      <ErrorAlert error={error} />
      {data.vendors.length === 0 ? <p className="muted">No engagements with escrow yet.</p> : (
        <table className="data"><thead><tr><th>Vendor</th><th>Engagements</th><th>Held in escrow</th><th>Frozen (disputes)</th><th>Awaiting funding</th><th>Released</th></tr></thead>
          <tbody>{data.vendors.map((v) => <tr key={`${v.professionalId}-${v.currency}`}>
            <td><Link to={`/professionals/${v.professionalId}`}>{v.name}</Link></td><td>{v.engagements}</td>
            <td>{money(v.heldMinor, v.currency)}</td><td>{v.frozenMinor ? <span className="badge warn">{money(v.frozenMinor, v.currency)}</span> : '—'}</td>
            <td>{money(v.awaitingFundingMinor, v.currency)}</td><td>{money(v.releasedMinor, v.currency)}</td></tr>)}</tbody></table>)}

      <h3 style={{ marginTop: 20 }}>Release timeline</h3>
      {data.releaseTimeline.length === 0 ? <p className="muted small">Nothing is held right now.</p> : (
        <table className="data"><thead><tr><th>Due</th><th>Engagement</th><th>Milestone</th><th>Vendor</th><th>Held</th></tr></thead>
          <tbody>{data.releaseTimeline.map((r, i) => <tr key={i}>
            <td className="small">{r.dueDate ? new Date(r.dueDate).toLocaleDateString() : 'No date'}</td>
            <td className="small"><Link to={`/app/engagements/${r.contractId}`}>{r.reference}</Link></td>
            <td className="small">{r.milestone}</td><td className="small">{r.vendor}</td><td>{money(r.amountMinor, r.currency)}</td></tr>)}</tbody></table>)}
      <p className="muted small">Held money is released only when you accept the milestone; the date is the milestone's due date.</p>

      <h3 style={{ marginTop: 20 }}>Fund several milestones</h3>
      {data.awaitingFunding.length === 0 ? <p className="muted small">No milestone is waiting for funding.</p> : <>
        <table className="data"><thead><tr><th><span className="sr-only">Pick</span></th><th>Engagement</th><th>Milestone</th><th>Vendor</th><th>Amount</th><th>Due</th></tr></thead>
          <tbody>{data.awaitingFunding.map((m) => <tr key={m.milestoneId}>
            <td><input type="checkbox" aria-label={`Fund ${m.milestone}`} checked={picked.includes(m.milestoneId)}
              onChange={(e) => setPicked(e.target.checked ? [...picked, m.milestoneId] : picked.filter((x) => x !== m.milestoneId))} /></td>
            <td className="small"><Link to={`/app/engagements/${m.contractId}`}>{m.reference}</Link></td><td className="small">{m.milestone}</td>
            <td className="small">{m.vendor}</td><td>{money(m.amountMinor, m.currency)}</td>
            <td className="small">{m.dueDate ? new Date(m.dueDate).toLocaleDateString() : '—'}</td></tr>)}</tbody></table>
        {hostedCheckout ? <p className="muted small">Bulk funding needs a saved payment method. With card checkout, fund each engagement from its page.</p> : (
          <div className="row" style={{ marginTop: 8 }}>
            <select className="input" aria-label="Payment method" value={token} onChange={(e) => setToken(e.target.value)}>
              {TEST_CARDS.map(([t, l]) => <option key={t} value={t}>{l}</option>)}</select>
            <button className="btn btn-primary" disabled={busy || picked.length === 0} onClick={fundPicked}>
              {busy ? 'Funding…' : `Fund ${picked.length} milestone${picked.length === 1 ? '' : 's'}`}
              {pickedTotal.length > 0 && ` (${[...new Set(pickedTotal.map((m) => m.currency))].map((c) => money(pickedTotal.filter((m) => m.currency === c).reduce((s, m) => s + m.amountMinor, 0), c)).join(' + ')})`}
            </button>
          </div>)}
        <p className="muted small">Each engagement is funded separately, with your spend limit and your organisation's policy checked for each.</p>
        {result && <div className="alert alert-success" role="status">{result}</div>}
      </>}
    </section>
  )
}
