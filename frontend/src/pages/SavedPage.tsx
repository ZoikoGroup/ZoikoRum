import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { LABEL } from '../api/professional'
import { savedApi, type SavedProfessional } from '../api/saved'
import { useAuth } from '../auth/AuthContext'
import { ErrorAlert } from '../components/ui'

/** Saved-ids for pages that show many professionals; null until known (or when the viewer cannot save). */
// eslint-disable-next-line react-refresh/only-export-components
export function useSavedIds() {
  const { user } = useAuth()
  const canSave = !!user?.personas.some((p) => p === 'BUYER' || p === 'ENTERPRISE_ADMIN' || p === 'ENTERPRISE_MEMBER')
  const [ids, setIds] = useState<Set<string> | null>(null)
  useEffect(() => {
    if (canSave) savedApi.list().then((l) => setIds(new Set(l.map((s) => s.professionalId)))).catch(() => setIds(new Set()))
  }, [canSave])
  const toggle = useCallback(async (id: string) => {
    if (!ids) return
    const next = new Set(ids)
    if (ids.has(id)) { await savedApi.remove(id); next.delete(id) } else { await savedApi.save(id); next.add(id) }
    setIds(next)
  }, [ids])
  return { canSave, ids, toggle }
}

export function SaveButton({ id, saved, onToggle }: { id: string; saved: boolean; onToggle: (id: string) => void }) {
  return (
    <button type="button" className={`btn btn-sm ${saved ? 'btn-secondary' : 'btn-ghost'}`} aria-pressed={saved}
      onClick={() => onToggle(id)}>{saved ? '★ Saved' : '☆ Save'}</button>
  )
}

export function SavedPage() {
  const [items, setItems] = useState<SavedProfessional[] | null>(null)
  const [error, setError] = useState<unknown>(null)
  const load = useCallback(() => savedApi.list().then(setItems).catch(setError), [])
  useEffect(() => { load() }, [load])

  async function remove(id: string) {
    try { await savedApi.remove(id); await load() } catch (err) { setError(err) }
  }

  return (
    <>
      <div className="page-head"><div><h1>Saved professionals</h1>
        <p className="muted" style={{ margin: 0 }}>Your shortlist. Compare them, and request proposals when you're ready.</p></div>
        <Link className="btn btn-primary" to="/professionals">Find more</Link></div>
      <ErrorAlert error={error} />
      <section className="card panel">
        {items === null ? <p className="muted">Loading…</p> : items.length === 0 ? (
          <p className="muted" style={{ margin: 0 }}>Nothing saved yet. Use ☆ Save on a profile or search result.</p>
        ) : (
          <table className="data">
            <thead><tr><th>Professional</th><th>Specialization</th><th>Trust Tier</th><th>Availability</th><th>Saved</th><th /></tr></thead>
            <tbody>{items.map((s) => (
              <tr key={s.professionalId}>
                <td>{s.available ? <Link to={`/professionals/${s.professionalId}`}><strong>{s.displayName}</strong></Link>
                  : <><strong>{s.displayName}</strong> <span className="badge warn">No longer listed</span></>}
                  {s.headline && <div className="muted small">{s.headline}</div>}</td>
                <td>{s.primarySpecialization ?? '—'}</td>
                <td><span className={`badge ${s.tier === 'C' ? 'warn' : 'green'}`}>Tier {s.tier}</span></td>
                <td>{LABEL[s.availability] ?? s.availability}</td>
                <td>{new Date(s.savedAt).toLocaleDateString()}</td>
                <td style={{ textAlign: 'right' }}><button className="btn btn-ghost btn-sm" onClick={() => remove(s.professionalId)}>Remove</button></td>
              </tr>
            ))}</tbody>
          </table>
        )}
      </section>
    </>
  )
}
