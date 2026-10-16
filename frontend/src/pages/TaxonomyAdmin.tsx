import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { taxonomyApi, type SpecializationFlags, type SpecializationSuggestion, type TaxonomyCategory, type TaxonomyGroup,
  type TaxonomySpecialization } from '../api/professional'
import { EmptyTable, PortalHeader } from '../components/portal'
import { ErrorAlert, useStepUp } from '../components/ui'

const FLAGS: [keyof SpecializationFlags, string][] = [
  ['requiresCredential', 'Credential required'], ['regulated', 'Regulated'], ['requiresInsurance', 'Insurance required'],
]
const flagsOf = (s: TaxonomySpecialization): SpecializationFlags =>
  ({ requiresCredential: s.requiresCredential, regulated: s.regulated, requiresInsurance: !!s.requiresInsurance })

function FlagBoxes({ value, onChange }: { value: SpecializationFlags; onChange: (v: SpecializationFlags) => void }) {
  return (
    <span className="row small" style={{ gap: 10 }}>
      {FLAGS.map(([key, label]) => (
        <label key={key} className="checkbox small"><input type="checkbox" checked={value[key]}
          onChange={(e) => onChange({ ...value, [key]: e.target.checked })} /><span>{label}</span></label>
      ))}
    </span>
  )
}

/** The specialization list: add, rename, change what a specialization requires, or retire it. Every change makes a new
    taxonomy version of the category; retired ones can no longer be chosen, but profiles that have them keep them. */
