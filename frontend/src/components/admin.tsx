import { useEffect, useState, type KeyboardEvent, type ReactNode } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { Icon, type IconName, type Tone } from './dashboard'

/* Staff console building blocks (admin designs D01–D24): page header, KPI strip, panels, count tabs, filter bar,
   status pills, right-hand detail panel, readiness checklists and small SVG charts. Every figure passed in is live;
   these components never invent data. */

export function AdminHeader({ crumb, title, subtitle, actions, meta }: {
  crumb: string; title: string; subtitle?: ReactNode; actions?: ReactNode; meta?: ReactNode
}) {
  return (
    <header className="adm-head">
      <div className="adm-head-row">
        <div>
          <div className="adm-crumb">{crumb}</div>
          <h1>{title}</h1>
          {subtitle && <p className="muted adm-sub">{subtitle}</p>}
        </div>
        {actions && <div className="adm-actions">{actions}</div>}
      </div>
      {meta && <div className="adm-meta">{meta}</div>}
    </header>
  )
}

export function AdminKpi({ icon, tone, label, value, sub, to }: { icon: IconName; tone: Tone; label: string; value: ReactNode; sub?: ReactNode; to?: string }) {
  const body = (
    <div className="card adm-kpi">
      <div className="adm-kpi-top"><span className={`kpi-icon ${tone}`}><Icon name={icon} /></span><span className="label">{label}</span></div>
      <div className="value">{value}</div>
      {sub && <div className="sub">{sub}</div>}
    </div>
  )
  return to ? <Link to={to} className="adm-kpi-link">{body}</Link> : body
}

export function KpiStrip({ children }: { children: ReactNode }) {
  return <div className="adm-kpis">{children}</div>
}

export function Panel({ title, meta, action, children, className }: { title: ReactNode; meta?: ReactNode; action?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={`card adm-panel ${className ?? ''}`}>
      <div className="adm-panel-head"><h2>{title}</h2>{meta && <span className="muted small">{meta}</span>}{action && <span className="adm-panel-action">{action}</span>}</div>
      {children}
    </section>
  )
}

/** Three panels side by side (stacks on narrow screens). */
export function PanelRow({ children, cols = 3 }: { children: ReactNode; cols?: 2 | 3 }) {
  return <div className={`adm-row cols-${cols}`}>{children}</div>
}

export function CountTabs<T extends string>({ tabs, value, onChange }: { tabs: { key: T; label: string; count?: number | null }[]; value: T; onChange: (t: T) => void }) {
  return (
    <div className="adm-tabs" role="tablist">
      {tabs.map((t) => (
        <button key={t.key} type="button" role="tab" aria-selected={t.key === value} onClick={() => onChange(t.key)}>
          {t.label}{t.count != null && <span className="adm-tab-count">{t.count}</span>}
        </button>
      ))}
    </div>
  )
}

export function FilterBar({ search, onSearch, placeholder, children }: { search?: string; onSearch?: (v: string) => void; placeholder?: string; children?: ReactNode }) {
  return (
    <div className="adm-filters">
      {onSearch && <label className="adm-search"><Icon name="search" />
        <input type="search" value={search ?? ''} onChange={(e) => onSearch(e.target.value)} placeholder={placeholder ?? 'Search…'} aria-label="Search" /></label>}
      {children}
    </div>
  )
}

