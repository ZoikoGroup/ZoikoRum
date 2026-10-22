import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from 'react'
import { messagingApi } from '../api/messaging'
import { useNavigate } from 'react-router-dom'
import { contractApi, type Contract } from '../api/contracts'
import { proposalApi, type ProposalRequest } from '../api/proposals'
import { searchApi } from '../api/search'
import { ApiError } from '../api/client'
import { comboKey, STAFF_SEARCH_MIN, staffSearchApi, type ComboState, type StaffSearchHit, type StaffSearchResult } from '../api/staffSearch'
import { Icon } from './dashboard'

/* Dashboard-scoped global search (Buyer Dashboard s.15): one box across professionals, engagements/contracts and
   requests, with autocomplete and type filters. Messages join once messaging exists (Step 10+).
   Engagements and requests are the viewer's own (loaded once, filtered locally); professionals come from search. */

type Kind = 'all' | 'professionals' | 'engagements' | 'requests' | 'messages'
interface Hit { kind: Exclude<Kind, 'all'>; id: string; title: string; sub: string; to: string }
const KINDS: [Kind, string][] = [['all', 'All'], ['professionals', 'Professionals'], ['engagements', 'Engagements'], ['requests', 'Requests'],
  ['messages', 'Messages']]

/* One box in the top bar: staff working in the staff console (/platform-admin/*) get the scoped staff search; everyone else
   keeps the dashboard search below, unchanged. */
export function GlobalSearch({ side, staff = false }: { side: 'buyer' | 'professional' | null; staff?: boolean }) {
  return staff ? <StaffSearch /> : <CustomerSearch side={side} />
}

/* Staff console search: debounced (250 ms) GET /v1/admin/search, results grouped by kind. The server only searches what
   the person's roles may see and masks email addresses. Combobox + listbox semantics, keyboard model in comboKey. */
type StaffStatus = 'idle' | 'loading' | 'done' | 'error'
const LISTBOX_ID = 'staff-search-results'
const optionId = (i: number) => `staff-search-option-${i}`