function SpecializationList({ taxonomy, run, onChanged, notify }: {
  taxonomy: TaxonomyCategory[]
  run: (action: () => Promise<void>) => void
  onChanged: () => Promise<unknown>
  notify: (text: string) => void
}) {
  const [editing, setEditing] = useState<{ slug: string; name: string; flags: SpecializationFlags } | null>(null)
  const [adding, setAdding] = useState<{ groupSlug: string; name: string; flags: SpecializationFlags } | null>(null)
  const none: SpecializationFlags = { requiresCredential: false, regulated: false, requiresInsurance: false }

  const save = (s: TaxonomySpecialization) => run(async () => {
    if (!editing) return
    const before = flagsOf(s)
    const changes = Object.fromEntries((Object.keys(before) as (keyof SpecializationFlags)[])
      .filter((k) => before[k] !== editing.flags[k]).map((k) => [k, editing.flags[k]]))
    await taxonomyApi.updateSpecialization(s.slug, { ...(editing.name.trim() !== s.name ? { name: editing.name.trim() } : {}), ...changes })
    setEditing(null)
    notify(`“${editing.name.trim()}” was updated.`)
    await onChanged()
  })
  const retire = (s: TaxonomySpecialization) => {
    if (!confirm(`Retire “${s.name}”? Professionals can no longer choose it; profiles that have it keep it.`)) return
    run(async () => { await taxonomyApi.retireSpecialization(s.slug); notify(`“${s.name}” was retired.`); await onChanged() })
  }
  const add = (e: FormEvent, g: TaxonomyGroup) => {
    e.preventDefault()
    if (!adding) return
    run(async () => {
      await taxonomyApi.createSpecialization({ groupSlug: g.slug, name: adding.name.trim(), ...adding.flags })
      notify(`“${adding.name.trim()}” was added to ${g.name}.`)
      setAdding(null)
      await onChanged()
    })
  }
  const seed = () => run(async () => {
    const r = await taxonomyApi.seedDefaults()
    notify(`Default list loaded: ${r.specializations} specializations in total. Edited entries were kept.`)
    await onChanged()
  })

  return (
    <section className="card panel">
      <div className="panel-head">
        <h2>Specialization list</h2>
        <button type="button" className="btn btn-secondary btn-sm" onClick={seed}>Load default list</button>
      </div>
      <p className="muted small" style={{ marginTop: 0 }}>
        Every change makes a new version of the category's taxonomy. Retired specializations cannot be chosen any more;
        profiles and contracts that use them keep them.
      </p>
      {taxonomy.length === 0 && <p className="muted">No categories yet. Load the default list to start.</p>}
      {taxonomy.map((c) => (
        <details key={c.slug} className="taxonomy-category">
          <summary><strong>{c.name}</strong> <span className="muted small">· version {c.version} ·{' '}
            {c.groups.reduce((n, g) => n + g.specializations.length, 0)} specializations</span></summary>
          {c.groups.map((g) => (
            <div key={g.slug} style={{ margin: '12px 0 0 12px' }}>
              <h3 style={{ fontSize: 14, margin: '0 0 6px' }}>{g.name}</h3>
              <table className="data">
                <thead><tr><th>Specialization</th><th>Requires</th><th aria-label="Actions" /></tr></thead>
                <tbody>{g.specializations.map((s) => editing?.slug === s.slug ? (
                  <tr key={s.slug}>
                    <td><input className="input" aria-label={`Name of ${s.name}`} value={editing.name}
                      onChange={(e) => setEditing({ ...editing, name: e.target.value })} /></td>
                    <td><FlagBoxes value={editing.flags} onChange={(flags) => setEditing({ ...editing, flags })} /></td>
                    <td style={{ textAlign: 'right', whiteSpace: 'nowrap' }}>
                      <button type="button" className="btn btn-primary btn-sm" disabled={editing.name.trim().length < 2} onClick={() => save(s)}>Save</button>{' '}
                      <button type="button" className="btn btn-ghost btn-sm" onClick={() => setEditing(null)}>Cancel</button>
                    </td>
                  </tr>
                ) : (
                  <tr key={s.slug}>
                    <td>{s.name}<div className="muted small">{s.slug}</div></td>
                    <td className="small">{FLAGS.filter(([k]) => flagsOf(s)[k]).map(([, label]) => label).join(' · ') || '—'}</td>
                    <td style={{ textAlign: 'right', whiteSpace: 'nowrap' }}>
                      <button type="button" className="btn btn-secondary btn-sm" onClick={() => setEditing({ slug: s.slug, name: s.name, flags: flagsOf(s) })}>Edit</button>{' '}
                      <button type="button" className="btn btn-ghost btn-sm" onClick={() => retire(s)}>Retire</button>
                    </td>
                  </tr>
                ))}</tbody>
              </table>
              {adding?.groupSlug === g.slug ? (
                <form className="row" style={{ marginTop: 6, flexWrap: 'wrap', gap: 8 }} onSubmit={(e) => add(e, g)}>
                  <input className="input" style={{ flex: 1, minWidth: 180 }} aria-label={`New specialization in ${g.name}`} placeholder="Name"
                    value={adding.name} onChange={(e) => setAdding({ ...adding, name: e.target.value })} maxLength={200} />
                  <FlagBoxes value={adding.flags} onChange={(flags) => setAdding({ ...adding, flags })} />
                  <button className="btn btn-primary btn-sm" disabled={adding.name.trim().length < 2}>Add</button>
                  <button type="button" className="btn btn-ghost btn-sm" onClick={() => setAdding(null)}>Cancel</button>
                </form>
              ) : (
                <button type="button" className="btn btn-ghost btn-sm" style={{ marginTop: 6 }}
                  onClick={() => setAdding({ groupSlug: g.slug, name: '', flags: none })}>+ Add specialization</button>
              )}
            </div>
          ))}
        </details>
      ))}
    </section>
  )
}

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
      <PortalHeader eyebrow="Administration" title="Taxonomy"
        subtitle="Review specializations professionals could not find, and maintain the specialization list." />
      <ErrorAlert error={error} />
      {notice && <div className="alert alert-success" role="status">{notice}</div>}
      {modal}
      <section className="card panel">
        <div className="panel-head"><h2>Suggestions from professionals</h2></div>
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
      <SpecializationList taxonomy={taxonomy} run={run} onChanged={load} notify={setNotice} />
    </>
  )
}