/** A select used as a filter chip. */
export function FilterSelect({ label, value, onChange, options }: { label: string; value: string; onChange: (v: string) => void; options: [string, string][] }) {
  return (
    <select className="adm-filter" aria-label={label} value={value} onChange={(e) => onChange(e.target.value)}>
      <option value="">{label}</option>
      {options.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
    </select>
  )
}

export type PillTone = 'green' | 'amber' | 'red' | 'blue' | 'violet' | 'grey'
export function Pill({ tone = 'grey', children }: { tone?: PillTone; children: ReactNode }) {
  return <span className={`adm-pill ${tone}`}>{children}</span>
}

/** Map a raw status word to a pill colour. Unknown words are grey. */
export function toneFor(status: string | null | undefined): PillTone {
  const s = (status ?? '').toUpperCase()
  if (/(FAIL|REJECT|DECLIN|BLOCK|ESCALAT|OVERDUE|CRITICAL|SEV1|HIGH|MISMATCH|SUSPEND|RESTRICT|DISPUT|FROZEN|DENIED|LOST)/.test(s)) return 'red'
  if (/(PENDING|REVIEW|EVIDENCE|WAIT|DRAFT|OPEN|TRIAGE|INTAKE|MEDIUM|SEV2|RETRY|PAUSED|HELD|NEW|REQUESTED)/.test(s)) return 'amber'
  if (/(MEDIAT|INVESTIGAT|ASSESS|PROGRESS|CONTAIN|SIGNATURE|FUNDING|SEV3|MONITOR)/.test(s)) return 'blue'
  if (/(APPROV|VERIFIED|ACTIVE|PASS|MATCH|RELEASED|RESOLVED|CLOSED|COMPLETE|PUBLISHED|OPERATIONAL|ON|LOW|OK|FUNDED|SETTLED|ELIGIBLE|CLEAR)/.test(s)) return 'green'
  return 'grey'
}

export const label = (s: string | null | undefined) => (s ?? '').toLowerCase().replace(/_/g, ' ').replace(/^\w/, (c) => c.toUpperCase())

export function StatusPill({ status }: { status: string | null | undefined }) {
  return <Pill tone={toneFor(status)}>{label(status) || '—'}</Pill>
}

/** Spread on a clickable table row so it can also be selected from the keyboard (Enter or Space). */
export const pickRow = {
  tabIndex: 0,
  onKeyDown: (e: KeyboardEvent<HTMLTableRowElement>) => {
    if (e.target === e.currentTarget && (e.key === 'Enter' || e.key === ' ')) { e.preventDefault(); e.currentTarget.click() }
  },
}

/** List + right-hand detail layout. */
export function ListDetail({ list, detail }: { list: ReactNode; detail?: ReactNode }) {
  return <div className={`adm-split ${detail ? '' : 'solo'}`}><div className="adm-list">{list}</div>{detail && <aside className="adm-detail-col">{detail}</aside>}</div>
}

export function DetailPanel({ title, subtitle, badge, onClose, tabs, children, footer }: {
  title: ReactNode; subtitle?: ReactNode; badge?: ReactNode; onClose?: () => void
  tabs?: { tabs: string[]; value: string; onChange: (t: string) => void }; children: ReactNode; footer?: ReactNode
}) {
  return (
    <section className="card adm-detail">
      <div className="adm-detail-head">
        <div style={{ minWidth: 0 }}><h2>{title}</h2>{subtitle && <div className="muted small">{subtitle}</div>}</div>
        {badge}
        {onClose && <button type="button" className="adm-x" aria-label="Close details" onClick={onClose}>×</button>}
      </div>
      {tabs && <div className="adm-detail-tabs" role="tablist">{tabs.tabs.map((t) => (
        <button key={t} type="button" role="tab" aria-selected={t === tabs.value} onClick={() => tabs.onChange(t)}>{t}</button>))}</div>}
      <div className="adm-detail-body">{children}</div>
      {footer && <div className="adm-detail-foot">{footer}</div>}
    </section>
  )
}

export function Callout({ tone = 'amber', title, children }: { tone?: 'amber' | 'green' | 'blue' | 'red'; title: ReactNode; children?: ReactNode }) {
  return <div className={`adm-callout ${tone}`}><strong>{title}</strong>{children && <div>{children}</div>}</div>
}

export function Facts({ title, rows }: { title?: string; rows: [ReactNode, ReactNode][] }) {
  return (
    <div className="adm-facts">
      {title && <h3>{title}</h3>}
      <dl>{rows.map(([k, v], i) => <div key={i}><dt>{k}</dt><dd>{v ?? '—'}</dd></div>)}</dl>
    </div>
  )
}

export type CheckState = 'done' | 'pending' | 'missing'
export function Checklist({ title, items }: { title?: string; items: { label: ReactNode; state: CheckState; note?: ReactNode }[] }) {
  const done = items.filter((i) => i.state === 'done').length
  return (
    <div className="adm-checks">
      {title && <h3>{title} <span className="muted small">· {done} of {items.length}</span></h3>}
      {items.length > 0 && <Progress value={done} max={items.length} />}
      <ul>{items.map((i, n) => (
        <li key={n}><span className={`adm-check ${i.state}`} aria-hidden>{i.state === 'done' ? '✓' : '!'}</span><span className="grow">{i.label}</span>
          {i.note && <Pill tone={i.state === 'done' ? 'green' : i.state === 'missing' ? 'red' : 'amber'}>{i.note}</Pill>}</li>))}</ul>
    </div>
  )
}

export function Progress({ value, max, tone = 'green' }: { value: number; max: number; tone?: 'green' | 'amber' | 'red' | 'blue' }) {
  const pct = max > 0 ? Math.min(100, Math.round((value / max) * 100)) : 0
  return <div className={`adm-progress ${tone}`} role="progressbar" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100}><span style={{ width: `${pct}%` }} /></div>
}

/** Label / value rows inside a panel (e.g. "Open disputes ........ 2"). */
export function MetricList({ rows }: { rows: { label: ReactNode; value: ReactNode; tone?: PillTone; to?: string }[] }) {
  return (
    <ul className="adm-metrics">{rows.map((r, i) => (
      <li key={i}><span>{r.to ? <Link to={r.to}>{r.label}</Link> : r.label}</span><strong className={r.tone ? `tone-${r.tone}` : ''}>{r.value}</strong></li>))}</ul>
  )
}

