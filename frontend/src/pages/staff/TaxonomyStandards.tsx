import { useCallback, useEffect, useState, type FormEvent, type ReactNode } from 'react'
import { taxonomyApi, type SpecializationFlags, type SpecializationSuggestion, type TaxonomyCategory, type TaxonomyGroup,
  type TaxonomySpecialization } from '../../api/professional'
import { AdminHeader, AdminKpi, Callout, CountTabs, DetailPanel, Facts, FilterBar, HBars, KpiStrip, ListDetail, MetricList, Panel, PanelRow,
  Pill, TableFoot, shortDate, pickRow } from '../../components/admin'
import { CaseOwner, OwnerCell, useAssignments } from '../../components/CaseOwner'
import { ErrorAlert, useStepUp } from '../../components/ui'

/* Taxonomy & Standards (design 56). Platform Admin maintains the specialization list (every change makes a new taxonomy
   version of the category; retired specializations can no longer be chosen, but profiles and contracts keep them) and
   decides on specializations professionals suggested ("Can't find yours?"): Approve creates it for everyone, Merge points
   it at an existing one, Reject explains why. Nothing goes live without this decision (AI assists, humans decide). */

const FLAGS: [keyof SpecializationFlags, string][] = [
  ['requiresCredential', 'Credential required'], ['regulated', 'Regulated'], ['requiresInsurance', 'Insurance required'],
]
const NONE: SpecializationFlags = { requiresCredential: false, regulated: false, requiresInsurance: false }
const flagsOf = (s: TaxonomySpecialization): SpecializationFlags =>
  ({ requiresCredential: s.requiresCredential, regulated: s.regulated, requiresInsurance: !!s.requiresInsurance })
const specsOf = (c: TaxonomyCategory) => c.groups.flatMap((g) => g.specializations)
const sourceLabel = (s: SpecializationSuggestion) => (s.source.startsWith('ai:') ? 'AI draft' : s.source === 'manual' ? 'Typed by the professional' : 'Keyword match')

function FlagBoxes({ value, onChange }: { value: SpecializationFlags; onChange: (v: SpecializationFlags) => void }) {
  return (
    <span className="row small" style={{ gap: 10, flexWrap: 'wrap' }}>
      {FLAGS.map(([key, label]) => (
        <label key={key} className="checkbox small"><input type="checkbox" checked={value[key]}
          onChange={(e) => onChange({ ...value, [key]: e.target.checked })} /><span>{label}</span></label>
      ))}
    </span>
  )
}

interface Draft { name: string; groupSlug: string; credential: boolean; regulated: boolean; mergeSlug: string; note: string }
type Tab = 'registry' | 'suggestions'

