import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { submittedNotice, type ApprovalRequest } from '../../api/approvals'
import { api } from '../../api/client'
import { useCapabilities } from '../../auth/capabilities'
import { ErrorAlert, useStepUp } from '../../components/ui'
import { Icon } from '../../components/dashboard'
import {
  AdminHeader, AdminKpi, Callout, CountTabs, DetailPanel, Facts, FilterBar, HBars, KpiStrip, ListDetail, MetricList, Panel, PanelRow, Pill,
  StackBar, TableFoot, shortDateTime,pickRow } from '../../components/admin'

/* Feature Controls (design 68): operational switches (pause one kind of action at once) and feature flags (gradual
   rollout). Sources: GET/PUT /v1/admin/switches, GET/PUT /v1/admin/flags, GET /v1/admin/flags/{key}/fairness. Every
   change needs two-step sign-in (step-up) and a reason, and is audited by the server. A switch change is a
   maker-checker request: it takes effect only when a second person with the same authority approves it (Approvals). */

interface OpsSwitch { key: string; label: string; effect: string; money: boolean; paused: boolean; reason: string | null; changedAt: string | null }
interface Flag {
  key: string; label: string; description: string; rankingExperiment: boolean; rolloutPct: number; organizationIds: string[]
  reason: string | null; changedAt: string | null
}
interface Fairness { passes: boolean; maxRelativeDrop: number; groups: { group: string; before: number; after: number; relativeDrop: number; ok: boolean }[] }

type TabKey = 'switches' | 'paused' | 'money' | 'flags'
type Sel = { type: 'switch' | 'flag'; key: string } | null

