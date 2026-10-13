import { useCallback, useEffect, useState } from 'react'
import { taxonomyApi, type SpecializationSuggestion, type TaxonomyCategory } from '../api/professional'
import { EmptyTable, PortalHeader } from '../components/portal'
import { ErrorAlert, useStepUp } from '../components/ui'

/* Platform Admin: specializations suggested by professionals ("Can't find yours?"). Approve creates it for everyone,
   Merge points it at an existing one (avoids duplicates such as "ML Engineer" vs "Machine Learning Engineering"),
   Reject explains why. Nothing goes live without this decision (AI assists, humans decide). */

interface Draft { name: string; groupSlug: string; credential: boolean; regulated: boolean; mergeSlug: string; note: string }

export default function TaxonomyAdminPage() {
  const [rows, setRows] = useState<SpecializationSuggestion[] | null>(null)
  const [taxonomy, setTaxonomy] = useState<TaxonomyCategory[]>([])
  const [drafts, setDrafts] = useState<Record<string, Draft>>({})
  const [error, setError] = useState<unknown>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const { run, modal } = useStepUp(setError)
  const load = useCallback(() => Promise.all([taxonomyApi.queue(), taxonomyApi.all()]).then(([q, t]) => {
    setRows(q); setTaxonomy(t)
    setDrafts(Object.fromEntries(q.map((s) => [s.id, { name: s.name, groupSlug: s.groupSlug ?? '', credential: s.credentialLikely, regulated: false, mergeSlug: '', note: '' }])))
  }).catch(setError), [])
  useEffect(() => { load() }, [load])

  const set = (id: string, patch: Partial<Draft>) => setDrafts({ ...drafts, [id]: { ...drafts[id], ...patch } })
  const decide = (s: SpecializationSuggestion, action: 'APPROVE' | 'MERGE' | 'REJECT') => run(async () => {
    const d = drafts[s.id]
    await taxonomyApi.decide(s.id, action === 'APPROVE' ? { action, name: d.name, groupSlug: d.groupSlug, requiresCredential: d.credential, regulated: d.regulated, note: d.note }
      : action === 'MERGE' ? { action, mergeSlug: d.mergeSlug, note: d.note } : { action, note: d.note })
    setNotice(action === 'APPROVE' ? `“${d.name}” is now a specialization and was added to the professional's profile.`
      : action === 'MERGE' ? 'Merged: the professional now has the existing specialization.' : 'Rejected; the professional sees your note.')
    await load()
  })

  return (
    <>
      <PortalHeader eyebrow="Administration" title="Taxonomy suggestions"
        subtitle="Specializations professionals could not find. Approve, merge into an existing one, or reject with a reason." />
      <ErrorAlert error={error} />
      {notice && <div className="alert alert-success" role="status">{notice}</div>}
      {modal}
      <section className="card panel">
        {rows && rows.length === 0 ? <EmptyTable columns={['Suggestion', 'Their words', 'Decision']}><strong>No suggestions waiting.</strong></EmptyTable> : (
          <table className="data"><thead><tr><th>Suggestion</th><th>Their words</th><th>Decision</th></tr></thead>
            <tbody>{(rows ?? []).map((s) => {
              const d = drafts[s.id]
              if (!d) return null
              return (
                <tr key={s.id}>
                  <td><strong>{s.name}</strong><div className="muted small">{s.professionalName ?? '—'} · {new Date(s.createdAt).toLocaleDateString()}</div>
                    <div className="small">{s.source.startsWith('ai:') ? 'AI draft' : s.source === 'manual' ? 'Typed by the professional' : 'Keyword match'}
                      {s.credentialLikely && <span className="badge warn" style={{ marginLeft: 6 }}>Credential likely</span>}</div></td>
                  <td className="small" style={{ maxWidth: 260 }}>“{s.text}”{s.description && s.description !== s.text && <div className="muted">{s.description}</div>}</td>
                  <td style={{ minWidth: 340 }}>
                    <div className="row" style={{ flexWrap: 'wrap' }}>
                      <input className="input" style={{ flex: 1, minWidth: 140 }} value={d.name} onChange={(e) => set(s.id, { name: e.target.value })} aria-label="Final name" />
                      <select className="input" style={{ flex: 1, minWidth: 140 }} value={d.groupSlug} onChange={(e) => set(s.id, { groupSlug: e.target.value })} aria-label="Group">
                        <option value="">Choose a group…</option>
                        {taxonomy.map((c) => <optgroup key={c.slug} label={c.name}>{c.groups.map((g) => <option key={g.slug} value={g.slug}>{g.name}</option>)}</optgroup>)}
                      </select>
                    </div>
                    <div className="row small" style={{ marginTop: 4 }}>
                      <label className="checkbox small"><input type="checkbox" checked={d.credential} onChange={(e) => set(s.id, { credential: e.target.checked })} /><span>Credential required</span></label>
                      <label className="checkbox small"><input type="checkbox" checked={d.regulated} onChange={(e) => set(s.id, { regulated: e.target.checked })} /><span>Regulated</span></label>
                    </div>
                    <select className="input" style={{ marginTop: 4 }} value={d.mergeSlug} onChange={(e) => set(s.id, { mergeSlug: e.target.value })} aria-label="Merge into">
                      <option value="">Or merge into an existing specialization…</option>
                      {taxonomy.map((c) => <optgroup key={c.slug} label={c.name}>{c.groups.flatMap((g) => g.specializations).map((x) => <option key={x.slug} value={x.slug}>{x.name}</option>)}</optgroup>)}
                    </select>
                    <input className="input" style={{ marginTop: 4 }} placeholder="Note to the professional (required to reject)" maxLength={500}
                      value={d.note} onChange={(e) => set(s.id, { note: e.target.value })} />
                    <div className="row" style={{ marginTop: 6, flexWrap: 'wrap' }}>
                      <button className="btn btn-primary btn-sm" disabled={!d.groupSlug || d.name.trim().length < 2} onClick={() => decide(s, 'APPROVE')}>Approve</button>
                      <button className="btn btn-secondary btn-sm" disabled={!d.mergeSlug} onClick={() => decide(s, 'MERGE')}>Merge</button>
                      <button className="btn btn-ghost btn-sm" disabled={d.note.trim().length < 5} onClick={() => decide(s, 'REJECT')}>Reject</button>
                    </div>
                  </td>
                </tr>
              )
            })}</tbody></table>
        )}
      </section>
    </>
  )
}
