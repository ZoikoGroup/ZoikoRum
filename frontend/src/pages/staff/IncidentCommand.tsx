import { useCallback, useEffect, useMemo, useState, type FormEvent } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../../api/client'
import { ErrorAlert } from '../../components/ui'
import { Icon } from '../../components/dashboard'
import {
  AdminHeader, AdminKpi, Callout, Checklist, CountTabs, DetailPanel, Facts, FilterBar, FilterSelect, HBars, Initials, KpiStrip,
  ListDetail, MetricList, Panel, PanelRow, Pill, StackBar, StatusPill, TableFoot, label, shortDateTime, type PillTone,
} from '../../components/admin'

/* Incident Command (design 64): the incident register (RUNBOOKS.md) as a governed response queue. Everything shown
   comes from GET /v1/admin/incidents; changes go through PATCH /v1/admin/incidents/{id} (owner or incident lead). */

type Severity = 'SEV1' | 'SEV2' | 'SEV3' | 'SEV4'
interface Incident {
  id: string; reference: string; title: string; kind: string; severity: Severity; status: string; summary: string
  detectedAt: string; containedAt: string | null; resolvedAt: string | null; closedAt: string | null; owner: string
  timeline: { at: string; note: string }[]; notifications: { party: string; note: string; at: string }[]
  rootCause: string | null; remediation: { task: string; done: boolean }[]; review: string | null
  createdAt?: string; updatedAt?: string
}

const KINDS = ['SECURITY', 'DATA', 'PAYMENTS', 'OUTAGE', 'SAFETY', 'OTHER']
const SEVERITIES: Severity[] = ['SEV1', 'SEV2', 'SEV3', 'SEV4']
const STAGES = ['OPEN', 'CONTAINED', 'RESOLVED', 'CLOSED'] as const
const NEXT_STEP: Record<string, string> = { OPEN: 'CONTAINED', CONTAINED: 'RESOLVED', RESOLVED: 'CLOSED' }
const STAGE_COLOR: Record<string, string> = { OPEN: '#f04438', CONTAINED: '#f79009', RESOLVED: '#2f80ed', CLOSED: '#12b76a' }
const SEV_TONE: Record<Severity, PillTone> = { SEV1: 'red', SEV2: 'red', SEV3: 'amber', SEV4: 'blue' }
const isActive = (i: Incident) => i.status === 'OPEN' || i.status === 'CONTAINED'

type TabKey = 'active' | 'OPEN' | 'CONTAINED' | 'RESOLVED' | 'CLOSED' | 'all'

function age(from: string, to?: string | null) {
  const mins = Math.max(0, Math.round(((to ? new Date(to).getTime() : Date.now()) - new Date(from).getTime()) / 60_000))
  if (mins < 60) return `${mins} min`
  if (mins < 48 * 60) return `${Math.floor(mins / 60)}h ${String(mins % 60).padStart(2, '0')}m`
  return `${Math.round(mins / 1440)} days`
}
const lastUpdate = (i: Incident) => i.timeline.length ? i.timeline[i.timeline.length - 1].at : i.detectedAt

