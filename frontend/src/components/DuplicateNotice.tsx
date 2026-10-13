import { useEffect, useState } from 'react'
import { duplicatesApi, type DuplicateCase } from '../api/duplicates'

/* Duplicate account suspected (Onboarding s.20): a calm notice with two answers and a support path. Nothing is merged
   automatically; support reviews the answer. */
export function DuplicateNotice() {
  const [items, setItems] = useState<DuplicateCase[]>([])
  const [note, setNote] = useState('')
  const [done, setDone] = useState<string | null>(null)
  useEffect(() => { duplicatesApi.mine().then(setItems).catch(() => {}) }, [])
  const d = items[0]
  if (done) return <div className="alert alert-success" role="status">{done}</div>
  if (!d) return null
  if (d.status === 'ANSWERED') return <div className="alert alert-info" role="status">Support is reviewing your answer about the account {d.otherAccount}.</div>
  const answer = (a: 'MERGE_REQUESTED' | 'NOT_ME') => duplicatesApi.answer(d.id, a, note || undefined)
    .then(() => setDone(a === 'MERGE_REQUESTED' ? 'Thanks. Support will merge your accounts and email you; the other account will be closed.'
      : 'Thanks. Support will check and get back to you.')).catch(() => setDone('Your answer could not be sent. Please try again or contact support.'))
  return (
    <div className="alert alert-warn" role="status">
      <strong>It looks like you may have another Zoikorum account</strong> ({d.otherAccount}): the same identity document was used on both.
      Keeping one account protects your verification and payment history.
      <div className="row" style={{ marginTop: 8, flexWrap: 'wrap' }}>
        <input className="input" style={{ flex: 1, minWidth: 200 }} placeholder="Anything support should know (optional)" maxLength={500}
          value={note} onChange={(e) => setNote(e.target.value)} />
        <button className="btn btn-primary btn-sm" onClick={() => answer('MERGE_REQUESTED')}>Yes, merge my accounts</button>
        <button className="btn btn-secondary btn-sm" onClick={() => answer('NOT_ME')}>That is not my account</button>
      </div>
    </div>
  )
}
