import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { DIMENSION_VALUE } from '../api/verification'
import { Icon, type IconName, type Tone } from './dashboard'

/* Customer-portal building blocks (management designs): page header, stat cards, tabs, empty tables,
   verification chips. Shared by every portal screen so they look and behave the same. */

export function PortalHeader({ eyebrow, title, subtitle, actions }: { eyebrow?: ReactNode; title: ReactNode; subtitle?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="portal-head">
      <div>
        {eyebrow && <div className="eyebrow">{eyebrow}</div>}
        <h1>{title}</h1>
        {subtitle && <p className="muted" style={{ margin: 0 }}>{subtitle}</p>}
      </div>
      {actions && <div className="row">{actions}</div>}
    </div>
  )
}

export function StatCard({ icon, tone, value, label, sub, to }: {
  icon: IconName; tone: Tone; value: ReactNode; label: string; sub?: ReactNode; to?: string
}) {
  const body = (
    <div className="card stat-card">
      <span className={`kpi-icon ${tone}`}><Icon name={icon} /></span>
      <div style={{ minWidth: 0 }}>
        <div className="label">{label}</div>
        <div className="value">{value}</div>
        {sub && <div className="sub">{sub}</div>}
      </div>
      {to && <span className="chev" aria-hidden>›</span>}
    </div>
  )
  return to ? (to.startsWith('#') ? <a href={to} className="stat-link">{body}</a> : <Link to={to} className="stat-link">{body}</Link>) : body
}

export function Tabs<T extends string>({ tabs, value, onChange }: { tabs: { key: T; label: string; count?: number }[]; value: T; onChange: (t: T) => void }) {
  return (
    <div className="portal-tabs" role="tablist">
      {tabs.map((t) => (
        <button key={t.key} type="button" role="tab" aria-selected={t.key === value} onClick={() => onChange(t.key)}>
          {t.label}{t.count !== undefined && ` (${t.count})`}
        </button>
      ))}
    </div>
  )
}

/** A table that shows its column headings even when empty, with a message saying what will appear. */
export function EmptyTable({ columns, children }: { columns: string[]; children: ReactNode }) {
  return (
    <table className="data">
      <thead><tr>{columns.map((c) => <th key={c}>{c}</th>)}</tr></thead>
      <tbody><tr><td colSpan={columns.length} className="empty-row">{children}</td></tr></tbody>
    </table>
  )
}

const CHIPS: { key: string; label: string }[] = [
  { key: 'identity', label: 'Identity' }, { key: 'credentials', label: 'Credentials' }, { key: 'jurisdiction', label: 'Eligibility' },
]

/** Identity / Credentials / Eligibility status chips (public view). */
export function VerifyChips({ dimensions, compact }: { dimensions: Record<string, string>; compact?: boolean }) {
  return (
    <div className={`verify-chips ${compact ? 'compact' : ''}`}>
      {CHIPS.map((c) => {
        const v = DIMENSION_VALUE[dimensions[c.key]] ?? { label: 'Not verified', good: false }
        return (
          <span key={c.key} className={`vchip ${v.good ? 'ok' : ''}`} title={`${c.label}: ${v.label}`}>
            <span aria-hidden>{v.good ? '✓' : '○'}</span>{c.label} <em>{v.label}</em>
          </span>
        )
      })}
    </div>
  )
}

export function TierBadge({ tier }: { tier: string }) {
  const label = { A: 'Fully Verified', B: 'Verified Identity', C: 'Unverified' }[tier] ?? ''
  return <span className={`badge ${tier === 'C' ? 'warn' : 'green'}`}>Tier {tier} · {label}</span>
}

/** Side panel shown on list pages (management designs: right-hand detail / help column). */
export function SidePanel({ title, children, action }: { title: string; children: ReactNode; action?: ReactNode }) {
  return (
    <section className="card panel">
      <div className="panel-head"><h2>{title}</h2>{action}</div>
      {children}
    </section>
  )
}
