import { useCallback, useEffect, useMemo, useState, type FormEvent } from 'react'
import { Link } from 'react-router-dom'
import { formatMoney } from '../../api/orgs'
import { LABEL } from '../../api/professional'
import { savedApi, type Collection, type SavedProfessional } from '../../api/saved'
import { CompareDialog } from '../../components/CompareDialog'
import { Avatar, Icon } from '../../components/dashboard'
import { PortalHeader, SidePanel, StatCard, Tabs, TierBadge, VerifyChips } from '../../components/portal'
import { SavedSearchesPanel } from '../../components/SavedSearches'
import { ErrorAlert } from '../../components/ui'
import { countryName } from '../ProfessionalPages'

const MAX_COMPARE = 3
type Tab = 'all' | 'loose' | 'unavailable'

/** Saved Professionals (management design 3): shortlist, collections and side-by-side comparison. */
export default function SavedProfessionals() {
  const [items, setItems] = useState<SavedProfessional[] | null>(null)
  const [collections, setCollections] = useState<Collection[]>([])
  const [selected, setSelected] = useState<string[]>([])
  const [tab, setTab] = useState<Tab>('all')
  const [collectionFilter, setCollectionFilter] = useState('')
  const [text, setText] = useState('')
  const [availability, setAvailability] = useState('')
  const [sort, setSort] = useState('recent')
  const [newName, setNewName] = useState('')
  const [comparing, setComparing] = useState(false)
  const [notice, setNotice] = useState<string | null>(null)
  const [error, setError] = useState<unknown>(null)

  const load = useCallback(async () => {
    try {
      const [s, c] = await Promise.all([savedApi.list(), savedApi.collections()])
      setItems(s)
      setCollections(c)
    } catch (err) {
      setError(err)
    }
  }, [])
  useEffect(() => { load() }, [load])

  async function act(action: () => Promise<unknown>, message?: string) {
    setError(null)
    try {
      await action()
      if (message) setNotice(message)
      await load()
    } catch (err) {
      setError(err)
    }
  }
  function toggle(id: string) {
    setSelected((s) => (s.includes(id) ? s.filter((x) => x !== id) : [...s, id]))
  }
  function createCollection(e: FormEvent) {
    e.preventDefault()
    if (!newName.trim()) return
    act(() => savedApi.createCollection(newName.trim()), `Collection “${newName.trim()}” created.`).then(() => setNewName(''))
  }

  const list = useMemo(() => {
    let l = items ?? []
    if (tab === 'loose') l = l.filter((s) => s.collectionIds.length === 0)
    if (tab === 'unavailable') l = l.filter((s) => !s.available)
    if (collectionFilter) l = l.filter((s) => s.collectionIds.includes(collectionFilter))
    if (availability) l = l.filter((s) => s.availability === availability)
    if (text.trim()) {
      const t = text.trim().toLowerCase()
      l = l.filter((s) => [s.displayName, s.headline, ...s.specializations].some((v) => v?.toLowerCase().includes(t)))
    }
    const tierRank = { A: 0, B: 1, C: 2 }
    return [...l].sort((a, b) => sort === 'name' ? a.displayName.localeCompare(b.displayName)
      : sort === 'tier' ? tierRank[a.tier] - tierRank[b.tier] : b.savedAt.localeCompare(a.savedAt))
  }, [items, tab, collectionFilter, availability, text, sort])

  const byId = Object.fromEntries((items ?? []).map((s) => [s.professionalId, s]))
  const inCollections = (items ?? []).filter((s) => s.collectionIds.length > 0).length
  const compareIds = selected.slice(0, MAX_COMPARE)

  return (
    <>
      <PortalHeader eyebrow="Saved professionals" title="Your saved professionals"
        subtitle="Organise, compare and invite verified professionals for current or future engagements."
        actions={<>
          <Link className="btn btn-primary" to="/app/find"><Icon name="search" /> Find Professionals</Link>
          <Link className="btn btn-secondary" to="/app/requests/new"><Icon name="request" /> Create a Request</Link>
        </>} />
      <ErrorAlert error={error} />
      {notice && <div className="alert alert-success" role="status">{notice}</div>}

      <div className="stat-row three">
        <StatCard icon="bookmark" tone="green" value={items?.length ?? '—'} label="Saved professionals" sub="Professionals in your shortlist" />
        <StatCard icon="team" tone="blue" value={inCollections} label="In collections" sub={`Across ${collections.length} collection${collections.length === 1 ? '' : 's'}`} />
        <StatCard icon="compare" tone="violet" value={compareIds.length} label="Comparing" sub="Selected for comparison (max 3)" />
      </div>

      <div className="home-grid wide">
        <section className="card panel">
          <Tabs<Tab> tabs={[
            { key: 'all', label: 'All saved', count: items?.length ?? 0 },
            { key: 'loose', label: 'Not in a collection', count: (items ?? []).filter((s) => s.collectionIds.length === 0).length },
            { key: 'unavailable', label: 'No longer listed', count: (items ?? []).filter((s) => !s.available).length },
          ]} value={tab} onChange={setTab} />
          <div className="filter-row compact">
            <label className="filter-box grow"><span>Search</span>
              <input value={text} onChange={(e) => setText(e.target.value)} placeholder="Name, title or expertise" /></label>
            <label className="filter-box"><span>Collection</span>
              <select value={collectionFilter} onChange={(e) => setCollectionFilter(e.target.value)}>
                <option value="">All</option>{collections.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
              </select></label>
            <label className="filter-box"><span>Availability</span>
              <select value={availability} onChange={(e) => setAvailability(e.target.value)}>
                <option value="">Any time</option>
                {['NOW', 'TWO_WEEKS', 'ONE_MONTH', 'AT_CAPACITY'].map((a) => <option key={a} value={a}>{LABEL[a]}</option>)}
              </select></label>
            <label className="filter-box"><span>Sort by</span>
              <select value={sort} onChange={(e) => setSort(e.target.value)}>
                <option value="recent">Recently added</option><option value="name">Name</option><option value="tier">Trust Tier</option>
              </select></label>
          </div>

          {items === null ? <p className="muted">Loading…</p> : list.length === 0 ? (
            <p className="muted" style={{ margin: '12px 0 0' }}>
              {items.length === 0 ? <>Nothing saved yet. <Link to="/app/find">Find professionals</Link> and use Save to build your shortlist.</> : 'No saved professionals match these filters.'}
            </p>
          ) : list.map((s) => (
            <article key={s.professionalId} className={`pro-row saved ${selected.includes(s.professionalId) ? 'selected' : ''}`}>
              <input type="checkbox" aria-label={`Select ${s.displayName}`} checked={selected.includes(s.professionalId)} onChange={() => toggle(s.professionalId)} />
              <Avatar name={s.displayName} photoUrl={s.photoUrl} size={60} />
              <div className="pro-main">
                <div className="name-line">
                  {s.available ? <Link to={`/professionals/${s.professionalId}`}><strong>{s.displayName}</strong></Link> : <strong>{s.displayName}</strong>}
                  {!s.available && <span className="badge warn">No longer listed</span>}
                </div>
                {s.headline && <div className="small">{s.headline}</div>}
                <div className="muted small"><Icon name="globe" /> {[s.city, s.country && countryName(s.country)].filter(Boolean).join(', ')}</div>
              </div>
              <div className="verify-box">
                <div className="small"><strong>Verification &amp; eligibility</strong> <TierBadge tier={s.tier} /></div>
                <VerifyChips dimensions={s.dimensions} compact />
                {s.lastVerifiedAt && <div className="muted small">Last checked {new Date(s.lastVerifiedAt).toLocaleDateString()}</div>}
              </div>
              <div className="pro-expertise">
                <div className="muted small">Key expertise</div>
                <div className="chips">{s.specializations.slice(0, 3).map((x) => <span key={x} className="chip">{x}</span>)}</div>
                <div className="muted small">
                  {s.yearsExperienceBand && <>{s.yearsExperienceBand} years · </>}{s.languages.join(', ')}{s.languages.length > 0 && ' · '}
                  <span className={s.availability === 'AT_CAPACITY' ? '' : 'ok-text'}>{LABEL[s.availability] ?? s.availability}</span>
                </div>
              </div>
              <div className="pro-cta">
                <div className="muted small">Engagement model</div>
                <div className="small">{s.pricingModels.map((p) => LABEL[p] ?? p).join(' or ') || '—'}</div>
                <div className="price">{s.startingPrice ? <>From <strong>{formatMoney(s.startingPrice)}</strong></> : ''}</div>
                <div className="row">
                  {s.available && <Link className="btn btn-primary btn-sm" to={`/professionals/${s.professionalId}`}>View profile</Link>}
                  <details className="more-menu">
                    <summary aria-label={`More actions for ${s.displayName}`}>⋮</summary>
                    <div className="menu card">
                      {collections.map((c) => s.collectionIds.includes(c.id) ? (
                        <button key={c.id} onClick={() => act(() => savedApi.removeFromCollection(c.id, s.professionalId))}>Remove from “{c.name}”</button>
                      ) : (
                        <button key={c.id} onClick={() => act(() => savedApi.addToCollection(c.id, [s.professionalId]), `Added to “${c.name}”.`)}>Add to “{c.name}”</button>
                      ))}
                      <button className="danger" onClick={() => act(() => savedApi.remove(s.professionalId), `${s.displayName} removed from your shortlist.`)}>Remove from saved</button>
                    </div>
                  </details>
                </div>
              </div>
            </article>
          ))}
        </section>

        <aside>
          <SavedSearchesPanel />
          <SidePanel title="Collections">
            <form className="row" onSubmit={createCollection} style={{ marginBottom: 12 }}>
              <input className="input" style={{ flex: 1, height: 38 }} aria-label="New collection name" placeholder="New collection" maxLength={80}
                value={newName} onChange={(e) => setNewName(e.target.value)} />
              <button className="btn btn-secondary btn-sm" disabled={!newName.trim()}><Icon name="plus" /> Add</button>
            </form>
            {collections.length === 0 ? <p className="muted small" style={{ margin: 0 }}>Group professionals by project, e.g. “Data Privacy Project”.</p> : (
              <ul className="collection-list">
                {collections.map((c) => (
                  <li key={c.id} className={collectionFilter === c.id ? 'active' : ''}>
                    <button className="link-btn" onClick={() => setCollectionFilter(collectionFilter === c.id ? '' : c.id)}>
                      <Icon name="folder" /><span><strong>{c.name}</strong><br /><span className="muted small">{c.count} professional{c.count === 1 ? '' : 's'}</span></span>
                    </button>
                    <details className="more-menu">
                      <summary aria-label={`Manage ${c.name}`}>⋮</summary>
                      <div className="menu card">
                        <button onClick={() => { const n = prompt('Rename collection', c.name); if (n && n.trim()) act(() => savedApi.renameCollection(c.id, n.trim())) }}>Rename</button>
                        <button className="danger" onClick={() => { if (confirm(`Delete “${c.name}”? The professionals stay saved.`)) act(() => savedApi.deleteCollection(c.id), 'Collection deleted.') }}>Delete</button>
                      </div>
                    </details>
                  </li>
                ))}
              </ul>
            )}
          </SidePanel>

          <SidePanel title={`Compare selected (${compareIds.length})`} action={selected.length > 0 && <button className="btn btn-ghost btn-sm" onClick={() => setSelected([])}>Clear</button>}>
            {compareIds.length === 0 ? <p className="muted small" style={{ margin: 0 }}>Tick up to 3 professionals to compare them side by side.</p> : (
              <>
                <ul className="pro-list">
                  {compareIds.map((id) => byId[id] && (
                    <li key={id}><Avatar name={byId[id].displayName} photoUrl={byId[id].photoUrl} size={32} />
                      <span><strong>{byId[id].displayName}</strong><br /><span className="muted small">{byId[id].headline}</span></span>
                      <button className="icon-btn" aria-label={`Remove ${byId[id].displayName}`} onClick={() => toggle(id)}>×</button></li>
                  ))}
                </ul>
                {selected.length > MAX_COMPARE && <p className="muted small">Only the first 3 are compared.</p>}
                <button className="btn btn-primary btn-block" style={{ marginTop: 12 }} onClick={() => setComparing(true)}>View comparison →</button>
              </>
            )}
            <div className="tip"><Icon name="help" /><span>Compare up to 3 professionals to weigh verification, expertise, availability and commercial terms.</span></div>
          </SidePanel>
        </aside>
      </div>

      {selected.length > 0 && (
        <div className="compare-tray">
          <strong>{selected.length} professional{selected.length > 1 ? 's' : ''} selected</strong>
          <div className="row" style={{ marginLeft: 'auto' }}>
            <button className="btn btn-secondary" onClick={() => setComparing(true)}><Icon name="compare" /> Compare ({compareIds.length})</button>
            {collections.length > 0 && (
              <select className="input tray-select" aria-label="Add selected to collection" value=""
                onChange={(e) => { const c = collections.find((x) => x.id === e.target.value); if (c) act(() => savedApi.addToCollection(c.id, selected), `Added ${selected.length} to “${c.name}”.`) }}>
                <option value="">Add to collection…</option>{collections.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
              </select>
            )}
            <Link className="btn btn-secondary" to={`/app/requests/new?${selected.slice(0, 3).map((id) => `pro=${id}`).join('&')}`}><Icon name="request" /> Request proposal{selected.length > 1 ? 's' : ''}</Link>
            <button className="btn btn-danger" onClick={() => {
              if (confirm(`Remove ${selected.length} from your shortlist?`)) act(async () => { for (const id of selected) await savedApi.remove(id); setSelected([]) }, 'Removed from your shortlist.')
            }}><Icon name="trash" /> Remove</button>
          </div>
        </div>
      )}
      {comparing && <CompareDialog ids={compareIds} onClose={() => setComparing(false)} />}
    </>
  )
}
