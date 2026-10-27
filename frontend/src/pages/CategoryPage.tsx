import { useEffect, useState, type FormEvent } from 'react'
import { Link, useParams, useSearchParams } from 'react-router-dom'
import { taxonomyApi, type TaxonomyCategory } from '../api/professional'
import { searchApi, type SearchResponse, type SearchResult } from '../api/search'
import { useAuth } from '../auth/AuthContext'
import { EducationCards } from '../components/Explainers'
import { ErrorAlert, SiteFooter, SiteHeader } from '../components/ui'
import { ProcurementFilters, ResultCard, SelectedPills, SpecializationNavigator } from './BrowseProfessionals'
import { useSavedIds } from './SavedPage'
import { lightColor, lightName } from '../lib/trustLight'

const PAGE = 12

/** What the category documents say buyers should know before engaging in that category. */
const GUIDANCE: Record<string, { intro: string; points: [string, string][] }> = {
  'finance-and-accounting': {
    intro: 'Accountants, controllers, fractional CFOs, tax and transaction specialists - verified before they appear, paid through escrow milestone by milestone.',
    points: [
      ['Credentials checked', 'CPA, CA, ACCA, CFA and other designations are validated with the issuing body before a profile shows them as verified.'],
      ['Regulated work', 'Audit, tax filing and regulatory reporting are marked as regulated. Enterprise policies usually require a Green trust light (fully verified) for them.'],
      ['Money in escrow', 'You fund each milestone before work starts and release it only when you accept the deliverable.'],
      ['Your controls', 'Spend limits, approvers and required clauses from your organisation\'s policy apply to every engagement.'],
    ],
  },
}

/** Search engines read the breadcrumb (Home > Professionals > Category) from structured data while the page is open. */
function useBreadcrumbData(category: TaxonomyCategory | null | undefined) {
  useEffect(() => {
    if (!category) return
    const origin = window.location.origin
    const tag = document.createElement('script')
    tag.type = 'application/ld+json'
    tag.text = JSON.stringify({
      '@context': 'https://schema.org', '@type': 'BreadcrumbList',
      itemListElement: [
        { '@type': 'ListItem', position: 1, name: 'Find professionals', item: `${origin}/professionals` },
        { '@type': 'ListItem', position: 2, name: category.name, item: `${origin}/categories/${category.slug}` },
      ],
    })
    document.head.appendChild(tag)
    const title = document.title
    document.title = `${category.name} professionals | Zoikorum`
    return () => { tag.remove(); document.title = title }
  }, [category])
}

/** Public category page: a search box scoped to the category, a multi-select specialization navigator (?spec=a,b),
    filters and results, plus what buyers should know and how to start (individually or as an enterprise). */