export function TableFoot({ shown, total, noun, page, pages, onPage, onMore, loadingMore }: { shown: number; total?: number | null; noun: string; page?: number; pages?: number; onPage?: (p: number) => void
  onMore?: () => void; loadingMore?: boolean }) {
  return (
    <div className="adm-tfoot">
      <span className="muted small">Showing {shown}{total != null ? ` of ${total}` : ''} {noun}</span>
      {onPage && pages && pages > 1 && <span className="adm-pager">
        <button type="button" disabled={!page || page <= 1} onClick={() => onPage((page ?? 1) - 1)} aria-label="Previous page">‹</button>
        <span>{page} / {pages}</span>
        <button type="button" disabled={(page ?? 1) >= pages} onClick={() => onPage((page ?? 1) + 1)} aria-label="Next page">›</button></span>}
      {onMore && <button type="button" className="btn btn-secondary btn-sm" disabled={loadingMore} onClick={onMore}>{loadingMore ? 'Loading…' : 'Load more'}</button>}
    </div>
  )
}

export function Initials({ name }: { name: string | null | undefined }) {
  const t = (name ?? '?').split(/[\s.@]+/).filter(Boolean).map((w) => w[0]).slice(0, 2).join('').toUpperCase()
  return <span className="adm-initials" aria-hidden>{t || '?'}</span>
}

/* ---------- charts (plain SVG, no library) ---------- */

export const CHART_COLORS = ['#2f80ed', '#12b76a', '#9b8afb', '#f79009', '#0e9384', '#f04438', '#667085']

export interface Series { label: string; values: number[]; color?: string }

function niceMax(v: number) {
  if (v <= 0) return 1
  const p = 10 ** Math.floor(Math.log10(v))
  return Math.ceil(v / p) * p
}

function Legend({ items }: { items: { label: string; color: string; value?: ReactNode }[] }) {
  return <ul className="adm-legend">{items.map((i) => <li key={i.label}><span style={{ background: i.color }} />{i.label}{i.value != null && <strong>{i.value}</strong>}</li>)}</ul>
}

/** Grouped bars (kind="bar") or lines (kind="line") over shared x labels. */
export function TrendChart({ labels, series, kind = 'line', height = 180 }: { labels: string[]; series: Series[]; kind?: 'line' | 'bar'; height?: number }) {
  const W = 560, H = height, L = 34, B = 22, T = 8
  const max = niceMax(Math.max(0, ...series.flatMap((s) => s.values)))
  const n = Math.max(1, labels.length)
  const x = (i: number) => L + ((W - L - 8) * (kind === 'bar' ? i + 0.5 : i)) / (kind === 'bar' ? n : Math.max(1, n - 1))
  const y = (v: number) => T + (H - T - B) * (1 - v / max)
  const colored = series.map((s, i) => ({ ...s, color: s.color ?? CHART_COLORS[i % CHART_COLORS.length] }))
  const step = Math.max(1, Math.ceil(n / 6))
  if (labels.length === 0) return <p className="muted small">No data in this period.</p>
  return (
    <div className="adm-chart">
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={series.map((s) => s.label).join(', ')} preserveAspectRatio="none">
        {[0, 0.25, 0.5, 0.75, 1].map((f) => (
          <g key={f}><line x1={L} x2={W - 4} y1={y(max * f)} y2={y(max * f)} className="grid" />
            <text x={L - 6} y={y(max * f) + 4} textAnchor="end" className="tick">{Math.round(max * f)}</text></g>))}
        {kind === 'bar' ? colored.map((s, si) => s.values.map((v, i) => {
          const bw = Math.max(2, ((W - L - 8) / n) * 0.7 / colored.length)
          const bx = x(i) - (bw * colored.length) / 2 + si * bw
          return <rect key={`${si}-${i}`} x={bx} y={y(v)} width={bw - 1} height={Math.max(0, y(0) - y(v))} fill={s.color} rx={1.5}><title>{`${labels[i]} · ${s.label}: ${v}`}</title></rect>
        })) : colored.map((s) => (
          <g key={s.label}>
            <polyline fill="none" stroke={s.color} strokeWidth={2} points={s.values.map((v, i) => `${x(i)},${y(v)}`).join(' ')} />
            {s.values.map((v, i) => <circle key={i} cx={x(i)} cy={y(v)} r={2.6} fill={s.color}><title>{`${labels[i]} · ${s.label}: ${v}`}</title></circle>)}
          </g>))}
        {labels.map((l, i) => (i % step === 0 || i === n - 1) && <text key={i} x={x(i)} y={H - 6} textAnchor="middle" className="tick">{l}</text>)}
      </svg>
      <Legend items={colored.map((s) => ({ label: s.label, color: s.color }))} />
    </div>
  )
}

