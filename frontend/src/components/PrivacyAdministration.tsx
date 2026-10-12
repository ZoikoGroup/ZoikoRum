import { useCallback, useEffect, useState } from 'react'
import { api } from '../api/client'
import type { DataRequest } from '../api/account'
import { ErrorAlert, useStepUp } from './ui'

type RequestRow = DataRequest & { identityId: string }
export default function PrivacyAdministration() {
  const [rows, setRows] = useState<RequestRow[]>([])
  const [note, setNote] = useState('')
  const [error, setError] = useState<unknown>(null)
  const step = useStepUp(setError)
  const load = useCallback(async () => { setRows(await api<RequestRow[]>('/v1/admin/privacy-requests')) }, [])
  useEffect(() => {
    let active = true
    api<RequestRow[]>('/v1/admin/privacy-requests')
      .then(value => { if (active) setRows(value) })
      .catch(err => { if (active) setError(err) })
    return () => { active = false }
  }, [])
  return <section className="card panel"><h1>Privacy requests</h1><ErrorAlert error={error} />{step.modal}
    <p>Review the account scope and document any withheld records before providing a data copy. Erasure needs a separate retention decision.</p>
    <label htmlFor="privacy-review-note">Scope and review note</label><textarea id="privacy-review-note" className="input" minLength={20} maxLength={2000} value={note} onChange={e => setNote(e.target.value)} />
    <button className="btn btn-secondary" onClick={() => step.run(load)}>Refresh</button>
    <table className="data"><thead><tr><th>Account</th><th>Request</th><th>Status</th><th>Action</th></tr></thead><tbody>{rows.map(r => <tr key={r.id}>
      <td>{r.identityId}</td><td>{r.requestType}</td><td>{r.status}</td><td>{r.requestType === 'ACCESS' && !r.exportReady && <button className="btn btn-primary btn-sm" disabled={note.trim().length < 20} onClick={() => step.run(async () => { await api(`/v1/admin/privacy-requests/${r.id}/access`, { method: 'POST', body: { note: note.trim() } }); await load() })}>Prepare data copy</button>}</td>
    </tr>)}</tbody></table>
  </section>
}
