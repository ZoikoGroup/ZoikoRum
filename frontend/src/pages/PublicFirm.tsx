import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { firmApi, type PublicFirm } from '../api/orgs'
import { Avatar } from '../components/dashboard'
import { ErrorAlert, Loading, SiteFooter, SiteHeader } from '../components/ui'
import { countryName } from './ProfessionalPages'
import { TrustLight } from '../components/TrustLight'


/** Public firm page: who the firm is, what is verified, and the professionals who practise under it.
    Works signed in or out; never shows the registration number, people's emails or internal roles. */
export default function PublicFirmPage() {
  const { id = '' } = useParams()
  const [firm, setFirm] = useState<PublicFirm | null>(null)
  const [error, setError] = useState<unknown>(null)
  useEffect(() => { firmApi.publicFirm(id).then(setFirm).catch(setError) }, [id])
  useEffect(() => {
    if (!firm) return
    const title = document.title
    document.title = `${firm.name} | Zoikorum`
    return () => { document.title = title }
  }, [firm])

  return (
    <>
      <SiteHeader />
      <main className="profile-wrap">
        <nav className="breadcrumb small" aria-label="Breadcrumb">
          <Link to="/professionals">Find professionals</Link>{firm && <> › <span>{firm.name}</span></>}
        </nav>
        <ErrorAlert error={error} />
        {!firm && !error && <Loading />}
        {firm && (
          <>
            <section className="card panel profile-head">
              <div>
                <div className="name-row"><Avatar name={firm.name} size={72} /><h1>{firm.name}</h1></div>
                {firm.name !== firm.legalName && <p className="muted small" style={{ margin: '0 0 6px' }}>Registered as {firm.legalName}</p>}
                <p className="muted small" style={{ margin: 0 }}>
                  {countryName(firm.hqCountry)}
                  {firm.sizeBand && ` · ${firm.sizeBand} people`}
                  {firm.website && <> · <a href={firm.website} target="_blank" rel="noopener noreferrer nofollow">{firm.website.replace(/^https?:\/\//, '')}</a></>}
                </p>
                <div className="badges" style={{ marginTop: 12 }}>
                  <span className={`badge ${firm.verified ? 'green' : 'warn'}`}>
                    {firm.verified ? 'Registration verified' : 'Registration not yet verified'}</span>
                  {firm.hasVerifiedRepresentative && <span className="badge green">Authorized representative verified</span>}
                  {firm.verifiedCredentials.map((c) => <span key={c} className="badge green">✓ {c}</span>)}
                </div>
              </div>
            </section>

            <section className="card panel">
              <h2>Professionals ({firm.professionals.length})</h2>
              {firm.professionals.length === 0 ? <p className="muted" style={{ margin: 0 }}>No published professionals yet.</p> : (
                <ul className="checklist">
                  {firm.professionals.map((p) => (
                    <li key={p.professionalId}>
                      <span className="row" style={{ gap: 12, flexWrap: 'nowrap' }}>
                        <Avatar name={p.displayName} photoUrl={p.photoUrl} />
                        <span><Link to={`/professionals/${p.professionalId}`}><strong>{p.displayName}</strong></Link>
                          {p.headline && <><br /><span className="muted small">{p.headline}</span></>}</span>
                      </span>
                      <TrustLight tier={p.tier} />
                    </li>
                  ))}
                </ul>
              )}
            </section>
            <p className="muted small">
              Verification confirms eligibility and trust signals. It is not a licence, endorsement or certification of the
              firm's services. Each engagement is with the professional named on its contract.
            </p>
          </>
        )}
      </main>
      <SiteFooter />
    </>
  )
}