export default function TaxonomyStandards() {
  const [rows, setRows] = useState<SpecializationSuggestion[] | null>(null)
  const [taxonomy, setTaxonomy] = useState<TaxonomyCategory[] | null>(null)
  const [drafts, setDrafts] = useState<Record<string, Draft>>({})
  const [error, setError] = useState<unknown>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const { run, modal } = useStepUp(setError)
  const [tab, setTab] = useState<Tab>('registry')
  const [search, setSearch] = useState('')
  const [selected, setSelected] = useState<string | null>(null)
  const owners = useAssignments(['TAXONOMY_SUGGESTION'])  // suggestions only: the registry itself has no case owner

  const load = useCallback(() => Promise.all([taxonomyApi.queue(), taxonomyApi.all()]).then(([q, t]) => {
    setRows(q); setTaxonomy(t)
    setDrafts(Object.fromEntries(q.map((s) => [s.id, { name: s.name, groupSlug: s.groupSlug ?? '', credential: s.credentialLikely, regulated: false, mergeSlug: '', note: '' }])))
  }).catch(setError), [])
  useEffect(() => { load() }, [load])

  const cats = taxonomy ?? []
  const queue = rows ?? []
  const allSpecs = cats.flatMap(specsOf)
  const groups = cats.reduce((n, c) => n + c.groups.length, 0)
  const pendingFor = (c: TaxonomyCategory) => queue.filter((s) => s.categorySlug === c.slug).length
  const term = search.trim().toLowerCase()
  const shownCats = cats.filter((c) => !term || c.name.toLowerCase().includes(term) || c.slug.includes(term)
    || specsOf(c).some((s) => s.name.toLowerCase().includes(term)))
  const shownSugs = queue.filter((s) => !term || `${s.name} ${s.text} ${s.professionalName ?? ''}`.toLowerCase().includes(term))
  const selCat = tab === 'registry' ? cats.find((c) => c.slug === selected) ?? null : null
  const selSug = tab === 'suggestions' ? queue.find((s) => s.id === selected) ?? null : null

  const seed = () => run(async () => {
    const r = await taxonomyApi.seedDefaults()
    setNotice(`Default list loaded: ${r.specializations} specializations in total. Edited entries were kept.`)
    await load()
  })
  const set = (id: string, patch: Partial<Draft>) => setDrafts({ ...drafts, [id]: { ...drafts[id], ...patch } })
  const decide = (s: SpecializationSuggestion, action: 'APPROVE' | 'MERGE' | 'REJECT') => run(async () => {
    const d = drafts[s.id]
    await taxonomyApi.decide(s.id, action === 'APPROVE' ? { action, name: d.name, groupSlug: d.groupSlug, requiresCredential: d.credential, regulated: d.regulated, note: d.note }
      : action === 'MERGE' ? { action, mergeSlug: d.mergeSlug, note: d.note } : { action, note: d.note })
    setNotice(action === 'APPROVE' ? `“${d.name}” is now a specialization and was added to the professional's profile.`
      : action === 'MERGE' ? 'Merged: the professional now has the existing specialization.' : 'Rejected; the professional sees your note.')
    setSelected(null)
    await load()
  })

  const count = (k: keyof SpecializationFlags) => allSpecs.filter((s) => flagsOf(s)[k]).length
  return (
    <>
      {modal}
      <AdminHeader crumb="Engagement operations / Controlled classification" title="Taxonomy & Standards"
        subtitle="Review specializations professionals could not find, and maintain the specialization list. Every change makes a new version of the category."
        actions={<button type="button" className="btn btn-secondary" onClick={seed}>Load default list</button>} />
      <ErrorAlert error={error} />
      {notice && <div className="alert alert-success" role="status">{notice}</div>}

      <KpiStrip>
        <AdminKpi icon="layers" tone="blue" label="Published categories" value={taxonomy ? cats.length : '—'} sub={`${groups} groups`} />
        <AdminKpi icon="list" tone="green" label="Active specializations" value={taxonomy ? allSpecs.length : '—'} sub={`Across ${cats.length} categories`} />
        <AdminKpi icon="star" tone="violet" label="Professional suggestions" value={rows ? queue.length : '—'} sub="Human decision required" />
        <AdminKpi icon="shield" tone="amber" label="Credential required" value={taxonomy ? count('requiresCredential') : '—'} sub="Specializations" />
        <AdminKpi icon="scale" tone="red" label="Regulated" value={taxonomy ? count('regulated') : '—'} sub="Specializations" />
        <AdminKpi icon="lock" tone="teal" label="Insurance required" value={taxonomy ? count('requiresInsurance') : '—'} sub="Specializations" />
      </KpiStrip>

      <PanelRow cols={3}>
        <Panel title="Published taxonomy inventory" meta={`${cats.length} categories · ${allSpecs.length} active terms`}>
          <HBars rows={[...cats].sort((a, b) => specsOf(b).length - specsOf(a).length).map((c) => ({ label: c.name, value: specsOf(c).length }))} />
        </Panel>
        <Panel title="Suggestion workflow" meta="Nothing is published automatically">
          <MetricList rows={[
            { label: 'Waiting for a decision', value: queue.length, tone: queue.length ? 'amber' : undefined },
            { label: 'AI drafts', value: queue.filter((s) => s.source.startsWith('ai:')).length },
            { label: 'Typed by the professional', value: queue.filter((s) => s.source === 'manual').length },
            { label: 'Credential likely', value: queue.filter((s) => s.credentialLikely).length },
            { label: 'No category proposed', value: queue.filter((s) => !s.categorySlug).length },
          ]} />
        </Panel>
        <Panel title="Requirements mix" meta="Active specializations">
          <HBars rows={FLAGS.map(([k, l], i) => ({ label: l, value: count(k), color: ['#f79009', '#f04438', '#0e9384'][i] }))} />
          <p className="adm-foot-note">Retired specializations stay on profiles and contracts that already use them.</p>
        </Panel>
      </PanelRow>

      <ListDetail
        list={
          <div className="card">
            <CountTabs<Tab> value={tab} onChange={(t) => { setTab(t); setSelected(null) }} tabs={[
              { key: 'registry', label: 'Published registry', count: taxonomy ? cats.length : null },
              { key: 'suggestions', label: 'Suggestions', count: rows ? queue.length : null },
            ]} />
            <FilterBar search={search} onSearch={setSearch} placeholder={tab === 'registry' ? 'Search category or specialization…' : 'Search suggestion or professional…'} />
            {tab === 'registry' ? <>
              <div className="adm-table-wrap"><table className="data">
                <thead><tr><th scope="col">Category</th><th scope="col">Version</th><th scope="col">Groups</th><th scope="col">Terms</th><th scope="col">Requirements</th><th scope="col">Suggestions</th></tr></thead>
                <tbody>
                  {taxonomy && shownCats.length === 0 && <tr><td colSpan={6} className="empty-row">{cats.length ? 'No categories match.' : 'No categories yet. Load the default list to start.'}</td></tr>}
                  {shownCats.map((c) => {
                    const sp = specsOf(c)
                    const p = pendingFor(c)
                    return (
                      <tr {...pickRow} key={c.slug} className={`pick ${selected === c.slug ? 'selected' : ''}`} onClick={() => setSelected(c.slug)}>
                        <td><div className="cell-main">{c.name}</div><div className="cell-sub">{c.slug}</div></td>
                        <td><Pill tone="grey">v{c.version}</Pill></td>
                        <td className="small">{c.groups.length}</td>
                        <td><strong>{sp.length}</strong><div className="cell-sub">Active terms</div></td>
                        <td className="small">{sp.filter((s) => s.requiresCredential).length} credential · {sp.filter((s) => s.regulated).length} regulated</td>
                        <td>{p ? <Pill tone="amber">{p} pending</Pill> : <span className="muted">—</span>}</td>
                      </tr>)
                  })}
                </tbody>
              </table></div>
              <TableFoot shown={shownCats.length} total={cats.length} noun="categories" />
            </> : <>
              <div className="adm-table-wrap"><table className="data">
                <thead><tr><th scope="col">Suggestion</th><th scope="col">Their words</th><th scope="col">Source</th><th scope="col">Proposed group</th><th scope="col">Owner</th></tr></thead>
                <tbody>
                  {rows && shownSugs.length === 0 && <tr><td colSpan={5} className="empty-row"><strong>No suggestions waiting.</strong></td></tr>}
                  {shownSugs.map((s) => (
                    <tr {...pickRow} key={s.id} className={`pick ${selected === s.id ? 'selected' : ''}`} onClick={() => setSelected(s.id)}>
                      <td><div className="cell-main">{s.name}</div><div className="cell-sub">{s.professionalName ?? '—'} · {shortDate(s.createdAt)}</div></td>
                      <td className="small" style={{ maxWidth: 260 }}>“{s.text}”</td>
                      <td className="small">{sourceLabel(s)}{s.credentialLikely && <div><Pill tone="amber">Credential likely</Pill></div>}</td>
                      <td className="small">{cats.flatMap((c) => c.groups).find((g) => g.slug === s.groupSlug)?.name ?? '—'}</td>
                      <td><OwnerCell assignment={owners.get('TAXONOMY_SUGGESTION', s.id)} /></td>
                    </tr>))}
                </tbody>
              </table></div>
              <TableFoot shown={shownSugs.length} total={queue.length} noun="suggestions" />
            </>}
          </div>
        }
        detail={selCat ? <CategoryEditor key={selCat.slug} c={selCat} pending={pendingFor(selCat)} run={run} onChanged={load} notify={setNotice} onClose={() => setSelected(null)} />
          : selSug && drafts[selSug.id] ? <SuggestionDecision s={selSug} d={drafts[selSug.id]} taxonomy={cats} set={(p) => set(selSug.id, p)}
            decide={(a) => decide(selSug, a)} onClose={() => setSelected(null)}
            owner={<CaseOwner key={selSug.id} kind="TAXONOMY_SUGGESTION" caseId={selSug.id} assignment={owners.get('TAXONOMY_SUGGESTION', selSug.id)} onChange={owners.put} />} />
            : undefined}
      />
    </>
  )
}

