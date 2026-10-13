import { useCallback, useEffect, useState } from 'react'
import { duplicatesApi, type DuplicateCase } from '../api/duplicates'
import { EmptyTable, PortalHeader } from '../components/portal'
import { ErrorAlert, useStepUp } from '../components/ui'

/* Support: possible duplicate accounts (Onboarding s.20 "merge flow with support path"). Confirming keeps one account and
   closes the other; anything that must move is moved by support. Every decision needs a fresh two-step confirmation. */
export default function DuplicateAccountsPage() {
  const [rows, setRows] = useState<DuplicateCase[] | null>(null)
  const [error, setError] = useState<unknown>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [notes, setNotes] = useState<Record<string, string>>({})
  const { run, modal } = useStepUp(setError)
  const load = useCallback(() => duplicatesApi.queue().then(setRows).catch(setError), [])
  useEffect(() => { load() }, [load])

  const resolve = (d: DuplicateCase, outcome: 'MERGED' | 'NOT_DUPLICATE', keep?: string) => run(async () => {
    await duplicatesApi.resolve(d.id, { outcome, keepIdentityId: keep, note: (notes[d.id] ?? '').trim() })
    setNotice(outcome === 'MERGED' ? 'Accounts merged: the duplicate is closed.' : 'Marked as not a duplicate.')
    await load()
  })

  return (
    <>
      <PortalHeader eyebrow="Support" title="Possible duplicate accounts" subtitle="Raised when the same identity document is used on two accounts. Nothing is merged automatically." />
      <ErrorAlert error={error} />
      {notice && <div className="alert alert-success" role="status">{notice}</div>}
      {modal}
      <section className="card panel">
        {rows && rows.length === 0 ? <EmptyTable columns={['Accounts', 'Signal', 'Their answer', 'Decision']}><strong>Nothing to review.</strong></EmptyTable> : (
          <table className="data"><thead><tr><th>Accounts</th><th>Signal</th><th>Their answer</th><th>Decision</th></tr></thead>
            <tbody>{(rows ?? []).map((d) => {
              const ok = (notes[d.id] ?? '').trim().length >= 5
              return (
                <tr key={d.id}>
                  <td><strong>{d.accountName}</strong> <span className="muted small">{d.account}</span><br />
                    <strong>{d.otherAccountName}</strong> <span className="muted small">{d.otherAccount}</span></td>
                  <td className="small">{d.signal === 'SAME_ID_DOCUMENT' ? 'Same identity document' : d.signal}<br /><span className="muted">{new Date(d.createdAt).toLocaleDateString()}</span></td>
                  <td className="small">{d.userAnswer === 'MERGE_REQUESTED' ? 'Asked to merge' : d.userAnswer === 'NOT_ME' ? 'Says it is not theirs' : 'No answer yet'}
                    {d.userNote && <div className="muted">“{d.userNote}”</div>}</td>
                  <td>
                    <input className="input" placeholder="Decision note (required)" maxLength={500} value={notes[d.id] ?? ''}
                      onChange={(e) => setNotes({ ...notes, [d.id]: e.target.value })} />
                    <div className="row" style={{ marginTop: 6, flexWrap: 'wrap' }}>
                      <button className="btn btn-secondary btn-sm" disabled={!ok} onClick={() => resolve(d, 'MERGED', d.identityId ?? undefined)}>Keep {d.accountName}</button>
                      <button className="btn btn-secondary btn-sm" disabled={!ok} onClick={() => resolve(d, 'MERGED', d.otherIdentityId ?? undefined)}>Keep {d.otherAccountName}</button>
                      <button className="btn btn-ghost btn-sm" disabled={!ok} onClick={() => resolve(d, 'NOT_DUPLICATE')}>Not a duplicate</button>
                    </div>
                  </td>
                </tr>
              )
            })}</tbody></table>
        )}
      </section>
    </>
  )
}
