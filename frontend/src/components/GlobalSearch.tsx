import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from 'react'
import { messagingApi } from '../api/messaging'
import { useNavigate } from 'react-router-dom'
import { contractApi, type Contract } from '../api/contracts'
import { proposalApi, type ProposalRequest } from '../api/proposals'
import { searchApi } from '../api/search'
import { Icon } from './dashboard'

/* Dashboard-scoped global search (Buyer Dashboard s.15): one box across professionals, engagements/contracts and
   requests, with autocomplete and type filters. Messages join once messaging exists (Step 10+).
   Engagements and requests are the viewer's own (loaded once, filtered locally); professionals come from search. */

type Kind = 'all' | 'professionals' | 'engagements' | 'requests' | 'messages'
interface Hit { kind: Exclude<Kind, 'all'>; id: string; title: string; sub: string; to: string }
const KINDS: [Kind, string][] = [['all', 'All'], ['professionals', 'Professionals'], ['engagements', 'Engagements'], ['requests', 'Requests'],
  ['messages', 'Messages']]

export function GlobalSearch({ side }: { side: 'buyer' | 'professional' | null }) {
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
