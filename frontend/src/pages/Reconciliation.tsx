import { Fragment, useCallback, useEffect, useState } from 'react'
import { formatMoney } from '../api/orgs'
import { paymentsApi, type Reconciliation } from '../api/escrow'
import { Icon } from '../components/dashboard'
import { EmptyTable, PortalHeader } from '../components/portal'
import { ErrorAlert } from '../components/ui'

/* Financial Ops: daily reconciliation (Engineering Handbook 15.4). Every night the escrow ledger, the payments records and
   the provider's report are compared per currency; any difference is a P0 financial incident. */

const CHECK_LABEL: Record<string, string> = {
  charges: 'Buyer payments captured', payouts: 'Owed to professionals', refunds: 'Refunds to buyers', chargebacks: 'Chargebacks',
}
const yesterday = () => new Date(Date.now() - 86_400_000).toISOString().slice(0, 10)

export default function ReconciliationPage() {
  const [rows, setRows] = useState<Reconciliation[] | null>(null)
  const [day, setDay] = useState(yesterday)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<unknown>(null)
  const [open, setOpen] = useState<string | null>(null)

  const load = useCallback(() => paymentsApi.reconciliations().then(setRows).catch(setError), [])
  useEffect(() => { load() }, [load])

  async function run() {
    setBusy(true)
    setError(null)
    try {
      const r = await paymentsApi.reconcile(day)
      setOpen(r.id)
      await load()
    } catch (err) { setError(err) } finally { setBusy(false) }
  }

  const bad = (rows ?? []).filter((r) => r.status === 'MISMATCH').length
  return (
    <>
      <PortalHeader eyebrow="Financial operations" title="Daily reconciliation"
        subtitle="Each night at 01:00 UTC the escrow ledger, payments records and provider report are compared. A mismatch is a P0 incident." />
      <ErrorAlert error={error} />
      {bad > 0 && <div className="alert alert-error" role="alert"><strong>{bad} day(s) do not reconcile.</strong> Investigate before the next payout run.</div>}
      <section className="card panel">
        <div className="row" style={{ alignItems: 'flex-end', gap: 12 }}>
          <label className="filter-box"><span>Day (UTC)</span><input type="date" value={day} max={new Date().toISOString().slice(0, 10)} onChange={(e) => setDay(e.target.value)} /></label>
          <button className="btn btn-primary" disabled={busy || !day} onClick={run}>{busy ? 'Checking…' : 'Run reconciliation'}</button>
        </div>
      </section>
      <section className="card panel">
        {rows && rows.length === 0 ? (
          <EmptyTable columns={['Day', 'Result', 'Checks', 'Run by']}><strong>No reconciliations yet.</strong> The first scheduled run happens tonight.</EmptyTable>
        ) : (
          <table className="data"><thead><tr><th>Day</th><th>Result</th><th>Checks</th><th>Run</th><th /></tr></thead>
            <tbody>{(rows ?? []).map((r) => <Fragment key={r.id}>
              <tr>
                <td><strong>{r.day}</strong></td>
                <td><span className={`badge ${r.status === 'MATCHED' ? 'green' : 'warn'}`}>{r.status === 'MATCHED' ? 'Matched' : `${r.mismatches} mismatch(es)`}</span></td>
                <td className="small">{r.checks.length}</td>
                <td className="small">{r.runBy === 'SCHEDULE' ? 'Nightly' : r.runBy === 'CLI' ? 'Command line' : 'Manual'} · {new Date(r.updatedAt).toLocaleString()}</td>
                <td><button className="btn btn-ghost btn-sm" onClick={() => setOpen(open === r.id ? null : r.id)}><Icon name="search" /> {open === r.id ? 'Hide' : 'Details'}</button></td>
              </tr>
              {open === r.id && <tr><td colSpan={5}>
                {r.checks.length === 0 ? <p className="muted small" style={{ margin: 0 }}>No money moved that day.</p> : (
                  <table className="data"><thead><tr><th>Check</th><th>Escrow ledger</th><th>Payments</th><th>Provider</th><th>Difference</th></tr></thead>
                    <tbody>{r.checks.map((c) => (
                      <tr key={c.name + c.currency}>
                        <td>{c.ok ? '✓' : '✗'} {CHECK_LABEL[c.name] ?? c.name}</td>
                        <td>{formatMoney({ amountMinor: c.ledger, currency: c.currency })}</td>
                        <td>{formatMoney({ amountMinor: c.payments, currency: c.currency })}</td>
                        <td className="small">{c.provider === null ? 'No report (test provider)' : formatMoney({ amountMinor: c.provider, currency: c.currency })}</td>
                        <td>{c.ok ? '—' : <strong>{formatMoney({ amountMinor: c.difference, currency: c.currency })}</strong>}</td>
                      </tr>))}</tbody></table>
                )}</td></tr>}
            </Fragment>)}</tbody></table>
        )}
      </section>
    </>
  )
}
