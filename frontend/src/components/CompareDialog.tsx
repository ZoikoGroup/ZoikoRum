import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { formatMoney } from '../api/orgs'
import { LABEL } from '../api/professional'
import { savedApi, type CompareItem } from '../api/saved'
import { DIMENSION_VALUE, DIMENSIONS } from '../api/verification'
import { Avatar } from './dashboard'
import { TierBadge } from './portal'
import { ErrorAlert } from './ui'

/** Side-by-side comparison of up to 3 professionals (Professional Profile doc: compare max 3). */
export function CompareDialog({ ids, onClose }: { ids: string[]; onClose: () => void }) {
  const [items, setItems] = useState<CompareItem[] | null>(null)
  const [error, setError] = useState<unknown>(null)
  useEffect(() => { savedApi.compare(ids).then(setItems).catch(setError) }, [ids])

  const rows: { label: string; render: (c: CompareItem) => React.ReactNode }[] = [
    { label: 'Trust Tier', render: (c) => <TierBadge tier={c.tier} /> },
    ...DIMENSIONS.map((d) => ({
      label: d.label,
      render: (c: CompareItem) => {
        const v = DIMENSION_VALUE[c.dimensions[d.key]] ?? { label: 'Not verified', good: false }
        return <span className={`badge ${v.good ? 'green' : ''}`}>{v.label}</span>
      },
    })),
    { label: 'Validated credentials', render: (c) => c.verifiedCredentials.join(', ') || '—' },
    { label: 'Specializations', render: (c) => c.specializations.join(', ') || '—' },
    { label: 'Experience', render: (c) => (c.yearsExperienceBand ? `${c.yearsExperienceBand} years` : '—') },
    { label: 'Engagement types', render: (c) => c.engagementTypes.map((t) => LABEL[t] ?? t).join(', ') || '—' },
    { label: 'Delivery', render: (c) => c.deliveryModes.map((t) => LABEL[t] ?? t).join(', ') || '—' },
    { label: 'Pricing', render: (c) => (c.startingPrice ? `From ${formatMoney(c.startingPrice)}` : c.pricingModels.map((t) => LABEL[t] ?? t).join(', ') || '—') },
    { label: 'Availability', render: (c) => LABEL[c.availability] ?? c.availability },
    { label: 'Serves', render: (c) => c.servedJurisdictions.join(', ') || '—' },
    { label: 'Languages', render: (c) => c.languages.join(', ') || '—' },
  ]

  return (
    <div className="modal-backdrop" role="dialog" aria-modal="true" aria-labelledby="compare-title" onClick={onClose}>
      <div className="card modal compare-modal" onClick={(e) => e.stopPropagation()}>
        <div className="panel-head"><h2 id="compare-title">Compare professionals</h2>
          <button className="icon-btn" aria-label="Close" onClick={onClose}>×</button></div>
        <ErrorAlert error={error} />
        {!items ? <p className="muted">Loading…</p> : (
          <div className="compare-scroll">
            <table className="data compare-table">
              <thead><tr><th />{items.map((c) => (
                <th key={c.professionalId}>
                  <div className="name-row"><Avatar name={c.displayName} photoUrl={c.photoUrl} size={40} />
                    <div><Link to={`/professionals/${c.professionalId}`}>{c.displayName}</Link>
                      <div className="muted small" style={{ textTransform: 'none', letterSpacing: 0 }}>{c.headline}</div></div></div>
                </th>))}</tr></thead>
              <tbody>{rows.map((r) => (
                <tr key={r.label}><th scope="row">{r.label}</th>{items.map((c) => <td key={c.professionalId}>{r.render(c)}</td>)}</tr>
              ))}</tbody>
            </table>
          </div>
        )}
        <div className="row" style={{ marginTop: 12, alignItems: 'center' }}>
          <p className="muted small" style={{ margin: 0, flex: 1 }}>Checks are made by a verification provider or a compliance reviewer — never by AI.</p>
          {items && items.length > 0 && <Link className="btn btn-primary" to={`/app/requests/new?${items.map((c) => `pro=${c.professionalId}`).join('&')}`}>
            Request proposal{items.length > 1 ? 's from these' : ''}</Link>}
        </div>
      </div>
    </div>
  )
}

/** Bottom tray: selected professionals + Compare (max 3). */
export function CompareTray({ selected, names, onRemove, onCompare, extra }: {
  selected: string[]; names: Record<string, { name: string; photoUrl: string | null }>; onRemove: (id: string) => void
  onCompare: () => void; extra?: React.ReactNode
}) {
  if (selected.length === 0) return null
  return (
    <div className="compare-tray">
      <div><strong>{selected.length} professional{selected.length > 1 ? 's' : ''} selected</strong>
        <div className="small">Compare up to 3 side by side</div></div>
      <div className="tray-people">
        {selected.map((id) => (
          <span key={id} className="tray-person" title={names[id]?.name}>
            <Avatar name={names[id]?.name ?? '?'} photoUrl={names[id]?.photoUrl} size={40} />
            <button aria-label={`Remove ${names[id]?.name}`} onClick={() => onRemove(id)}>×</button>
          </span>
        ))}
      </div>
      <div className="row" style={{ marginLeft: 'auto' }}>
        {extra}
        <button className="btn btn-primary" onClick={onCompare}>Compare selected</button>
      </div>
    </div>
  )
}
