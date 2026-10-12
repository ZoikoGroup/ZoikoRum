import { useCallback, useEffect, useState } from 'react'
import { api } from '../api/client'
import { ErrorAlert } from './ui'
interface Relationship { id: string; name: string; kind: 'BUYER' | 'ORGANIZATION'; emailAlerts: boolean; inAppAlerts: boolean; savedAt: string }
const root = '/v1/professionals/me/relationships'
export function SavedBuyers() {
  const [items, setItems] = useState<Relationship[] | null>(null)
  const [error, setError] = useState<unknown>(null)
  const [busy, setBusy] = useState(false)
  const load = useCallback(() => api<Relationship[]>(root).then(setItems).catch(setError), [])
  useEffect(() => { load() }, [load])
  async function alerts(r: Relationship, field: 'emailAlerts' | 'inAppAlerts', value: boolean) {
    setBusy(true); setError(null)
    try { await api(`${root}/${r.id}`, { method: 'PATCH', body: { emailAlerts: r.emailAlerts, inAppAlerts: r.inAppAlerts, [field]: value } }); await load() }
    catch (err) { setError(err) } finally { setBusy(false) }
  }
  return <section className="card panel"><h1>Saved buyers &amp; followed organisations</h1><ErrorAlert error={error} />
    <p>Save buyers or follow organisations from your incoming requests. Follows grant no access to private work. These settings apply to new requests sent to you; global notification preferences still apply.</p>
    {items === null ? <p>Loading…</p> : items.length === 0 ? <p>No saved relationships.</p> : items.map(r => <article className="case" key={r.id}>
      <h2>{r.name}</h2><p>{r.kind === 'BUYER' ? 'Saved buyer' : 'Followed organisation'} · Saved {new Date(r.savedAt).toLocaleDateString()}</p>
      <label><input type="checkbox" checked={r.emailAlerts} disabled={busy} onChange={e => alerts(r, 'emailAlerts', e.target.checked)} /> Email new-request alerts</label>
      <label><input type="checkbox" checked={r.inAppAlerts} disabled={busy} onChange={e => alerts(r, 'inAppAlerts', e.target.checked)} /> In-app new-request alerts</label>
      <button className="btn btn-ghost" disabled={busy} onClick={async () => {
        setBusy(true); setError(null)
        try { await api(`${root}/${r.id}`, { method: 'DELETE' }); await load() }
        catch (err) { setError(err) } finally { setBusy(false) }
      }}>{r.kind === 'BUYER' ? 'Unsave buyer' : 'Unfollow organisation'}</button>
    </article>)}
  </section>
}
export function RelationshipButtons({ requestId }: { requestId: string }) {
  const [busy, setBusy] = useState(false)
  const [notice, setNotice] = useState('')
  const [error, setError] = useState<unknown>(null)
  async function save(kind: Relationship['kind']) {
    setBusy(true); setError(null)
    try { await api(root, { method: 'POST', body: { requestId, kind } }); setNotice(kind === 'BUYER' ? 'Buyer saved.' : 'Organisation followed.') }
    catch (err) { setError(err) } finally { setBusy(false) }
  }
  return <section className="card panel"><h2>Keep in touch</h2><ErrorAlert error={error} />
    {notice && <p role="status">{notice}</p>}
    <button className="btn btn-secondary" disabled={busy} onClick={() => save('BUYER')}>Save buyer</button>
    <button className="btn btn-secondary" disabled={busy} onClick={() => save('ORGANIZATION')}>Follow organisation</button>
  </section>
}
