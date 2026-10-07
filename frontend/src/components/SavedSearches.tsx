import { useCallback, useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { savedApi, type SavedSearch } from '../api/saved'
import { searchApi } from '../api/search'
import { Icon } from './dashboard'
import { SidePanel } from './portal'

/** Saved searches (Buyer Dashboard s.13): filters persist; "new" counts professionals published since you last looked. */
export function SavedSearchesPanel() {
  const navigate = useNavigate()
  const [list, setList] = useState<SavedSearch[] | null>(null)
  const [fresh, setFresh] = useState<Record<string, number>>({})
  const load = useCallback(async () => {
    const searches = await savedApi.searches().catch(() => [] as SavedSearch[])
    setList(searches)
    const counts = await Promise.all(searches.map((s) => searchApi.professionals({ ...s.params, publishedAfter: s.lastViewedAt, limit: '1' })
      .then((r) => [s.id, r.total] as const).catch(() => [s.id, 0] as const)))
    setFresh(Object.fromEntries(counts))
  }, [])
  useEffect(() => { load() }, [load])

  return (
    <SidePanel title="Saved searches">
      {list && list.length === 0 ? <p className="muted small" style={{ margin: 0 }}>On Find Professionals, use <strong>Save this search</strong> to keep your filters
        and see new matches here.</p> : (
        <ul className="collection-list">{(list ?? []).map((s) => (
          <li key={s.id}>
            <button className="link-btn" onClick={async () => {
              await savedApi.searchViewed(s.id).catch(() => {})
              navigate(`/app/find?${new URLSearchParams(s.params).toString()}`)
            }}>
              <Icon name="search" /><span><strong>{s.name}</strong><br />
                <span className="muted small">{fresh[s.id] ? `${fresh[s.id]} new since you last looked` : 'No new matches'}</span></span>
            </button>
            {!!fresh[s.id] && <span className="badge green">{fresh[s.id]} new</span>}
            <button className="icon-btn" aria-label={`Delete ${s.name}`} onClick={() => { if (confirm(`Delete the saved search “${s.name}”?`)) savedApi.deleteSearch(s.id).then(load) }}>×</button>
          </li>))}</ul>
      )}
    </SidePanel>
  )
}
