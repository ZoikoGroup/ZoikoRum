import { useCallback, useEffect, useMemo, useState, type FormEvent } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../../api/client'
import { useAuth } from '../../auth/AuthContext'
import { ErrorAlert } from '../../components/ui'
import { Icon } from '../../components/dashboard'
import {
  AdminHeader, AdminKpi, Callout, Checklist, CountTabs, DetailPanel, Facts, FilterBar, FilterSelect, HBars, Initials, KpiStrip,
  ListDetail, MetricList, Panel, PanelRow, Pill, StackBar, StatusPill, TableFoot, label, shortDateTime, type PillTone, pickRow, useSelectedParam } from '../../components/admin'

/* Incident Command (design 64): the incident register (RUNBOOKS.md) as a governed response queue. Everything shown
   comes from GET /v1/admin/incidents; changes go through PATCH /v1/admin/incidents/{id} (owner or incident lead).
   Lifecycle: unacknowledged -> investigating -> mitigating -> monitoring -> recovered -> closed. Mitigation is not
   verified recovery: "recovered" needs a verification note from someone other than the owner and the mitigator.
   Stage changes are blocked while the data on screen is more than two minutes old, until it is refreshed. */

type Severity = 'SEV1' | 'SEV2' | 'SEV3' | 'SEV4'
interface Incident {
  id: string; reference: string; title: string; kind: string; severity: Severity; status: string; summary: string
  detectedAt: string; acknowledgedAt: string | null; mitigatingAt: string | null; monitoringAt: string | null; recoveredAt: string | null
  containedAt: string | null; resolvedAt: string | null; closedAt: string | null; owner: string; ownerId: string
  mitigatedBy: string | null; mitigatedById: string | null; recoveryNote: string | null; recoveryVerifiedBy: string | null
  timeline: { at: string; note: string }[]; notifications: { party: string; note: string; at: string }[]
  rootCause: string | null; remediation: { task: string; done: boolean }[]; review: string | null
  createdAt?: string; updatedAt?: string
}

const KINDS = ['SECURITY', 'DATA', 'PAYMENTS', 'OUTAGE', 'SAFETY', 'OTHER']
const SEVERITIES: Severity[] = ['SEV1', 'SEV2', 'SEV3', 'SEV4']
const STAGES = ['UNACKNOWLEDGED', 'INVESTIGATING', 'MITIGATING', 'MONITORING', 'RECOVERED', 'CLOSED'] as const
type Stage = typeof STAGES[number]
const NEXT_STEP: Record<string, Stage> = {
  UNACKNOWLEDGED: 'INVESTIGATING', INVESTIGATING: 'MITIGATING', MITIGATING: 'MONITORING', MONITORING: 'RECOVERED', RECOVERED: 'CLOSED',
}
const STEP_ACTION: Record<Stage, string> = {
  UNACKNOWLEDGED: '', INVESTIGATING: 'Acknowledge and investigate', MITIGATING: 'Start mitigation', MONITORING: 'Mitigation in place: monitor',
  RECOVERED: 'Verify recovery', CLOSED: 'Close incident',
}
const STAGE_COLOR: Record<Stage, string> = {
  UNACKNOWLEDGED: '#f04438', INVESTIGATING: '#f79009', MITIGATING: '#9b8afb', MONITORING: '#2f80ed', RECOVERED: '#12b76a', CLOSED: '#667085',
}
const SEV_TONE: Record<Severity, PillTone> = { SEV1: 'red', SEV2: 'red', SEV3: 'amber', SEV4: 'blue' }
const ACTIVE: string[] = ['UNACKNOWLEDGED', 'INVESTIGATING', 'MITIGATING', 'MONITORING']
const isActive = (i: Incident) => ACTIVE.includes(i.status)
const STALE_MS = 2 * 60_000
const fmtTime = (t: number) => new Date(t).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit', second: '2-digit' })

