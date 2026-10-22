import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { submittedNotice } from '../../api/approvals'
import { paymentsApi, type OpsItem, type Reconciliation } from '../../api/escrow'
import { formatMoney } from '../../api/orgs'
import { AdminHeader, AdminKpi, Callout, CountTabs, DetailPanel, Facts, FilterBar, FilterSelect, KpiStrip, ListDetail, MetricList, Panel,
  PanelRow, Pill, StackBar, TableFoot, shortDate, pickRow } from '../../components/admin'
import { ErrorAlert, useStepUp } from '../../components/ui'

/* Financial Exceptions (design 62): payouts and refunds that still failed after the automatic retries, and chargebacks
   the platform paid for. Staff retry them or ask to close them with what happened; a close is a maker-checker request
   that a second Financial Operations member approves before it is recorded. Amounts are shown per currency only. */

const OPS_KIND: Record<OpsItem['kind'], string> = { PAYOUT: 'Payout to a professional', REFUND: 'Refund to a buyer', CHARGEBACK_LOSS: 'Chargeback loss' }
const SHORT: Record<OpsItem['kind'], string> = { PAYOUT: 'Payouts', REFUND: 'Refunds', CHARGEBACK_LOSS: 'Chargebacks' }
const COLOR: Record<OpsItem['kind'], string> = { PAYOUT: '#2f80ed', REFUND: '#f79009', CHARGEBACK_LOSS: '#9b8afb' }
const KINDS: OpsItem['kind'][] = ['PAYOUT', 'REFUND', 'CHARGEBACK_LOSS']
type Tab = 'open' | OpsItem['kind'] | 'closed'
type Outcome = 'RECOVERED' | 'WRITTEN_OFF' | 'SETTLED_OUTSIDE'

/** "USD 24,000 · EUR 1,000": one total per currency, never added across currencies. */
function perCurrency(items: OpsItem[]): string {
  const t = items.reduce<Record<string, number>>((a, i) => ({ ...a, [i.amount.currency]: (a[i.amount.currency] ?? 0) + i.amount.amountMinor }), {})
  return Object.entries(t).sort().map(([currency, amountMinor]) => formatMoney({ currency, amountMinor })).join(' · ') || 'None'
}
const ageDays = (since: string, now: number) => Math.floor((now - new Date(since).getTime()) / 86_400_000)
const keyOf = (i: OpsItem) => i.kind + i.id

