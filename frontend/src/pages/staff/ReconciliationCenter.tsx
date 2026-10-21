import { useCallback, useEffect, useState } from 'react'
import { paymentsApi, type Reconciliation, type ReconciliationCheck } from '../../api/escrow'
import { formatMoney } from '../../api/orgs'
import { AdminHeader, AdminKpi, Callout, Checklist, CountTabs, DetailPanel, Facts, FilterBar, FilterSelect, KpiStrip, ListDetail, Panel,
  PanelRow, Pill, StatusPill, TableFoot, TrendChart, shortDateTime } from '../../components/admin'
import { ErrorAlert, useStepUp } from '../../components/ui'

/* Reconciliation (design 60; Engineering Handbook 15.4). Every night the escrow ledger, the payments records and the
   provider's report are compared per currency; any difference is a P0 financial incident. Staff can run a day again. */

const CHECK_LABEL: Record<string, string> = {
  charges: 'Buyer payments captured', payouts: 'Owed to professionals', refunds: 'Refunds to buyers', chargebacks: 'Chargebacks',
}
const checkLabel = (c: ReconciliationCheck) => CHECK_LABEL[c.name] ?? c.name
const keyOf = (c: ReconciliationCheck) => `${c.name}:${c.currency}`
const runByLabel = (r: Reconciliation) => (r.runBy === 'SCHEDULE' ? 'Nightly' : r.runBy === 'CLI' ? 'Command line' : 'Manual')
const yesterday = () => new Date(Date.now() - 86_400_000).toISOString().slice(0, 10)
const m = (minor: number | null, currency: string) => (minor === null ? 'No report' : formatMoney({ amountMinor: minor, currency }))

type Tab = 'all' | 'breaks' | 'passed' | 'runs'