type TabKey = 'active' | Stage | 'all'

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
  useSelectedParam(setSelectedId)
  const [detailTab, setDetailTab] = useState('Response')
  const [busy, setBusy] = useState(false)
  const [loadedAt, setLoadedAt] = useState<number | null>(null)
  const [tick, setTick] = useState(() => Date.now())
  const { user: me } = useAuth()

  const reload = useCallback(async () => {
    setRows(await api<Incident[]>('/v1/admin/incidents'))
    const at = Date.now()
    setLoadedAt(at); setTick(at)
  }, [])
  useEffect(() => { reload().catch(setError) }, [reload])
  useEffect(() => {
    const t = window.setInterval(() => setTick(Date.now()), 10_000)
    return () => window.clearInterval(t)
  }, [])
  const stale = loadedAt !== null && tick - loadedAt > STALE_MS

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
    ...STAGES.map((s) => ({ key: s as TabKey, label: label(s), count: count(s) })),
    { key: 'all', label: 'All', count: all.length },
  ]

  return (
    <>
      <AdminHeader crumb="Platform reliability / Governed incident response" title="Incident Command"
        subtitle="Coordinate acknowledgement, mitigation, independently verified recovery, who was told, and evidence-backed closure. SEV1/SEV2 incidents close only with a root cause, finished remediation and a review."
        actions={<>
          <Link className="btn btn-secondary" to="/platform-admin/service-health-workers"><Icon name="pulse" /> Service status</Link>
          <button type="button" className="btn btn-secondary" onClick={() => reload().catch(setError)}><Icon name="refresh" /> Refresh</button>
          <button type="button" className="btn btn-primary" onClick={() => setDeclaring((v) => !v)}><Icon name="plus" /> Declare incident</button>
        </>}
        meta={rows && <span className="live">{active.length} active · {closed30} closed in 30 days · Data as of {loadedAt ? fmtTime(loadedAt) : '—'}
          {stale && <> <Pill tone="amber">Stale</Pill></>}</span>} />
      <ErrorAlert error={error} />
      {stale && (
        <Callout tone="amber" title={`Data is more than 2 minutes old (as of ${loadedAt ? fmtTime(loadedAt) : '—'})`}>
          Stage changes are paused until you refresh, so no one acts on an out-of-date picture.{' '}
          <button type="button" className="btn btn-secondary btn-sm" onClick={() => reload().catch(setError)}>Refresh now</button>
        </Callout>
      )}
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
        <AdminKpi icon="bell" tone="amber" label="Unacknowledged" value={rows ? count('UNACKNOWLEDGED') : '—'} sub="No one investigating yet" />
        <AdminKpi icon="mail" tone="violet" label="Parties notified" value={rows ? notified : '—'} sub="Active incidents with a recorded notice" />
        <AdminKpi icon="clock" tone="teal" label="Awaiting closure" value={rows ? count('RECOVERED') : '—'} sub="Recovery verified; review and close" />
        <AdminKpi icon="check" tone="green" label="Closed · 30 days" value={rows ? closed30 : '—'} />
      </KpiStrip>

      <PanelRow cols={3}>
        <Panel title="Incident lifecycle" meta={`${all.length} recorded`}>
          <StackBar segments={STAGES.map((s) => ({ label: label(s), value: count(s), color: STAGE_COLOR[s] }))} />
          <p className="adm-foot-note">Unacknowledged → investigating → mitigating → monitoring → recovered → closed. Each step is a separate, timestamped change; recovery is verified by a second person.</p>
        </Panel>
        <Panel title="Active severity mix" meta={`${active.length} active`}>
          <HBars rows={SEVERITIES.map((s, n) => ({ label: s, value: active.filter((i) => i.severity === s).length, color: ['#f04438', '#f79009', '#2f80ed', '#667085'][n] }))} />
        </Panel>
        <Panel title="Remediation and review" meta="Active incidents">
          <MetricList rows={[
            { label: 'Remediation tasks done', value: `${tasks.filter((t) => t.done).length} / ${tasks.length}` },
            { label: 'Root cause recorded', value: `${active.filter((i) => i.rootCause).length} / ${active.length}` },
            { label: 'Post-incident review written', value: `${active.filter((i) => i.review).length} / ${active.length}` },
            { label: 'Monitoring, awaiting recovery check', value: count('MONITORING'), tone: count('MONITORING') ? 'amber' : undefined },
            { label: 'Recovered, awaiting closure', value: count('RECOVERED'), tone: count('RECOVERED') ? 'amber' : undefined },
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
                <thead><tr><th scope="col">Incident</th><th scope="col">Summary / kind</th><th scope="col">Severity</th><th scope="col">Stage</th><th scope="col">Age</th><th scope="col">Last update</th><th scope="col">Owner</th><th scope="col"><span className="sr-only">Action</span></th></tr></thead>
                <tbody>
                  {rows === null && <tr><td colSpan={8} className="empty-row">Loading incidents…</td></tr>}
                  {rows && shown.length === 0 && <tr><td colSpan={8} className="empty-row">No incidents here.</td></tr>}
                  {shown.map((i) => (
                    <tr {...pickRow} key={i.id} className={`pick ${i.id === selectedId ? 'selected' : ''}`} onClick={() => setSelectedId(i.id)}>
                      <td><div className="cell-id">{i.reference}</div><div className="cell-sub">Detected {shortDateTime(i.detectedAt)}</div></td>
                      <td><div className="cell-main">{i.title}</div><div className="cell-sub">{label(i.kind)}</div></td>
                      <td><Pill tone={SEV_TONE[i.severity]}>{i.severity}</Pill></td>
                      <td><StatusPill status={i.status} /></td>
                      <td className="small">{age(i.detectedAt, i.closedAt ?? i.recoveredAt)}</td>
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
          <IncidentDetail key={selected.id} i={selected} tab={detailTab} setTab={setDetailTab} busy={busy} stale={stale} meId={me?.id ?? null}
            onClose={() => setSelectedId(null)} patch={(body, done) => patch(selected.id, body, done)} />
        )}
      />
    </>
  )
}

function IncidentDetail({ i, tab, setTab, busy, stale, meId, onClose, patch }: {
  i: Incident; tab: string; setTab: (t: string) => void; busy: boolean; stale: boolean; meId: string | null; onClose: () => void
  patch: (body: Record<string, unknown>, done?: string) => Promise<void>
}) {
  const next = NEXT_STEP[i.status] as Stage | undefined
  const closed = i.status === 'CLOSED'
  const needsReview = i.severity === 'SEV1' || i.severity === 'SEV2'
  const allDone = i.remediation.every((t) => t.done)
  const blockedClose = next === 'CLOSED' && needsReview && (!i.rootCause || !i.review || !allDone)
  const verifying = next === 'RECOVERED'
  const notIndependent = verifying && !!meId && (meId === i.ownerId || meId === i.mitigatedById)
  const [recoveryNote, setRecoveryNote] = useState('')
  const noteOk = recoveryNote.trim().length >= 10
  const blockedStep = stale || busy || blockedClose || (verifying && (notIndependent || !noteOk))
  const advance = () => void patch(verifying ? { advanceTo: next, recoveryNote: recoveryNote.trim() } : { advanceTo: next },
    `${i.reference} moved to ${label(next ?? '').toLowerCase()}.`).then(() => setRecoveryNote(''))

  function save(e: FormEvent<HTMLFormElement>) {
    e.preventDefault()
    const form = e.currentTarget
    const d = new FormData(form)
    const body: Record<string, unknown> = {}
    for (const k of ['note', 'rootCause', 'review']) if (String(d.get(k) ?? '').trim()) body[k] = String(d.get(k)).trim()
    const task = String(d.get('task') ?? '').trim(); if (task) body.addRemediation = [task]
    const party = String(d.get('party') ?? '').trim(); if (party) body.notified = [{ party, note: String(d.get('partyNote') ?? '') }]
    const severity = String(d.get('severity') ?? ''); if (severity && severity !== i.severity) body.severity = severity
    if (d.get('advance') && next && next !== 'RECOVERED' && !stale) body.advanceTo = next
    if (Object.keys(body).length === 0) return
    void patch(body, `${i.reference} updated.`).then(() => form.reset())
  }

  const callout = {
    UNACKNOWLEDGED: <Callout tone="red" title="Unacknowledged">No one has picked this up yet. Acknowledge it and record what is being looked at.</Callout>,
    INVESTIGATING: <Callout tone="red" title="Investigating — impact not yet mitigated">Record findings in the timeline and start mitigation once the cause of the impact is known.</Callout>,
    MITIGATING: <Callout tone="amber" title="Mitigation in progress — recovery not verified">Mitigation is under way. Move to monitoring once it is in place.</Callout>,
    MONITORING: <Callout tone="amber" title="Monitoring — recovery not yet verified">Mitigation is not verified recovery. Someone other than the owner{i.mitigatedBy ? ` and ${i.mitigatedBy}` : ''} must check and record how recovery was verified.</Callout>,
    RECOVERED: <Callout tone="blue" title="Recovered — awaiting closure">{needsReview ? 'A SEV1/SEV2 incident closes only with a root cause, every remediation task done and a post-incident review.' : 'Record the review and close the incident.'}</Callout>,
    CLOSED: <Callout tone="green" title="Closed">This incident is closed. Its record can no longer be changed.</Callout>,
  }[i.status as Stage] ?? <Callout tone="amber" title={label(i.status)}>Unrecognised stage.</Callout>

  return (
    <DetailPanel title={i.reference} subtitle={`${i.title} · ${label(i.kind)}`}
      badge={<span style={{ display: 'inline-flex', gap: 6, marginLeft: 'auto' }}><Pill tone={SEV_TONE[i.severity]}>{i.severity}</Pill><StatusPill status={i.status} /></span>}
      onClose={onClose}
      tabs={{ tabs: closed ? ['Response', 'Timeline', 'Remediation'] : ['Response', 'Timeline', 'Remediation', 'Update'], value: tab, onChange: setTab }}
      footer={!closed && next ? <>
        <button type="button" className="btn btn-primary btn-sm" disabled={blockedStep}
          title={stale ? 'Refresh the data first' : undefined} onClick={advance}>{STEP_ACTION[next]}</button>
        <button type="button" className="btn btn-secondary btn-sm" onClick={() => setTab('Update')}>Record update</button>
      </> : undefined}>
      {tab === 'Response' && <>
        {callout}
        {stale && !closed && <p className="adm-foot-note">The data is stale: refresh before changing the stage.</p>}
        <p className="small" style={{ margin: 0 }}>{i.summary}</p>
        {verifying && (notIndependent
          ? <Callout tone="amber" title="Needs an independent check">You own this incident or set it to mitigating, so another staff member must verify recovery.</Callout>
          : <div className="field"><label htmlFor={`rn-${i.id}`}>Recovery verification note <span className="muted small">(required · how you confirmed recovery)</span></label>
            <textarea id={`rn-${i.id}`} className="input" rows={2} maxLength={2000} value={recoveryNote} onChange={(e) => setRecoveryNote(e.target.value)}
              placeholder="e.g. error rate back to baseline for 60 min; 50 test payouts settled" /></div>)}
        <Facts title="Incident control facts" rows={[
          ['Kind', label(i.kind)], ['Severity', i.severity], ['Incident owner', i.owner],
          ['Detected', shortDateTime(i.detectedAt)], ['Acknowledged', shortDateTime(i.acknowledgedAt)],
          ['Mitigating', `${shortDateTime(i.mitigatingAt)}${i.mitigatedBy ? ` · ${i.mitigatedBy}` : ''}`], ['Monitoring', shortDateTime(i.monitoringAt)],
          ['Recovered', `${shortDateTime(i.recoveredAt)}${i.recoveryVerifiedBy ? ` · verified by ${i.recoveryVerifiedBy}` : ''}`], ['Closed', shortDateTime(i.closedAt)],
          ['Parties notified', i.notifications.length],
        ]} />
        {i.recoveryNote && <Facts title="Recovery verification" rows={[['Recorded', i.recoveryNote]]} />}
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
          {next && next !== 'RECOVERED' && <label className="checkbox"><input type="checkbox" name="advance" disabled={stale} /> <span>{STEP_ACTION[next]}{stale ? ' (refresh first)' : ''}</span></label>}
          {next === 'RECOVERED' && <p className="adm-foot-note">Recovery is verified from the Response tab with a verification note.</p>}
          <button className="btn btn-primary btn-sm" disabled={busy}>Save</button>
          <p className="adm-foot-note">Only the owner or an incident lead can change severity, stage or the review.</p>
        </form>
      )}
    </DetailPanel>
  )
}
