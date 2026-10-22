import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { submittedNotice, type ApprovalRequest } from '../../api/approvals'
import { api } from '../../api/client'
import { useCapabilities } from '../../auth/capabilities'
import { ErrorAlert, useStepUp } from '../../components/ui'
import { Icon } from '../../components/dashboard'
import {
  AdminHeader, AdminKpi, Callout, CountTabs, DetailPanel, Facts, FilterBar, FilterSelect, HBars, KpiStrip, ListDetail, MetricList, Panel,
  PanelRow, Pill, TableFoot,pickRow } from '../../components/admin'

/* Failed Event Deliveries (design 70): dead-lettered consumer deliveries and governed replay. Sources:
   GET /v1/admin/dead-letters (newest first, 50 a page), GET /v1/admin/worker (totals), and
   POST /v1/admin/dead-letters/{id}/replay (step-up). Standard deliveries are replayed at once. A money delivery is a
   maker-checker request: it is replayed only when a second Financial Operations member approves it (Approvals). */

interface Failure { id: string; eventType: string; consumer: string; attempts: number; financial: boolean; lastError: string }
interface Backlog { retryingDeliveries: number; deadLetters: number; deadFinancialLetters: number }

const PAGE = 50
type TabKey = 'all' | 'money' | 'standard'

function group(rows: Failure[], key: (f: Failure) => string) {
  const m = new Map<string, number>()
  for (const r of rows) m.set(key(r), (m.get(key(r)) ?? 0) + 1)
  return [...m.entries()].sort((a, b) => b[1] - a[1]).map(([label, value]) => ({ label, value }))
}

