import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { proApi, LABEL, type PublicProfile } from '../api/professional'
import { formatMoney } from '../api/orgs'
import { ErrorAlert } from './ui'
import { TierBadge } from './portal'
export function QuickViewProfile({ id, why, onClose }: { id: string; why: string[]; onClose: () => void }) {
  const [profile, setProfile] = useState<PublicProfile | null>(null)
  const [error, setError] = useState<unknown>(null)
  useEffect(() => {
    let live = true
    proApi.publicProfile(id).then(p => { if (live) setProfile(p) }).catch(e => { if (live) setError(e) })
    return () => { live = false }
  }, [id])
  return <div className="modal-backdrop" role="dialog" aria-modal="true" aria-label="Professional quick view" onClick={onClose}>
    <section className="card modal" onClick={e => e.stopPropagation()}>
      <button className="icon-btn" aria-label="Close quick view" onClick={onClose}>×</button><ErrorAlert error={error} />
      {!profile ? <p>Loading profile…</p> : <><h2>{profile.displayName} <TierBadge tier={profile.trust.tier} /></h2>
        <p>{profile.headline}</p><p>{profile.bio}</p><p>{LABEL[profile.availability] ?? profile.availability}</p>
        {profile.indicativeRate && <p>{formatMoney(profile.indicativeRate)} · {profile.rateUnit}</p>}
        <ul>{why.map(w => <li key={w}>{w}</li>)}</ul>
        <p>Serves: {profile.servedJurisdictions.join(', ') || 'No country restriction stated'}</p>
        <p>Verified jurisdictions: {profile.verifiedJurisdictions.join(', ') || 'None verified'}</p>
        <p>Stated licences: {profile.licensedJurisdictions.join(', ') || 'None stated'}</p>
        <p>Country coverage does not establish regulatory eligibility. The engagement checks your organisation policy and required verification.</p>
        <Link className="btn btn-primary" to={`/professionals/${id}`}>View full profile</Link>
        <Link className="btn btn-secondary" to={`/app/requests/new?pro=${id}`}>Request proposal</Link>
      </>}
    </section>
  </div>
}