/** One category: add, rename, change what a specialization requires, or retire it. */
function CategoryEditor({ c, pending, run, onChanged, notify, onClose }: {
  c: TaxonomyCategory; pending: number; run: (action: () => Promise<void>) => void; onChanged: () => Promise<unknown>
  notify: (text: string) => void; onClose: () => void
}) {
  const [editing, setEditing] = useState<{ slug: string; name: string; flags: SpecializationFlags } | null>(null)
  const [adding, setAdding] = useState<{ groupSlug: string; name: string; flags: SpecializationFlags } | null>(null)
  const sp = specsOf(c)

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

  return (
    <DetailPanel title={c.name} subtitle={`${c.slug} · ${sp.length} active specializations`} badge={<Pill tone="green">Published v{c.version}</Pill>} onClose={onClose}>
      <Facts rows={[['Version', `v${c.version}`], ['Groups', c.groups.length], ['Specializations', sp.length],
        ['Credential required', sp.filter((s) => s.requiresCredential).length], ['Regulated', sp.filter((s) => s.regulated).length],
        ['Suggestions waiting', pending]]} />
      <p className="muted small" style={{ margin: 0 }}>Every change makes a new version of this category. Retired specializations cannot be chosen any more;
        profiles and contracts that use them keep them.</p>
      {c.groups.map((g) => (
        <div key={g.slug} className="adm-facts">
          <h3>{g.name} <span className="muted small">· {g.specializations.length}</span></h3>
          <ul className="adm-metrics">{g.specializations.map((s) => editing?.slug === s.slug ? (
            <li key={s.slug} style={{ display: 'grid', gap: 6 }}>
              <input className="input" aria-label={`Name of ${s.name}`} value={editing.name} onChange={(e) => setEditing({ ...editing, name: e.target.value })} />
              <FlagBoxes value={editing.flags} onChange={(flags) => setEditing({ ...editing, flags })} />
              <span className="row" style={{ gap: 6 }}>
                <button type="button" className="btn btn-primary btn-sm" disabled={editing.name.trim().length < 2} onClick={() => save(s)}>Save</button>
                <button type="button" className="btn btn-ghost btn-sm" onClick={() => setEditing(null)}>Cancel</button>
              </span>
            </li>
          ) : (
            <li key={s.slug}>
              <span style={{ minWidth: 0 }}>{s.name}<div className="cell-sub">{FLAGS.filter(([k]) => flagsOf(s)[k]).map(([, l]) => l).join(' · ') || s.slug}</div></span>
              <span style={{ whiteSpace: 'nowrap' }}>
                <button type="button" className="btn btn-secondary btn-sm" onClick={() => setEditing({ slug: s.slug, name: s.name, flags: flagsOf(s) })}>Edit</button>{' '}
                <button type="button" className="btn btn-ghost btn-sm" onClick={() => retire(s)}>Retire</button>
              </span>
            </li>
          ))}</ul>
          {adding?.groupSlug === g.slug ? (
            <form style={{ display: 'grid', gap: 6, marginTop: 6 }} onSubmit={(e) => add(e, g)}>
              <input className="input" aria-label={`New specialization in ${g.name}`} placeholder="Name"
                value={adding.name} onChange={(e) => setAdding({ ...adding, name: e.target.value })} maxLength={200} />
              <FlagBoxes value={adding.flags} onChange={(flags) => setAdding({ ...adding, flags })} />
              <span className="row" style={{ gap: 6 }}>
                <button className="btn btn-primary btn-sm" disabled={adding.name.trim().length < 2}>Add</button>
                <button type="button" className="btn btn-ghost btn-sm" onClick={() => setAdding(null)}>Cancel</button>
              </span>
            </form>
          ) : (
            <button type="button" className="btn btn-ghost btn-sm" style={{ marginTop: 6 }}
              onClick={() => setAdding({ groupSlug: g.slug, name: '', flags: NONE })}>+ Add specialization</button>
          )}
        </div>
      ))}
    </DetailPanel>
  )
}

