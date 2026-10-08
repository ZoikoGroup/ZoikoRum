import { useEffect, useState } from 'react'
import { api } from '../api/client'
import { ErrorAlert } from './ui'

interface Reviews { reviewCount: number; averageRating: number | null; items: { id: string; rating: number; comment: string; reviewerName: string; organizationName: string; engagementReference: string; createdAt: string }[] }
export function PublicReviews({ professionalId }: { professionalId: string }) {
  const [data, setData] = useState<Reviews | null>(null), [error, setError] = useState<unknown>(null), [offset, setOffset] = useState(0)
  useEffect(() => { api<Reviews>(`/v1/professionals/${professionalId}/reviews`, { auth: false, query: { offset: String(offset) } }).then(setData).catch(setError) }, [professionalId, offset])
  return <section className="card panel"><h2>Verified engagement reviews</h2><ErrorAlert error={error} />{data && <><p>{data.reviewCount ? `${data.averageRating}/5 from ${data.reviewCount} completed engagements` : 'No verified reviews yet.'}</p>{data.items.map(r => <article key={r.id}><strong>{r.rating}/5 · {r.reviewerName}, {r.organizationName}</strong><p>{r.comment}</p><p className="muted small">{r.engagementReference} · {new Date(r.createdAt).toLocaleDateString()}</p></article>)}<button className="btn" disabled={!offset} onClick={() => setOffset(n => Math.max(0, n - 20))}>Previous</button><button className="btn" disabled={offset + data.items.length >= data.reviewCount} onClick={() => setOffset(n => n + 20)}>Next</button></>}</section>
}