export default function CategoryPage() {
  const { slug = '' } = useParams()
  const { user } = useAuth()
  const [params, setParams] = useSearchParams()
  const [category, setCategory] = useState<TaxonomyCategory | null | undefined>(undefined)
  const [data, setData] = useState<SearchResponse | null>(null)
  const [items, setItems] = useState<SearchResult[]>([])
  const [error, setError] = useState<unknown>(null)
  const [q, setQ] = useState(params.get('q') ?? '')
  const savedIds = useSavedIds()
  const key = params.toString()

  useEffect(() => {
    taxonomyApi.all().then((all) => setCategory(all.find((c) => c.slug === slug) ?? null)).catch(setError)
  }, [slug])
  useEffect(() => {
    let cancelled = false
    searchApi.professionals({ sort: 'verified', ...Object.fromEntries(new URLSearchParams(key)), category: slug, limit: String(PAGE), offset: '0' })
      .then((r) => { if (!cancelled) { setData(r); setItems(r.items); setError(null) } })
      .catch((err) => { if (!cancelled) setError(err) })
    return () => { cancelled = true }
  }, [slug, key])
  useBreadcrumbData(category)

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
  async function more() {
    const r = await searchApi.professionals({ sort: 'verified', ...Object.fromEntries(params), category: slug, limit: String(PAGE), offset: String(items.length) })
    setItems([...items, ...r.items])
  }
  function search(e: FormEvent) {
    e.preventDefault()
    set('q', q.trim() || null)
  }

  const guide = GUIDANCE[slug]
  const find = `/app/find?category=${encodeURIComponent(slug)}`
  const post = user ? find : `/join?type=BUYER&next=${encodeURIComponent(find)}`
  const specs = (params.get('spec') ?? '').split(',').filter(Boolean)
  const tiers = (params.get('tier') ?? '').split(',').filter(Boolean)
  return (
    <>
      <SiteHeader />
      <main className="profile-wrap">
        <ErrorAlert error={error} />
        {category === undefined && !error && <div className="card panel skeleton" style={{ height: 180 }} aria-busy="true" />}
        {category === null && <section className="card panel"><h1>Category not found</h1><p><Link to="/professionals">Browse all professionals</Link></p></section>}
        {category && <>
          <nav aria-label="Breadcrumb" className="breadcrumb small"><Link to="/professionals">Find professionals</Link> › <span aria-current="page">{category.name}</span></nav>
          <section className="card panel hero">
            <h1 style={{ marginTop: 0 }}>{category.name}</h1>
            <p className="lead">{guide?.intro ?? `Verified ${category.name.toLowerCase()} professionals, engaged through structured requests and paid through escrow.`}</p>
            <form className="row" role="search" onSubmit={search} style={{ alignItems: 'stretch' }}>
              <input className="input" style={{ flex: 1, minWidth: 0 }} aria-label={`Search ${category.name}`} value={q} onChange={(e) => setQ(e.target.value)}
                placeholder={`Search within ${category.name}, e.g. “month-end close” or “transfer pricing”`} />
              <button className="btn btn-primary">Search</button>
            </form>
            <div className="row" style={{ marginTop: 12 }}>
              <Link className="btn btn-secondary" to={post}>Post your requirement</Link>
              {!user && <Link className="btn btn-ghost" to={`/login?next=${encodeURIComponent(find)}`}>Sign in</Link>}
            </div>
          </section>

          <div className="cat-layout">
            <aside className="card panel filters" aria-label="Filters">
              <SpecializationNavigator groups={category.groups} selected={specs} onToggle={(s) => toggleList('spec', s)} facets={data?.facets} />
              <div className="filter-label">Trust light</div>
              {['A', 'B', 'C'].map((t) => (
                <label key={t} className="checkbox small"><input type="checkbox" checked={tiers.includes(t)} onChange={() => toggleList('tier', t)} />
                  <span><span className="light-dot" style={{ background: lightColor(t), marginRight: 6 }} aria-hidden />{lightName(t)}</span></label>
              ))}
              <ProcurementFilters params={params} facets={data?.facets} set={set} toggleList={toggleList} />
              {key && <button type="button" className="btn btn-ghost btn-sm" style={{ marginTop: 12 }} onClick={() => { setQ(''); setParams({}) }}>Clear all</button>}
            </aside>
            <section aria-label="Results">
              <div className="results-head">
                <span className="muted">{data ? `${data.total} professional${data.total === 1 ? '' : 's'} in ${category.name}` : 'Searching…'}</span>
              </div>
              <SelectedPills params={params} groups={category.groups} toggleList={toggleList} set={set} />
              {data && data.total === 0 && <section className="card panel"><p className="muted" style={{ margin: 0 }}>
                No published professionals match yet. Try fewer specializations or filters, or <Link to={post}>post your requirement</Link> and let professionals come to you.</p></section>}
              <div className="results">{items.map((r) => <ResultCard key={r.professionalId} r={r} saved={savedIds.ids?.has(r.professionalId)}
                onToggle={savedIds.canSave && savedIds.ids ? (id) => { savedIds.toggle(id).catch(setError) } : undefined} />)}</div>
              {data && items.length < data.total && <button className="btn btn-secondary" style={{ marginTop: 8 }} onClick={() => more().catch(setError)}>Show more</button>}
            </section>
          </div>

          {guide && <section className="stat-row">
            {guide.points.map(([title, text]) => <div key={title} className="card panel"><h3 style={{ marginTop: 0 }}>{title}</h3><p className="small muted">{text}</p></div>)}
          </section>}

          <EducationCards />

          <section className="card panel">
            <h2>What is covered</h2>
            <div className="home-grid">
              {category.groups.map((g) => <div key={g.slug}>
                <h3>{g.name}</h3>
                <ul className="plain">{g.specializations.map((s) => <li key={s.slug}>
                  <Link to={`/categories/${slug}?spec=${encodeURIComponent(s.slug)}`}>{s.name}</Link>
                  {s.regulated && <span className="badge warn" title="Regulated work: enterprise policies usually require a Green trust light (fully verified)"> regulated</span>}
                  {s.requiresCredential && <span className="badge" title="A validated credential is required"> credential</span>}
                </li>)}</ul>
              </div>)}
            </div>
            {category.credentialHints.length > 0 && <p className="muted small">Credentials we validate here: {category.credentialHints.join(', ')}.</p>}
          </section>

          <section className="card panel">
            <h2>For enterprises</h2>
            <p>Bring your procurement rules: minimum trust light, required credentials and jurisdictions, approvers and spend limits,
              required contract clauses and cost centres. They are applied to every request and engagement automatically.</p>
            <Link className="btn btn-secondary" to={user ? '/app/policies' : '/enterprise'}>{user ? 'Your procurement rules' : 'Set up enterprise access'}</Link>
          </section>
        </>}
      </main>
      <SiteFooter />
    </>
  )
}
