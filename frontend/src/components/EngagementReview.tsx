import { useEffect, useState } from 'react'
import { api } from '../api/client'
import { Icon } from './dashboard'
import { ErrorAlert } from './ui'

/* The buyer's public review of a completed engagement. Only a party to a completed engagement can write one, once, and
   it cannot be edited afterwards, so the form shows exactly how it will appear and asks for a confirmation. */

interface Review { rating: number; comment: string; reviewerName: string; organizationName: string; engagementReference?: string; createdAt?: string }

const LABELS = ['', 'Poor', 'Fair', 'Good', 'Very good', 'Excellent']
const HIGHLIGHTS = ['Quality of work', 'Clear communication', 'Delivered on time', 'Good value', 'Deep expertise', 'Would hire again']
const MIN = 10
const MAX = 2000

function Stars({ value, size = 'md' }: { value: number; size?: 'md' | 'lg' }) {
  return <span className={`stars ${size}`} aria-label={`${value} out of 5`}>
    {[1, 2, 3, 4, 5].map((n) => <span key={n} className={n <= value ? 'on' : ''} aria-hidden>★</span>)}</span>
}

export function EngagementReview({ contractId, canReview, professionalName, organizationName, reference }: {
  contractId: string; canReview: boolean; professionalName?: string; organizationName?: string; reference?: string
}) {
  const [review, setReview] = useState<Review | null>(null)
  const [loaded, setLoaded] = useState(false)
  const [error, setError] = useState<unknown>(null)
  const [busy, setBusy] = useState(false)
  const [rating, setRating] = useState(0)
  const [hover, setHover] = useState(0)
  const [comment, setComment] = useState('')
  const [tags, setTags] = useState<string[]>([])
  const [confirming, setConfirming] = useState(false)
  const url = `/v1/contracts/${contractId}/review`
  useEffect(() => { api<Review | null>(url).then((r) => { setReview(r); setLoaded(true) }).catch((err) => { setError(err); setLoaded(true) }) }, [url])

  const text = [tags.length ? `${tags.join(' · ')}.` : '', comment.trim()].filter(Boolean).join(' ')
  const shown = hover || rating
  const ready = rating > 0 && text.length >= MIN
  const publish = async () => {
    setBusy(true); setError(null)
    try {
      setReview(await api<Review>(url, { method: 'POST', body: { rating, comment: text }, headers: { 'Idempotency-Key': crypto.randomUUID() } }))
    } catch (err) { setError(err); setConfirming(false) } finally { setBusy(false) }
  }

  return (
    <section className="card panel engagement-review">
      <div className="review-head">
        <span className="kpi-icon green"><Icon name="star" /></span>
        <div>
          <h2 style={{ margin: 0 }}>Verified engagement review</h2>
          <p className="muted small" style={{ margin: '2px 0 0' }}>
            {review ? 'Published on the professional’s public profile.'
              : canReview ? `How was working with ${professionalName ?? 'the professional'}? Your review helps other buyers choose.`
                : 'The buyer can review this engagement now that it is complete.'}</p>
        </div>
        <span className="badge green review-verified"><Icon name="shield" /> Verified engagement{reference ? ` · ${reference}` : ''}</span>
      </div>
      <ErrorAlert error={error} />

      {!loaded ? <p className="muted small">Loading…</p> : review ? (
        <figure className="review-published">
          <div className="review-published-top"><Stars value={review.rating} size="lg" /><strong>{LABELS[review.rating]}</strong></div>
          <blockquote>{review.comment}</blockquote>
          <figcaption className="muted small">{review.reviewerName}, {review.organizationName}
            {review.createdAt && ` · ${new Date(review.createdAt).toLocaleDateString()}`}</figcaption>
        </figure>
      ) : canReview ? (
        <div className="review-form">
          <div className="review-fields">
            <div>
              <span className="field-label">Your rating</span>
              <div className="star-input" role="group" aria-label="Rating" onMouseLeave={() => setHover(0)}>
                {[1, 2, 3, 4, 5].map((n) => (
                  <button key={n} type="button" aria-pressed={rating === n} aria-label={`${n} star${n > 1 ? 's' : ''} – ${LABELS[n]}`}
                    className={n <= shown ? 'on' : ''} onMouseEnter={() => setHover(n)} onClick={() => setRating(n)}
                    onKeyDown={(e) => {
                      if (e.key === 'ArrowRight' || e.key === 'ArrowUp') { e.preventDefault(); setRating(Math.min(5, (rating || 0) + 1)) }
                      if (e.key === 'ArrowLeft' || e.key === 'ArrowDown') { e.preventDefault(); setRating(Math.max(1, (rating || 2) - 1)) }
                    }}>★</button>
                ))}
                <span className="star-label">{shown ? LABELS[shown] : 'Choose 1–5 stars'}</span>
              </div>
            </div>

            <div>
              <span className="field-label">What stood out? <span className="muted">(optional)</span></span>
              <div className="quick-chips">{HIGHLIGHTS.map((h) => (
                <button key={h} type="button" aria-pressed={tags.includes(h)} className={`chip pick ${tags.includes(h) ? 'on' : ''}`}
                  onClick={() => setTags(tags.includes(h) ? tags.filter((t) => t !== h) : [...tags, h])}>{h}</button>))}</div>
            </div>

            <label className="filter-box"><span className="field-label">Your review</span>
              <textarea rows={4} maxLength={MAX - 120} value={comment} onChange={(e) => setComment(e.target.value)}
                placeholder="What did they deliver, how did the work go, and would you recommend them?" /></label>
            <div className="review-count small">
              <span className={text.length >= MIN ? 'ok-text' : 'muted'}>{text.length >= MIN ? '✓ Long enough' : `At least ${MIN} characters`}</span>
              <span className="muted">{text.length} / {MAX}</span>
            </div>
          </div>

          <aside className="review-preview" aria-label="Preview">
            <span className="field-label">Preview · how others will see it</span>
            <figure className="review-published">
              <div className="review-published-top"><Stars value={rating} />{rating > 0 && <strong>{LABELS[rating]}</strong>}</div>
              <blockquote className={text ? '' : 'muted'}>{text || 'Your review will appear here.'}</blockquote>
              <figcaption className="muted small">You, {organizationName ?? 'your organisation'} · verified engagement</figcaption>
            </figure>
            <p className="muted small" style={{ margin: 0 }}><Icon name="lock" /> Your name and organisation are shown publicly.
              One review per completed engagement; it cannot be edited after publishing.</p>
          </aside>

          <div className="review-actions">
            {confirming ? <>
              <span className="small"><strong>Publish this review permanently?</strong> It cannot be changed afterwards.</span>
              <span className="row" style={{ flexWrap: 'nowrap' }}>
                <button type="button" className="btn btn-ghost" disabled={busy} onClick={() => setConfirming(false)}>Keep editing</button>
                <button type="button" className="btn btn-primary" disabled={busy} onClick={() => { void publish() }}>{busy ? 'Publishing…' : 'Yes, publish'}</button>
              </span>
            </> : <>
              <span className="muted small">{!rating ? 'Choose a rating to continue.' : text.length < MIN ? 'Add a few words about the engagement.' : 'Ready to publish.'}</span>
              <button type="button" className="btn btn-primary" disabled={!ready} onClick={() => setConfirming(true)}>Publish review</button>
            </>}
          </div>
        </div>
      ) : (
        <div className="review-empty"><Stars value={0} /><span className="muted small">No review yet.</span></div>
      )}
    </section>
  )
}
