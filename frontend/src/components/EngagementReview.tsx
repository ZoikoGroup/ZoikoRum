import { useEffect, useState } from 'react'
import { api } from '../api/client'
import { ErrorAlert } from './ui'

interface Review { rating: number; comment: string; reviewerName: string; organizationName: string }
export function EngagementReview({ contractId, canReview }: { contractId: string; canReview: boolean }) {
  const [review, setReview] = useState<Review | null>(null)
  const [error, setError] = useState<unknown>(null)
  const [busy, setBusy] = useState(false)
  const url = `/v1/contracts/${contractId}/review`
  useEffect(() => { api<Review | null>(url).then(setReview).catch(setError) }, [url])
  return <section className="card panel"><h2>Verified engagement review</h2><ErrorAlert error={error} />
    {review ? <><strong>{review.rating}/5 · {review.reviewerName}, {review.organizationName}</strong><p>{review.comment}</p></> : canReview ?
      <form onSubmit={async e => { e.preventDefault(); const data = new FormData(e.currentTarget); setBusy(true); try { setReview(await api<Review>(url, { method: 'POST', body: { rating: Number(data.get('rating')), comment: data.get('comment') }, headers: { 'Idempotency-Key': crypto.randomUUID() } })) } catch (err) { setError(err) } finally { setBusy(false) } }}>
        <label>Rating<select className="input" name="rating">{[5, 4, 3, 2, 1].map(n => <option key={n} value={n}>{n}/5</option>)}</select></label>
        <textarea name="comment" className="input" required minLength={10} maxLength={2000} placeholder="Describe the completed engagement" />
        <p className="muted small">Your name and organisation will appear publicly. One review is permitted per completed engagement.</p>
        <button className="btn btn-primary" disabled={busy}>Publish review</button></form> : <p>No review submitted yet.</p>}</section>
}
