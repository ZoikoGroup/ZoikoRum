import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { proApi, type BuyerCandidate, type SavedBuyer } from '../api/professional'
import { EmptyTable, PortalHeader } from '../components/portal'
import { ErrorAlert } from '../components/ui'

const day = (iso: string | null) => (iso ? new Date(iso).toLocaleDateString() : '—')

/** Professional Dashboard s.17: your client list. Only organisations that have sent you a request can be saved
 *  (no buyer directory, no cold outreach). Notes are private; "Always alert me" emails their requests even when
 *  email notifications are off. */
export default function SavedBuyersPage() {
  const [saved, setSaved] = useState<SavedBuyer[] | null>(null)
  const [candidates, setCandidates] = useState<BuyerCandidate[]>([])
  const [notes, setNotes] = useState<Record<string, string>>({})
  const [error, setError] = useState<unknown>(null)
  const [notice, setNotice] = useState<string | null>(null)

  const load = useCallback(async () => {
    try {
      const [s, c] = await Promise.all([proApi.savedBuyers(), proApi.buyerCandidates()])
      setSaved(s)
      setCandidates(c.filter((x) => !x.saved))
      setNotes(Object.fromEntries(s.map((b) => [b.id, b.note ?? ''])))
    } catch (err) {
      setError(err)
    }
  }, [])
  useEffect(() => { load() }, [load])

  const act = (fn: () => Promise<unknown>, message: string) => async () => {
    setError(null)
    setNotice(null)
    try {
      await fn()
      await load()
      setNotice(message)
    } catch (err) {
      setError(err)
    }
  }

  return (
    <>
      <PortalHeader eyebrow="Clients" title="Saved buyers"
        subtitle="Organisations that have worked with you or sent you requests. Notes are only visible to you." />
      <ErrorAlert error={error} />
      {notice && <div className="alert alert-success" role="status">{notice}</div>}
      <section className="card panel">
        <div className="panel-head"><h2>Your saved buyers</h2></div>
        {saved && saved.length === 0 ? (
          <EmptyTable columns={['Buyer', 'Requests', 'Engagements', 'Last activity', 'Alerts']}>
            <strong>No saved buyers yet.</strong> Save an organisation below once it has sent you a request.
          </EmptyTable>
        ) : (
          <div className="table-scroll"><table className="data">
            <thead><tr><th>Buyer</th><th>Requests</th><th>Engagements</th><th>Last activity</th><th>Private note</th><th>Alerts</th><th /></tr></thead>
            <tbody>{(saved ?? []).map((b) => (
              <tr key={b.id}>
                <td><strong>{b.name}</strong>{b.country && <div className="muted small">{b.country}</div>}</td>
                <td>{b.requests}</td>
                <td>{b.engagements}{b.completed > 0 && <span className="muted small"> · {b.completed} completed</span>}</td>
                <td className="small">{day(b.lastActivityAt)}</td>
                <td style={{ minWidth: 220 }}>
                  <input className="input" maxLength={500} aria-label={`Private note about ${b.name}`} placeholder="Add a private note"
                    value={notes[b.id] ?? ''} onChange={(e) => setNotes({ ...notes, [b.id]: e.target.value })}
                    onBlur={() => { if ((notes[b.id] ?? '') !== (b.note ?? '')) act(() => proApi.updateSavedBuyer(b.id, { note: notes[b.id] ?? '' }), 'Note saved.')() }} />
                </td>
                <td><label className="small" style={{ whiteSpace: 'nowrap' }}>
                  <input type="checkbox" checked={b.alerts}
                    onChange={act(() => proApi.updateSavedBuyer(b.id, { alerts: !b.alerts }), b.alerts ? 'Alerts off.' : 'Alerts on.')} /> Always alert me</label></td>
                <td style={{ textAlign: 'right' }}>
                  <button className="btn btn-ghost btn-sm" onClick={act(() => proApi.removeSavedBuyer(b.id), `${b.name} removed.`)}>Remove</button></td>
              </tr>))}</tbody>
          </table></div>
        )}
      </section>
      <section className="card panel">
        <div className="panel-head"><h2>Buyers who contacted you</h2></div>
        {candidates.length === 0 ? <p className="muted small" style={{ margin: 0 }}>
          Everyone who has sent you a request is saved. New buyers appear here after their first request. See <Link to="/app/professional/requests">Requests</Link>.</p> : (
          <ul className="pro-list">{candidates.map((c) => (
            <li key={c.organizationId}>
              <span><strong>{c.name}</strong><span className="muted small"> · {c.requests} request{c.requests === 1 ? '' : 's'}
                {c.engagements > 0 && ` · ${c.engagements} engagement${c.engagements === 1 ? '' : 's'}`} · last {day(c.lastActivityAt)}</span></span>
              <button className="btn btn-secondary btn-sm" onClick={act(() => proApi.saveBuyer(c.organizationId), `${c.name} saved.`)}>Save</button>
            </li>))}</ul>
        )}
      </section>
    </>
  )
}
