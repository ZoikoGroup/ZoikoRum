import { useCallback, useEffect, useState } from 'react'
import { paymentsApi, type BreakStatus, type Reconciliation, type ReconciliationBreak, type ReconciliationCheck } from '../../api/escrow'
import { formatMoney } from '../../api/orgs'
import { AdminHeader, AdminKpi, Callout, Checklist, CountTabs, DetailPanel, Facts, FilterBar, FilterSelect, KpiStrip, ListDetail, Panel,
  PanelRow, Pill, TableFoot, TrendChart, shortDateTime, type PillTone, pickRow } from '../../components/admin'
import { ErrorAlert, useStepUp } from '../../components/ui'

/* Reconciliation (design 60; Engineering Handbook 15.4; PAY-02 suspense). Every night the escrow ledger, the payments
   records and the provider's report are compared per currency; any difference is a P0 financial incident and becomes a
   break that Financial Ops move OPEN -> EVIDENCE_GATHERING -> REVIEWED -> CLOSED (closing needs a fresh step-up and a
   different person from the reviewer). A day is never shown as clean while any of its breaks is unresolved. */

const CHECK_LABEL: Record<string, string> = {
  charges: 'Buyer payments captured', payouts: 'Owed to professionals', refunds: 'Refunds to buyers', chargebacks: 'Chargebacks',
}
const checkLabel = (c: ReconciliationCheck) => CHECK_LABEL[c.name] ?? c.name
const kindLabel = (k: string) => CHECK_LABEL[k] ?? k
const keyOf = (c: ReconciliationCheck) => `${c.name}:${c.currency}`
const runByLabel = (r: Reconciliation) => (r.runBy === 'SCHEDULE' ? 'Nightly' : r.runBy === 'CLI' ? 'Command line' : 'Manual')
const yesterday = () => new Date(Date.now() - 86_400_000).toISOString().slice(0, 10)
const m = (minor: number | null | undefined, currency: string) => (minor === null || minor === undefined ? 'No report' : formatMoney({ amountMinor: minor, currency }))

const RUN_STATUS: Record<Reconciliation['runStatus'], { label: string; tone: PillTone }> = {
  CLEAN: { label: 'Clean', tone: 'green' }, BREAKS_OPEN: { label: 'Breaks open', tone: 'red' }, BREAKS_RESOLVED: { label: 'Breaks resolved', tone: 'blue' },
}
const runPill = (r: Reconciliation) => <Pill tone={RUN_STATUS[r.runStatus].tone}>{r.runStatus === 'BREAKS_OPEN' ? `${r.openBreaks} break(s) open` : RUN_STATUS[r.runStatus].label}</Pill>

const BREAK_STEPS: BreakStatus[] = ['OPEN', 'EVIDENCE_GATHERING', 'REVIEWED', 'CLOSED']
const BREAK_LABEL: Record<BreakStatus, string> = { OPEN: 'Open', EVIDENCE_GATHERING: 'Gathering evidence', REVIEWED: 'Reviewed', CLOSED: 'Closed' }
const BREAK_TONE: Record<BreakStatus, PillTone> = { OPEN: 'red', EVIDENCE_GATHERING: 'amber', REVIEWED: 'blue', CLOSED: 'green' }
const breakPill = (b: ReconciliationBreak) => <Pill tone={BREAK_TONE[b.status]}>{BREAK_LABEL[b.status]}</Pill>
const nextStep = (s: BreakStatus) => BREAK_STEPS[BREAK_STEPS.indexOf(s) + 1] as Exclude<BreakStatus, 'OPEN'> | undefined

type Tab = 'all' | 'breaks' | 'passed' | 'runs'
type BreakFilter = '' | BreakStatus | 'UNRESOLVED'