export default function ReconciliationCenter() {
  const [rows, setRows] = useState<Reconciliation[] | null>(null)
  const [day, setDay] = useState(yesterday)
  const [today] = useState(() => new Date().toISOString().slice(0, 10))  // read the clock once, not on every render
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<unknown>(null)
  const { run, modal } = useStepUp(setError)
  const [runId, setRunId] = useState<string | null>(null)
  const [tab, setTab] = useState<Tab>('all')
  const [currency, setCurrency] = useState('')
  const [search, setSearch] = useState('')
  const [selected, setSelected] = useState<string | null>(null)

  const load = useCallback(() => paymentsApi.reconciliations().then(setRows).catch(setError), [])
  useEffect(() => { load() }, [load])

  const start = () => {
    setBusy(true); setError(null)
    run(async () => {
      const r = await paymentsApi.reconcile(day)
      setRunId(r.id); setTab('all'); setSelected(null)
      await load()
    }).finally(() => setBusy(false))
  }

  const byDay = [...(rows ?? [])].sort((a, b) => b.day.localeCompare(a.day) || b.updatedAt.localeCompare(a.updatedAt))
  const latest = byDay[0] ?? null
  const current = byDay.find((r) => r.id === runId) ?? latest
  const bad = (rows ?? []).filter((r) => r.status === 'MISMATCH').length
  const currencies = [...new Set((current?.checks ?? []).map((c) => c.currency))].sort()
  const cur = currency && currencies.includes(currency) ? currency : currencies[0] ?? ''
  const checks = current?.checks ?? []
  const passed = checks.filter((c) => c.ok).length
  const term = search.trim().toLowerCase()
  const shown = checks.filter((c) => (tab === 'breaks' ? !c.ok : tab === 'passed' ? c.ok : true) && (!currency || c.currency === currency)
    && (!term || `${checkLabel(c)} ${c.name} ${c.currency}`.toLowerCase().includes(term)))
  const chartRuns = [...byDay].reverse().slice(-14)
  const selCheck = checks.find((c) => keyOf(c) === selected) ?? null
  const selRun = tab === 'runs' ? byDay.find((r) => r.id === selected) ?? null : null

  return (
    <>
      {modal}
      <AdminHeader crumb="Financial operations / Three-way custody assurance" title="Reconciliation"
        subtitle="Each night at 01:00 UTC the escrow ledger, payments records and provider report are compared per currency. A mismatch is a P0 incident."
        actions={<>
          <label className="small muted" style={{ display: 'inline-flex', gap: 8, alignItems: 'center' }}>Day (UTC)
            <input className="adm-filter" type="date" value={day} max={today} onChange={(e) => setDay(e.target.value)} /></label>
          <button className="btn btn-primary" disabled={busy || !day} onClick={start}>{busy ? 'Checking…' : 'Run reconciliation'}</button>
        </>}
        meta={current ? <span>Run {current.day} · {runByLabel(current)} · updated {shortDateTime(current.updatedAt)} UTC</span> : undefined} />
      <ErrorAlert error={error} />
      {bad > 0 && <div className="alert alert-error" role="alert"><strong>{bad} day(s) do not reconcile.</strong> Investigate before the next payout run.</div>}
      {rows && rows.length === 0 && <Callout tone="blue" title="No reconciliations yet">The first scheduled run happens tonight.</Callout>}

      {current && <KpiStrip>
        <AdminKpi icon="refresh" tone="blue" label={current.id === latest?.id ? 'Latest run' : 'Selected run'} value={current.day} sub={`${runByLabel(current)} · ${shortDateTime(current.updatedAt)}`} />
        <AdminKpi icon={current.status === 'MATCHED' ? 'check' : 'alert'} tone={current.status === 'MATCHED' ? 'green' : 'red'} label="Result"
          value={current.status === 'MATCHED' ? 'Matched' : 'Mismatch'} sub={`${current.mismatches} mismatch(es)`} />
        <AdminKpi icon="list" tone="teal" label="Checks passed" value={`${passed} / ${checks.length}`} sub={checks.length ? `${Math.round((passed / checks.length) * 100)}% of checks` : 'No money moved that day'} />
        <AdminKpi icon="alert" tone="amber" label="Unresolved breaks" value={checks.length - passed} sub="Differences in this run" />
        <AdminKpi icon="globe" tone="violet" label="Currencies" value={currencies.length} sub={currencies.join(' · ') || '—'} />
        <AdminKpi icon="scale" tone="red" label="Days not reconciling" value={bad} sub={`Of ${rows?.length ?? 0} runs on record`} />
      </KpiStrip>}

      {current && <PanelRow cols={2}>
        <Panel title="Three-way source control" meta={cur ? `One currency · ${cur}` : undefined}
          action={currencies.length > 1 ? <select className="adm-filter" aria-label="Source control currency" value={cur} onChange={(e) => setCurrency(e.target.value)}>
            {currencies.map((c) => <option key={c} value={c}>{c}</option>)}</select> : undefined}>
          {checks.length === 0 ? <p className="muted small">No money moved that day.</p> : (
            <div className="adm-table-wrap"><table className="data">
              <thead><tr><th>Check</th><th>Escrow ledger</th><th>Payments</th><th>Provider</th><th>Result</th></tr></thead>
              <tbody>{checks.filter((c) => c.currency === cur).map((c) => (
                <tr key={keyOf(c)}><td>{checkLabel(c)}</td><td>{m(c.ledger, c.currency)}</td><td>{m(c.payments, c.currency)}</td>
                  <td className="small">{c.provider === null ? 'No report (test provider)' : m(c.provider, c.currency)}</td>
                  <td>{c.ok ? <Pill tone="green">Matched</Pill> : <Pill tone="red">{m(c.difference, c.currency)}</Pill>}</td></tr>))}</tbody>
            </table></div>
          )}
        </Panel>
        <Panel title="Daily matching quality" meta={`${chartRuns.length} most recent runs`}>
          <TrendChart kind="bar" labels={chartRuns.map((r) => r.day.slice(5))} series={[
            { label: 'Checks matched', values: chartRuns.map((r) => r.checks.filter((c) => c.ok).length), color: '#12b76a' },
            { label: 'Mismatches', values: chartRuns.map((r) => r.mismatches), color: '#f04438' },
          ]} />
        </Panel>
      </PanelRow>}

      <ListDetail
        list={
          <div className="card">
            <CountTabs<Tab> value={tab} onChange={(t) => { setTab(t); setSelected(null) }} tabs={[
              { key: 'all', label: 'All checks & findings', count: checks.length },
              { key: 'breaks', label: 'Open breaks', count: checks.length - passed },
              { key: 'passed', label: 'Passed controls', count: passed },
              { key: 'runs', label: 'Run history', count: rows?.length ?? null },
            ]} />
            {tab !== 'runs' ? <>
              <FilterBar search={search} onSearch={setSearch} placeholder="Search check or currency…">
                {currencies.length > 1 && <FilterSelect label="All currencies" value={currency} onChange={setCurrency} options={currencies.map((c) => [c, c])} />}
              </FilterBar>
              {current && <div className="adm-note">Run {current.day} · {checks.length} checks · {checks.length - passed} unresolved</div>}
              <div className="adm-table-wrap"><table className="data">
                <thead><tr><th>Check</th><th>Finding</th><th>Escrow ledger</th><th>Difference</th><th>Result</th></tr></thead>
                <tbody>
                  {shown.length === 0 && <tr><td colSpan={5} className="empty-row">{current ? 'No checks match.' : 'No reconciliation runs yet.'}</td></tr>}
                  {shown.map((c) => (
                    <tr key={keyOf(c)} className={`pick ${selected === keyOf(c) ? 'selected' : ''}`} onClick={() => setSelected(keyOf(c))}>
                      <td><div className="cell-main">{checkLabel(c)}</div><div className="cell-sub">{c.currency}</div></td>
                      <td className="small">{c.ok ? 'Ledger, payments and provider agree' : c.provider === null ? 'Ledger and payments differ' : 'Sources differ'}</td>
                      <td>{m(c.ledger, c.currency)}</td>
                      <td>{c.ok ? '—' : <strong>{m(c.difference, c.currency)}</strong>}</td>
                      <td>{c.ok ? <Pill tone="green">Passed</Pill> : <Pill tone="red">Mismatch</Pill>}</td>
                    </tr>))}
                </tbody>
              </table></div>
              <TableFoot shown={shown.length} total={checks.length} noun="checks" />
            </> : <>
              <div className="adm-table-wrap"><table className="data">
                <thead><tr><th>Day</th><th>Result</th><th>Checks</th><th>Run</th></tr></thead>
                <tbody>
                  {byDay.length === 0 && <tr><td colSpan={4} className="empty-row">No reconciliations yet.</td></tr>}
                  {byDay.map((r) => (
                    <tr key={r.id} className={`pick ${selected === r.id ? 'selected' : ''}`} onClick={() => setSelected(r.id)}>
                      <td><div className="cell-main">{r.day}</div></td>
                      <td>{r.status === 'MATCHED' ? <Pill tone="green">Matched</Pill> : <Pill tone="red">{r.mismatches} mismatch(es)</Pill>}</td>
                      <td className="small">{r.checks.length}</td>
                      <td className="small">{runByLabel(r)} · {shortDateTime(r.updatedAt)}</td>
                    </tr>))}
                </tbody>
              </table></div>
              <TableFoot shown={byDay.length} noun="runs" />
            </>}
          </div>
        }
        detail={selCheck && tab !== 'runs' ? <CheckDetail c={selCheck} run={current!} onClose={() => setSelected(null)} />
          : selRun ? <DetailPanel title={`Run ${selRun.day}`} subtitle={`${runByLabel(selRun)} · ${shortDateTime(selRun.updatedAt)}`}
            badge={<StatusPill status={selRun.status} />} onClose={() => setSelected(null)}
            footer={<button type="button" className="btn btn-primary btn-sm" onClick={() => { setRunId(selRun.id); setTab('all'); setSelected(null) }}>Show this run's checks</button>}>
            <Facts rows={[['Checks', selRun.checks.length], ['Passed', selRun.checks.filter((c) => c.ok).length], ['Mismatches', selRun.mismatches],
              ['Currencies', [...new Set(selRun.checks.map((c) => c.currency))].join(' · ') || '—']]} />
          </DetailPanel> : undefined}
      />
    </>
  )
}

function CheckDetail({ c, run, onClose }: { c: ReconciliationCheck; run: Reconciliation; onClose: () => void }) {
  return (
    <DetailPanel title={checkLabel(c)} subtitle={`${c.currency} · run ${run.day}`} badge={c.ok ? <Pill tone="green">Passed</Pill> : <Pill tone="red">Mismatch</Pill>} onClose={onClose}>
      {!c.ok && <Callout tone="red" title="Clean close blocked">The sources differ by {m(c.difference, c.currency)}. Investigate before the next payout run.</Callout>}
      <Facts title="Evidence-linked reconciliation" rows={[
        ['Escrow ledger', m(c.ledger, c.currency)],
        ['Payments records', m(c.payments, c.currency)],
        ['Provider report', c.provider === null ? 'No report (test provider)' : m(c.provider, c.currency)],
        ['Difference', c.ok ? '—' : m(c.difference, c.currency)],
        ['Run by', runByLabel(run)],
        ['Run updated', shortDateTime(run.updatedAt)],
      ]} />
      <Checklist title="Control checklist" items={[
        { label: 'Ledger agrees with payments records', state: c.ledger === c.payments ? 'done' : 'missing', note: c.ledger === c.payments ? 'Matched' : 'Differs' },
        { label: 'Provider report received', state: c.provider !== null ? 'done' : 'pending', note: c.provider !== null ? 'Received' : 'None' },
        { label: 'Provider agrees with ledger', state: c.provider === null ? 'pending' : c.provider === c.ledger ? 'done' : 'missing',
          note: c.provider === null ? 'No report' : c.provider === c.ledger ? 'Matched' : 'Differs' },
      ]} />
    </DetailPanel>
  )
}
