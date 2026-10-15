import { useCallback, useEffect, useState } from 'react'
import { api } from '../api/client'
import { saveBlob } from '../lib/exports'
import { Icon } from './dashboard'
import { ErrorAlert, useStepUp } from './ui'

interface ApiKey { id: string; name: string; prefix: string; scope: 'READ' | 'WRITE'; tier: string; createdAt: string; expiresAt: string | null
  lastUsedAt: string | null; revokedAt: string | null; active: boolean }

/** Organisation Admins: API keys for connecting the organisation's own systems. */
export function ApiKeysPanel({ orgId }: { orgId: string }) {
  const [keys, setKeys] = useState<ApiKey[] | null>(null)
  const [f, setF] = useState({ name: '', scope: 'READ', days: '' })
  const [created, setCreated] = useState<string | null>(null)
  const [error, setError] = useState<unknown>(null)
  const { run, modal } = useStepUp(setError)
  const base = `/v1/organizations/${orgId}/api-keys`
  const load = useCallback(() => { api<ApiKey[]>(base).then(setKeys).catch(setError) }, [base])
  useEffect(() => { load() }, [load])
  const create = () => run(async () => {
    const r = await api<ApiKey & { key: string }>(base, { method: 'POST', body: { name: f.name, scope: f.scope, expiresInDays: f.days ? Number(f.days) : null } })
    setCreated(r.key); setF({ name: '', scope: 'READ', days: '' }); load()
  })
  const revoke = (k: ApiKey) => { if (confirm(`Revoke "${k.name}"? Systems using it stop working at once.`)) run(async () => { await api(`${base}/${k.id}/revoke`, { method: 'POST' }); load() }) }
  return (
    <section className="card panel">
      {modal}
      <div className="panel-head"><h2>API keys</h2></div>
      <p className="small muted">A key acts as you, with your current roles, and stops working if you leave or stop being an Org Admin.
        It cannot sign, release money or do anything else that asks for two-step confirmation. Send it as <code>Authorization: Bearer &lt;key&gt;</code>.</p>
      <ErrorAlert error={error} />
      {created && <div className="alert alert-success" role="status"><strong>Copy this key now; it is not shown again:</strong>
        <div><code style={{ wordBreak: 'break-all' }}>{created}</code></div>
        <button className="btn btn-ghost btn-sm" onClick={() => { navigator.clipboard?.writeText(created).catch(() => {}) }}>Copy</button>
        <button className="btn btn-ghost btn-sm" onClick={() => setCreated(null)}>Done</button></div>}
      {keys && keys.length > 0 && <table className="data small"><thead><tr><th>Name</th><th>Key</th><th>Access</th><th>Budget</th><th>Last used</th><th /></tr></thead>
        <tbody>{keys.map((k) => <tr key={k.id}><td>{k.name}</td><td><code>{k.prefix}…</code></td><td>{k.scope === 'WRITE' ? 'Read and write' : 'Read only'}</td>
          <td>{k.tier.toLowerCase()}</td><td>{k.lastUsedAt ? new Date(k.lastUsedAt).toLocaleString() : 'never'}</td>
          <td>{k.active ? <button className="btn btn-ghost btn-sm" onClick={() => revoke(k)}>Revoke</button>
            : <span className="badge">{k.revokedAt ? 'revoked' : 'expired'}</span>}</td></tr>)}</tbody></table>}
      <div className="row" style={{ marginTop: 10 }}>
        <input className="input" aria-label="Key name" placeholder="What it is for, e.g. ERP sync" value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} />
        <select className="input" aria-label="Access" value={f.scope} onChange={(e) => setF({ ...f, scope: e.target.value })}>
          <option value="READ">Read only</option><option value="WRITE">Read and write</option></select>
        <input className="input" aria-label="Expires in days" type="number" min={1} max={730} placeholder="Expires in days (optional)" value={f.days} onChange={(e) => setF({ ...f, days: e.target.value })} />
        <button className="btn btn-secondary btn-sm" disabled={f.name.trim().length < 2} onClick={create}>Create key</button>
      </div>
    </section>
  )
}

/** The security and compliance summary for a procurement review. */
export function ProcurementPackButton({ onError }: { onError: (e: unknown) => void }) {
  return <button className="btn btn-secondary btn-sm" onClick={() => api<Blob>('/v1/procurement-pack', { blob: true })
    .then((b) => saveBlob('zoikorum-procurement-pack.pdf', b)).catch(onError)}><Icon name="download" /> Procurement pack (PDF)</button>
}
