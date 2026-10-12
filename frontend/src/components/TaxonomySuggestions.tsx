import { useCallback, useEffect, useState } from 'react'
import { api } from '../api/client'
import { ErrorAlert, useStepUp } from './ui'
interface Suggestion { id: string; name: string; description: string; groupSlug: string | null; status: string; resolutionNote: string | null }
interface Matches { matches: { slug: string; name: string; groupName: string }[]; draft: { name: string; groupSlug: string | null; categorySlug: string | null; description: string; credentialLikely: boolean } | null; source: string }
export function TaxonomySuggestions({ staff = false }: { staff?: boolean }) {
  const [items, setItems] = useState<Suggestion[]>([])
  const [text, setText] = useState('')
  const [matches, setMatches] = useState<Matches | null>(null)
  const [note, setNote] = useState('')
  const [group, setGroup] = useState('')
  const [merge, setMerge] = useState('')
  const [regulated, setRegulated] = useState(false)
  const [credential, setCredential] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<unknown>(null)
  const { run, modal } = useStepUp(setError)
  const load = useCallback(() => api<Suggestion[]>(staff ? '/v1/admin/taxonomy/suggestions' : '/v1/taxonomy/suggestions/mine').then(setItems).catch(setError), [staff])
  useEffect(() => { load() }, [load])
  async function suggest() {
    setBusy(true); setError(null)
    try { setMatches(await api<Matches>('/v1/taxonomy/suggest', { method: 'POST', body: { text } })) }
    catch (err) { setError(err) } finally { setBusy(false) }
  }
  function decide(s: Suggestion, action: 'APPROVE' | 'MERGE' | 'REJECT') {
    run(async () => {
      setBusy(true)
      try { await api(`/v1/admin/taxonomy/suggestions/${s.id}/decision`, { method: 'POST', body: {
        action, note, groupSlug: group || s.groupSlug, mergeSlug: merge || null, requiresCredential: credential, regulated,
      } }); await load() } finally { setBusy(false) }
    })
  }
  return <section className="card panel"><h2>{staff ? 'Taxonomy suggestion review' : 'Cannot find your specialisation?'}</h2>{modal}<ErrorAlert error={error} />
    {!staff && <><label className="filter-box">Describe your work
      <textarea minLength={3} maxLength={1000} value={text} onChange={e => setText(e.target.value)} /></label>
      <button type="button" className="btn btn-secondary" disabled={busy || text.trim().length < 3} onClick={suggest}>Find specialisations</button>
      {matches && <><ul>{matches.matches.map(m => <li key={m.slug}>{m.name} · {m.groupName} · {m.slug}</li>)}</ul>
        <p className="muted small">Suggestions are advisory. Choose an existing specialisation in the profile selector.</p>
        {matches.draft && <button type="button" className="btn btn-secondary" disabled={busy} onClick={async () => {
          setBusy(true); setError(null)
          try { await api('/v1/taxonomy/suggestions', { method: 'POST', body: { text, ...matches.draft, source: matches.source } }); await load(); setMatches(null) }
          catch (err) { setError(err) } finally { setBusy(false) }
        }}>Submit “{matches.draft.name}” for review</button>}</>}
    </>}
    {staff && <><label className="filter-box">Group slug for approval<input value={group} onChange={e => setGroup(e.target.value)} /></label>
      <label className="filter-box">Existing specialisation slug for merge<input value={merge} onChange={e => setMerge(e.target.value)} /></label>
      <label className="filter-box">Decision explanation<textarea maxLength={500} value={note} onChange={e => setNote(e.target.value)} /></label>
      <label><input type="checkbox" checked={regulated} onChange={e => setRegulated(e.target.checked)} /> Regulated</label>
      <label><input type="checkbox" checked={credential} onChange={e => setCredential(e.target.checked)} /> Requires credential</label></>}
    {items.map(s => <article className="case" key={s.id}><h3>{s.name} · {s.status}</h3><p>{s.description}</p><p>{s.resolutionNote}</p>
      {staff && s.status === 'PENDING' && <>
        <button type="button" className="btn btn-primary" disabled={busy || !(group || s.groupSlug)} onClick={() => decide(s, 'APPROVE')}>Approve</button>
        <button type="button" className="btn btn-secondary" disabled={busy || !merge} onClick={() => decide(s, 'MERGE')}>Merge into existing</button>
        <button type="button" className="btn btn-ghost" disabled={busy || !note.trim()} onClick={() => decide(s, 'REJECT')}>Reject</button>
      </>}
    </article>)}
  </section>
}