export default function FinancialExceptions() {
  const [items, setItems] = useState<OpsItem[] | null>(null)
  const [history, setHistory] = useState(false)
  const [recon, setRecon] = useState<Reconciliation[] | null>(null)
  const [tab, setTab] = useState<Tab>('open')
  const [search, setSearch] = useState('')
  const [currency, setCurrency] = useState('')
  const [selected, setSelected] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [error, setError] = useState<unknown>(null)
  const { run, modal } = useStepUp(setError)
  const [now] = useState(() => Date.now())  // read the clock once, not on every render
  useEffect(() => { paymentsApi.opsWorklist(history).then((r) => setItems(r.items)).catch(setError) }, [history])
  // Reconciliation breaks are a separate control; shown only for reference and only when this role can read them.
  useEffect(() => { paymentsApi.reconciliations().then(setRecon).catch(() => setRecon(null)) }, [])

  const all = items ?? []
  const open = all.filter((i) => !i.resolution)
  const closed = all.filter((i) => i.resolution)
  const currencies = [...new Set(all.map((i) => i.amount.currency))].sort()
  const term = search.trim().toLowerCase()
  const rows = (tab === 'closed' ? closed : tab === 'open' ? open : open.filter((i) => i.kind === tab))
    .filter((i) => (!currency || i.amount.currency === currency)
      && (!term || [i.engagement, i.buyer, i.professional, i.problem, i.id, OPS_KIND[i.kind]].some((v) => v.toLowerCase().includes(term))))
  const sel = all.find((i) => keyOf(i) === selected) ?? null
  const retryable = open.filter((i) => i.canRetry && i.kind !== 'CHARGEBACK_LOSS')
  const latestRecon = [...(recon ?? [])].sort((a, b) => b.day.localeCompare(a.day))[0] ?? null

  const changeTab = (t: Tab) => { setTab(t); setSelected(null); if (t === 'closed') setHistory(true) }

  return (
    <>
      {modal}
      <AdminHeader crumb="Financial operations / Governed exception resolution" title="Financial Exceptions"
        subtitle="Payouts and refunds that still failed after the automatic retries, and chargebacks the platform paid for. Retry them, or close them with what happened."
        actions={<label className="checkbox"><input type="checkbox" checked={history} onChange={(e) => { setHistory(e.target.checked); if (!e.target.checked && tab === 'closed') setTab('open') }} /> <span>Show closed</span></label>}
        meta={<span>Amounts are case references per currency, not custody balances</span>} />
      {notice && <div className="alert alert-success" role="status">{notice}</div>}
      <ErrorAlert error={error} />

      <KpiStrip>
        <AdminKpi icon="alert" tone="red" label="Open cases" value={items ? open.length : '—'} sub={items ? perCurrency(open) : undefined} />
        <AdminKpi icon="wallet" tone="blue" label="Failed payouts" value={items ? open.filter((i) => i.kind === 'PAYOUT').length : '—'} sub={items ? perCurrency(open.filter((i) => i.kind === 'PAYOUT')) : undefined} />
        <AdminKpi icon="download" tone="amber" label="Failed refunds" value={items ? open.filter((i) => i.kind === 'REFUND').length : '—'} sub={items ? perCurrency(open.filter((i) => i.kind === 'REFUND')) : undefined} />
        <AdminKpi icon="lock" tone="violet" label="Chargeback losses" value={items ? open.filter((i) => i.kind === 'CHARGEBACK_LOSS').length : '—'} sub={items ? perCurrency(open.filter((i) => i.kind === 'CHARGEBACK_LOSS')) : undefined} />
        <AdminKpi icon="refresh" tone="teal" label="Retry available" value={items ? retryable.length : '—'} sub="Can be sent again now" />
        <AdminKpi icon="check" tone="green" label="Closed" value={history ? closed.length : '—'} sub={history ? 'Shown in Resolved history' : 'Tick “Show closed”'} />
      </KpiStrip>

      <PanelRow cols={3}>
        <Panel title="Open exception exposure by type" meta="Case counts">
          <StackBar segments={KINDS.map((k) => ({ label: SHORT[k], value: open.filter((i) => i.kind === k).length, color: COLOR[k] }))} />
          <MetricList rows={KINDS.map((k) => ({ label: SHORT[k], value: perCurrency(open.filter((i) => i.kind === k)) }))} />
        </Panel>
        <Panel title="Case stage" meta="Open cases">
          <MetricList rows={[
            { label: 'Retry available', value: retryable.length, tone: retryable.length ? 'amber' : undefined },
            { label: 'Needs a closing decision', value: open.length - retryable.length, tone: open.length - retryable.length ? 'red' : undefined },
            { label: 'Open more than 7 days', value: open.filter((i) => ageDays(i.since, now) > 7).length },
            { label: 'Open more than 30 days', value: open.filter((i) => ageDays(i.since, now) > 30).length, tone: open.some((i) => ageDays(i.since, now) > 30) ? 'red' : undefined },
          ]} />
        </Panel>
        {latestRecon && <Panel title="Separate reconciliation control" meta={`Run ${latestRecon.day}`}>
          <Callout tone={latestRecon.status === 'MATCHED' ? 'green' : 'red'} title={latestRecon.status === 'MATCHED' ? 'Latest run matched' : `${latestRecon.mismatches} reconciliation break(s)`}>
            Not included above. Reconciliation breaks are tracked on the Reconciliation page.</Callout>
          <p className="adm-foot-note"><Link to="/platform-admin/reconciliation">Open reconciliation</Link></p>
        </Panel>}
      </PanelRow>

      <ListDetail
        list={
          <div className="card">
            <CountTabs<Tab> value={tab} onChange={changeTab} tabs={[
              { key: 'open', label: 'Open cases', count: items ? open.length : null },
              ...KINDS.map((k) => ({ key: k as Tab, label: SHORT[k], count: items ? open.filter((i) => i.kind === k).length : null })),
              { key: 'closed', label: 'Resolved history', count: history ? closed.length : null },
            ]} />
            <FilterBar search={search} onSearch={setSearch} placeholder="Search engagement, party or problem…">
              {currencies.length > 1 && <FilterSelect label="All currencies" value={currency} onChange={setCurrency} options={currencies.map((c) => [c, c])} />}
            </FilterBar>
            <div className="adm-table-wrap"><table className="data">
              <thead><tr><th scope="col">Problem</th><th scope="col">Engagement</th><th scope="col">Amount</th><th scope="col">Since</th><th scope="col">State</th></tr></thead>
              <tbody>
                {items && rows.length === 0 && <tr><td colSpan={5} className="empty-row">{tab === 'closed' ? 'No closed cases.' : <><strong>Nothing needs attention.</strong> Failed payouts and refunds
                  are retried automatically first; only what still fails shows here.</>}</td></tr>}
                {!items && !error && <tr><td colSpan={5} className="empty-row">Loading…</td></tr>}
                {rows.map((i) => (
                  <tr {...pickRow} key={keyOf(i)} className={`pick ${selected === keyOf(i) ? 'selected' : ''}`} onClick={() => setSelected(keyOf(i))}>
                    <td><div className="cell-main">{OPS_KIND[i.kind]}</div><div className="cell-sub">{i.problem}</div></td>
                    <td><div className="cell-id">{i.engagement}</div><div className="cell-sub">{i.buyer} · {i.professional}</div></td>
                    <td><strong>{formatMoney(i.amount)}</strong></td>
                    <td className="small">{shortDate(i.since)}<div className="cell-sub">{ageDays(i.since, now)} days</div></td>
                    <td>{i.resolution ? <Pill tone="green">Closed</Pill> : i.canRetry && i.kind !== 'CHARGEBACK_LOSS' ? <Pill tone="amber">Retry available</Pill> : <Pill tone="red">Decision due</Pill>}</td>
                  </tr>))}
              </tbody>
            </table></div>
            <TableFoot shown={rows.length} total={tab === 'closed' ? closed.length : open.length} noun="cases" />
          </div>
        }
        detail={sel && <ExceptionDetail key={keyOf(sel)} i={sel} now={now} onClose={() => setSelected(null)}
          onRetry={() => run(async () => { setItems((await paymentsApi.opsRetry(sel.kind as 'PAYOUT' | 'REFUND', sel.id)).items); setNotice('Sent again.') })}
          onResolve={(outcome, note) => run(async () => {
            const request = await paymentsApi.opsResolve(sel.kind, sel.id, outcome, note)
            setSelected(null); setNotice(`${OPS_KIND[sel.kind]}: ${submittedNotice(request)}`)
          })} />}
      />
    </>
  )
}

