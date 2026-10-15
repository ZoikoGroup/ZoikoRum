import { useEffect, useState } from 'react'
import { api } from '../api/client'
import { ErrorAlert } from './ui'

interface Archive { id: string; fromSeq: number; toSeq: number; records: number; sha256: string; objectKey: string; locked: boolean
  archivedAt: string; lastVerifiedAt: string | null }

/** Audit records copied to write-once storage after 90 days; each batch can be read back and checked. */
export function AuditArchives() {
  const [rows, setRows] = useState<Archive[] | null>(null)
  const [error, setError] = useState<unknown>(null)
  const [result, setResult] = useState<Record<string, string>>({})
  useEffect(() => { api<Archive[]>('/v1/admin/audit/archives').then(setRows).catch(setError) }, [])
  const verify = (a: Archive) => api<{ ok: boolean; problems: string[] }>(`/v1/admin/audit/archives/${a.id}/verify`, { method: 'POST' })
    .then((r) => setResult({ ...result, [a.id]: r.ok ? 'Unchanged and the chain holds' : r.problems.join('; ') })).catch(setError)
  if (error) return <ErrorAlert error={error} />
  if (!rows) return null
  return (
    <section className="card panel">
      <div className="panel-head"><h2>Archived audit records</h2></div>
      <p className="muted small">Records older than 90 days are copied daily to write-once storage; the database keeps them too.</p>
      {rows.length === 0 ? <p className="muted small">Nothing archived yet.</p> : (
        <table className="data small"><thead><tr><th>Records</th><th>Archived</th><th>Locked</th><th>Fingerprint</th><th>Check</th></tr></thead>
          <tbody>{rows.map((a) => <tr key={a.id}><td>#{a.fromSeq}–#{a.toSeq} ({a.records})</td><td>{new Date(a.archivedAt).toLocaleDateString()}</td>
            <td>{a.locked ? 'legal hold' : 'write-once'}</td><td><code>{a.sha256.slice(0, 12)}…</code></td>
            <td>{result[a.id] ?? <button className="btn btn-ghost btn-sm" onClick={() => verify(a)}>Verify</button>}</td></tr>)}</tbody></table>)}
    </section>
  )
}