export default function FailedDeliveries() {
  const { has } = useCapabilities()
  const [rows, setRows] = useState<Failure[] | null>(null)
  const [backlog, setBacklog] = useState<Backlog | null>(null)
  const [page, setPage] = useState(1)
  const [error, setError] = useState<unknown>(null)
  const [notice, setNotice] = useState('')
  const [why, setWhy] = useState('')
  const [tab, setTab] = useState<TabKey>('all')
  const [q, setQ] = useState('')
  const [consumer, setConsumer] = useState('')
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const { run, modal } = useStepUp(setError)

  const reload = useCallback(async () => {
    const [r, b] = await Promise.all([
      api<Failure[]>('/v1/admin/dead-letters', { query: { limit: String(PAGE), offset: String((page - 1) * PAGE) } }),
      api<Backlog>('/v1/admin/worker'),
    ])
    setRows(r); setBacklog(b)
  }, [page])
  useEffect(() => { reload().catch(setError) }, [reload])

  const all = rows ?? []
  const money = all.filter((r) => r.financial)
  const s = q.trim().toLowerCase()
  const shown = all.filter((r) => (tab === 'money' ? r.financial : tab === 'standard' ? !r.financial : true)
    && (!consumer || r.consumer === consumer)
    && (!s || [r.id, r.eventType, r.consumer, r.lastError].some((v) => v.toLowerCase().includes(s))))
  const selected = all.find((r) => r.id === selectedId) ?? null
  const consumers = group(all, (r) => r.consumer)
  const total = backlog?.deadLetters ?? null
  const pages = total ? Math.max(1, Math.ceil(total / PAGE)) : 1
  const canReplay = (f: Failure) => has('dlq.replay') && (!f.financial || has('dlq.replay_financial', 'dlq.replay'))

  const replay = (f: Failure) => run(async () => {
    setNotice('')
    if (f.financial) {
      const request = await api<ApprovalRequest>(`/v1/admin/dead-letters/${f.id}/replay`, { method: 'POST', body: { justification: why.trim() } })
      setWhy('')
      setNotice(`Replay of ${f.eventType} to ${f.consumer}: ${submittedNotice(request)}`)
      return
    }
    const res = await api<{ replayed: boolean }>(`/v1/admin/dead-letters/${f.id}/replay`, { method: 'POST' })
    await reload()
    setNotice(res.replayed ? `${f.eventType} redelivered to ${f.consumer}.` : `${f.eventType} replay to ${f.consumer} failed again; it stays in the queue.`)
    if (res.replayed) setSelectedId(null)
  })

  return (
    <>
      <AdminHeader crumb="Platform reliability / Message recovery" title="Failed Event Deliveries"
        subtitle="Inspect consumer deliveries that used every retry, and trigger authorised replays one at a time."
        actions={<>
          <Link className="btn btn-secondary" to="/platform-admin/service-health-workers"><Icon name="pulse" /> Service health</Link>
          <button type="button" className="btn btn-secondary" onClick={() => reload().catch(setError)}><Icon name="refresh" /> Refresh</button>
        </>} />
      <ErrorAlert error={error} />
      {notice && <div className="alert alert-success" role="status">{notice}</div>}
      {modal}

      <KpiStrip>
        <AdminKpi icon="alert" tone={total ? 'red' : 'green'} label="Open dead letters" value={total ?? '—'} sub="Every retry used" />
        <AdminKpi icon="wallet" tone="amber" label="About money" value={backlog ? backlog.deadFinancialLetters : '—'} sub="Financial Operations replay only" />
        <AdminKpi icon="refresh" tone="blue" label="Still retrying" value={backlog ? backlog.retryingDeliveries : '—'} sub="Not yet dead-lettered" />
        <AdminKpi icon="layers" tone="violet" label="Consumers affected" value={rows ? consumers.length : '—'} sub={pages > 1 ? 'On this page' : undefined} />
        <AdminKpi icon="list" tone="teal" label="Event types" value={rows ? new Set(all.map((r) => r.eventType)).size : '—'} sub={pages > 1 ? 'On this page' : undefined} />
      </KpiStrip>

      <PanelRow cols={3}>
        <Panel title="Failing consumer routes" meta={`Dead letters per consumer${pages > 1 ? ' · this page' : ''}`}>
          <HBars rows={consumers.slice(0, 6)} />
        </Panel>
        <Panel title="Failing event types" meta={pages > 1 ? 'This page' : `${all.length} dead letters`}>
          <HBars rows={group(all, (r) => r.eventType).slice(0, 6)} />
        </Panel>
        <Panel title="Replay authority">
          <MetricList rows={[
            { label: 'Standard deliveries', value: `${all.length - money.length} · Platform Admin or Financial Ops` },
            { label: 'Money deliveries', value: `${money.length} · Financial Ops only`, tone: money.length ? 'amber' : undefined },
            { label: 'Two-step sign-in', value: 'Required for every replay' },
            { label: 'Bulk replay', value: 'Not available' },
          ]} />
        </Panel>
      </PanelRow>

      <ListDetail
        list={
          <div className="card">
            <CountTabs tabs={[
              { key: 'all' as TabKey, label: 'Dead letters', count: all.length },
              { key: 'money' as TabKey, label: 'About money', count: money.length },
              { key: 'standard' as TabKey, label: 'Standard', count: all.length - money.length },
            ]} value={tab} onChange={setTab} />
            <FilterBar search={q} onSearch={setQ} placeholder="Search event type, consumer, error or ID…">
              <FilterSelect label="Consumer" value={consumer} onChange={setConsumer} options={consumers.map((c) => [c.label, c.label])} />
            </FilterBar>
            <div className="adm-note">Scope: current dead letters only · no bulk replay</div>
            <div className="adm-table-wrap">
              <table className="data">
                <thead><tr><th scope="col">Event</th><th scope="col">Consumer</th><th scope="col">Last failure</th><th scope="col">Attempts</th><th scope="col">Authority</th><th scope="col"><span className="sr-only">Action</span></th></tr></thead>
                <tbody>
                  {rows === null && <tr><td colSpan={6} className="empty-row">Loading failed deliveries…</td></tr>}
                  {rows && shown.length === 0 && <tr><td colSpan={6} className="empty-row">No dead-letter event failures in queue. All subscribers processed cleanly.</td></tr>}
                  {shown.map((r) => (
                    <tr {...pickRow} key={r.id} className={`pick ${r.id === selectedId ? 'selected' : ''}`} onClick={() => setSelectedId(r.id)}>
                      <td><div className="cell-main">{r.eventType}</div><div className="cell-sub">{r.id.slice(0, 8)}</div></td>
                      <td className="small">{r.consumer}</td>
                      <td className="small" style={{ color: 'var(--zk-danger)', maxWidth: 260, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={r.lastError}>{r.lastError}</td>
                      <td>{r.attempts}</td>
                      <td><Pill tone={r.financial ? 'red' : 'amber'}>{r.financial ? 'Financial Ops' : 'Standard ops'}</Pill></td>
                      <td><button type="button" className="btn btn-secondary btn-sm" onClick={(e) => { e.stopPropagation(); setSelectedId(r.id) }}>Open</button></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <TableFoot shown={shown.length} total={total} noun="dead letters · newest first" page={page} pages={pages} onPage={(p) => { setPage(p); setSelectedId(null) }} />
          </div>
        }
        detail={selected && (
          <DetailPanel title={selected.eventType} subtitle={<>to <code>{selected.consumer}</code></>}
            badge={<Pill tone={selected.financial ? 'red' : 'amber'}>{selected.financial ? 'Money' : 'Standard'}</Pill>} onClose={() => setSelectedId(null)}
            footer={canReplay(selected)
              ? <button type="button" className="btn btn-primary btn-sm" disabled={selected.financial && why.trim().length < 10}
                onClick={() => void replay(selected)}>{selected.financial ? 'Request approved replay' : 'Replay Event Delivery'}</button>
              : undefined}>
            {selected.financial
              ? <Callout tone="amber" title="Second Financial Operations approval required">A replay redelivers the original event to this consumer only. A money delivery is replayed only after another Financial Operations member approves the request.</Callout>
              : <Callout tone="blue" title="Governed replay">A replay redelivers the original event to this consumer only, after two-step sign-in. It is audited.</Callout>}
            {selected.financial && canReplay(selected) && <label className="small" style={{ display: 'grid', gap: 4 }}>Reason (the approver reads it)
              <textarea className="input" rows={2} value={why} onChange={(e) => setWhy(e.target.value)} placeholder="e.g. Ledger consumer fixed in release 2026.10.3" /></label>}
            {!canReplay(selected) && <p className="adm-foot-note">You do not hold Financial Operations, so you cannot replay this delivery.</p>}
            <Facts title="Delivery context" rows={[['Failure ID', <code key="id">{selected.id}</code>], ['Event type', selected.eventType], ['Consumer', selected.consumer], ['Attempts', selected.attempts]]} />
            <div className="adm-facts"><h3>Last error</h3>
              <pre style={{ whiteSpace: 'pre-wrap', background: 'var(--zk-bg-soft)', padding: 10, borderRadius: 'var(--radius-sm)', fontSize: 12.5, color: 'var(--zk-danger)', margin: 0 }}>{selected.lastError}</pre>
            </div>
          </DetailPanel>
        )}
      />
    </>
  )
}
