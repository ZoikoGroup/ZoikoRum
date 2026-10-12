import { useState, useEffect, useCallback } from 'react'
import { api } from '../api/client'
import { ErrorAlert, useStepUp } from './ui'
interface Duplicate {
  id: string; signal: string; status: string; userAnswer: string | null; userNote: string | null
  resolutionNote: string | null; account: string | null; otherAccount: string | null
  identityId: string | null; otherIdentityId: string | null
}
export function DuplicateAccountReview({ staff = false }: { staff?: boolean }) {
  const [items, setItems] = useState<Duplicate[]>([])
  const [error, setError] = useState<unknown>(null)
  const [busy, setBusy] = useState(false)
  const [note, setNote] = useState('')
  const { run, modal } = useStepUp(setError)
  const root = staff ? '/v1/admin/duplicate-accounts' : '/v1/me/duplicate-accounts'
  const load = useCallback(() => api<Duplicate[]>(root).then(setItems).catch(setError), [root])
  useEffect(() => { load() }, [load])
  async function answer(d: Duplicate, answer: 'MERGE_REQUESTED' | 'NOT_ME') {
    setBusy(true); setError(null)
    try { await api(`${root}/${d.id}/answer`, { method: 'POST', body: { answer, note } }); await load() }
    catch (err) { setError(err) } finally { setBusy(false) }
  }
  function resolve(d: Duplicate, keepIdentityId: string | null) {
    run(async () => {
      setBusy(true)
      try { await api(`${root}/${d.id}/resolve`, { method: 'POST', body: { outcome: keepIdentityId ? 'MERGED' : 'NOT_DUPLICATE', keepIdentityId, note: note.trim() } }); await load() }
      finally { setBusy(false) }
    })
  }
  return <section className="card panel"><h2>Possible duplicate accounts</h2>{modal}<ErrorAlert error={error} />
    {items.length === 0 ? <p>No duplicate account cases.</p> : <>
      <label className="filter-box">Explanation {staff && '(required)'}<textarea maxLength={500} value={note} onChange={e => setNote(e.target.value)} /></label>
      {items.map(d => <article className="case" key={d.id}><p>{d.account ?? 'Your account'} · {d.otherAccount} · {d.status}</p>
        <p>{d.userAnswer} {d.userNote} {d.resolutionNote}</p>
        {['OPEN', 'ANSWERED'].includes(d.status) && (staff ? <>
          <p>Keeping an account closes and restricts the duplicate. This does not transfer business records.</p>
          <button className="btn btn-secondary" disabled={busy || note.trim().length < 5} onClick={() => resolve(d, d.identityId)}>Keep {d.account}</button>
          <button className="btn btn-secondary" disabled={busy || note.trim().length < 5} onClick={() => resolve(d, d.otherIdentityId)}>Keep {d.otherAccount}</button>
          <button className="btn btn-ghost" disabled={busy || note.trim().length < 5} onClick={() => resolve(d, null)}>Not duplicate</button>
        </> : <>
          <button className="btn btn-secondary" disabled={busy} onClick={() => answer(d, 'MERGE_REQUESTED')}>Request account merge</button>
          <button className="btn btn-ghost" disabled={busy} onClick={() => answer(d, 'NOT_ME')}>This is not me</button>
        </>)}
      </article>)}
    </>}
  </section>
}
