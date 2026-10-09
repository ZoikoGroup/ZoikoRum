import { useEffect, useRef, useState, type FormEvent } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { formatMoney, orgApi } from '../../api/orgs'
import { LABEL, taxonomyApi, type TaxonomyCategory } from '../../api/professional'
import { searchApi, type SearchResponse, type SearchResult } from '../../api/search'
import { CompareDialog, CompareTray } from '../../components/CompareDialog'
import { EducationCards } from '../../components/Explainers'
import { QuickView } from '../../components/QuickView'
import { Avatar, Icon } from '../../components/dashboard'
import { PortalHeader, TierBadge, VerifyChips } from '../../components/portal'
import { ErrorAlert } from '../../components/ui'
import { COUNTRIES } from '../Join'
import { countryName } from '../ProfessionalPages'
import { useSavedIds } from '../SavedPage'
import { savedApi } from '../../api/saved'

const PAGE = 20
const MAX_COMPARE = 3
const SORTS: [string, string][] = [
  ['best', 'Relevance'], ['verified', 'Most verified'], ['availability', 'Soonest available'], ['experience', 'Most experienced'],
  ['price_asc', 'Price: low to high'], ['price_desc', 'Price: high to low'], ['recent', 'Newest'],
]
const VERIFIED: [string, string][] = [
  ['identity', 'Identity verified'], ['credentials', 'Credentials verified'], ['jurisdiction', 'Eligibility current'], ['insurance', 'Professional indemnity'],
]
const PRICING: [string, string][] = [['HOURLY', 'Hourly rate'], ['FIXED', 'Fixed fee'], ['RETAINER', 'Retainer'], ['CUSTOM', 'Request quote']]
const GOOD: Record<string, string> = { identity: 'VERIFIED', credentials: 'VALIDATED', jurisdiction: 'ELIGIBLE', insurance: 'VERIFIED' }
const VIEW_KEY = 'zk.findView'
const readView = (): 'list' | 'grid' => { try { return localStorage.getItem(VIEW_KEY) === 'grid' ? 'grid' : 'list' } catch { return 'list' } }

/** Filters (other than the search text and expertise) a result does not meet: labels for "partial matches". */
function unmet(r: SearchResult, params: URLSearchParams): string[] {
  const list = (k: string) => (params.get(k) ?? '').split(',').filter(Boolean)
  const out: string[] = []
  if (list('tier').length && !list('tier').includes(r.tier)) out.push(`Tier ${r.tier}`)
  const j = params.get('jurisdiction')
  if (j && r.servedJurisdictions.length && !r.servedJurisdictions.includes(j) && !r.licensedJurisdictions.includes(j)) out.push(`Does not serve ${countryName(j)}`)
  for (const [k, values] of [['delivery', r.deliveryModes], ['engagementType', r.engagementTypes], ['pricingModel', r.pricingModels]] as const) {
    const want = params.get(k)
    if (want && !values.includes(want)) out.push(`No ${(LABEL[want] ?? want).toLowerCase()}`)
  }
  const a = params.get('availability')
  if (a && r.availability !== a) out.push(LABEL[r.availability] ?? 'Different availability')
  for (const d of list('verified')) if (r.dimensions[d] !== GOOD[d]) out.push(`${d} not verified`)
  const x = params.get('experience')
  if (x && r.yearsExperienceBand !== x) out.push(`${r.yearsExperienceBand ?? 'Unknown'} years`)
  return out
}

