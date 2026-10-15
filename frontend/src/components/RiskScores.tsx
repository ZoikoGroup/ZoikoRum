import { useEffect, useState } from 'react'
import { api } from '../api/client'
import { ErrorAlert } from './ui'

interface Risk { subjectType: 'IDENTITY' | 'ORGANIZATION'; subjectId: string; score: number; reviewAt: number; windowDays: number
  signals: { signal: string; label: string; count: number; points: number }[] }

/** Trust & Safety: risk scores from payment and behaviour signals. Advisory: a high score opens a case for a person. */
export function RiskScores() {
  const [rows, setRows] = useState<Risk[] | null>(null)
  const [error, setError] = useState<unknown>(null)
  useEffect(() => { api<Risk[]>('/v1/admin/risk').then(setRows).catch(setError) }, [])
  if (error) return <ErrorAlert error={error} />
  if (!rows) return null
  return (
    <section className="card panel">
      <div className="panel-head"><h2>Risk scores</h2><span className="muted small">last {rows[0]?.windowDays ?? 30} days</span></div>
      <p className="muted small">Weighted from failed payments, chargebacks, reversed funding, disputes, failed sign-ins, flagged messages and
        suspected duplicates. At {rows[0]?.reviewAt ?? 60} a review case opens below. Nothing is restricted by a score.</p>
      {rows.length === 0 ? <p className="muted small">No signals recorded.</p> : (
        <table className="data small"><thead><tr><th>Subject</th><th>Score</th><th>Signals</th></tr></thead>
          <tbody>{rows.map((r) => <tr key={`${r.subjectType}-${r.subjectId}`}>
            <td>{r.subjectType === 'ORGANIZATION' ? 'Organisation' : 'Person'} <code>{r.subjectId.slice(0, 8)}</code></td>
            <td><span className={`badge ${r.score >= r.reviewAt ? 'warn' : ''}`}>{r.score}</span></td>
            <td>{r.signals.map((s) => `${s.count} ${s.label} (${s.points})`).join(', ')}</td></tr>)}</tbody></table>)}
    </section>
  )
}
