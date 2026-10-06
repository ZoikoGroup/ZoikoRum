import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { savedApi, type SavedProfessional } from '../../api/saved'
import { DIMENSION_VALUE, DIMENSIONS } from '../../api/verification'
import { Avatar, Icon } from '../../components/dashboard'
import { PortalHeader, SidePanel, StatCard, TierBadge } from '../../components/portal'
import { ErrorAlert } from '../../components/ui'

const good = (p: SavedProfessional, key: string) => DIMENSION_VALUE[p.dimensions[key]]?.good ?? false

/** Verification (management design 11), customer view: what has been checked about the professionals you are
    considering. Figures come from your own shortlist — no platform-wide statistics and no partner logos. */
export default function CustomerVerification() {
  const [saved, setSaved] = useState<SavedProfessional[] | null>(null)
  const [error, setError] = useState<unknown>(null)
  useEffect(() => { savedApi.list().then(setSaved).catch(setError) }, [])

  const list = saved ?? []
  const count = (key: string) => list.filter((p) => good(p, key)).length
  const tierA = list.filter((p) => p.tier === 'A').length

  return (
    <>
      <PortalHeader eyebrow="Verification" title="Trusted professionals. Verified with confidence."
        subtitle="See exactly what has been checked for the professionals you are considering — identity, credentials, eligibility, restrictions and insurance."
        actions={<Link className="btn btn-primary" to="/app/find"><Icon name="search" /> Find verified professionals</Link>} />
      <ErrorAlert error={error} />

      <div className="stat-row four">
        <StatCard icon="bookmark" tone="blue" value={saved ? list.length : '…'} label="On your shortlist" sub="Saved professionals" to="/app/saved" />
        <StatCard icon="user" tone="green" value={saved ? count('identity') : '…'} label="Identity verified" sub="Government ID and liveness" />
        <StatCard icon="shield" tone="violet" value={saved ? count('credentials') : '…'} label="Credentials validated" sub="Licences and qualifications" />
        <StatCard icon="star" tone="amber" value={saved ? tierA : '…'} label="Tier A" sub="Fully verified and eligible" />
      </div>

      <div className="home-grid wide">
        <section className="card panel">
          <div className="panel-head"><h2>Your shortlist — verification status</h2><Link className="btn btn-ghost btn-sm" to="/app/saved">Manage shortlist →</Link></div>
          {saved && list.length === 0 ? (
            <div className="empty-row" style={{ padding: 24 }}>
              <strong>No saved professionals yet.</strong> Save professionals from search to see their verification status side by side here.
            </div>
          ) : (
            <div className="compare-scroll">
              <table className="data">
                <thead><tr><th>Professional</th><th>Tier</th>{DIMENSIONS.map((d) => <th key={d.key}>{d.label}</th>)}<th>Last checked</th></tr></thead>
                <tbody>{list.map((p) => (
                  <tr key={p.professionalId}>
                    <td><div className="name-row"><Avatar name={p.displayName} photoUrl={p.photoUrl} size={32} />
                      <Link to={`/professionals/${p.professionalId}`}><strong>{p.displayName}</strong></Link></div></td>
                    <td><TierBadge tier={p.tier} /></td>
                    {DIMENSIONS.map((d) => {
                      const v = DIMENSION_VALUE[p.dimensions[d.key]] ?? { label: 'Not verified', good: false }
                      return <td key={d.key}><span className={`badge ${v.good ? 'green' : ''}`}>{v.label}</span></td>
                    })}
                    <td className="small">{p.lastVerifiedAt ? new Date(p.lastVerifiedAt).toLocaleDateString() : '—'}</td>
                  </tr>
                ))}</tbody>
              </table>
            </div>
          )}
          <p className="muted small" style={{ marginBottom: 0 }}>Restrictions are shown only when the screening is clear. Checks are made by a verification
            provider or a compliance reviewer — never by AI.</p>
        </section>

        <aside>
          <SidePanel title="What each check means">
            <ul className="assurance compact">
              <li><Icon name="user" /><span><strong>Identity</strong> — government ID matched to a live person.</span></li>
              <li><Icon name="contract" /><span><strong>Credentials</strong> — licences and qualifications confirmed with the issuer.</span></li>
              <li><Icon name="globe" /><span><strong>Jurisdiction</strong> — eligible to practise where you need the work.</span></li>
              <li><Icon name="shield" /><span><strong>Restrictions</strong> — sanctions and disciplinary screening is clear.</span></li>
              <li><Icon name="lock" /><span><strong>Insurance</strong> — professional indemnity cover is in force.</span></li>
            </ul>
          </SidePanel>
          <SidePanel title="Trust Tiers">
            <ul className="assurance compact">
              <li><Icon name="check" /><span><strong>Tier A</strong> — identity, credentials and eligibility all verified.</span></li>
              <li><Icon name="check" /><span><strong>Tier B</strong> — identity verified and restrictions clear.</span></li>
              <li><Icon name="clock" /><span><strong>Tier C</strong> — verification not yet complete.</span></li>
            </ul>
          </SidePanel>
          <SidePanel title="Your organisation">
            <p className="muted small" style={{ margin: 0 }}>Organisation verification (business registration and authorised signatory) arrives with
              enterprise onboarding. Your organisation profile is on the <Link to="/app/organisation">Organisation</Link> page.</p>
          </SidePanel>
        </aside>
      </div>
    </>
  )
}
