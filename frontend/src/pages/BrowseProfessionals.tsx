import { useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { formatMoney } from '../api/orgs'
import { LABEL, taxonomyApi, type TaxonomyCategory } from '../api/professional'
import { searchApi, type Facet, type SearchResponse, type SearchResult } from '../api/search'
import { Avatar } from '../components/dashboard'
import { ErrorAlert, SiteHeader } from '../components/ui'
import { COUNTRIES } from './Join'
import { countryName } from './ProfessionalPages'
import { SaveButton, useSavedIds } from './SavedPage'
import { SearchBox } from '../components/SearchBox'

const PAGE = 20
const SORTS: [string, string][] = [
  ['best', 'Best match'], ['verified', 'Most verified'], ['availability', 'Soonest available'],
  ['experience', 'Most experienced'], ['price_asc', 'Price: low to high'], ['price_desc', 'Price: high to low'], ['recent', 'Newest'],
]
const VERIFIED: [string, string][] = [
  ['identity', 'Identity verified'], ['credentials', 'Credentials validated'], ['jurisdiction', 'Jurisdiction eligible'],
  ['insurance', 'Insurance verified'],
]

/** A result card: who, tier, specializations, and why it matched. */
export function ResultCard({ r, saved, onToggle }: { r: SearchResult; saved?: boolean; onToggle?: (id: string) => void }) {
  return (
    <article className="card result">
      <div className="offering-top">
        <div>
          <div className="name-row"><Avatar name={r.displayName} photoUrl={r.photoUrl} size={44} />
            <h3><Link to={`/professionals/${r.professionalId}`}>{r.displayName}</Link></h3></div>
          {r.headline && <div className="headline">{r.headline}</div>}
          {r.firm && <div className="small">Practises with <Link to={`/firms/${r.firm.id}`}>{r.firm.name}</Link>
            {r.firm.verified && <span className="badge green" style={{ marginLeft: 6 }}>Firm verified</span>}</div>}
          <div className="muted small">{[r.city, countryName(r.country)].filter(Boolean).join(', ')}
            {' · '}{LABEL[r.availability] ?? r.availability}</div>
        </div>
        <div className="result-side">
          <span className={`badge ${r.tier === 'C' ? 'warn' : 'green'}`}>Tier {r.tier} · {r.tierLabel}</span>
          {r.enterpriseReady && <span className="badge green">Enterprise Ready</span>}
          {r.regulatedPreview && <span className="badge warn" title="Regulated work (audit, tax filing, regulatory reporting) needs Tier A">Preview for regulated work</span>}
          {onToggle && <SaveButton id={r.professionalId} saved={!!saved} onToggle={onToggle} />}
        </div>
      </div>
      <div className="badges" style={{ margin: '10px 0' }}>
        {r.specializations.map((s) => <span key={s.slug} className={`badge ${s.primary ? 'green' : ''}`}>{s.name}</span>)}
      </div>
      <div className="result-foot">
        <ul className="why-inline" aria-label="Why this result">{r.whyThisResult.map((w) => <li key={w}>{w}</li>)}</ul>
        <span className="price">{r.startingPrice ? `From ${formatMoney(r.startingPrice)}` : r.pricingModels.includes('CUSTOM') ? 'Quote on request' : ''}</span>
      </div>
    </article>
  )
}

function FacetCount({ facets, name, value }: { facets?: Record<string, Facet[]>; name: string; value: string }) {
  const n = facets?.[name]?.find((f) => f.value === value)?.count
  return n !== undefined ? <span className="muted small"> ({n})</span> : null
}

/** Public discovery page. Filters live in the URL so searches can be shared and bookmarked. */
export default function BrowseProfessionals() {
  const [params, setParams] = useSearchParams()
  const [taxonomy, setTaxonomy] = useState<TaxonomyCategory[]>([])
  const [data, setData] = useState<SearchResponse | null>(null)
  const [items, setItems] = useState<SearchResult[]>([])
  const [offset, setOffset] = useState(0)
  const [error, setError] = useState<unknown>(null)
  const [q, setQ] = useState(params.get('q') ?? '')
  const savedIds = useSavedIds()
  const key = params.toString()

  useEffect(() => { taxonomyApi.all().then(setTaxonomy).catch(() => {}) }, [])
  useEffect(() => {
    let cancelled = false
    searchApi.professionals({ ...Object.fromEntries(new URLSearchParams(key)), limit: String(PAGE), offset: '0' })
      .then((r) => { if (!cancelled) { setData(r); setItems(r.items); setOffset(0); setError(null) } })
      .catch((err) => { if (!cancelled) setError(err) })
    return () => { cancelled = true }
  }, [key])

  function set(name: string, value: string | null) {
    const next = new URLSearchParams(params)
    if (value) next.set(name, value)
    else next.delete(name)
    setParams(next, { replace: true })
  }
  function toggleList(name: string, value: string) {
    const list = (params.get(name) ?? '').split(',').filter(Boolean)
    set(name, (list.includes(value) ? list.filter((v) => v !== value) : [...list, value]).join(','))
  }
  const inList = (name: string, value: string) => (params.get(name) ?? '').split(',').includes(value)
  const list = (name: string) => (params.get(name) ?? '').split(',').filter(Boolean)
  async function more() {
    const next = offset + PAGE
    const r = await searchApi.professionals({ ...Object.fromEntries(params), limit: String(PAGE), offset: String(next) })
    setItems([...items, ...r.items])
    setOffset(next)
  }
  const groups = taxonomy.flatMap((c) => c.groups)
  return (
    <>
      <SiteHeader />
      <main className="profile-wrap">
        <div className="page-head"><div><h1>Browse verified professionals</h1>
          <p className="muted" style={{ margin: 0 }}>Every result shows its Trust Tier and why it matched. Ranking can't be bought.</p></div></div>
        <SearchBox value={q} onChange={setQ} onSearch={(v) => set('q', v || null)}
          onPickSpecialization={(slug) => { if (!inList('spec', slug)) toggleList('spec', slug) }} placeholder="Try “fractional CFO”, “transfer pricing” or “SOX”" />
        <div className="browse">
          <aside className="card panel filters" aria-label="Filters">
            <SpecializationNavigator groups={groups} selected={list('spec')} onToggle={(slug) => toggleList('spec', slug)}
              facets={data?.facets} />

            <div className="filter-label">Trust Tier</div>
            {['A', 'B', 'C'].map((t) => (
              <label key={t} className="checkbox small"><input type="checkbox" checked={inList('tier', t)} onChange={() => toggleList('tier', t)} />
                <span>Tier {t}<FacetCount facets={data?.facets} name="tier" value={t} /></span></label>
            ))}

            <div className="filter-label">Verification</div>
            {VERIFIED.map(([v, label]) => (
              <label key={v} className="checkbox small"><input type="checkbox" checked={inList('verified', v)} onChange={() => toggleList('verified', v)} />
                <span>{label}</span></label>
            ))}

            <ProcurementFilters params={params} facets={data?.facets} set={set} toggleList={toggleList} />

            {([['engagementType', 'Engagement', ['ADVISORY', 'PROJECT', 'RETAINER', 'FRACTIONAL']],
              ['delivery', 'Delivery', ['REMOTE', 'ONSITE', 'HYBRID']],
              ['availability', 'Availability', ['NOW', 'TWO_WEEKS', 'ONE_MONTH']],
              ['pricingModel', 'Pricing', ['HOURLY', 'FIXED', 'RETAINER', 'CUSTOM']]] as [string, string, string[]][]).map(([name, label, values]) => (
              <div key={name}>
                <label className="filter-label" htmlFor={`f-${name}`}>{label}</label>
                <select id={`f-${name}`} className="input" value={params.get(name) ?? ''} onChange={(e) => set(name, e.target.value || null)}>
                  <option value="">Any</option>
                  {values.map((v) => <option key={v} value={v}>{LABEL[v] ?? v}</option>)}
                </select>
              </div>
            ))}

            <label className="filter-label" htmlFor="f-jur">Serves or licensed in</label>
            <select id="f-jur" className="input" value={params.get('jurisdiction') ?? ''} onChange={(e) => set('jurisdiction', e.target.value || null)}>
              <option value="">Anywhere</option>
              {COUNTRIES.map(([c, n]) => <option key={c} value={c}>{n}</option>)}
            </select>
            {key && <button type="button" className="btn btn-ghost btn-sm" style={{ marginTop: 12 }} onClick={() => { setQ(''); setParams({}) }}>Clear all</button>}
          </aside>

          <section>
            <div className="results-head">
              <span className="muted">{data ? `${data.total} professional${data.total === 1 ? '' : 's'}` : 'Searching…'}</span>
              <label className="small">Sort{' '}
                <select className="input" value={params.get('sort') ?? 'best'} onChange={(e) => set('sort', e.target.value === 'best' ? null : e.target.value)}>
                  {SORTS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
                </select>
              </label>
            </div>
            <SelectedPills params={params} groups={groups} toggleList={toggleList} set={set} />
            <ErrorAlert error={error} />
            {data && data.total === 0 && (
              <section className="card panel"><p className="muted" style={{ margin: 0 }}>
                No published professionals match these filters yet. Try fewer filters or a broader search term.</p></section>
            )}
            {items.map((r) => <ResultCard key={r.professionalId} r={r} saved={savedIds.ids?.has(r.professionalId)}
              onToggle={savedIds.canSave && savedIds.ids ? (id) => { savedIds.toggle(id).catch(setError) } : undefined} />)}
            {data && items.length < data.total && (
              <button className="btn btn-secondary" style={{ marginTop: 8 }} onClick={() => more().catch(setError)}>Show more</button>
            )}
          </section>
        </div>
      </main>
    </>
  )
}

type Group = TaxonomyCategory['groups'][number]

/** Multi-select specialization navigator: checkbox per specialization, grouped and collapsible, with a quick filter. */
export function SpecializationNavigator({ groups, selected, onToggle, facets }: {
  groups: Group[]; selected: string[]; onToggle: (slug: string) => void; facets?: Record<string, Facet[]>
}) {
  const [term, setTerm] = useState('')
  const t = term.trim().toLowerCase()
  const shown = groups.map((g) => ({ g, specs: g.specializations.filter((s) => !t || `${s.name} ${g.name}`.toLowerCase().includes(t)) }))
    .filter((x) => x.specs.length > 0)
  return (
    <div className="spec-nav">
      <div className="filter-label">Specializations {selected.length > 0 && <span className="muted small">({selected.length} selected)</span>}</div>
      <input className="input" aria-label="Filter specializations" placeholder="Filter the list" value={term} onChange={(e) => setTerm(e.target.value)} />
      {shown.map(({ g, specs }) => (
        <details key={g.slug} open={!!t || specs.some((s) => selected.includes(s.slug)) || groups.length <= 3}>
          <summary className="small"><strong>{g.name}</strong></summary>
          <fieldset><legend className="sr-only">{g.name}</legend>
            {specs.map((s) => (
              <label key={s.slug} className="checkbox small"><input type="checkbox" checked={selected.includes(s.slug)} onChange={() => onToggle(s.slug)} />
                <span>{s.name}<FacetCount facets={facets} name="specialization" value={s.slug} /></span></label>
            ))}
          </fieldset>
        </details>
      ))}
      {shown.length === 0 && <p className="muted small">Nothing matches “{term}”.</p>}
    </div>
  )
}

/** Enterprise and procurement filters, all derived from verified platform data. */
export function ProcurementFilters({ params, facets, set, toggleList }: {
  params: URLSearchParams; facets?: Record<string, Facet[]>
  set: (name: string, value: string | null) => void; toggleList: (name: string, value: string) => void
}) {
  const on = (name: string) => params.get(name) === 'true'
  const creds = (params.get('credentials') ?? '').split(',').filter(Boolean)
  const options = [...new Set([...(facets?.credential ?? []).map((f) => f.value), ...creds])]
  const flags: [string, string, string][] = [
    ['enterpriseReady', 'Security-review ready', 'Enterprise Ready: security practice attested and reviewed by Zoikorum compliance'],
    ['priorEnterprise', 'Prior enterprise engagements', 'Has completed at least one engagement for an enterprise buyer on Zoikorum'],
    ['multiCurrency', 'Accepts multiple currencies', 'Prices services in more than one currency'],
  ]
  return (
    <>
      <div className="filter-label">Enterprise &amp; procurement</div>
      <label className="checkbox small"><input type="checkbox" checked={(params.get('verified') ?? '').split(',').includes('insurance')}
        onChange={() => toggleList('verified', 'insurance')} /><span>Insurance verified<FacetCount facets={facets} name="insurance" value="true" /></span></label>
      {flags.map(([name, label, title]) => (
        <label key={name} className="checkbox small" title={title}><input type="checkbox" checked={on(name)} onChange={() => set(name, on(name) ? null : 'true')} />
          <span>{label}<FacetCount facets={facets} name={name} value="true" /></span></label>
      ))}
      {options.length > 0 && <>
        <div className="filter-label">Verified credentials</div>
        {options.map((c) => (
          <label key={c} className="checkbox small"><input type="checkbox" checked={creds.includes(c)} onChange={() => toggleList('credentials', c)} />
            <span>{c}<FacetCount facets={facets} name="credential" value={c} /></span></label>
        ))}
      </>}
    </>
  )
}

const FLAG_LABEL: Record<string, string> = { enterpriseReady: 'Security-review ready', priorEnterprise: 'Prior enterprise engagements', multiCurrency: 'Multiple currencies' }

/** Selected specializations and procurement filters as removable pills above the results. */
export function SelectedPills({ params, groups, toggleList, set }: {
  params: URLSearchParams; groups: Group[]
  toggleList: (name: string, value: string) => void; set: (name: string, value: string | null) => void
}) {
  const names = Object.fromEntries(groups.flatMap((g) => g.specializations.map((s) => [s.slug, s.name])))
  const specs = (params.get('spec') ?? '').split(',').filter(Boolean)
  const creds = (params.get('credentials') ?? '').split(',').filter(Boolean)
  const flags = Object.keys(FLAG_LABEL).filter((f) => params.get(f) === 'true')
  if (!specs.length && !creds.length && !flags.length) return null
  return (
    <div className="filter-pills chips" aria-label="Selected filters" style={{ marginBottom: 10 }}>
      {specs.map((s) => <button key={s} type="button" className="pill" aria-label={`Remove ${names[s] ?? s}`} onClick={() => toggleList('spec', s)}>{names[s] ?? s} ×</button>)}
      {creds.map((c) => <button key={c} type="button" className="pill" aria-label={`Remove ${c}`} onClick={() => toggleList('credentials', c)}>{c} ×</button>)}
      {flags.map((f) => <button key={f} type="button" className="pill" aria-label={`Remove ${FLAG_LABEL[f]}`} onClick={() => set(f, null)}>{FLAG_LABEL[f]} ×</button>)}
    </div>
  )
}
