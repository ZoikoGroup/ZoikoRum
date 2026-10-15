import { useEffect, useState } from 'react'
import { proApi, type Insights } from '../api/professional'
import { PortalHeader, StatCard } from '../components/portal'
import { ErrorAlert } from '../components/ui'

/** A professional's own performance from platform records. Only they see it. */
export default function PerformanceInsights() {
  const [data, setData] = useState<Insights | null>(null)
  const [error, setError] = useState<unknown>(null)
  useEffect(() => { proApi.insights().then(setData).catch(setError) }, [])
  return (
    <div className="page">
      <PortalHeader eyebrow="Professional" title="Performance insights"
        subtitle="How buyers experience working with you, from your records on Zoikorum. Only you can see this page." />
      <ErrorAlert error={error} />
      {!data && !error && <div className="card panel skeleton" style={{ height: 160 }} aria-busy="true" />}
      {data && <>
        <div className="stat-row">
          <StatCard icon="briefcase" tone="blue" value={data.completedEngagements} label="Completed engagements" />
          <StatCard icon="star" tone="amber" value={data.averageRating ?? '—'} label="Average rating" sub={`${data.reviewCount} reviews`} />
          <StatCard icon="clock" tone="teal" value={data.medianResponseHours != null ? `${data.medianResponseHours} h` : '—'} label="Median response time" />
          <StatCard icon="user" tone="violet" value={data.profileViews30d ?? 0} label="Profile views (30 days)" sub="by other people, once a day each" />
        </div>
        <section className="card panel">
          <table className="data">
            <thead><tr><th>Measure</th><th>Rate</th><th>Based on</th><th>How to improve</th></tr></thead>
            <tbody>{data.metrics.map((m) => <tr key={m.key}>
              <td><strong>{m.label}</strong>{m.lowerIsBetter && <div className="muted small">lower is better</div>}</td>
              <td>{m.value == null ? <span className="muted small">Not enough records yet</span> : <>
                <strong>{m.value}%</strong>
                <div className="progress" aria-hidden><span style={{ width: `${Math.min(100, m.value)}%` }} /></div></>}</td>
              <td className="small">{m.basis}</td>
              <td className="small muted">{m.hint}</td>
            </tr>)}</tbody>
          </table>
          <p className="muted small">A rate appears once it rests on at least {data.minimumSample} records. Updated {new Date(data.generatedAt).toLocaleString()}.</p>
        </section>
      </>}
    </div>
  )
}