/** Find Professionals (management design 2): filter bar, filter panel, verified results, save and compare. */
export default function FindProfessionals() {
  const [params, setParams] = useSearchParams()
  const [taxonomy, setTaxonomy] = useState<TaxonomyCategory[]>([])
  const [data, setData] = useState<SearchResponse | null>(null)
  const [items, setItems] = useState<SearchResult[]>([])
  const [offset, setOffset] = useState(0)
  const [error, setError] = useState<unknown>(null)
  const [q, setQ] = useState(params.get('q') ?? '')
  const [selected, setSelected] = useState<string[]>([])
  const [comparing, setComparing] = useState(false)
  const [notice, setNotice] = useState<string | null>(null)
  const saved = useSavedIds()
  const key = params.toString()
  const [view, setViewState] = useState<'list' | 'grid'>(readView)
  const [quick, setQuick] = useState<string | null>(null)
  const hover = useRef<number | undefined>(undefined)
  const [buyerCountry, setBuyerCountry] = useState<string | null>(null)
  const [partial, setPartial] = useState<SearchResult[] | null>(null)
  const setView = (v: 'list' | 'grid') => { setViewState(v); try { localStorage.setItem(VIEW_KEY, v) } catch { /* per-viewer convenience only */ } }

  useEffect(() => { if (saved.canSave) orgApi.mine().then((o) => setBuyerCountry(o[0]?.country?.toUpperCase() ?? null)).catch(() => {}) }, [saved.canSave])

  useEffect(() => { taxonomyApi.all().then(setTaxonomy).catch(() => {}) }, [])
  useEffect(() => {
    let cancelled = false
    searchApi.professionals({ ...Object.fromEntries(new URLSearchParams(key)), limit: String(PAGE), offset: '0' })
      .then((r) => { if (!cancelled) { setData(r); setItems(r.items); setOffset(0); setError(null); setPartial(null) } })
      .catch((err) => { if (!cancelled) setError(err) })
    return () => { cancelled = true }
  }, [key])

  function set(name: string, value: string | null) {
    const next = new URLSearchParams(params)
    if (value) next.set(name, value)
    else next.delete(name)
    setParams(next, { replace: true })
  }
  const inList = (name: string, value: string) => (params.get(name) ?? '').split(',').includes(value)
  function toggleList(name: string, value: string) {
    const list = (params.get(name) ?? '').split(',').filter(Boolean)
    set(name, (list.includes(value) ? list.filter((v) => v !== value) : [...list, value]).join(','))
  }
  function toggleSelect(id: string) {
    setSelected((s) => (s.includes(id) ? s.filter((x) => x !== id) : s.length >= MAX_COMPARE ? s : [...s, id]))
  }
  async function more() {
    const next = offset + PAGE
    const r = await searchApi.professionals({ ...Object.fromEntries(params), limit: String(PAGE), offset: String(next) })
    setItems([...items, ...r.items])
    setOffset(next)
  }
  function submit(e: FormEvent) { e.preventDefault(); set('q', q.trim() || null) }
  /** Few results (Category doc s.5.5): the same search and expertise with the other filters relaxed, clearly labelled. */
  async function showPartial() {
    const keep = Object.fromEntries(['q', 'spec', 'sort'].flatMap((k) => (params.get(k) ? [[k, params.get(k)!]] : [])))
    const r = await searchApi.professionals({ ...keep, limit: String(PAGE) })
    const shown = new Set(items.map((i) => i.professionalId))
    setPartial(r.items.filter((i) => !shown.has(i.professionalId)))
  }
  const hoverOpen = (id: string) => { window.clearTimeout(hover.current); hover.current = window.setTimeout(() => setQuick(id), 700) }
  const hoverCancel = () => window.clearTimeout(hover.current)
  const limited = (r: SearchResult) => !!buyerCountry && r.servedJurisdictions.length > 0
    && !r.servedJurisdictions.includes(buyerCountry) && !r.licensedJurisdictions.includes(buyerCountry)

  const groups = taxonomy.flatMap((c) => c.groups)
  // Active filter summary bar (Category doc s.4.5): every filter visible and removable on its own.
  const specName = Object.fromEntries(groups.flatMap((g) => g.specializations.map((s) => [s.slug, s.name])))
  const NAMES: Record<string, (v: string) => string> = {
    q: (v) => `“${v}”`, spec: (v) => v.split(',').map((s) => specName[s] ?? s).join(', '), tier: (v) => `Tier ${v.replace(',', ' or ')}`,
    verified: (v) => `Verified: ${v.replace(/,/g, ', ')}`, jurisdiction: (v) => `Serves ${countryName(v)}`, experience: (v) => `${v} years`,
    engagementType: (v) => LABEL[v] ?? v, delivery: (v) => LABEL[v] ?? v, availability: (v) => LABEL[v] ?? v, pricingModel: (v) => LABEL[v] ?? v,
    credential: (v) => `Credential: ${v}`,
  }
  const active: [string, string][] = [...params.entries()].filter(([k]) => k in NAMES).map(([k, v]) => [k, NAMES[k](v)])
  const relaxable = active.some(([k]) => !['q', 'spec'].includes(k))
  const names = Object.fromEntries(items.map((r) => [r.professionalId, { name: r.displayName, photoUrl: r.photoUrl }]))
  const select = (name: string, label: string, options: [string, string][], any = 'Any') => (
    <label className="filter-box">
      <span>{label}</span>
      <select value={params.get(name) ?? ''} onChange={(e) => set(name, e.target.value || null)}>
        <option value="">{any}</option>
        {options.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
      </select>
    </label>
  )

  const card = (r: SearchResult, misses?: string[]) => (
    <article key={r.professionalId} className={view === 'grid' ? 'pro-card' : 'pro-row'} onMouseLeave={hoverCancel}>
      <input type="checkbox" aria-label={`Select ${r.displayName} to compare`} checked={selected.includes(r.professionalId)}
        disabled={!selected.includes(r.professionalId) && selected.length >= MAX_COMPARE} onChange={() => toggleSelect(r.professionalId)} />
      <span onMouseEnter={() => hoverOpen(r.professionalId)}><Avatar name={r.displayName} photoUrl={r.photoUrl} size={view === 'grid' ? 48 : 64} /></span>
      <div className="pro-main" onMouseEnter={() => hoverOpen(r.professionalId)}>
        <div className="name-line"><Link to={`/professionals/${r.professionalId}`}><strong>{r.displayName}</strong></Link> <TierBadge tier={r.tier} />
          {saved.canSave && saved.ids && <button className="icon-btn" aria-label={saved.ids.has(r.professionalId) ? 'Saved' : 'Save'} title={saved.ids.has(r.professionalId) ? 'Saved' : 'Save'}
            onClick={() => saved.toggle(r.professionalId).catch(setError)}><Icon name="bookmark" />{saved.ids.has(r.professionalId) ? '✓' : ''}</button>}</div>
        {r.headline && <div className="small">{r.headline}</div>}
        <div className="muted small"><Icon name="globe" /> {[r.city, countryName(r.country)].filter(Boolean).join(', ')}
          {r.deliveryModes.length > 0 && ` · ${r.deliveryModes.map((d) => LABEL[d] ?? d).join(', ')}`}
          {view === 'list' && r.languages.length > 0 && ` · ${r.languages.join(', ')}`}</div>
        {limited(r) && <div className="small" style={{ marginTop: 4 }}><span className="badge warn">Jurisdiction-limited</span>{' '}
          <span className="muted">Does not take work in {countryName(buyerCountry!)}.</span>{' '}
          <button className="link-btn small" style={{ display: 'inline', padding: 0 }} onClick={() => set('jurisdiction', buyerCountry)}>Show eligible professionals</button></div>}
        {misses && misses.length > 0 && <div className="small" style={{ marginTop: 4 }}><span className="badge">Partial match</span> <span className="muted">Not met: {misses.join(' · ')}</span></div>}
      </div>
      <VerifyChips dimensions={r.dimensions} compact />
      <div className="pro-expertise">
        <div className="muted small">Key expertise</div>
        <div className="chips">{r.specializations.slice(0, 3).map((s) => <span key={s.slug} className="chip">{s.name}</span>)}
          {r.specializations.length > 3 && <span className="chip muted">+{r.specializations.length - 3} more</span>}</div>
      </div>
      <div className="pro-facts small">
        {r.yearsExperienceBand && <div><Icon name="clock" /> {r.yearsExperienceBand} years experience</div>}
        <div><Icon name="check" /> {LABEL[r.availability] ?? r.availability}</div>
        {r.engagementTypes.length > 0 && <div><Icon name="briefcase" /> {r.engagementTypes.map((t) => LABEL[t] ?? t).join(', ')}</div>}
        <div className="muted"><Icon name="shield" /> Contract-ready · Payment protection · Engagement records</div>
      </div>
      <div className="pro-cta">
        <div className="price">{r.startingPrice ? <>From <strong>{formatMoney(r.startingPrice)}</strong></> : r.pricingModels.includes('CUSTOM') ? 'Quote on request' : ''}</div>
        <div className="row">
          <Link className="btn btn-primary btn-sm" to={`/professionals/${r.professionalId}`}>View profile</Link>
          <Link className="btn btn-secondary btn-sm" to={`/app/requests/new?pro=${r.professionalId}`}>Request proposal</Link>
          <button className="btn btn-ghost btn-sm" onClick={() => setQuick(quick === r.professionalId ? null : r.professionalId)} aria-expanded={quick === r.professionalId}>Quick view</button>
          <button className="btn btn-ghost btn-sm" onClick={() => toggleSelect(r.professionalId)}
            disabled={!selected.includes(r.professionalId) && selected.length >= MAX_COMPARE}><Icon name="compare" /> {selected.includes(r.professionalId) ? 'Selected' : 'Compare'}</button>
        </div>
      </div>
      {view === 'list' && r.whyThisResult.length > 0 && <ul className="why-inline">{r.whyThisResult.map((w) => <li key={w}>{w}</li>)}</ul>}
      {view === 'grid' && r.whyThisResult.length > 0 && <details className="why-inline small"><summary>Why this result?</summary>{r.whyThisResult.join(' · ')}</details>}
      {quick === r.professionalId && <QuickView id={r.professionalId} buyerCountry={buyerCountry}
        saved={saved.canSave && saved.ids ? saved.ids.has(r.professionalId) : null}
        onSave={() => saved.toggle(r.professionalId).catch(setError)} onClose={() => setQuick(null)} />}
    </article>
  )

  return (
    <>
      <PortalHeader eyebrow="Find professionals" title="Find the right professional"
        subtitle="Search verified professionals by expertise, jurisdiction and engagement requirements."
        actions={<div className="trust-points">
          <span><Icon name="shield" /><span><strong>Verified identities</strong><br />Know who you are engaging with</span></span>
          <span><Icon name="request" /><span><strong>Credentials checked</strong><br />Qualifications and licences</span></span>
          <span><Icon name="team" /><span><strong>Engagement ready</strong><br />Eligible and governable</span></span>
        </div>} />

      <section className="card panel search-panel">
        <form className="search-bar" onSubmit={submit} role="search">
          <input className="input" aria-label="Search professionals" value={q} onChange={(e) => setQ(e.target.value)}
            placeholder="Search by profession, expertise, service or keyword (e.g. fractional CFO, transfer pricing, SOX)" />
          <button className="btn btn-primary"><Icon name="search" /> Search</button>
        </form>
        <div className="filter-row">
          {select('spec', 'Expertise', groups.flatMap((g) => g.specializations.map((s) => [s.slug, s.name] as [string, string])), 'Any expertise')}
          {select('jurisdiction', 'Jurisdiction', COUNTRIES, 'Global')}
          {select('tier', 'Verification', [['A', 'Tier A — Fully verified'], ['B', 'Tier B — Verified identity'], ['A,B', 'Tier A or B']], 'Any status')}
          {select('pricingModel', 'Engagement model', PRICING, 'Any model')}
          {select('availability', 'Availability', [['NOW', 'Available now'], ['TWO_WEEKS', 'Within 2 weeks'], ['ONE_MONTH', 'Within a month']], 'Any time')}
          {select('delivery', 'Delivery', [['REMOTE', 'Remote'], ['ONSITE', 'On-site'], ['HYBRID', 'Hybrid']], 'Any')}
          {select('experience', 'Experience', [['0-2', '0–2 years'], ['3-5', '3–5 years'], ['6-10', '6–10 years'], ['11-15', '11–15 years'], ['16+', '16+ years']], 'Any')}
        </div>
      </section>

      <div className="browse">
        <aside className="card panel filters" aria-label="Filters">
          <div className="panel-head"><h2>Filters</h2>{key && <button className="btn btn-ghost btn-sm" onClick={() => { setQ(''); setParams({}) }}>Clear all</button>}</div>
          <div className="filter-label">Verification status</div>
          {VERIFIED.map(([v, label]) => (
            <label key={v} className="checkbox small"><input type="checkbox" checked={inList('verified', v)} onChange={() => toggleList('verified', v)} /><span>{label}</span></label>
          ))}
          <div className="filter-label">Engagement type</div>
          {(['ADVISORY', 'PROJECT', 'RETAINER', 'FRACTIONAL'] as const).map((t) => (
            <label key={t} className="checkbox small"><input type="radio" name="et" checked={params.get('engagementType') === t}
              onChange={() => set('engagementType', t)} /><span>{LABEL[t]}</span></label>
          ))}
          {params.get('engagementType') && <button className="btn btn-ghost btn-sm" onClick={() => set('engagementType', null)}>Any engagement type</button>}
          <div className="filter-label">Trust Tier</div>
          {['A', 'B', 'C'].map((t) => (
            <label key={t} className="checkbox small"><input type="checkbox" checked={inList('tier', t)} onChange={() => toggleList('tier', t)} />
              <span>Tier {t} <span className="muted">({data?.facets.tier?.find((f) => f.value === t)?.count ?? 0})</span></span></label>
          ))}
        </aside>

        <section className="card panel results-panel">
          {active.length > 0 && <div className="filter-pills" aria-label="Active filters">
            {active.map(([k, label]) => <button key={k} className="pill" onClick={() => { if (k === 'q') setQ(''); set(k, null) }}>{label} ×</button>)}
            <button className="link-btn small" style={{ flex: 'none' }} onClick={() => { setQ(''); setParams({}) }}>Clear all</button>
            {saved.canSave && <button className="btn btn-ghost btn-sm" style={{ marginLeft: 'auto' }} onClick={() => {
              const name = prompt('Name this search', params.get('q') || active.map(([, l]) => l).slice(0, 2).join(', '))
              if (name && name.trim()) savedApi.saveSearch(name.trim(), Object.fromEntries(params)).then(() => setNotice('Search saved. Find it on Saved Professionals, with new matches.')).catch(setError)
            }}><Icon name="bookmark" /> Save this search</button>}
          </div>}
          {notice && <div className="alert alert-success" role="status">{notice}</div>}
          <div className="results-head">
            <h2 style={{ margin: 0 }}>{data ? `${data.total} professional${data.total === 1 ? '' : 's'} found` : 'Searching…'}</h2>
            <div className="view-toggle" role="group" aria-label="View">
              <button className={`btn btn-sm ${view === 'grid' ? 'btn-primary' : 'btn-ghost'}`} aria-pressed={view === 'grid'} onClick={() => setView('grid')}>Grid</button>
              <button className={`btn btn-sm ${view === 'list' ? 'btn-primary' : 'btn-ghost'}`} aria-pressed={view === 'list'} onClick={() => setView('list')}>List</button>
            </div>
            <span className="small muted">Compare: ({selected.length}/{MAX_COMPARE})</span>
            <label className="small">Sort by{' '}
              <select className="input" value={params.get('sort') ?? 'best'} onChange={(e) => set('sort', e.target.value === 'best' ? null : e.target.value)}>
                {SORTS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
              </select>
            </label>
          </div>
          <ErrorAlert error={error} />
          {data && data.total === 0 && <div className="empty-row" style={{ padding: 24 }}>
            <strong>No professionals match these filters.</strong> {active.length > 0 ? `Filters in use: ${active.map(([, l]) => l).join(', ')}. Remove one to widen the search.` : 'Try a different search term.'}
            <div className="row" style={{ justifyContent: 'center', marginTop: 10 }}>
              <button className="btn btn-secondary btn-sm" onClick={() => { setQ(''); setParams({}) }}>Reset filters</button>
              <button className="btn btn-ghost btn-sm" onClick={() => { setQ(''); setParams({}) }}>Browse all</button></div></div>}
          <div className={view === 'grid' ? 'pro-grid' : 'pro-list'}>{items.map((r) => card(r))}</div>
          {data && data.total > 0 && data.total < 3 && relaxable && !partial && <div className="tip" style={{ marginTop: 12 }}>
            <Icon name="help" /><span>Only {data.total} professional{data.total === 1 ? '' : 's'} meet every filter.{' '}
              <button className="link-btn small" style={{ display: 'inline', padding: 0 }} onClick={() => showPartial().catch(setError)}>Show partial matches</button></span></div>}
          {data && data.total === 0 && relaxable && !partial && <div className="row" style={{ justifyContent: 'center' }}>
            <button className="btn btn-ghost btn-sm" onClick={() => showPartial().catch(setError)}>Show partial matches</button></div>}
          {partial && <>
            <h3 style={{ marginTop: 20 }}>Partial matches</h3>
            <p className="muted small">These match your search but not every filter. What they do not meet is listed on each.</p>
            {partial.length === 0 ? <p className="muted small">No partial matches either. Try Reset filters.</p>
              : <div className={view === 'grid' ? 'pro-grid' : 'pro-list'}>{partial.map((r) => card(r, unmet(r, params)))}</div>}
          </>}
          {(params.size > 0 || items.length >= 20) && <EducationCards />}
          {data && items.length < data.total && <button className="btn btn-secondary" onClick={() => more().catch(setError)}>Show more</button>}
        </section>
      </div>

      <CompareTray selected={selected} names={names} onRemove={(id) => setSelected(selected.filter((x) => x !== id))}
        onCompare={() => setComparing(true)} extra={<>
          <Link className="btn btn-secondary" to="/app/saved"><Icon name="bookmark" /> View shortlist</Link>
          <Link className="btn btn-secondary" to={`/app/requests/new?${selected.map((id) => `pro=${id}`).join('&')}`}><Icon name="request" /> Request proposal{selected.length > 1 ? 's' : ''}</Link>
        </>} />
      {comparing && <CompareDialog ids={selected} onClose={() => setComparing(false)} />}
    </>
  )
}