/** Donut with a centre figure and a legend that shows each value and share. */
export function Donut({ segments, center, caption, format = (v) => String(v) }: { segments: { label: string; value: number; color?: string }[]; center: ReactNode; caption?: string
  format?: (v: number) => string }) {
  const total = segments.reduce((s, x) => s + x.value, 0)
  const R = 54, C = 2 * Math.PI * R
  let offset = 0
  const segs = segments.map((s, i) => ({ ...s, color: s.color ?? CHART_COLORS[i % CHART_COLORS.length] }))
  return (
    <div className="adm-donut">
      <div className="adm-donut-ring">
        <svg viewBox="0 0 140 140" role="img" aria-label={caption ?? 'Distribution'}>
          <circle cx="70" cy="70" r={R} fill="none" stroke="#eef2f6" strokeWidth="18" />
          {total > 0 && segs.map((s) => {
            const len = (s.value / total) * C
            const el = <circle key={s.label} cx="70" cy="70" r={R} fill="none" stroke={s.color} strokeWidth="18" strokeDasharray={`${len} ${C - len}`}
              strokeDashoffset={-offset} transform="rotate(-90 70 70)"><title>{`${s.label}: ${s.value}`}</title></circle>
            offset += len
            return el
          })}
        </svg>
        <div className="adm-donut-center"><strong>{center}</strong>{caption && <span>{caption}</span>}</div>
      </div>
      <Legend items={segs.map((s) => ({ label: s.label, color: s.color, value: `${format(s.value)}${total ? ` (${Math.round((s.value / total) * 100)}%)` : ''}` }))} />
    </div>
  )
}

/** Horizontal bars, one per row, scaled to the largest. */
export function HBars({ rows, format = (v) => String(v) }: { rows: { label: string; value: number; color?: string }[]; format?: (v: number) => string }) {
  const max = Math.max(1, ...rows.map((r) => r.value))
  if (rows.length === 0) return <p className="muted small">Nothing to show yet.</p>
  return (
    <ul className="adm-hbars">{rows.map((r, i) => (
      <li key={r.label}><span className="lbl">{r.label}</span>
        <span className="bar"><span style={{ width: `${(r.value / max) * 100}%`, background: r.color ?? CHART_COLORS[i % CHART_COLORS.length] }} /></span>
        <strong>{format(r.value)}</strong></li>))}</ul>
  )
}

/** One stacked bar showing how a whole splits into parts, with a legend. */
export function StackBar({ segments }: { segments: { label: string; value: number; color?: string }[] }) {
  const total = segments.reduce((s, x) => s + x.value, 0)
  const segs = segments.map((s, i) => ({ ...s, color: s.color ?? CHART_COLORS[i % CHART_COLORS.length] }))
  return (
    <div className="adm-stack">
      <div className="adm-stack-bar">{total > 0 ? segs.filter((s) => s.value > 0).map((s) => (
        <span key={s.label} style={{ flex: s.value, background: s.color }} title={`${s.label}: ${s.value}`} />)) : <span style={{ flex: 1, background: '#eef2f6' }} />}</div>
      <Legend items={segs.map((s) => ({ label: s.label, color: s.color, value: s.value }))} />
    </div>
  )
}

/** Local selection helper for list + detail pages. */
export function useSelection<T extends { id: string }>(rows: T[] | null) {
  const [id, setId] = useState<string | null>(null)
  const selected = rows?.find((r) => r.id === id) ?? null
  return { selected, select: (r: T | null) => setId(r?.id ?? null), selectedId: id, selectId: setId }
}

/** Open the record named in ?selected= (staff search results link here), also when already on the page. */
export function useSelectedParam(apply: (id: string) => void) {
  const [params] = useSearchParams()
  const id = params.get('selected')
  useEffect(() => { if (id) apply(id) }, [id])  // eslint-disable-line react-hooks/exhaustive-deps
}

/** Short date and relative-age helpers used across the console. */
export const shortDate = (d: string | null | undefined) => (d ? new Date(d).toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' }) : '—')
export const shortDateTime = (d: string | null | undefined) => (d ? new Date(d).toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }) : '—')
export function dueText(d: string | null | undefined): { text: string; late: boolean } {
  if (!d) return { text: '—', late: false }
  const days = Math.round((new Date(d).getTime() - Date.now()) / 86_400_000)
  if (days < 0) return { text: `${-days} day${days === -1 ? '' : 's'} overdue`, late: true }
  if (days === 0) return { text: 'Due today', late: true }
  return { text: `${days} day${days === 1 ? '' : 's'} left`, late: false }
}
export const money = (minor: number | null | undefined, currency = 'USD') =>
  minor == null ? '—' : new Intl.NumberFormat(undefined, { style: 'currency', currency, maximumFractionDigits: 0 }).format(minor / 100)
