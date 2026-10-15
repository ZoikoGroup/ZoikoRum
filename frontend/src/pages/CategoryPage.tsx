import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { taxonomyApi, type TaxonomyCategory } from '../api/professional'
import { searchApi, type SearchResult } from '../api/search'
import { useAuth } from '../auth/AuthContext'
import { ErrorAlert, SiteFooter, SiteHeader } from '../components/ui'
import { ResultCard } from './BrowseProfessionals'

/** What the category documents say buyers should know before engaging in that category. */
const GUIDANCE: Record<string, { intro: string; points: [string, string][] }> = {
  'finance-and-accounting': {
    intro: 'Accountants, controllers, fractional CFOs, tax and transaction specialists - verified before they appear, paid through escrow milestone by milestone.',
    points: [
      ['Credentials checked', 'CPA, CA, ACCA, CFA and other designations are validated with the issuing body before a profile shows them as verified.'],
      ['Regulated work', 'Audit, tax filing and regulatory reporting are marked as regulated. Enterprise policies usually require Tier A for them.'],
      ['Money in escrow', 'You fund each milestone before work starts and release it only when you accept the deliverable.'],
      ['Your controls', 'Spend limits, approvers and required clauses from your organisation\'s policy apply to every engagement.'],
    ],
  },
}

/** Public category landing page: what is covered, who is verified, and how to start (individually or as an enterprise). */
export default function CategoryPage() {
  const { slug = '' } = useParams()
  const { user } = useAuth()
  const [category, setCategory] = useState<TaxonomyCategory | null | undefined>(undefined)
  const [top, setTop] = useState<SearchResult[]>([])
  const [total, setTotal] = useState<number | null>(null)
  const [error, setError] = useState<unknown>(null)

  useEffect(() => {
    taxonomyApi.all().then((all) => setCategory(all.find((c) => c.slug === slug) ?? null)).catch(setError)
    searchApi.professionals({ category: slug, sort: 'verified', limit: '6' })
      .then((r) => { setTop(r.items); setTotal(r.total) }).catch(() => {})
  }, [slug])

  const guide = GUIDANCE[slug]
  const find = `/app/find?category=${encodeURIComponent(slug)}`
  const post = user ? find : `/join?type=BUYER&next=${encodeURIComponent(find)}`
  return (
    <>
      <SiteHeader />
      <main className="profile-wrap">
        <ErrorAlert error={error} />
        {category === undefined && !error && <div className="card panel skeleton" style={{ height: 180 }} aria-busy="true" />}
        {category === null && <section className="card panel"><h1>Category not found</h1><p><Link to="/professionals">Browse all professionals</Link></p></section>}
        {category && <>
          <nav aria-label="Breadcrumb" className="muted small"><Link to="/professionals">Professionals</Link> › {category.name}</nav>
          <section className="card panel hero">
            <h1 style={{ marginTop: 0 }}>{category.name}</h1>
            <p className="lead">{guide?.intro ?? `Verified ${category.name.toLowerCase()} professionals, engaged through structured requests and paid through escrow.`}</p>
            <div className="row">
              <Link className="btn btn-primary" to={post}>Post your requirement</Link>
              <Link className="btn btn-secondary" to={`/professionals?category=${encodeURIComponent(slug)}`}>
                Browse {total != null ? `${total} ` : ''}professionals</Link>
            </div>
          </section>

          {guide && <section className="stat-row">
            {guide.points.map(([title, text]) => <div key={title} className="card panel"><h3 style={{ marginTop: 0 }}>{title}</h3><p className="small muted">{text}</p></div>)}
          </section>}

          <section className="card panel">
            <h2>What is covered</h2>
            <div className="home-grid">
              {category.groups.map((g) => <div key={g.slug}>
                <h3>{g.name}</h3>
                <ul className="plain">{g.specializations.map((s) => <li key={s.slug}>
                  <Link to={`/professionals?spec=${encodeURIComponent(s.slug)}`}>{s.name}</Link>
                  {s.regulated && <span className="badge warn" title="Regulated work: enterprise policies usually require Tier A"> regulated</span>}
                  {s.requiresCredential && <span className="badge" title="A validated credential is required"> credential</span>}
                </li>)}</ul>
              </div>)}
            </div>
            {category.credentialHints.length > 0 && <p className="muted small">Credentials we validate here: {category.credentialHints.join(', ')}.</p>}
          </section>

          {top.length > 0 && <section>
            <h2>Most verified in {category.name}</h2>
            <div className="results">{top.map((r) => <ResultCard key={r.professionalId} r={r} />)}</div>
          </section>}

          <section className="card panel">
            <h2>For enterprises</h2>
            <p>Bring your procurement rules: minimum trust tier, required credentials and jurisdictions, approvers and spend limits,
              required contract clauses and cost centres. They are applied to every request and engagement automatically.</p>
            <Link className="btn btn-secondary" to="/enterprise">Set up enterprise access</Link>
          </section>
        </>}
      </main>
      <SiteFooter />
    </>
  )
}