export default function FeatureControls() {
  const { has } = useCapabilities()
  const admin = has('flags.manage')  // feature flags (Platform Admin)
  const [switches, setSwitches] = useState<OpsSwitch[] | null>(null)
  const [flags, setFlags] = useState<Flag[] | null>(null)
  const [error, setError] = useState<unknown>(null)
  const [notice, setNotice] = useState('')
  const [tab, setTab] = useState<TabKey>('switches')
  const [q, setQ] = useState('')
  const [sel, setSel] = useState<Sel>(null)
  const [editing, setEditing] = useState(false)
  const { run, modal } = useStepUp(setError)

  const reload = useCallback(async () => {
    const [s, f] = await Promise.all([api<OpsSwitch[]>('/v1/admin/switches'), admin ? api<Flag[]>('/v1/admin/flags') : Promise.resolve(null)])
    setSwitches(s); setFlags(f)
  }, [admin])
  useEffect(() => { reload().catch(setError) }, [reload])

  const sw = switches ?? []
  const fl = flags ?? []
  const paused = sw.filter((s) => s.paused)
  const canChange = (s: OpsSwitch) => has(s.money ? 'switches.request_money' : 'switches.request')
  const partial = fl.filter((f) => f.rolloutPct > 0 && f.rolloutPct < 100).length
  const s = q.trim().toLowerCase()
  const match = (...v: string[]) => !s || v.some((x) => x.toLowerCase().includes(s))
  const shownSwitches = sw.filter((x) => (tab === 'paused' ? x.paused : tab === 'money' ? x.money : true) && match(x.label, x.key, x.effect))
  const shownFlags = fl.filter((f) => match(f.label, f.key, f.description))
  const selSwitch = sel?.type === 'switch' ? sw.find((x) => x.key === sel.key) ?? null : null
  const selFlag = sel?.type === 'flag' ? fl.find((x) => x.key === sel.key) ?? null : null

  const changes = [
    ...sw.filter((x) => x.changedAt).map((x) => ({ at: x.changedAt!, what: `${x.label}: ${x.paused ? 'paused' : 'switched on'}`, why: x.reason })),
    ...fl.filter((x) => x.changedAt).map((x) => ({ at: x.changedAt!, what: `${x.label}: ${x.rolloutPct}%`, why: x.reason })),
  ].sort((a, b) => b.at.localeCompare(a.at)).slice(0, 5)

  function pick(next: Sel, edit = false) { setSel(next); setEditing(edit); setNotice('') }

  const tabs: { key: TabKey; label: string; count: number }[] = [
    { key: 'switches', label: 'All switches', count: sw.length },
    { key: 'paused', label: 'Effective pauses', count: paused.length },
    { key: 'money', label: 'Money switches', count: sw.filter((x) => x.money).length },
    ...(admin ? [{ key: 'flags' as TabKey, label: 'Feature flags', count: fl.length }] : []),
  ]

  return (
    <>
      <AdminHeader crumb="Platform reliability / Governed control plane" title="Feature Controls"
        subtitle="Pause one kind of action at once during an incident, and roll features out gradually. Every change needs two-step sign-in and a reason, and is audited."
        actions={<button type="button" className="btn btn-secondary" onClick={() => reload().catch(setError)}><Icon name="refresh" /> Refresh</button>} />
      <ErrorAlert error={error} />
      {notice && <div className="alert alert-success" role="status">{notice}</div>}
      {modal}

      <KpiStrip>
        <AdminKpi icon="list" tone="blue" label="Switch catalogue" value={switches ? sw.length : '—'} sub={`${sw.filter((x) => x.money).length} about money`} />
        <AdminKpi icon="check" tone="green" label="Effective: on" value={switches ? sw.length - paused.length : '—'} />
        <AdminKpi icon="alert" tone={paused.length ? 'red' : 'violet'} label="Effective: paused" value={switches ? paused.length : '—'} sub={paused.length ? 'Actions refused while paused' : 'No effective pauses'} />
        {admin && <AdminKpi icon="sliders" tone="teal" label="Feature flags" value={flags ? fl.length : '—'} sub={`${fl.filter((f) => f.rankingExperiment).length} ranking experiments`} />}
        {admin && <AdminKpi icon="layers" tone="amber" label="Partly rolled out" value={flags ? partial : '—'} sub="Between 0% and 100%" />}
      </KpiStrip>

      <PanelRow cols={3}>
        <Panel title="Effective switch state" meta={`${sw.length - paused.length} on · ${paused.length} paused`}>
          <StackBar segments={[{ label: 'On', value: sw.length - paused.length, color: '#12b76a' }, { label: 'Paused', value: paused.length, color: '#f04438' }]} />
          <MetricList rows={sw.map((x) => ({ label: x.label, value: x.paused ? 'Paused' : 'On', tone: x.paused ? 'red' : 'green' }))} />
        </Panel>
        {admin ? (
          <Panel title="Feature rollout" meta="Share of organisations">
            <HBars rows={fl.map((f) => ({ label: f.label, value: f.rolloutPct }))} format={(v) => `${v}%`} />
          </Panel>
        ) : (
          <Panel title="Your authority">
            <p className="small" style={{ margin: 0 }}>Financial Operations may pause and resume money switches. The other switches and feature flags are changed by a Platform Admin.</p>
          </Panel>
        )}
        <Panel title="Recent control changes" meta="Latest recorded change per control">
          {changes.length === 0 ? <p className="muted small">No change recorded yet.</p>
            : <MetricList rows={changes.map((c) => ({ label: <span>{c.what}<span className="cell-sub" style={{ display: 'block' }}>{c.why}</span></span>, value: <span className="small muted">{shortDateTime(c.at)}</span> }))} />}
        </Panel>
      </PanelRow>

      <ListDetail
        list={
          <div className="card">
            <CountTabs tabs={tabs} value={tab} onChange={(t) => { setTab(t); setSel(null) }} />
            <FilterBar search={q} onSearch={setQ} placeholder={tab === 'flags' ? 'Search flag name or key…' : 'Search control, key or effect…'} />
            <div className="adm-note">{tab === 'flags' ? 'Rollout is per organisation; each always gets the same answer' : 'Effective state as enforced by the server'}</div>
            <div className="adm-table-wrap">
              {tab !== 'flags' ? (
                <table className="data">
                  <thead><tr><th scope="col">Action</th><th scope="col">While paused</th><th scope="col">Authority</th><th scope="col">State</th><th scope="col"><span className="sr-only">Change</span></th></tr></thead>
                  <tbody>
                    {switches === null && <tr><td colSpan={5} className="empty-row">Loading switches…</td></tr>}
                    {switches && shownSwitches.length === 0 && <tr><td colSpan={5} className="empty-row">No switches here.</td></tr>}
                    {shownSwitches.map((x) => (
                      <tr {...pickRow} key={x.key} className={`pick ${selSwitch?.key === x.key ? 'selected' : ''}`} onClick={() => pick({ type: 'switch', key: x.key })}>
                        <td><div className="cell-main">{x.label}</div><div className="cell-sub">{x.key}</div></td>
                        <td className="small">{x.effect}</td>
                        <td className="small">{x.money ? 'Platform Admin or Financial Ops' : 'Platform Admin'}</td>
                        <td>
                          <Pill tone={x.paused ? 'red' : 'green'}>{x.paused ? 'Paused' : 'On'}</Pill>
                          {x.reason && <div className="cell-sub">{x.reason}{x.changedAt ? ` · ${shortDateTime(x.changedAt)}` : ''}</div>}
                        </td>
                        <td>{canChange(x) && (
                          <button type="button" className={`btn btn-sm ${x.paused ? 'btn-primary' : 'btn-secondary'}`}
                            onClick={(e) => { e.stopPropagation(); pick({ type: 'switch', key: x.key }, true) }}>{x.paused ? 'Switch back on' : 'Pause'}</button>)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              ) : (
                <table className="data">
                  <thead><tr><th scope="col">Flag</th><th scope="col">Rollout</th><th scope="col">Named organisations</th><th scope="col">Last change</th><th scope="col"><span className="sr-only">Change</span></th></tr></thead>
                  <tbody>
                    {shownFlags.length === 0 && <tr><td colSpan={5} className="empty-row">No flags here.</td></tr>}
                    {shownFlags.map((f) => (
                      <tr {...pickRow} key={f.key} className={`pick ${selFlag?.key === f.key ? 'selected' : ''}`} onClick={() => pick({ type: 'flag', key: f.key })}>
                        <td><div className="cell-main">{f.label}{f.rankingExperiment && <> <Pill tone="violet">ranking experiment</Pill></>}</div><div className="cell-sub">{f.description}</div></td>
                        <td>{f.rolloutPct}%</td><td>{f.organizationIds.length}</td>
                        <td className="small">{f.changedAt ? `${shortDateTime(f.changedAt)}: ${f.reason}` : '—'}</td>
                        <td><button type="button" className="btn btn-secondary btn-sm" onClick={(e) => { e.stopPropagation(); pick({ type: 'flag', key: f.key }, true) }}>Change</button></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
            <TableFoot shown={tab === 'flags' ? shownFlags.length : shownSwitches.length} total={tab === 'flags' ? fl.length : sw.length} noun={tab === 'flags' ? 'flags' : 'switches'} />
          </div>
        }
        detail={selSwitch ? (
          <SwitchDetail key={selSwitch.key} s={selSwitch} allowed={canChange(selSwitch)} editing={editing} setEditing={setEditing} onClose={() => setSel(null)}
            save={(reason) => run(async () => {
              const request = await api<ApprovalRequest>(`/v1/admin/switches/${selSwitch.key}`, { method: 'PUT', body: { paused: !selSwitch.paused, reason } })
              setEditing(false); await reload()
              setNotice(`${selSwitch.paused ? 'Switching back on' : 'Pausing'} ${selSwitch.label}: ${submittedNotice(request)}`)
            })} />
        ) : selFlag ? (
          <FlagDetail key={selFlag.key} f={selFlag} editing={editing} setEditing={setEditing} onClose={() => setSel(null)} onError={setError}
            save={(body) => run(async () => {
              await api(`/v1/admin/flags/${selFlag.key}`, { method: 'PUT', body })
              setEditing(false); await reload()
              setNotice(`${selFlag.label} saved.`)
            })} />
        ) : undefined}
      />
    </>
  )
}

function SwitchDetail({ s, allowed, editing, setEditing, onClose, save }: {
  s: OpsSwitch; allowed: boolean; editing: boolean; setEditing: (v: boolean) => void; onClose: () => void; save: (reason: string) => Promise<void>
}) {
  const [reason, setReason] = useState('')
  function submit(e: FormEvent) { e.preventDefault(); void save(reason).then(() => setReason('')) }
  return (
    <DetailPanel title={s.label} subtitle={s.key} badge={<Pill tone={s.paused ? 'red' : 'green'}>{s.paused ? 'Paused' : 'On'}</Pill>} onClose={onClose}
      footer={allowed && !editing ? <button type="button" className={`btn btn-sm ${s.paused ? 'btn-primary' : 'btn-secondary'}`} onClick={() => setEditing(true)}>
        {s.paused ? 'Switch back on' : 'Pause'}</button> : undefined}>
      {s.paused
        ? <Callout tone="red" title="Effective: paused">{s.effect}</Callout>
        : <Callout tone="green" title="Effective: on">Pausing it means: {s.effect}</Callout>}
      <Facts title="Effective state" rows={[
        ['State', s.paused ? 'Paused' : 'On'], ['Authority', s.money ? 'Platform Admin or Financial Ops' : 'Platform Admin'],
        ['Last change', shortDateTime(s.changedAt)], ['Recorded reason', s.reason ?? '—'],
      ]} />
      {!allowed && <p className="adm-foot-note">Only a Platform Admin can change this switch.</p>}
      {allowed && editing && (
        <form onSubmit={submit} style={{ display: 'grid', gap: 6 }}>
          <label className="small" htmlFor={`reason-${s.key}`}>Reason (recorded in the audit trail)</label>
          <input id={`reason-${s.key}`} className="input" value={reason} onChange={(e) => setReason(e.target.value)} minLength={10} maxLength={500} required />
          <div style={{ display: 'flex', gap: 6 }}>
            <button className="btn btn-primary btn-sm">{s.paused ? 'Request switch on' : 'Request pause'}</button>
            <button type="button" className="btn btn-ghost btn-sm" onClick={() => setEditing(false)}>Cancel</button>
          </div>
          <p className="adm-foot-note">You will be asked for a fresh two-step code. The change applies once another
            {s.money ? ' Platform Admin or Financial Operations member' : ' Platform Admin'} approves it.</p>
        </form>
      )}
    </DetailPanel>
  )
}

function FlagDetail({ f, editing, setEditing, onClose, onError, save }: {
  f: Flag; editing: boolean; setEditing: (v: boolean) => void; onClose: () => void; onError: (e: unknown) => void
  save: (body: { rolloutPct: number; organizationIds: string[]; reason: string }) => Promise<void>
}) {
  const [pct, setPct] = useState(f.rolloutPct)
  const [orgs, setOrgs] = useState(f.organizationIds.join(', '))
  const [reason, setReason] = useState('')
  const [fairness, setFairness] = useState<Fairness | null>(null)
  useEffect(() => {
    if (f.rankingExperiment) api<Fairness>(`/v1/admin/flags/${f.key}/fairness`).then(setFairness).catch(onError)
  }, [f.key, f.rankingExperiment, onError])
  return (
    <DetailPanel title={f.label} subtitle={f.key} badge={<Pill tone={f.rolloutPct === 100 ? 'green' : f.rolloutPct === 0 ? 'grey' : 'amber'}>{f.rolloutPct}%</Pill>} onClose={onClose}
      footer={!editing ? <button type="button" className="btn btn-secondary btn-sm" onClick={() => setEditing(true)}>Change</button> : undefined}>
      <p className="small" style={{ margin: 0 }}>{f.description}</p>
      <Facts title="Effective rollout" rows={[
        ['Share of organisations', `${f.rolloutPct}%`], ['Named organisations', f.organizationIds.length],
        ['Ranking experiment', f.rankingExperiment ? 'Yes' : 'No'], ['Last change', shortDateTime(f.changedAt)], ['Recorded reason', f.reason ?? '—'],
      ]} />
      {fairness && <>
        <Callout tone={fairness.passes ? 'green' : 'amber'} title={`Fairness check ${fairness.passes ? 'passes' : 'fails'}`}>
          No group may lose more than {Math.round(fairness.maxRelativeDrop * 100)}% of its share of top-10 search places.</Callout>
        <table className="data small"><thead><tr><th scope="col">Group</th><th scope="col">Share now</th><th scope="col">With the change</th><th scope="col" /></tr></thead>
          <tbody>{fairness.groups.map((g) => <tr key={g.group}><td>{g.group}</td><td>{Math.round(g.before * 100)}%</td>
            <td>{Math.round(g.after * 100)}%</td><td><Pill tone={g.ok ? 'green' : 'amber'}>{g.ok ? 'ok' : 'loses too much'}</Pill></td></tr>)}</tbody></table>
      </>}
      {editing && (
        <form onSubmit={(e) => {
          e.preventDefault()
          void save({ rolloutPct: pct, organizationIds: orgs.split(',').map((x) => x.trim()).filter(Boolean), reason })
        }} style={{ display: 'grid', gap: 8 }}>
          <label className="small">Share of organisations: {pct}%<input type="range" min={0} max={100} step={5} value={pct} onChange={(e) => setPct(Number(e.target.value))} style={{ width: '100%' }} /></label>
          <label className="small">Named organisations (IDs, comma-separated)<input className="input" value={orgs} onChange={(e) => setOrgs(e.target.value)} /></label>
          <label className="small">Reason<input className="input" value={reason} onChange={(e) => setReason(e.target.value)} placeholder="e.g. Pilot with two buyers before wider release" /></label>
          <div style={{ display: 'flex', gap: 6 }}>
            <button className="btn btn-primary btn-sm" disabled={reason.trim().length < 10}>Save</button>
            <button type="button" className="btn btn-ghost btn-sm" onClick={() => setEditing(false)}>Cancel</button>
          </div>
        </form>
      )}
    </DetailPanel>
  )
}