function StaffSearch() {
  const navigate = useNavigate()
  const [q, setQ] = useState('')
  const [combo, setCombo] = useState<ComboState>({ open: false, active: -1 })
  const [status, setStatus] = useState<StaffStatus>('idle')
  const [result, setResult] = useState<StaffSearchResult | null>(null)
  const [error, setError] = useState('')
  const box = useRef<HTMLFormElement>(null)
  const term = q.trim()
  const ready = term.length >= STAFF_SEARCH_MIN

  useEffect(() => {
    if (!ready) return  // too short: nothing is fetched or shown
    let live = true
    const t = window.setTimeout(() => {
      setStatus('loading')
      staffSearchApi.search(term).then((r) => {
        if (!live) return
        setResult(r); setStatus('done'); setCombo((c) => ({ ...c, active: -1 }))
      }).catch((e: unknown) => {
        if (!live) return
        setResult(null); setStatus('error')
        setError(e instanceof ApiError && e.status === 429 ? 'Too many searches. Wait a moment and try again.'
          : e instanceof ApiError && e.status === 403 ? 'Your staff access does not allow searching here.'
            : 'Search is unavailable right now. Try again.')
      })
    }, 250)
    return () => { live = false; window.clearTimeout(t) }
  }, [term, ready])

  useEffect(() => {
    const close = (e: MouseEvent) => { if (box.current && !box.current.contains(e.target as Node)) setCombo({ open: false, active: -1 }) }
    document.addEventListener('mousedown', close)
    return () => document.removeEventListener('mousedown', close)
  }, [])

  const current = ready && result && result.query === term.split(/\s+/).join(' ') ? result : null
  const flat: StaffSearchHit[] = current ? current.groups.flatMap((g) => g.items) : []
  const expanded = combo.open && ready
  const go = (hit: StaffSearchHit) => { setCombo({ open: false, active: -1 }); setQ(''); setResult(null); navigate(hit.link) }
  function keys(e: KeyboardEvent<HTMLInputElement>) {
    const out = comboKey(e.key, combo, flat.length)
    if (out.handled) e.preventDefault()
    setCombo(out.state)
    if (out.choose !== undefined && flat[out.choose]) go(flat[out.choose])
    if (out.clear) { setQ(''); setResult(null) }
  }
  useEffect(() => {  // keep the highlighted option in view
    if (combo.active >= 0) document.getElementById(optionId(combo.active))?.scrollIntoView?.({ block: 'nearest' })
  }, [combo.active])

  const busy = ready && (status === 'loading' || (status !== 'error' && !current))
  const message = !ready ? '' : status === 'error' ? error : busy ? 'Searching…'
    : flat.length === 0 ? 'No matches' : `${flat.length} result${flat.length === 1 ? '' : 's'}`
  let index = -1
  return (
    <form ref={box} className="top-search staff-search" role="search" aria-label="Staff console" onSubmit={(e: FormEvent) => e.preventDefault()}>
      <Icon name="search" />
      <input type="search" aria-label="Search accounts, cases, contracts and disputes" placeholder="Search accounts, cases, contracts, disputes…"
        value={q} autoComplete="off" spellCheck={false} role="combobox" aria-autocomplete="list" aria-expanded={expanded}
        aria-controls={LISTBOX_ID} aria-activedescendant={expanded && combo.active >= 0 ? optionId(combo.active) : undefined}
        aria-describedby="staff-search-status"
        onChange={(e) => {
          setQ(e.target.value); setCombo({ open: true, active: -1 })
          if (e.target.value.trim().length >= STAFF_SEARCH_MIN) setStatus('loading')
        }}
        onFocus={() => setCombo((c) => ({ ...c, open: true }))} onKeyDown={keys} />
      <span id="staff-search-status" className="sr-only" role="status" aria-live="polite">{expanded ? message : ''}</span>
      <div className="search-pop card staff-search-pop" hidden={!expanded}>
        {expanded && (status === 'error' ? <p className="staff-search-msg error" role="alert">{error}</p>
          : busy ? <p className="staff-search-msg muted small">Searching…</p>
            : flat.length === 0 ? <p className="staff-search-msg muted small">No matches for “{term}” in the areas you can see.</p> : null)}
        <ul id={LISTBOX_ID} role="listbox" aria-label="Search results">
          {expanded && current?.groups.map((g) => (
            <li key={g.kind} role="presentation">
              <ul role="group" aria-labelledby={`staff-search-group-${g.kind}`}>
                <li role="presentation" id={`staff-search-group-${g.kind}`} className="staff-search-group">{g.label}</li>
                {g.items.map((h) => {
                  const i = ++index
                  return (
                    <li key={h.kind + h.id} id={optionId(i)} role="option" aria-selected={i === combo.active}
                      className={`search-hit ${i === combo.active ? 'active' : ''}`}
                      onMouseDown={(e) => e.preventDefault()} onMouseEnter={() => setCombo((c) => ({ ...c, active: i }))} onClick={() => go(h)}>
                      <span><strong>{h.title}</strong>{h.subtitle && <><br /><span className="muted small">{h.subtitle}</span></>}</span>
                    </li>)
                })}
              </ul>
            </li>))}
        </ul>
      </div>
    </form>
  )
}

