import { useEffect, useId, useRef, useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { searchApi, type Suggestions } from '../api/search'

const RECENT_KEY = 'zk.recentSearches'
const MAX_RECENT = 6

function readRecent(): string[] {
  try { const v = JSON.parse(localStorage.getItem(RECENT_KEY) ?? '[]'); return Array.isArray(v) ? v.filter((x) => typeof x === 'string') : [] } catch { return [] }
}
function remember(q: string) {
  try { localStorage.setItem(RECENT_KEY, JSON.stringify([q, ...readRecent().filter((x) => x !== q)].slice(0, MAX_RECENT))) } catch { /* private mode */ }
}

/** Search box with autocomplete (expertise, then professionals) and this browser's recent searches. */
export function SearchBox({ value, onChange, onSearch, onPickSpecialization, placeholder, profileBase = '/professionals' }: {
  value: string; onChange: (v: string) => void; onSearch: (q: string) => void; onPickSpecialization: (slug: string) => void
  placeholder: string; profileBase?: string
}) {
  const navigate = useNavigate()
  const listId = useId()
  const [open, setOpen] = useState(false)
  const [hints, setHints] = useState<Suggestions | null>(null)
  const [recent, setRecent] = useState<string[]>(readRecent)
  const [active, setActive] = useState(-1)
  const timer = useRef<number | undefined>(undefined)

  useEffect(() => {
    window.clearTimeout(timer.current)
    const q = value.trim()
    if (q.length < 2) { timer.current = window.setTimeout(() => setHints(null), 0); return }
    timer.current = window.setTimeout(() => { searchApi.suggest(q).then(setHints).catch(() => setHints(null)) }, 200)
    return () => window.clearTimeout(timer.current)
  }, [value])

  type Option = { key: string; label: string; sub?: string; run: () => void }
  const options: Option[] = value.trim().length < 2
    ? recent.map((r) => ({ key: `r:${r}`, label: r, sub: 'Recent', run: () => { onChange(r); go(r) } }))
    : [
        ...(hints?.specializations ?? []).map((s) => ({ key: `s:${s.slug}`, label: s.name, sub: 'Expertise', run: () => { onChange(''); onPickSpecialization(s.slug); setOpen(false) } })),
        ...(hints?.professionals ?? []).map((p) => ({ key: `p:${p.id}`, label: p.name, sub: p.headline ?? 'Professional', run: () => navigate(`${profileBase}/${p.id}`) })),
      ]

  function go(q: string) {
    const t = q.trim()
    if (t) { remember(t); setRecent(readRecent()) }
    setOpen(false)
    onSearch(t)
  }
  function submit(e: FormEvent) {
    e.preventDefault()
    if (open && active >= 0 && options[active]) options[active].run()
    else go(value)
  }

  return (
    <form className="search-bar search-box" onSubmit={submit} role="search">
      <input className="input" aria-label="Search professionals" placeholder={placeholder} value={value} autoComplete="off"
        role="combobox" aria-expanded={open && options.length > 0} aria-controls={listId} aria-autocomplete="list"
        aria-activedescendant={active >= 0 ? `${listId}-${active}` : undefined}
        onChange={(e) => { onChange(e.target.value); setOpen(true); setActive(-1) }}
        onFocus={() => setOpen(true)} onBlur={() => window.setTimeout(() => setOpen(false), 150)}
        onKeyDown={(e) => {
          if (e.key === 'ArrowDown') { e.preventDefault(); setOpen(true); setActive((a) => Math.min(options.length - 1, a + 1)) }
          else if (e.key === 'ArrowUp') { e.preventDefault(); setActive((a) => Math.max(-1, a - 1)) }
          else if (e.key === 'Escape') setOpen(false)
        }} />
      <button className="btn btn-primary">Search</button>
      {open && options.length > 0 && <ul id={listId} role="listbox" className="suggest-list card">
        {options.map((o, i) => <li key={o.key} id={`${listId}-${i}`} role="option" aria-selected={i === active}
          className={i === active ? 'active' : ''} onMouseDown={(e) => { e.preventDefault(); o.run() }}>
          <span>{o.label}</span>{o.sub && <span className="muted small">{o.sub}</span>}</li>)}
        {value.trim().length < 2 && recent.length > 0 && <li role="presentation" className="small">
          <button type="button" className="link-btn small" onMouseDown={(e) => { e.preventDefault(); try { localStorage.removeItem(RECENT_KEY) } catch { /* ignore */ } setRecent([]) }}>
            Clear recent searches</button></li>}
      </ul>}
    </form>
  )
}