function ExceptionDetail({ i, now, onClose, onRetry, onResolve }: {
  i: OpsItem; now: number; onClose: () => void; onRetry: () => void; onResolve: (outcome: Outcome, note: string) => void
}) {
  const [closing, setClosing] = useState(false)
  const [outcome, setOutcome] = useState<Outcome>(i.kind === 'CHARGEBACK_LOSS' ? 'WRITTEN_OFF' : 'SETTLED_OUTSIDE')
  const [note, setNote] = useState('')
  const canRetry = !i.resolution && i.canRetry && i.kind !== 'CHARGEBACK_LOSS'
  return (
    <DetailPanel title={OPS_KIND[i.kind]} subtitle={`${i.engagement} · ${formatMoney(i.amount)}`}
      badge={i.resolution ? <Pill tone="green">Closed</Pill> : <Pill tone="red">Open</Pill>} onClose={onClose}
      footer={!i.resolution && !closing ? <>
        {canRetry && <button type="button" className="btn btn-secondary btn-sm" onClick={onRetry}>Retry now</button>}
        <button type="button" className="btn btn-primary btn-sm" onClick={() => setClosing(true)}>Close…</button>
      </> : undefined}>
      {!i.resolution && <Callout tone={canRetry ? 'amber' : 'red'} title={canRetry ? 'Retry available' : 'Closing decision needed'}>{i.problem}</Callout>}
      {i.resolution && <Callout tone="green" title={`Closed ${i.resolvedAt ? shortDate(i.resolvedAt) : ''}`}>{i.resolution}</Callout>}
      <Facts title="Financial exception facts" rows={[
        ['Type', OPS_KIND[i.kind]], ['Amount', formatMoney(i.amount)], ['Engagement', <code key="e">{i.engagement}</code>],
        ['Buyer', i.buyer], ['Professional', i.professional], ['Since', `${shortDate(i.since)} · ${ageDays(i.since, now)} days`],
        ['Reference', <code key="r">{i.id}</code>],
      ]} />
      {closing && <form onSubmit={(e) => { e.preventDefault(); onResolve(outcome, note.trim()) }}>
        <p className="muted small" style={{ marginTop: 0 }}>Record what happened. Another Financial Operations member approves it before
          the item is closed; it cannot be changed later and goes into the audit trail.</p>
        <label className="label" htmlFor="ops-outcome">Outcome</label>
        <select id="ops-outcome" className="input" value={outcome} onChange={(e) => setOutcome(e.target.value as Outcome)}>
          <option value="SETTLED_OUTSIDE">Settled another way (e.g. bank transfer)</option>
          <option value="RECOVERED">Money recovered</option>
          <option value="WRITTEN_OFF">Written off</option>
        </select>
        <label className="label" htmlFor="ops-note" style={{ marginTop: 10 }}>What happened</label>
        <textarea id="ops-note" className="input" rows={3} maxLength={1000} value={note} onChange={(e) => setNote(e.target.value)} required />
        <div className="row" style={{ marginTop: 10 }}>
          <button className="btn btn-primary btn-sm" disabled={note.trim().length < 10}>Request approval to close</button>
          <button type="button" className="btn btn-ghost btn-sm" onClick={() => setClosing(false)}>Cancel</button>
        </div>
      </form>}
    </DetailPanel>
  )
}
