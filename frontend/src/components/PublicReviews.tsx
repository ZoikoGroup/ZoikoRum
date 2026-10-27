import { useAuth } from '../auth/AuthContext'
import { ReportButton } from './ReportButton'
import { useEffect, useState } from 'react'
import { growthApi, type PublicReview, type ReviewPage } from '../api/professional'
import { ErrorAlert } from './ui'

/** Verified engagement reviews, each with the professional's public reply underneath. The reviewed professional
    (canReply) can write one reply per review and edit it; every version is kept in the audit ledger. */
export function PublicReviews({ professionalId, canReply = false }: { professionalId: string; canReply?: boolean }) {
  const { user } = useAuth()
  const [data, setData] = useState<ReviewPage | null>(null), [error, setError] = useState<unknown>(null), [offset, setOffset] = useState(0)
  useEffect(() => { growthApi.reviews(professionalId, offset).then(setData).catch(setError) }, [professionalId, offset])
  const replaced = (r: PublicReview) => setData((d) => d && { ...d, items: d.items.map((x) => (x.id === r.id ? r : x)) })
  return <section className="card panel"><h2>Verified engagement reviews</h2><ErrorAlert error={error} />{data && <>
    <p>{data.reviewCount ? `${data.averageRating}/5 from ${data.reviewCount} completed engagements` : 'No verified reviews yet.'}</p>
    {data.items.map(r => <article key={r.id} className="review-item"><strong>{r.rating}/5 · {r.reviewerName}, {r.organizationName}</strong><p>{r.comment}</p>
      <p className="muted small">{r.engagementReference} · {new Date(r.createdAt).toLocaleDateString()}{user && !canReply && <> · <ReportButton subjectType="REVIEW" subjectId={r.id} what="this review" className="link-button small" /></>}</p>
      <ReviewReplyBlock review={r} canReply={canReply} onSaved={replaced} onError={setError} />
    </article>)}
    {data.reviewCount > 20 && <div className="row">
      <button className="btn" disabled={!offset} onClick={() => setOffset(n => Math.max(0, n - 20))}>Previous</button>
      <button className="btn" disabled={offset + data.items.length >= data.reviewCount} onClick={() => setOffset(n => n + 20)}>Next</button></div>}
  </>}</section>
}

function ReviewReplyBlock({ review, canReply, onSaved, onError }: {
  review: PublicReview; canReply: boolean; onSaved: (r: PublicReview) => void; onError: (e: unknown) => void
}) {
  const [editing, setEditing] = useState(false)
  const [text, setText] = useState(review.reply?.body ?? '')
  const [busy, setBusy] = useState(false)
  const reply = review.reply
  if (editing) {
    return <form className="review-reply" onSubmit={async (e) => {
      e.preventDefault(); setBusy(true); onError(null)
      try { onSaved(await growthApi.replyToReview(review.id, text)); setEditing(false) } catch (err) { onError(err) } finally { setBusy(false) }
    }}>
      <label className="small" htmlFor={`reply-${review.id}`}><strong>Your public reply</strong></label>
      <textarea id={`reply-${review.id}`} className="input" rows={3} maxLength={1500} value={text} onChange={(e) => setText(e.target.value)} />
      <p className="muted small" style={{ margin: '4px 0' }}>Shown under the review to everyone. Keep it factual and courteous; edits are recorded.</p>
      <div className="row"><button className="btn btn-primary btn-sm" disabled={busy || text.trim().length < 2}>{busy ? 'Saving…' : 'Publish reply'}</button>
        <button type="button" className="btn btn-ghost btn-sm" onClick={() => { setEditing(false); setText(reply?.body ?? '') }}>Cancel</button></div>
    </form>
  }
  if (!reply) return canReply ? <button type="button" className="btn btn-ghost btn-sm" onClick={() => setEditing(true)}>Reply publicly</button> : null
  return <div className="review-reply">
    <p className="small" style={{ margin: 0 }}><strong>Reply from the professional</strong>
      <span className="muted"> · {new Date(reply.updatedAt).toLocaleDateString()}{reply.edited && ' · edited'}</span></p>
    <p style={{ margin: '4px 0 0' }}>{reply.body}</p>
    {canReply && <button type="button" className="btn btn-ghost btn-sm" onClick={() => setEditing(true)}>Edit reply</button>}
  </div>
}
