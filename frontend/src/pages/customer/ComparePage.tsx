import { Link, useSearchParams } from 'react-router-dom'
import { CompareTable } from '../../components/CompareDialog'
import { PortalHeader } from '../../components/portal'

/** A shared comparison link (/app/compare?ids=a,b,c): the same table, for any signed-in customer. */
export default function ComparePage() {
  const [params] = useSearchParams()
  const ids = (params.get('ids') ?? '').split(',').filter((x) => /^[0-9a-f-]{36}$/i.test(x)).slice(0, 3)
  return (
    <>
      <PortalHeader eyebrow="Find professionals" title="Compare professionals" subtitle="A comparison shared with you. Details reflect each profile today." />
      <section className="card panel">
        {ids.length === 0 ? <p className="muted">This comparison link is not valid. <Link to="/app/find">Find professionals</Link></p> : <CompareTable ids={ids} />}
      </section>
    </>
  )
}
