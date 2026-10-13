import { useEffect, useState } from 'react'
import { taxonomyApi, type SpecializationDraft, type SpecializationMatch, type SpecializationSuggestion, type TaxonomyCategory } from '../api/professional'
import { ErrorAlert } from './ui'

/* "Can't find yours?": the professional describes the work in their own words; AI (or keyword matching) points to the
   closest existing specializations, and if nothing fits, drafts a new one that an admin approves before it goes live.
   AI assists, humans decide: the professional picks, the admin approves. */

const STATUS: Record<SpecializationSuggestion['status'], string> = {
  PENDING: 'Under review', APPROVED: 'Approved: added to your profile', MERGED: 'Matched to an existing specialization', REJECTED: 'Not added',
}

export function CantFindSpecialization({ taxonomy, onPick }: {
  taxonomy: TaxonomyCategory[]; onPick: (slug: string, as: 'primary' | 'secondary') => void
}) {
  const [open, setOpen] = useState(false)
  const [text, setText] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<unknown>(null)
  const [result, setResult] = useState<{ matches: SpecializationMatch[]; draft: SpecializationDraft | null; source: string } | null>(null)
  const [draft, setDraft] = useState<SpecializationDraft | null>(null)
  const [mine, setMine] = useState<SpecializationSuggestion[]>([])
  const [sent, setSent] = useState<string | null>(null)
  useEffect(() => { taxonomyApi.mySuggestions().then(setMine).catch(() => {}) }, [])
  const groups = taxonomy.flatMap((c) => c.groups.map((g) => ({ ...g, categorySlug: c.slug, categoryName: c.name })))

  async function find() {
    setBusy(true); setError(null); setSent(null)
    try {
      const r = await taxonomyApi.suggest(text.trim())
      setResult(r)
      setDraft(r.draft ?? { name: '', categorySlug: null, groupSlug: null, description: text.trim(), credentialLikely: false })
    } catch (err) { setError(err) } finally { setBusy(false) }
  }
  async function submit() {
    if (!draft) return
    setBusy(true); setError(null)
    try {
      const s = await taxonomyApi.submitSuggestion({ text: text.trim(), name: draft.name.trim(), groupSlug: draft.groupSlug,
        categorySlug: draft.categorySlug, description: draft.description, credentialLikely: draft.credentialLikely, source: result?.source })
      setMine([s, ...mine]); setSent(`“${s.name}” was sent for review. It shows on your profile as “under review” until an admin approves it.`)
      setResult(null); setText('')
    } catch (err) { setError(err) } finally { setBusy(false) }
  }

  return (
    <section className="cant-find">
      {!open ? <p className="small">Can't find your specialization?{' '}
        <button type="button" className="link-btn small" style={{ display: 'inline', padding: 0 }} onClick={() => setOpen(true)}>Describe it in your own words</button></p> : <>
        <h3>Can't find yours?</h3>
        <ErrorAlert error={error} />
        {sent && <div className="alert alert-success" role="status">{sent}</div>}
        <textarea className="input" rows={2} maxLength={1000} value={text} onChange={(e) => setText(e.target.value)}
          placeholder="e.g. I build machine-learning models that read invoices and receipts for finance teams" />
        <div className="row" style={{ marginTop: 8 }}>
          <button type="button" className="btn btn-secondary btn-sm" disabled={busy || text.trim().length < 3} onClick={find}>{busy ? 'Looking…' : 'Find matches'}</button>
          <button type="button" className="btn btn-ghost btn-sm" onClick={() => setOpen(false)}>Close</button>
        </div>
        {result && <div style={{ marginTop: 12 }}>
          <p className="muted small">{result.source.startsWith('ai:') ? 'Suggested by AI from your description.' : 'Matched by keywords.'} You choose.</p>
          {result.matches.length > 0 ? <ul className="match-list">{result.matches.map((m) => (
            <li key={m.slug}><span><strong>{m.name}</strong> <span className="muted small">{m.categoryName} · {m.groupName}</span></span>
              <span className="row"><button type="button" className="btn btn-ghost btn-sm" onClick={() => onPick(m.slug, 'primary')}>Make primary</button>
                <button type="button" className="btn btn-ghost btn-sm" onClick={() => onPick(m.slug, 'secondary')}>Add</button></span></li>))}</ul>
            : <p className="small">No existing specialization matches well.</p>}
          {draft && <div className="evidence-form">
            <strong>None of these? Suggest a new specialization</strong>
            <p className="muted small">An admin reviews it. Until then your profile shows it as “under review”; once approved anyone can filter by it.</p>
            <div className="row">
              <label className="filter-box grow"><span>Name</span><input value={draft.name} maxLength={200} onChange={(e) => setDraft({ ...draft, name: e.target.value })} /></label>
              <label className="filter-box"><span>Where it belongs</span>
                <select value={draft.groupSlug ?? ''} onChange={(e) => {
                  const g = groups.find((x) => x.slug === e.target.value)
                  setDraft({ ...draft, groupSlug: g?.slug ?? null, categorySlug: g?.categorySlug ?? null })
                }}><option value="">Not sure</option>
                  {taxonomy.map((c) => <optgroup key={c.slug} label={c.name}>{c.groups.map((g) => <option key={g.slug} value={g.slug}>{g.name}</option>)}</optgroup>)}
                </select></label>
            </div>
            <label className="checkbox small" style={{ marginTop: 6 }}><input type="checkbox" checked={draft.credentialLikely}
              onChange={(e) => setDraft({ ...draft, credentialLikely: e.target.checked })} /><span>This work usually needs a licence or certificate</span></label>
            <button type="button" className="btn btn-primary btn-sm" style={{ marginTop: 8 }} disabled={busy || draft.name.trim().length < 2} onClick={submit}>Send for review</button>
          </div>}
        </div>}
      </>}
      {mine.length > 0 && <ul className="match-list" style={{ marginTop: 8 }}>{mine.slice(0, 5).map((s) => (
        <li key={s.id}><span><strong>{s.name}</strong> <span className="muted small">your suggestion</span></span>
          <span className={`badge ${s.status === 'APPROVED' || s.status === 'MERGED' ? 'green' : s.status === 'PENDING' ? 'warn' : ''}`}
            title={s.resolutionNote ?? undefined}>{STATUS[s.status]}</span></li>))}</ul>}
    </section>
  )
}