export default function ReconciliationCenter() {
  const [rows, setRows] = useState<Reconciliation[] | null>(null)
  const [breaks, setBreaks] = useState<ReconciliationBreak[] | null>(null)
  const [day, setDay] = useState(yesterday)
  const [today] = useState(() => new Date().toISOString().slice(0, 10))  // read the clock once, not on every render
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<unknown>(null)
  const [notice, setNotice] = useState('')
  const { run, modal } = useStepUp(setError)
  const [runId, setRunId] = useState<string | null>(null)
  const [tab, setTab] = useState<Tab>('all')
  const [currency, setCurrency] = useState('')
  const [breakFilter, setBreakFilter] = useState<BreakFilter>('UNRESOLVED')
  const [search, setSearch] = useState('')
  const [selected, setSelected] = useState<string | null>(null)

  const load = useCallback(() => Promise.all([
    paymentsApi.reconciliations().then(setRows),
    paymentsApi.reconciliationBreaks().then(setBreaks),
  ]).catch(setError), [])
  useEffect(() => { load() }, [load])

  const start = () => {
    setBusy(true); setError(null); setNotice('')
    run(async () => {
      const r = await paymentsApi.reconcile(day)
      setRunId(r.id); setTab('all'); setSelected(null)
      await load()
    }).finally(() => setBusy(false))
  }

  const advance = (b: ReconciliationBreak, note: string) => {
    const to = nextStep(b.status)
    if (!to) return Promise.resolve()
    setBusy(true); setError(null); setNotice('')
    return run(async () => {
      await paymentsApi.advanceBreak(b.id, to, note)
      await load()
      setNotice(`Break ${kindLabel(b.kind)} · ${b.currency} · ${b.day} moved to ${BREAK_LABEL[to].toLowerCase()}.`)
    }).finally(() => setBusy(false))
  }

  const byDay = [...(rows ?? [])].sort((a, b) => b.day.localeCompare(a.day) || b.updatedAt.localeCompare(a.updatedAt))
  const latest = byDay[0] ?? null
  const current = byDay.find((r) => r.id === runId) ?? latest
  const daysOpen = (rows ?? []).filter((r) => r.runStatus === 'BREAKS_OPEN').length
  const allBreaks = breaks ?? []
  const unresolved = allBreaks.filter((b) => b.status !== 'CLOSED')
  const currencies = [...new Set((current?.checks ?? []).map((c) => c.currency))].sort()
  const cur = currency && currencies.includes(currency) ? currency : currencies[0] ?? ''
  const checks = current?.checks ?? []
  const passed = checks.filter((c) => c.ok).length
  const term = search.trim().toLowerCase()
  const shown = checks.filter((c) => (tab === 'passed' ? c.ok : true) && (!currency || c.currency === currency)
    && (!term || `${checkLabel(c)} ${c.name} ${c.currency}`.toLowerCase().includes(term)))
  const shownBreaks = allBreaks.filter((b) => (breakFilter === 'UNRESOLVED' ? b.status !== 'CLOSED' : !breakFilter || b.status === breakFilter)
    && (!currency || b.currency === currency)
    && (!term || `${kindLabel(b.kind)} ${b.kind} ${b.currency} ${b.day} ${b.owner ?? ''}`.toLowerCase().includes(term)))
  const chartRuns = [...byDay].reverse().slice(-14)
  const selCheck = tab === 'all' || tab === 'passed' ? checks.find((c) => keyOf(c) === selected) ?? null : null
  const selRun = tab === 'runs' ? byDay.find((r) => r.id === selected) ?? null : null
  const selBreak = tab === 'breaks' ? allBreaks.find((b) => b.id === selected) ?? null : null
  const breakFor = (c: ReconciliationCheck, d: string) => allBreaks.find((b) => b.day === d && b.kind === c.name && b.currency === c.currency) ?? null
  const breakCurrencies = [...new Set(allBreaks.map((b) => b.currency))].sort()

  return (
    <>
      {modal}
      <AdminHeader crumb="Financial operations / Three-way custody assurance" title="Reconciliation"
        subtitle="Each night at 01:00 UTC the escrow ledger, payments records and provider report are compared per currency. Every difference is a break that must be evidenced, reviewed and closed by a second person."
        actions={<>
          <label className="small muted" style={{ display: 'inline-flex', gap: 8, alignItems: 'center' }}>Day (UTC)
            <input className="adm-filter" type="date" value={day} max={today} onChange={(e) => setDay(e.target.value)} /></label>
          <button className="btn btn-primary" disabled={busy || !day} onClick={start}>{busy ? 'Checking…' : 'Run reconciliation'}</button>
        </>}
        meta={current ? <span>Run {current.day} · {runByLabel(current)} · updated {shortDateTime(current.updatedAt)} UTC</span> : undefined} />
      <ErrorAlert error={error} />
      {notice && <div className="alert alert-success" role="status">{notice}</div>}
      {daysOpen > 0 && <div className="alert alert-error" role="alert"><strong>{daysOpen} day(s) have open breaks ({unresolved.length} break(s) unresolved).</strong> No day reports clean until its breaks are closed.</div>}
      {rows && rows.length === 0 && <Callout tone="blue" title="No reconciliations yet">The first scheduled run happens tonight.</Callout>}
      {current?.runStatus === 'BREAKS_OPEN' && (
        <Callout tone="red" title={`Clean close blocked for ${current.day}`}>
          {current.openBreaks} break(s) for this day are not closed{current.status === 'MATCHED' ? ' (the sources agree again, but each break still needs its explanation and a second-person close)' : ''}.{' '}
          <button type="button" className="btn btn-ghost btn-sm" onClick={() => { setTab('breaks'); setBreakFilter('UNRESOLVED'); setSelected(null) }}>Open break register</button>
        </Callout>
      )}

      {current && <KpiStrip>
        <AdminKpi icon="refresh" tone="blue" label={current.id === latest?.id ? 'Latest run' : 'Selected run'} value={current.day} sub={`${runByLabel(current)} · ${shortDateTime(current.updatedAt)}`} />
        <AdminKpi icon={current.runStatus === 'CLEAN' ? 'check' : 'alert'} tone={current.runStatus === 'CLEAN' ? 'green' : current.runStatus === 'BREAKS_OPEN' ? 'red' : 'blue'} label="Result"
          value={RUN_STATUS[current.runStatus].label} sub={`${current.mismatches} mismatch(es) · ${current.breaks} break(s) recorded`} />
        <AdminKpi icon="list" tone="teal" label="Checks passed" value={`${passed} / ${checks.length}`} sub={checks.length ? `${Math.round((passed / checks.length) * 100)}% of checks` : 'No money moved that day'} />
        <AdminKpi icon="alert" tone="amber" label="Unresolved breaks" value={breaks ? unresolved.length : '—'} sub={`${current.openBreaks} for this run's day`} />
        <AdminKpi icon="globe" tone="violet" label="Currencies" value={currencies.length} sub={currencies.join(' · ') || '—'} />
        <AdminKpi icon="scale" tone="red" label="Days with open breaks" value={daysOpen} sub={`Of ${rows?.length ?? 0} runs on record`} />
      </KpiStrip>}

      {current && <PanelRow cols={2}>
        <Panel title="Three-way source control" meta={cur ? `One currency · ${cur}` : undefined}
          action={currencies.length > 1 ? <select className="adm-filter" aria-label="Source control currency" value={cur} onChange={(e) => setCurrency(e.target.value)}>
            {currencies.map((c) => <option key={c} value={c}>{c}</option>)}</select> : undefined}>
          {checks.length === 0 ? <p className="muted small">No money moved that day.</p> : (
            <div className="adm-table-wrap"><table className="data">
              <thead><tr><th scope="col">Check</th><th scope="col">Escrow ledger</th><th scope="col">Payments</th><th scope="col">Provider</th><th scope="col">Result</th></tr></thead>
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
              { key: 'breaks', label: 'Break register', count: breaks ? unresolved.length : null },
              { key: 'passed', label: 'Passed controls', count: passed },
              { key: 'runs', label: 'Run history', count: rows?.length ?? null },
            ]} />
            {tab === 'all' || tab === 'passed' ? <>
              <FilterBar search={search} onSearch={setSearch} placeholder="Search check or currency…">
                {currencies.length > 1 && <FilterSelect label="All currencies" value={currency} onChange={setCurrency} options={currencies.map((c) => [c, c])} />}
              </FilterBar>
              {current && <div className="adm-note">Run {current.day} · {checks.length} checks · {checks.length - passed} differ · {current.openBreaks} break(s) open</div>}
              <div className="adm-table-wrap"><table className="data">
                <thead><tr><th scope="col">Check</th><th scope="col">Finding</th><th scope="col">Escrow ledger</th><th scope="col">Difference</th><th scope="col">Result</th></tr></thead>
                <tbody>
                  {shown.length === 0 && <tr><td colSpan={5} className="empty-row">{current ? 'No checks match.' : 'No reconciliation runs yet.'}</td></tr>}
                  {shown.map((c) => {
                    const b = current ? breakFor(c, current.day) : null
                    return (
                      <tr {...pickRow} key={keyOf(c)} className={`pick ${selected === keyOf(c) ? 'selected' : ''}`} onClick={() => setSelected(keyOf(c))}>
                        <td><div className="cell-main">{checkLabel(c)}</div><div className="cell-sub">{c.currency}</div></td>
                        <td className="small">{c.ok ? 'Ledger, payments and provider agree' : c.provider === null ? 'Ledger and payments differ' : 'Sources differ'}</td>
                        <td>{m(c.ledger, c.currency)}</td>
                        <td>{c.ok ? '—' : <strong>{m(c.difference, c.currency)}</strong>}</td>
                        <td>{!c.ok ? <Pill tone="red">Mismatch</Pill> : b && b.status !== 'CLOSED' ? <Pill tone="amber">Agrees · break open</Pill> : <Pill tone="green">Passed</Pill>}</td>
                      </tr>)
                  })}
                </tbody>
              </table></div>
              <TableFoot shown={shown.length} total={checks.length} noun="checks" />
            </> : tab === 'breaks' ? <>
              <FilterBar search={search} onSearch={setSearch} placeholder="Search check, currency, day or owner…">
                <FilterSelect label="Any status" value={breakFilter} onChange={(v) => setBreakFilter(v as BreakFilter)}
                  options={[['UNRESOLVED', 'Unresolved'], ...BREAK_STEPS.map((s) => [s, BREAK_LABEL[s]] as [string, string])]} />
                {breakCurrencies.length > 1 && <FilterSelect label="All currencies" value={currency} onChange={setCurrency} options={breakCurrencies.map((c) => [c, c])} />}
              </FilterBar>
              <div className="adm-note">Suspense items across all days · open → gathering evidence → reviewed → closed by a second person</div>
              <div className="adm-table-wrap"><table className="data">
                <thead><tr><th scope="col">Day</th><th scope="col">Check</th><th scope="col">Difference</th><th scope="col">Owner</th><th scope="col">Status</th><th scope="col"><span className="sr-only">Action</span></th></tr></thead>
                <tbody>
                  {breaks === null && <tr><td colSpan={6} className="empty-row">Loading breaks…</td></tr>}
                  {breaks && shownBreaks.length === 0 && <tr><td colSpan={6} className="empty-row">No breaks here.</td></tr>}
                  {shownBreaks.map((b) => {
                    const to = nextStep(b.status)
                    return (
                      <tr {...pickRow} key={b.id} className={`pick ${selected === b.id ? 'selected' : ''}`} onClick={() => setSelected(b.id)}>
                        <td><div className="cell-main">{b.day}</div><div className="cell-sub">Found {shortDateTime(b.createdAt)}</div></td>
                        <td><div className="cell-main">{kindLabel(b.kind)}</div><div className="cell-sub">{b.currency}</div></td>
                        <td><strong>{m(b.amountMinor, b.currency)}</strong></td>
                        <td className="small">{b.owner ?? 'Unassigned'}</td>
                        <td>{breakPill(b)}</td>
                        <td>{to && <button type="button" className="btn btn-secondary btn-sm" onClick={(e) => { e.stopPropagation(); setSelected(b.id) }}>
                          {to === 'CLOSED' ? 'Close…' : `Move to ${BREAK_LABEL[to].toLowerCase()}…`}</button>}</td>
                      </tr>)
                  })}
                </tbody>
              </table></div>
              <TableFoot shown={shownBreaks.length} total={allBreaks.length} noun="breaks" />
            </> : <>
              <div className="adm-table-wrap"><table className="data">
                <thead><tr><th scope="col">Day</th><th scope="col">Result</th><th scope="col">Checks</th><th scope="col">Run</th></tr></thead>
                <tbody>
                  {byDay.length === 0 && <tr><td colSpan={4} className="empty-row">No reconciliations yet.</td></tr>}
                  {byDay.map((r) => (
                    <tr {...pickRow} key={r.id} className={`pick ${selected === r.id ? 'selected' : ''}`} onClick={() => setSelected(r.id)}>
                      <td><div className="cell-main">{r.day}</div></td>
                      <td>{runPill(r)}</td>
                      <td className="small">{r.checks.length}{r.mismatches ? ` · ${r.mismatches} differ` : ''}</td>
                      <td className="small">{runByLabel(r)} · {shortDateTime(r.updatedAt)}</td>
                    </tr>))}
                </tbody>
              </table></div>
              <TableFoot shown={byDay.length} noun="runs" />
            </>}
          </div>
        }
        detail={selCheck && current ? <CheckDetail c={selCheck} run={current} brk={breakFor(selCheck, current.day)} onClose={() => setSelected(null)}
          onOpenBreak={(id) => { setTab('breaks'); setBreakFilter(''); setSelected(id) }} />
          : selBreak ? <BreakDetail key={selBreak.id} b={selBreak} busy={busy} onAdvance={advance} onClose={() => setSelected(null)} />
          : selRun ? <DetailPanel title={`Run ${selRun.day}`} subtitle={`${runByLabel(selRun)} · ${shortDateTime(selRun.updatedAt)}`}
            badge={runPill(selRun)} onClose={() => setSelected(null)}
            footer={<button type="button" className="btn btn-primary btn-sm" onClick={() => { setRunId(selRun.id); setTab('all'); setSelected(null) }}>Show this run's checks</button>}>
            {selRun.runStatus === 'BREAKS_OPEN' && <Callout tone="red" title="Not clean">{selRun.openBreaks} break(s) for this day are not closed.</Callout>}
            <Facts rows={[['Result', RUN_STATUS[selRun.runStatus].label], ['Checks', selRun.checks.length], ['Passed', selRun.checks.filter((c) => c.ok).length],
              ['Mismatches', selRun.mismatches], ['Breaks recorded', selRun.breaks], ['Breaks open', selRun.openBreaks],
              ['Currencies', [...new Set(selRun.checks.map((c) => c.currency))].join(' · ') || '—']]} />
          </DetailPanel> : undefined}
      />
    </>
  )
}

function CheckDetail({ c, run, brk, onClose, onOpenBreak }: {
  c: ReconciliationCheck; run: Reconciliation; brk: ReconciliationBreak | null; onClose: () => void; onOpenBreak: (id: string) => void
}) {
  return (
    <DetailPanel title={checkLabel(c)} subtitle={`${c.currency} · run ${run.day}`} badge={c.ok ? <Pill tone="green">Passed</Pill> : <Pill tone="red">Mismatch</Pill>} onClose={onClose}
      footer={brk ? <button type="button" className="btn btn-primary btn-sm" onClick={() => onOpenBreak(brk.id)}>Open break ({BREAK_LABEL[brk.status].toLowerCase()})</button> : undefined}>
      {!c.ok && <Callout tone="red" title="Clean close blocked">The sources differ by {m(c.difference, c.currency)}. The break must be evidenced, reviewed and closed by a second person.</Callout>}
      {c.ok && brk && brk.status !== 'CLOSED' && <Callout tone="amber" title="Break still open">The sources agree on this run, but the earlier difference has not been explained and closed.</Callout>}
      <Facts title="Evidence-linked reconciliation" rows={[
        ['Escrow ledger', m(c.ledger, c.currency)],
        ['Payments records', m(c.payments, c.currency)],
        ['Provider report', c.provider === null ? 'No report (test provider)' : m(c.provider, c.currency)],
        ['Difference', c.ok ? '—' : m(c.difference, c.currency)],
        ['Break', brk ? `${BREAK_LABEL[brk.status]}${brk.owner ? ` · ${brk.owner}` : ''}` : '—'],
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

function BreakDetail({ b, busy, onAdvance, onClose }: {
  b: ReconciliationBreak; busy: boolean; onAdvance: (b: ReconciliationBreak, note: string) => Promise<void>; onClose: () => void
}) {
  const [note, setNote] = useState('')
  const to = nextStep(b.status)
  const ok = note.trim().length >= 5
  const ref = b.references
  return (
    <DetailPanel title={`${kindLabel(b.kind)} · ${b.currency}`} subtitle={`Break for ${b.day} · ${m(b.amountMinor, b.currency)}`} badge={breakPill(b)} onClose={onClose}
      footer={to ? <button type="button" className="btn btn-primary btn-sm" disabled={busy || !ok}
        onClick={() => void onAdvance(b, note.trim()).then(() => setNote(''))}>{to === 'CLOSED' ? 'Close break (confirm with MFA)' : `Move to ${BREAK_LABEL[to].toLowerCase()}`}</button> : undefined}>
      {b.status === 'CLOSED'
        ? <Callout tone="green" title="Closed">{b.resolutionNote}</Callout>
        : b.status === 'REVIEWED'
          ? <Callout tone="blue" title="Awaiting a second-person close">The person who reviewed this break cannot close it. Closing needs a fresh MFA confirmation.</Callout>
          : <Callout tone="red" title="Unresolved">Until this break is closed, {b.day} cannot be reported clean.</Callout>}
      <Facts title="Break" rows={[
        ['Difference', m(b.amountMinor, b.currency)],
        ['Escrow ledger', m(ref.ledger, b.currency)],
        ['Payments records', m(ref.payments, b.currency)],
        ['Provider report', ref.provider === null || ref.provider === undefined ? 'No report' : m(ref.provider, b.currency)],
        ['Owner', b.owner ?? 'Unassigned (whoever moves it first)'],
        ['Reviewed', shortDateTime(b.reviewedAt)],
        ['Closed', shortDateTime(b.closedAt)],
      ]} />
      {to && <div className="field"><label htmlFor={`bn-${b.id}`}>{to === 'CLOSED' ? 'Resolution note' : 'Note'} <span className="muted small">(required)</span></label>
        <textarea id={`bn-${b.id}`} className="input" rows={2} maxLength={2000} value={note} onChange={(e) => setNote(e.target.value)}
          placeholder={to === 'EVIDENCE_GATHERING' ? 'What evidence is being gathered' : to === 'REVIEWED' ? 'What the evidence shows' : 'How the difference was resolved'} /></div>}
      <div className="adm-facts"><h3>History</h3>
        <ol style={{ listStyle: 'none', margin: 0, padding: 0, display: 'grid', gap: 8 }}>
          {[...b.history].reverse().map((h, n) => (
            <li key={n} style={{ display: 'grid', gridTemplateColumns: '110px 1fr', gap: 10, fontSize: 13 }}>
              <span className="muted small">{shortDateTime(h.at)}</span>
              <span>{h.fromStatus && h.fromStatus !== h.toStatus ? `${BREAK_LABEL[h.fromStatus as BreakStatus] ?? h.fromStatus} → ` : ''}{BREAK_LABEL[h.toStatus as BreakStatus] ?? h.toStatus}{h.note ? ` · ${h.note}` : ''}</span></li>))}
        </ol></div>
    </DetailPanel>
  )
}
