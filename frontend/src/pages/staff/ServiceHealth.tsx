import { useCallback, useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../../api/client'
import { ErrorAlert } from '../../components/ui'
import { Icon } from '../../components/dashboard'
import {
  AdminHeader, AdminKpi, Callout, CountTabs, DetailPanel, Facts, HBars, KpiStrip, ListDetail, MetricList, Panel, PanelRow, Pill,
  TableFoot, TrendChart, type PillTone,
} from '../../components/admin'

/* Service Health & Workers (design 66). Read-only. Sources: GET /v1/admin/worker (background worker backlog, the same
   numbers as /metrics), GET /health (liveness) and GET /ready (database reachable and migrated). /ready is served by
   the production web server; a development server that does not proxy it shows "Not reachable from this app". */

interface Backlog {
  unpublishedEvents: number; oldestUnpublishedSeconds: number; overdueTimers: number; oldestOverdueTimerSeconds: number
  retryingDeliveries: number; deadLetters: number; deadFinancialLetters: number
}
type Probe = { state: 'ok' | 'down' | 'unreachable'; detail: string; service?: string } | null
type Health = 'Operational' | 'Degraded' | 'Down' | 'Unknown'

const ago = (s: number) => (s < 90 ? `${Math.round(s)} s` : s < 5400 ? `${Math.round(s / 60)} min` : `${Math.round(s / 3600)} h`)
const TONE: Record<Health, PillTone> = { Operational: 'green', Degraded: 'amber', Down: 'red', Unknown: 'grey' }
const POLL_MS = 30_000
const MAX_SAMPLES = 20

async function probe(path: string, okWord: string): Promise<Probe> {
  try {
    const res = await fetch(path, { headers: { Accept: 'application/json' } })
    if (!(res.headers.get('content-type') ?? '').includes('json')) return { state: 'unreachable', detail: 'Not reachable from this app' }
    const body = await res.json() as { status?: string; reason?: string; service?: string }
    return body.status === okWord ? { state: 'ok', detail: body.status, service: body.service }
      : { state: 'down', detail: body.reason ?? body.status ?? `HTTP ${res.status}`, service: body.service }
  } catch {
    return { state: 'unreachable', detail: 'No answer' }
  }
}

interface Row { id: string; name: string; kind: string; health: Health; signal: string; queue: string; facts: [string, string][]; note: string; to?: string }

function rowsFor(b: Backlog | null, live: Probe, ready: Probe): Row[] {
  const probeHealth = (p: Probe): Health => (!p ? 'Unknown' : p.state === 'ok' ? 'Operational' : p.state === 'down' ? 'Down' : 'Unknown')
  const out: Row[] = [
    { id: 'api', name: 'API process', kind: 'Liveness · /health', health: probeHealth(live), signal: live?.detail ?? 'Checking…', queue: '—',
      facts: [['Endpoint', '/health'], ['Answer', live?.detail ?? '—'], ['Service', live?.service ?? '—']],
      note: 'The API process answers. It does not show whether the database is reachable.' },
    { id: 'ready', name: 'Database and migrations', kind: 'Readiness · /ready', health: probeHealth(ready), signal: ready?.detail ?? 'Checking…', queue: '—',
      facts: [['Endpoint', '/ready'], ['Answer', ready?.detail ?? '—'], ['Service', ready?.service ?? '—']],
      note: 'Ready means the database answers and is migrated to the current schema. Not ready tells the load balancer to send traffic elsewhere.' },
  ]
  if (!b) return out
  out.push(
    { id: 'outbox', name: 'Event publisher', kind: 'Worker · outbox', queue: String(b.unpublishedEvents),
      health: b.oldestUnpublishedSeconds > 120 ? 'Degraded' : 'Operational',
      signal: b.unpublishedEvents ? `Oldest waiting ${ago(b.oldestUnpublishedSeconds)}` : 'Up to date',
      facts: [['Events waiting', String(b.unpublishedEvents)], ['Oldest waiting', b.unpublishedEvents ? ago(b.oldestUnpublishedSeconds) : '—'], ['Alert threshold', 'Oldest over 2 min']],
      note: 'Events waiting to be published (emails, payment follow-ups, search updates). A growing oldest age means the worker is down or too slow.' },
    { id: 'timers', name: 'Timers', kind: 'Worker · scheduled deadlines', queue: String(b.overdueTimers),
      health: b.oldestOverdueTimerSeconds > 300 ? 'Degraded' : 'Operational',
      signal: b.overdueTimers ? `Oldest overdue ${ago(b.oldestOverdueTimerSeconds)}` : 'None overdue',
      facts: [['Overdue timers', String(b.overdueTimers)], ['Oldest overdue', b.overdueTimers ? ago(b.oldestOverdueTimerSeconds) : '—'], ['Alert threshold', 'Oldest over 5 min']],
      note: 'Deadlines that should already have fired (acceptance windows, response timers).' },
    { id: 'retry', name: 'Consumer deliveries', kind: 'Worker · retries', queue: String(b.retryingDeliveries),
      health: b.retryingDeliveries ? 'Degraded' : 'Operational',
      signal: b.retryingDeliveries ? `${b.retryingDeliveries} retrying` : 'No retries',
      facts: [['Retrying deliveries', String(b.retryingDeliveries)]],
      note: 'Event deliveries that failed and are being retried automatically. After the last retry they become failed deliveries.' },
    { id: 'dead', name: 'Failed deliveries', kind: 'Dead letters', queue: String(b.deadLetters),
      health: b.deadLetters ? 'Down' : 'Operational',
      signal: b.deadLetters ? `${b.deadLetters} need a replay${b.deadFinancialLetters ? ` · ${b.deadFinancialLetters} about money` : ''}` : 'None',
      facts: [['Failed deliveries', String(b.deadLetters)], ['About money', String(b.deadFinancialLetters)]],
      note: 'Deliveries that used every retry. Each needs an authorised replay; money deliveries need Financial Operations.', to: '/app/ops/dead-letters' },
  )
  return out
}

type TabKey = 'all' | 'attention' | 'worker'

export default function ServiceHealth() {
  const [backlog, setBacklog] = useState<Backlog | null>(null)
  const [live, setLive] = useState<Probe>(null)
  const [ready, setReady] = useState<Probe>(null)
  const [checkedAt, setCheckedAt] = useState<Date | null>(null)
  const [samples, setSamples] = useState<{ at: Date; events: number; retrying: number }[]>([])
  const [error, setError] = useState<unknown>(null)
  const [tab, setTab] = useState<TabKey>('all')
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const timer = useRef<number | undefined>(undefined)

  const reload = useCallback(async () => {
    const [b, l, r] = await Promise.all([api<Backlog>('/v1/admin/worker'), probe('/health', 'ok'), probe('/ready', 'ready')])
    const at = new Date()
    setBacklog(b); setLive(l); setReady(r); setCheckedAt(at)
    setSamples((s) => [...s, { at, events: b.unpublishedEvents, retrying: b.retryingDeliveries }].slice(-MAX_SAMPLES))
  }, [])
  useEffect(() => {
    reload().catch(setError)
    timer.current = window.setInterval(() => { reload().catch(setError) }, POLL_MS)
    return () => window.clearInterval(timer.current)
  }, [reload])

  const rows = rowsFor(backlog, live, ready)
  const attention = rows.filter((r) => r.health === 'Degraded' || r.health === 'Down')
  const shown = tab === 'attention' ? attention : tab === 'worker' ? rows.filter((r) => r.kind.startsWith('Worker') || r.id === 'dead') : rows
  const selected = rows.find((r) => r.id === selectedId) ?? null
  const b = backlog
  const fmtTime = (d: Date) => d.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit', second: '2-digit' })

  return (
    <>
      <AdminHeader crumb="Platform reliability / Read-only operational observability" title="Service Health & Workers"
        subtitle="Inspect service readiness and how far behind the background worker is. Read-only; act from Incident Command or Failed Event Deliveries."
        actions={<>
          <button type="button" className="btn btn-secondary" onClick={() => reload().catch(setError)}><Icon name="refresh" /> Refresh</button>
          <Link className="btn btn-primary" to="/app/ops/incidents"><Icon name="alert" /> Open incident command</Link>
        </>}
        meta={checkedAt && <span className="live">Checked {fmtTime(checkedAt)} · refreshes every 30 s</span>} />
      <ErrorAlert error={error} />

      <KpiStrip>
        <AdminKpi icon="pulse" tone={ready?.state === 'ok' ? 'green' : ready?.state === 'down' ? 'red' : 'amber'} label="Readiness"
          value={ready ? (ready.state === 'ok' ? 'Ready' : ready.state === 'down' ? 'Not ready' : 'Unknown') : '—'} sub={ready?.detail} />
        <AdminKpi icon="clock" tone={b && b.oldestUnpublishedSeconds > 120 ? 'red' : 'green'} label="Events waiting" value={b ? b.unpublishedEvents : '—'}
          sub={b && (b.unpublishedEvents ? `oldest ${ago(b.oldestUnpublishedSeconds)}` : 'worker is up to date')} />
        <AdminKpi icon="bell" tone={b && b.oldestOverdueTimerSeconds > 300 ? 'red' : 'green'} label="Overdue timers" value={b ? b.overdueTimers : '—'}
          sub={b && (b.overdueTimers ? `oldest ${ago(b.oldestOverdueTimerSeconds)}` : 'none')} />
        <AdminKpi icon="refresh" tone={b?.retryingDeliveries ? 'amber' : 'green'} label="Retrying deliveries" value={b ? b.retryingDeliveries : '—'} />
        <AdminKpi icon="shield" tone={b?.deadLetters ? 'red' : 'green'} label="Failed deliveries" value={b ? b.deadLetters : '—'}
          sub={b?.deadFinancialLetters ? `${b.deadFinancialLetters} about money` : undefined} to="/app/ops/dead-letters" />
        <AdminKpi icon="layers" tone={attention.length ? 'amber' : 'green'} label="Needing attention" value={b ? `${attention.length} / ${rows.length}` : '—'} sub="Checks degraded or down" />
      </KpiStrip>

      <PanelRow cols={3}>
        <Panel title="Service checks" meta={`${rows.length} checks`}>
          <MetricList rows={rows.map((r) => ({ label: r.name, value: <Pill tone={TONE[r.health]}>{r.health}</Pill> }))} />
          <p className="adm-foot-note">Readiness and worker signals only; they do not certify payment integrity or overall availability.</p>
        </Panel>
        <Panel title="Worker queues" meta="Items now">
          <HBars rows={b ? [
            { label: 'Events waiting', value: b.unpublishedEvents, color: '#2f80ed' },
            { label: 'Overdue timers', value: b.overdueTimers, color: '#9b8afb' },
            { label: 'Retrying deliveries', value: b.retryingDeliveries, color: '#f79009' },
            { label: 'Failed deliveries', value: b.deadLetters, color: '#f04438' },
          ] : []} />
        </Panel>
        <Panel title="Backlog while this page is open" meta={`${samples.length} sample${samples.length === 1 ? '' : 's'} · every 30 s`}>
          {samples.length < 2 ? <p className="muted small">The trend appears after the next sample.</p> : (
            <TrendChart labels={samples.map((s) => s.at.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' }))} height={150}
              series={[{ label: 'Events waiting', values: samples.map((s) => s.events) }, { label: 'Retrying', values: samples.map((s) => s.retrying), color: '#f79009' }]} />
          )}
        </Panel>
      </PanelRow>

      <ListDetail
        list={
          <div className="card">
            <CountTabs tabs={[
              { key: 'all' as TabKey, label: 'All checks', count: rows.length },
              { key: 'attention' as TabKey, label: 'Needing attention', count: attention.length },
              { key: 'worker' as TabKey, label: 'Worker', count: rows.filter((r) => r.kind.startsWith('Worker') || r.id === 'dead').length },
            ]} value={tab} onChange={setTab} />
            <div className="adm-note">Current state · queue depths are per check, not a cross-platform total</div>
            <div className="adm-table-wrap">
              <table className="data">
                <thead><tr><th>Service / worker</th><th>Health</th><th>Queue</th><th>Signal</th><th><span className="sr-only">Action</span></th></tr></thead>
                <tbody>
                  {shown.length === 0 && <tr><td colSpan={5} className="empty-row">Nothing needs attention.</td></tr>}
                  {shown.map((r) => (
                    <tr key={r.id} className={`pick ${r.id === selectedId ? 'selected' : ''}`} onClick={() => setSelectedId(r.id)}>
                      <td><div className="cell-main">{r.name}</div><div className="cell-sub">{r.kind}</div></td>
                      <td><Pill tone={TONE[r.health]}>{r.health}</Pill></td>
                      <td>{r.queue}</td>
                      <td className="small">{r.signal}</td>
                      <td><button type="button" className="btn btn-secondary btn-sm" onClick={(e) => { e.stopPropagation(); setSelectedId(r.id) }}>Inspect</button></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <TableFoot shown={shown.length} total={rows.length} noun="checks" />
          </div>
        }
        detail={selected && (
          <DetailPanel title={selected.name} subtitle={selected.kind} badge={<Pill tone={TONE[selected.health]}>{selected.health}</Pill>} onClose={() => setSelectedId(null)}
            footer={<>
              {selected.to && <Link className="btn btn-primary btn-sm" to={selected.to}>Open failed deliveries</Link>}
              <Link className="btn btn-secondary btn-sm" to="/app/ops/incidents">Incident command</Link>
            </>}>
            {selected.health === 'Down' && <Callout tone="red" title="Needs action">{selected.signal}</Callout>}
            {selected.health === 'Degraded' && <Callout tone="amber" title="Degraded">{selected.signal}</Callout>}
            <p className="small" style={{ margin: 0 }}>{selected.note}</p>
            <Facts title="Signal facts" rows={[...selected.facts, ['Checked', checkedAt ? fmtTime(checkedAt) : '—']]} />
          </DetailPanel>
        )}
      />
    </>
  )
}