function CustomerSearch({ side }: { side: 'buyer' | 'professional' | null }) {
  const navigate = useNavigate()
  const [q, setQ] = useState('')
  const [kind, setKind] = useState<Kind>('all')
  const [open, setOpen] = useState(false)
  const [hits, setHits] = useState<Hit[]>([])
  const [active, setActive] = useState(0)
  const own = useRef<{ contracts: Contract[]; requests: ProposalRequest[] } | null>(null)
  const box = useRef<HTMLFormElement>(null)

  async function loadOwn() {
    if (own.current || !side) return
    const [contracts, requests] = await Promise.all([contractApi.list(side).catch(() => []), proposalApi.list(side).catch(() => [])])
    own.current = { contracts, requests }
  }

  useEffect(() => {
    const term = q.trim().toLowerCase()
    if (term.length < 2) return  // too short: nothing is shown (see `shown`)
    let live = true
    const t = window.setTimeout(async () => {
      await loadOwn()
      const base = side === 'professional' ? '/app/professional' : '/app'
      const has = (...xs: (string | null | undefined)[]) => xs.some((x) => x?.toLowerCase().includes(term))
      const engagements: Hit[] = (own.current?.contracts ?? []).filter((c) => has(c.title, c.reference, ...c.parties.map((p) => p.name)))
        .slice(0, 5).map((c) => ({ kind: 'engagements', id: c.id, title: c.title, sub: `${c.reference} · ${c.status.replace(/_/g, ' ').toLowerCase()}`,
          to: `${base}/engagements/${c.id}` }))
      const requests: Hit[] = (own.current?.requests ?? []).filter((r) => has(r.service, r.objective, r.professional.displayName, r.organizationName))
        .slice(0, 5).map((r) => ({ kind: 'requests', id: r.id, title: r.service, sub: side === 'professional' ? (r.organizationName ?? 'Request') : `To ${r.professional.displayName}`,
          to: `${base}/requests/${r.id}` }))
      const pros = await searchApi.professionals({ q: q.trim(), limit: '5' }).then((r) => r.items).catch(() => [])
      const professionals: Hit[] = pros.map((p) => ({ kind: 'professionals', id: p.professionalId, title: p.displayName,
        sub: p.headline ?? p.tierLabel, to: `/professionals/${p.professionalId}` }))
      const found = side ? await messagingApi.search(q.trim()).catch(() => []) : []
      const messages: Hit[] = found.map((m) => ({ kind: 'messages', id: `${m.threadId}:${m.sequence ?? 0}`, title: m.threadTitle,
        sub: m.senderName ? `${m.senderName}: ${m.snippet}` : m.snippet, to: `/app/messages?thread=${m.threadId}` }))
      if (live) { setHits([...engagements, ...requests, ...messages, ...professionals]); setActive(0) }
    }, 250)
    return () => { live = false; window.clearTimeout(t) }
  }, [q, side])  // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    const close = (e: MouseEvent) => { if (box.current && !box.current.contains(e.target as Node)) setOpen(false) }
    document.addEventListener('mousedown', close)
    return () => document.removeEventListener('mousedown', close)
  }, [])

  const shown = (q.trim().length < 2 ? [] : hits).filter((h) => kind === 'all' || h.kind === kind)
  const go = (to: string) => { setOpen(false); setQ(''); navigate(to) }
  function submit(e: FormEvent) {
    e.preventDefault()
    if (shown[active]) return go(shown[active].to)
    const findBase = side === 'buyer' ? '/app/find' : '/professionals'
    go(q.trim() ? `${findBase}?q=${encodeURIComponent(q.trim())}` : findBase)
  }
  function keys(e: KeyboardEvent) {
    if (e.key === 'ArrowDown') { e.preventDefault(); setActive((a) => Math.min(a + 1, shown.length - 1)) }
    if (e.key === 'ArrowUp') { e.preventDefault(); setActive((a) => Math.max(a - 1, 0)) }
    if (e.key === 'Escape') setOpen(false)
  }

  return (
    <form ref={box} className="top-search" role="search" onSubmit={submit}>
      <Icon name="search" />
      <input aria-label="Search engagements, requests, messages and professionals" placeholder="Search engagements, requests, messages…"
        value={q} onChange={(e) => { setQ(e.target.value); setOpen(true) }} onFocus={() => { setOpen(true); loadOwn() }} onKeyDown={keys}
        role="combobox" aria-expanded={open && q.trim().length >= 2} aria-controls="global-search-results" autoComplete="off" />
      {open && q.trim().length >= 2 && <div className="search-pop card" id="global-search-results">
        <div className="filter-pills" role="group" aria-label="Filter results">{KINDS.map(([k, l]) => (
          <button key={k} type="button" className={`pill ${kind === k ? 'on' : ''}`} aria-pressed={kind === k} onClick={() => { setKind(k); setActive(0) }}>{l}</button>))}</div>
        {shown.length === 0 ? <p className="muted small" style={{ margin: 8 }}>No matches yet. Press Enter to search all professionals.</p> : (
          <ul role="listbox">{shown.map((h, i) => (
            <li key={h.kind + h.id} role="option" aria-selected={i === active}>
              <button type="button" className={`search-hit ${i === active ? 'active' : ''}`} onMouseEnter={() => setActive(i)} onClick={() => go(h.to)}>
                <span className="badge">{KINDS.find(([k]) => k === h.kind)?.[1]}</span>
                <span><strong>{h.title}</strong><br /><span className="muted small">{h.sub}</span></span>
              </button></li>))}</ul>
        )}
      </div>}
    </form>
  )
}
