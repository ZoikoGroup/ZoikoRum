import { useCallback, useEffect, useState } from 'react'
import { api } from '../api/client'
import { ErrorAlert, useStepUp } from './ui'

interface Flag {
  key: string; label: string; description: string; rankingExperiment: boolean; rolloutPct: number; organizationIds: string[]
  reason: string | null; changedAt: string | null
}
interface Fairness { passes: boolean; maxRelativeDrop: number; groups: { group: string; before: number; after: number; relativeDrop: number; ok: boolean }[] }

/** Platform Admin: roll features out gradually. Ranking experiments show their fairness check first. */
export function FeatureFlags({ admin }: { admin: boolean }) {
  const [flags, setFlags] = useState<Flag[] | null>(null)
  const [editing, setEditing] = useState<Flag | null>(null)
  const [pct, setPct] = useState(0)
  const [orgs, setOrgs] = useState('')
  const [reason, setReason] = useState('')
  const [fairness, setFairness] = useState<Fairness | null>(null)
  const [error, setError] = useState<unknown>(null)
  const { run, modal } = useStepUp(setError)
  const load = useCallback(() => { if (admin) api<Flag[]>('/v1/admin/flags').then(setFlags).catch(setError) }, [admin])
  useEffect(() => { load() }, [load])
  if (!admin) return null

  function edit(f: Flag) {
    setEditing(f); setPct(f.rolloutPct); setOrgs(f.organizationIds.join(', ')); setReason(''); setFairness(null)
    if (f.rankingExperiment) api<Fairness>(`/v1/admin/flags/${f.key}/fairness`).then(setFairness).catch(setError)
  }
  const save = () => run(async () => {
    const organizationIds = orgs.split(',').map((x) => x.trim()).filter(Boolean)
    await api(`/v1/admin/flags/${editing!.key}`, { method: 'PUT', body: { rolloutPct: pct, organizationIds, reason } })
    setEditing(null); load()
  })
  return (
    <section className="card panel">
      {modal}
      <div className="panel-head"><h2>Feature flags</h2></div>
      <p className="muted small">Roll a feature out to a share of organisations (each always gets the same answer) or to named ones first.
        Every change needs two-step sign-in and a reason, and is audited.</p>
      <ErrorAlert error={error} />
      {!flags ? null : <table className="data"><thead><tr><th>Flag</th><th>Rollout</th><th>Named organisations</th><th>Last change</th><th /></tr></thead>
        <tbody>{flags.map((f) => <tr key={f.key}>
          <td><strong>{f.label}</strong>{f.rankingExperiment && <span className="badge" style={{ marginLeft: 6 }}>ranking experiment</span>}
            <div className="muted small">{f.description}</div></td>
          <td>{f.rolloutPct}%</td><td>{f.organizationIds.length}</td>
          <td className="small">{f.changedAt ? `${new Date(f.changedAt).toLocaleString()}: ${f.reason}` : '—'}</td>
          <td><button className="btn btn-ghost btn-sm" onClick={() => edit(f)}>Change</button></td></tr>)}</tbody></table>}
      {editing && <div className="card panel" style={{ marginTop: 12 }}>
        <h3 style={{ marginTop: 0 }}>{editing.label}</h3>
        {fairness && <>
          <p className={`small ${fairness.passes ? 'ok-text' : 'warn-text'}`}>Fairness check {fairness.passes ? 'passes' : 'fails'}: no group may lose more than
            {' '}{Math.round(fairness.maxRelativeDrop * 100)}% of its share of top-10 search places.</p>
          <table className="data small"><thead><tr><th>Group</th><th>Share now</th><th>With the change</th><th /></tr></thead>
            <tbody>{fairness.groups.map((g) => <tr key={g.group}><td>{g.group}</td><td>{Math.round(g.before * 100)}%</td>
              <td>{Math.round(g.after * 100)}%</td><td><span className={`badge ${g.ok ? 'green' : 'warn'}`}>{g.ok ? 'ok' : 'loses too much'}</span></td></tr>)}</tbody></table>
        </>}
        <label>Share of organisations: {pct}%<input type="range" min={0} max={100} step={5} value={pct} onChange={(e) => setPct(Number(e.target.value))} style={{ width: '100%' }} /></label>
        <label>Named organisations (IDs, comma-separated)<input className="input" value={orgs} onChange={(e) => setOrgs(e.target.value)} /></label>
        <label>Reason<input className="input" value={reason} onChange={(e) => setReason(e.target.value)} placeholder="e.g. Pilot with two buyers before wider release" /></label>
        <div className="row" style={{ marginTop: 8 }}>
          <button className="btn btn-primary btn-sm" disabled={reason.trim().length < 10} onClick={save}>Save</button>
          <button className="btn btn-ghost btn-sm" onClick={() => setEditing(null)}>Cancel</button></div>
      </div>}
    </section>
  )
}