export default function IncidentCommand() {
  const [rows, setRows] = useState<Incident[] | null>(null)
  const [error, setError] = useState<unknown>(null)
  const [notice, setNotice] = useState('')
  const [declaring, setDeclaring] = useState(false)
  const [tab, setTab] = useState<TabKey>('active')
  const [q, setQ] = useState('')
  const [sev, setSev] = useState('')
  const [kind, setKind] = useState('')
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [detailTab, setDetailTab] = useState('Response')
  const [busy, setBusy] = useState(false)

  const reload = useCallback(async () => setRows(await api<Incident[]>('/v1/admin/incidents')), [])
  useEffect(() => { reload().catch(setError) }, [reload])

  const all = useMemo(() => rows ?? [], [rows])
  const active = all.filter(isActive)
  const count = (s: string) => all.filter((i) => i.status === s).length
  const highest = SEVERITIES.find((s) => active.some((i) => i.severity === s)) ?? null
  const [now] = useState(() => Date.now())
  const since30 = now - 30 * 86_400_000
  const closed30 = all.filter((i) => i.closedAt && new Date(i.closedAt).getTime() >= since30).length
  const notified = active.filter((i) => i.notifications.length > 0).length
  const tasks = active.flatMap((i) => i.remediation)

  const shown = all.filter((i) => {
    if (tab === 'active' ? !isActive(i) : tab !== 'all' && i.status !== tab) return false
    if (sev && i.severity !== sev) return false
    if (kind && i.kind !== kind) return false
    const s = q.trim().toLowerCase()
    return !s || [i.reference, i.title, i.summary, i.owner, i.kind].some((v) => v.toLowerCase().includes(s))
  })
  const selected = all.find((i) => i.id === selectedId) ?? null

  async function patch(id: string, body: Record<string, unknown>, done?: string) {
    setBusy(true); setError(null); setNotice('')
    try {
      await api(`/v1/admin/incidents/${id}`, { method: 'PATCH', body })
      await reload()
      if (done) setNotice(done)
    } catch (err) { setError(err) } finally { setBusy(false) }
  }

  function declare(e: FormEvent<HTMLFormElement>) {
    e.preventDefault()
    const form = e.currentTarget
    const d = new FormData(form)
    setError(null); setNotice('')
    api<Incident>('/v1/admin/incidents', { method: 'POST', body: { title: d.get('title'), kind: d.get('kind'), severity: d.get('severity'), summary: d.get('summary') } })
      .then(async (created) => {
        form.reset(); setDeclaring(false); await reload()
        setSelectedId(created.id); setDetailTab('Response'); setTab('active')
        setNotice(`${created.reference} declared. You own it until you hand it over.`)
      }).catch(setError)
  }

  const tabs: { key: TabKey; label: string; count: number }[] = [
    { key: 'active', label: 'Active incidents', count: active.length },
    { key: 'OPEN', label: 'Open', count: count('OPEN') },
    { key: 'CONTAINED', label: 'Contained', count: count('CONTAINED') },
    { key: 'RESOLVED', label: 'Resolved', count: count('RESOLVED') },
    { key: 'CLOSED', label: 'Closed', count: count('CLOSED') },
    { key: 'all', label: 'All', count: all.length },
  ]

  return (
    <>
      <AdminHeader crumb="Platform reliability / Governed incident response" title="Incident Command"
        subtitle="Coordinate detection, containment, recovery, who was told, and evidence-backed incident closure. SEV1/SEV2 incidents close only with a root cause, finished remediation and a review."
        actions={<>
          <Link className="btn btn-secondary" to="/app/ops/health"><Icon name="pulse" /> Service status</Link>
          <button type="button" className="btn btn-secondary" onClick={() => reload().catch(setError)}><Icon name="refresh" /> Refresh</button>
          <button type="button" className="btn btn-primary" onClick={() => setDeclaring((v) => !v)}><Icon name="plus" /> Declare incident</button>
        </>}
        meta={rows && <span className="live">{active.length} active · {closed30} closed in 30 days</span>} />
      <ErrorAlert error={error} />
      {notice && <div className="alert alert-success" role="status">{notice}</div>}

      {declaring && (
        <form className="card adm-panel" style={{ marginBottom: 16 }} onSubmit={declare}>
          <div className="adm-panel-head"><h2>Declare an incident</h2><span className="muted small">You become its owner; every change is audited.</span></div>
          <div className="row">
            <div className="field" style={{ flex: 2 }}><label htmlFor="inc-title">Title</label><input id="inc-title" name="title" className="input" required minLength={5} maxLength={200} /></div>
            <div className="field"><label htmlFor="inc-kind">Kind</label><select id="inc-kind" name="kind" className="input">
              {KINDS.map((k) => <option key={k} value={k}>{label(k)}</option>)}</select></div>
            <div className="field"><label htmlFor="inc-sev">Severity</label><select id="inc-sev" name="severity" className="input" defaultValue="SEV3">
              {SEVERITIES.map((k) => <option key={k}>{k}</option>)}</select></div>
          </div>
          <div className="field" style={{ marginTop: 12 }}><label htmlFor="inc-summary">What is happening?</label>
            <textarea id="inc-summary" name="summary" className="input" rows={2} required minLength={10} maxLength={4000} /></div>
          <div className="row">
            <button className="btn btn-primary btn-sm">Open incident</button>
            <button type="button" className="btn btn-ghost btn-sm" onClick={() => setDeclaring(false)}>Cancel</button>
          </div>
        </form>
      )}

      <KpiStrip>
        <AdminKpi icon="alert" tone="blue" label="Active incidents" value={rows ? active.length : '—'}
          sub={rows && SEVERITIES.map((s) => `${active.filter((i) => i.severity === s).length} ${s}`).join(' · ')} />
        <AdminKpi icon="alert" tone="red" label="Highest active severity" value={rows ? highest ?? 'None' : '—'} sub={highest ? 'Across active incidents' : 'No active incident'} />
        <AdminKpi icon="bell" tone="amber" label="Not yet contained" value={rows ? count('OPEN') : '—'} sub="Status open" />
        <AdminKpi icon="mail" tone="violet" label="Parties notified" value={rows ? notified : '—'} sub="Active incidents with a recorded notice" />
        <AdminKpi icon="clock" tone="teal" label="Awaiting closure" value={rows ? count('RESOLVED') : '—'} sub="Resolved; review and close" />
        <AdminKpi icon="check" tone="green" label="Closed · 30 days" value={rows ? closed30 : '—'} />
      </KpiStrip>

      <PanelRow cols={3}>
        <Panel title="Incident lifecycle" meta={`${all.length} recorded`}>
          <StackBar segments={STAGES.map((s) => ({ label: label(s), value: count(s), color: STAGE_COLOR[s] }))} />
          <p className="adm-foot-note">Open → contained → resolved → closed. Each step is a separate, timestamped change.</p>
        </Panel>
        <Panel title="Active severity mix" meta={`${active.length} active`}>
          <HBars rows={SEVERITIES.map((s, n) => ({ label: s, value: active.filter((i) => i.severity === s).length, color: ['#f04438', '#f79009', '#2f80ed', '#667085'][n] }))} />
        </Panel>
        <Panel title="Remediation and review" meta="Active incidents">
          <MetricList rows={[
            { label: 'Remediation tasks done', value: `${tasks.filter((t) => t.done).length} / ${tasks.length}` },
            { label: 'Root cause recorded', value: `${active.filter((i) => i.rootCause).length} / ${active.length}` },
            { label: 'Post-incident review written', value: `${active.filter((i) => i.review).length} / ${active.length}` },
            { label: 'Resolved, awaiting closure', value: count('RESOLVED'), tone: count('RESOLVED') ? 'amber' : undefined },
          ]} />
        </Panel>
      </PanelRow>

      <ListDetail
        list={
          <div className="card">
            <CountTabs tabs={tabs} value={tab} onChange={setTab} />
            <FilterBar search={q} onSearch={setQ} placeholder="Search incident, summary, owner or reference…">
              <FilterSelect label="Severity" value={sev} onChange={setSev} options={SEVERITIES.map((s) => [s, s])} />
              <FilterSelect label="Kind" value={kind} onChange={setKind} options={KINDS.map((k) => [k, label(k)])} />
            </FilterBar>
            <div className="adm-note">Severity and lifecycle stage are separate attributes · times in your local zone</div>
            <div className="adm-table-wrap">
              <table className="data">
                <thead><tr><th>Incident</th><th>Summary / kind</th><th>Severity</th><th>Stage</th><th>Age</th><th>Last update</th><th>Owner</th><th><span className="sr-only">Action</span></th></tr></thead>
                <tbody>
                  {rows === null && <tr><td colSpan={8} className="empty-row">Loading incidents…</td></tr>}
                  {rows && shown.length === 0 && <tr><td colSpan={8} className="empty-row">No incidents here.</td></tr>}
                  {shown.map((i) => (
                    <tr key={i.id} className={`pick ${i.id === selectedId ? 'selected' : ''}`} onClick={() => setSelectedId(i.id)}>
                      <td><div className="cell-id">{i.reference}</div><div className="cell-sub">Detected {shortDateTime(i.detectedAt)}</div></td>
                      <td><div className="cell-main">{i.title}</div><div className="cell-sub">{label(i.kind)}</div></td>
                      <td><Pill tone={SEV_TONE[i.severity]}>{i.severity}</Pill></td>
                      <td><StatusPill status={i.status} /></td>
                      <td className="small">{age(i.detectedAt, i.closedAt ?? i.resolvedAt)}</td>
                      <td className="small">{shortDateTime(lastUpdate(i))}</td>
                      <td><span className="name-cell"><Initials name={i.owner} /><span className="small">{i.owner}</span></span></td>
                      <td><button type="button" className="btn btn-secondary btn-sm" onClick={(e) => { e.stopPropagation(); setSelectedId(i.id) }}>Open</button></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <TableFoot shown={shown.length} total={all.length} noun="incidents" />
          </div>
        }
        detail={selected && (
          <IncidentDetail key={selected.id} i={selected} tab={detailTab} setTab={setDetailTab} busy={busy}
            onClose={() => setSelectedId(null)} patch={(body, done) => patch(selected.id, body, done)} />
        )}
      />
    </>
  )
}

function IncidentDetail({ i, tab, setTab, busy, onClose, patch }: {
  i: Incident; tab: string; setTab: (t: string) => void; busy: boolean; onClose: () => void
  patch: (body: Record<string, unknown>, done?: string) => Promise<void>
}) {
  const next = NEXT_STEP[i.status]
  const closed = i.status === 'CLOSED'
  const needsReview = i.severity === 'SEV1' || i.severity === 'SEV2'
  const allDone = i.remediation.every((t) => t.done)
  const blockedClose = next === 'CLOSED' && needsReview && (!i.rootCause || !i.review || !allDone)

  function save(e: FormEvent<HTMLFormElement>) {
    e.preventDefault()
    const form = e.currentTarget
    const d = new FormData(form)
    const body: Record<string, unknown> = {}
    for (const k of ['note', 'rootCause', 'review']) if (String(d.get(k) ?? '').trim()) body[k] = String(d.get(k)).trim()
    const task = String(d.get('task') ?? '').trim(); if (task) body.addRemediation = [task]
    const party = String(d.get('party') ?? '').trim(); if (party) body.notified = [{ party, note: String(d.get('partyNote') ?? '') }]
    const severity = String(d.get('severity') ?? ''); if (severity && severity !== i.severity) body.severity = severity
    if (d.get('advance') && next) body.advanceTo = next
    if (Object.keys(body).length === 0) return
    void patch(body, `${i.reference} updated.`).then(() => form.reset())
  }

  const callout = i.status === 'OPEN'
    ? <Callout tone="red" title="Not yet contained">Record what is being done in the timeline and move to contained once the impact stops growing.</Callout>
    : i.status === 'CONTAINED'
      ? <Callout tone="amber" title="Containment in progress — resolution not confirmed">Impact is contained; recovery is not yet recorded.</Callout>
      : i.status === 'RESOLVED'
        ? <Callout tone="blue" title="Resolved — awaiting closure">{needsReview ? 'A SEV1/SEV2 incident closes only with a root cause, every remediation task done and a post-incident review.' : 'Record the review and close the incident.'}</Callout>
        : <Callout tone="green" title="Closed">This incident is closed. Its record can no longer be changed.</Callout>

  return (
    <DetailPanel title={i.reference} subtitle={`${i.title} · ${label(i.kind)}`}
      badge={<span style={{ display: 'inline-flex', gap: 6, marginLeft: 'auto' }}><Pill tone={SEV_TONE[i.severity]}>{i.severity}</Pill><StatusPill status={i.status} /></span>}
      onClose={onClose}
      tabs={{ tabs: closed ? ['Response', 'Timeline', 'Remediation'] : ['Response', 'Timeline', 'Remediation', 'Update'], value: tab, onChange: setTab }}
      footer={!closed && next ? <>
        <button type="button" className="btn btn-primary btn-sm" disabled={busy || blockedClose}
          onClick={() => void patch({ advanceTo: next }, `${i.reference} moved to ${next.toLowerCase()}.`)}>Move to {next.toLowerCase()}</button>
        <button type="button" className="btn btn-secondary btn-sm" onClick={() => setTab('Update')}>Record update</button>
      </> : undefined}>
      {tab === 'Response' && <>
        {callout}
        <p className="small" style={{ margin: 0 }}>{i.summary}</p>
        <Facts title="Incident control facts" rows={[
          ['Kind', label(i.kind)], ['Severity', i.severity], ['Incident owner', i.owner],
          ['Detected', shortDateTime(i.detectedAt)], ['Contained', shortDateTime(i.containedAt)],
          ['Resolved', shortDateTime(i.resolvedAt)], ['Closed', shortDateTime(i.closedAt)],
          ['Parties notified', i.notifications.length],
        ]} />
        <Checklist title="Closure readiness" items={[
          { label: 'Root cause recorded', state: i.rootCause ? 'done' : 'pending', note: i.rootCause ? 'Recorded' : 'Pending' },
          { label: `Remediation tasks done (${i.remediation.filter((t) => t.done).length} of ${i.remediation.length})`, state: allDone ? 'done' : 'pending', note: allDone ? 'Recorded' : 'Pending' },
          { label: 'Post-incident review written', state: i.review ? 'done' : 'pending', note: i.review ? 'Recorded' : 'Pending' },
        ]} />
        {blockedClose && <p className="adm-foot-note">Closing is blocked until every item above is recorded.</p>}
        {i.rootCause && <Facts title="Root cause" rows={[['Recorded', i.rootCause]]} />}
        {i.review && <Facts title="Post-incident review" rows={[['Recorded', i.review]]} />}
      </>}

      {tab === 'Timeline' && <>
        <div className="adm-facts"><h3>Response timeline</h3>
          <ol style={{ listStyle: 'none', margin: 0, padding: 0, display: 'grid', gap: 8 }}>
            {[...i.timeline].reverse().map((t, n) => (
              <li key={n} style={{ display: 'grid', gridTemplateColumns: '110px 1fr', gap: 10, fontSize: 13 }}>
                <span className="muted small">{shortDateTime(t.at)}</span><span>{t.note}</span></li>))}
          </ol></div>
        <div className="adm-facts"><h3>Who was told</h3>
          {i.notifications.length === 0 ? <p className="muted small" style={{ margin: 0 }}>No notification recorded yet.</p>
            : <dl>{i.notifications.map((t, n) => <div key={n}><dt>{t.party} · {shortDateTime(t.at)}</dt><dd>{t.note || '—'}</dd></div>)}</dl>}
        </div>
      </>}

      {tab === 'Remediation' && (
        <div className="adm-checks"><h3>Remediation <span className="muted small">· {i.remediation.filter((t) => t.done).length} of {i.remediation.length}</span></h3>
          {i.remediation.length === 0 ? <p className="muted small" style={{ margin: 0 }}>No remediation task recorded.</p> : (
            <ul>{i.remediation.map((t, n) => (
              <li key={n}><span className={`adm-check ${t.done ? 'done' : 'pending'}`} aria-hidden>{t.done ? '✓' : '!'}</span><span className="grow">{t.task}</span>
                {t.done ? <Pill tone="green">done</Pill> : !closed && (
                  <button type="button" className="btn btn-ghost btn-sm" disabled={busy} onClick={() => void patch({ completeRemediation: [n] }, 'Remediation task marked done.')}>Mark done</button>)}
              </li>))}</ul>)}
        </div>
      )}

      {tab === 'Update' && !closed && (
        <form onSubmit={save}>
          <div className="field"><label htmlFor={`n-${i.id}`}>Update (timeline)</label><input id={`n-${i.id}`} name="note" className="input" maxLength={2000} /></div>
          <div className="field"><label htmlFor={`t-${i.id}`}>Add remediation task</label><input id={`t-${i.id}`} name="task" className="input" /></div>
          <div className="field"><label htmlFor={`p-${i.id}`}>Told (who)</label><input id={`p-${i.id}`} name="party" className="input" placeholder="e.g. Regulator, affected buyers" maxLength={100} /></div>
          <div className="field"><label htmlFor={`pn-${i.id}`}>How / what</label><input id={`pn-${i.id}`} name="partyNote" className="input" maxLength={500} /></div>
          <div className="field"><label htmlFor={`sv-${i.id}`}>Severity</label><select id={`sv-${i.id}`} name="severity" className="input" defaultValue={i.severity}>
            {SEVERITIES.map((s) => <option key={s}>{s}</option>)}</select></div>
          <div className="field"><label htmlFor={`rc-${i.id}`}>Root cause</label><textarea id={`rc-${i.id}`} name="rootCause" className="input" rows={2} maxLength={4000} defaultValue={i.rootCause ?? ''} /></div>
          <div className="field"><label htmlFor={`rv-${i.id}`}>Post-incident review</label><textarea id={`rv-${i.id}`} name="review" className="input" rows={2} maxLength={8000} defaultValue={i.review ?? ''} /></div>
          {next && <label className="checkbox"><input type="checkbox" name="advance" /> <span>Move to {next.toLowerCase()}</span></label>}
          <button className="btn btn-primary btn-sm" disabled={busy}>Save</button>
          <p className="adm-foot-note">Only the owner or an incident lead can change severity, stage or the review.</p>
        </form>
      )}
    </DetailPanel>
  )
}