function SuggestionDecision({ s, d, taxonomy, set, decide, onClose, owner }: {
  s: SpecializationSuggestion; d: Draft; owner?: ReactNode; taxonomy: TaxonomyCategory[]; set: (p: Partial<Draft>) => void
  decide: (a: 'APPROVE' | 'MERGE' | 'REJECT') => void; onClose: () => void
}) {
  return (
    <DetailPanel title={s.name} subtitle={`${s.professionalName ?? '—'} · ${shortDate(s.createdAt)}`} badge={<Pill tone="amber">Pending</Pill>} onClose={onClose}
      footer={<>
        <button className="btn btn-primary btn-sm" disabled={!d.groupSlug || d.name.trim().length < 2} onClick={() => decide('APPROVE')}>Approve</button>
        <button className="btn btn-secondary btn-sm" disabled={!d.mergeSlug} onClick={() => decide('MERGE')}>Merge</button>
        <button className="btn btn-ghost btn-sm" disabled={d.note.trim().length < 5} onClick={() => decide('REJECT')}>Reject</button>
      </>}>
      <Callout tone="blue" title="Their words">“{s.text}”{s.description && s.description !== s.text && <div>{s.description}</div>}</Callout>
      <Facts rows={[['Source', sourceLabel(s)], ['Credential likely', s.credentialLikely ? 'Yes' : 'No'],
        ['Proposed category', taxonomy.find((c) => c.slug === s.categorySlug)?.name ?? '—']]} />
      {owner}
      <div style={{ display: 'grid', gap: 8 }}>
        <label className="label" htmlFor="tax-final-name" style={{ margin: 0 }}>Approve as a new specialization</label>
        <input id="tax-final-name" className="input" value={d.name} onChange={(e) => set({ name: e.target.value })} aria-label="Final name" />
        <select className="input" value={d.groupSlug} onChange={(e) => set({ groupSlug: e.target.value })} aria-label="Group">
          <option value="">Choose a group…</option>
          {taxonomy.map((c) => <optgroup key={c.slug} label={c.name}>{c.groups.map((g) => <option key={g.slug} value={g.slug}>{g.name}</option>)}</optgroup>)}
        </select>
        <span className="row small" style={{ gap: 10 }}>
          <label className="checkbox small"><input type="checkbox" checked={d.credential} onChange={(e) => set({ credential: e.target.checked })} /><span>Credential required</span></label>
          <label className="checkbox small"><input type="checkbox" checked={d.regulated} onChange={(e) => set({ regulated: e.target.checked })} /><span>Regulated</span></label>
        </span>
        <select className="input" value={d.mergeSlug} onChange={(e) => set({ mergeSlug: e.target.value })} aria-label="Merge into">
          <option value="">Or merge into an existing specialization…</option>
          {taxonomy.map((c) => <optgroup key={c.slug} label={c.name}>{specsOf(c).map((x) => <option key={x.slug} value={x.slug}>{x.name}</option>)}</optgroup>)}
        </select>
        <input className="input" placeholder="Note to the professional (required to reject)" maxLength={500} aria-label="Note to the professional"
          value={d.note} onChange={(e) => set({ note: e.target.value })} />
      </div>
    </DetailPanel>
  )
}
