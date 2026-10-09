import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { LABEL, proApi, type PublicProfile } from '../api/professional'
import { equivalency } from '../lib/equivalency'
import { countryName } from '../pages/ProfessionalPages'

/* Profile preview (Finance & Accounting category s.6): opened by hovering a result for ~0.7s on desktop or the
   "Quick view" button. Strict content: short summary, verified credentials only, top specializations, engagement
   types, up to 3 typical deliverables, and the three actions. Deep proof stays on the profile page. */

export function QuickView({ id, buyerCountry, saved, onSave, onClose }: {
  id: string; buyerCountry: string | null; saved: boolean | null; onSave: () => void; onClose: () => void
}) {
  const [p, setP] = useState<PublicProfile | null>(null)
  const [failed, setFailed] = useState(false)
  useEffect(() => { proApi.publicProfile(id).then(setP).catch(() => setFailed(true)) }, [id])

  const deliverables = (p?.offerings ?? []).flatMap((o) => o.deliverables ?? []).slice(0, 3)
  const credentials = (p?.credentials ?? []).filter((c) => c.status === 'VERIFIED')
  return (
    <div className="quick-view card" role="dialog" aria-label="Profile preview" onMouseLeave={onClose}>
      <button className="icon-btn qv-close" aria-label="Close preview" onClick={onClose}>×</button>
      {failed ? <p className="muted small">The preview could not be loaded.</p> : !p ? <p className="muted small">Loading…</p> : <>
        {p.bio && <p className="qv-summary">{p.bio}</p>}
        <div className="qv-grid">
          <div><div className="filter-label">Verified credentials</div>
            {credentials.length === 0 ? <span className="muted small">None verified yet</span> : <ul className="qv-list">{credentials.map((c) => {
              const eq = equivalency(c, buyerCountry, countryName)
              return <li key={c.name + c.issuingBody} title={eq.explanation ?? undefined}>{c.displayLabel}
                {eq.recognisedHere && <span className="badge green" style={{ marginLeft: 6 }}>Recognised in your region</span>}
                {eq.explanation && <span className="muted small"> ⓘ</span>}</li>
            })}</ul>}</div>
          <div><div className="filter-label">Top specializations</div>
            <div className="chips">{p.specializations.slice(0, 3).map((s) => <span key={s.slug} className="chip">{s.name}</span>)}</div></div>
          <div><div className="filter-label">Engagement types</div>
            <span className="small">{p.engagementTypes.map((t) => LABEL[t] ?? t).join(' · ') || '—'}</span></div>
          {deliverables.length > 0 && <div><div className="filter-label">Typical deliverables</div>
            <ul className="qv-list">{deliverables.map((d) => <li key={d}>{d}</li>)}</ul></div>}
        </div>
        <div className="row" style={{ marginTop: 10 }}>
          <Link className="btn btn-primary btn-sm" to={`/professionals/${id}`}>View profile</Link>
          <Link className="btn btn-secondary btn-sm" to={`/app/requests/new?pro=${id}`}>Request proposal</Link>
          {saved !== null && <button className="btn btn-secondary btn-sm" onClick={onSave}>{saved ? 'Saved' : 'Save'}</button>}
        </div>
      </>}
    </div>
  )
}
