import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { adminConsoleApi, type AdminProfessional, type AdminProfessionalSummary } from '../../api/adminConsole'
import {
  AdminHeader, AdminKpi, Callout, Checklist, CountTabs, DetailPanel, Facts, FilterBar, FilterSelect, Initials, KpiStrip, ListDetail,
  Pill, StatusPill, TableFoot, label, shortDate, toneFor, useSelection, type CheckState, pickRow, useSelectedParam } from '../../components/admin'
import { ErrorAlert } from '../../components/ui'

type Tab = '' | 'PUBLISHED' | 'IN_REVIEW' | 'DRAFT' | 'RESTRICTED'
const stateOf = (s: string | null | undefined): CheckState => {
  const t = toneFor(s)
  return t === 'green' ? 'done' : t === 'red' ? 'missing' : 'pending'
}
const TIER_TONE = { A: 'green', B: 'blue', C: 'violet' } as const

/** Governed directory of professional profiles. Read-only: publication and trust-tier changes come from verification
 *  decisions, never from this list. */
export default function ProfessionalDirectory() {
  const [summary, setSummary] = useState<AdminProfessionalSummary | null>(null)
  const [tab, setTab] = useState<Tab>('')
  const [q, setQ] = useState('')
  const [country, setCountry] = useState('')
  const [filters, setFilters] = useState({ q: '', country: '' })
  const [tier, setTier] = useState('')
  const [verif, setVerif] = useState('')
  const [rows, setRows] = useState<AdminProfessional[]>([])
  const [next, setNext] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<unknown>(null)
  const { selected, select, selectId } = useSelection(rows)
  useSelectedParam(selectId)

  useEffect(() => { adminConsoleApi.professionalSummary().then(setSummary).catch(() => setSummary(null)) }, [])
  // Search after a short pause in typing, not on every key.
  useEffect(() => {
    const t = window.setTimeout(() => setFilters({ q: q.trim(), country: country.trim().toUpperCase() }), 350)
    return () => window.clearTimeout(t)
  }, [q, country])

  const fetchPage = useCallback((cursor: string | null) =>
    adminConsoleApi.professionals({ q: filters.q, country: filters.country, tier, publication: tab, cursor }), [filters, tier, tab])
  // First page whenever the filters change.
  useEffect(() => {
    let live = true
    fetchPage(null)
      .then((page) => { if (live) { setRows(page.items); setNext(page.nextCursor); setError(null) } })
      .catch((e) => { if (live) setError(e) })
      .finally(() => { if (live) setLoading(false) })
    return () => { live = false }
  }, [fetchPage])
  function loadMore(cursor: string) {
    setLoading(true)
    fetchPage(cursor)
      .then((page) => { setRows((current) => [...current, ...page.items]); setNext(page.nextCursor) })
      .catch(setError)
      .finally(() => setLoading(false))
  }

  // Identity verification has no server filter; it narrows the rows already loaded.
  const shown = verif ? rows.filter((r) => (stateOf(r.verification.identity) === 'done') === (verif === 'verified')) : rows
  const s = summary
  const tabs: { key: Tab; label: string; count?: number | null }[] = [
    { key: '', label: 'All profiles', count: s?.total }, { key: 'PUBLISHED', label: 'Published', count: s?.published },
    { key: 'IN_REVIEW', label: 'In review', count: s?.inReview }, { key: 'DRAFT', label: 'Draft', count: s?.draft },
    { key: 'RESTRICTED', label: 'Restricted', count: s?.restricted },
  ]

  const list = (
    <div className="card">
      <CountTabs tabs={tabs} value={tab} onChange={(t) => { setTab(t); select(null) }} />
      <FilterBar search={q} onSearch={setQ} placeholder="Search professional, specialty…">
        <input className="adm-filter" style={{ width: 130 }} aria-label="Jurisdiction (country code)" placeholder="Jurisdiction (US)" maxLength={2}
          value={country} onChange={(e) => setCountry(e.target.value)} />
        <FilterSelect label="Trust tier" value={tier} onChange={setTier} options={[['A', 'Tier A'], ['B', 'Tier B'], ['C', 'Tier C']]} />
        <FilterSelect label="Verification" value={verif} onChange={setVerif} options={[['verified', 'Identity verified'], ['unverified', 'Identity not verified']]} />
      </FilterBar>
      {s && <div className="adm-note">Profiles by trust tier: A {s.tiers.A} · B {s.tiers.B} · C {s.tiers.C} = {s.tiers.A + s.tiers.B + s.tiers.C}</div>}
      <div className="adm-table-wrap">
        <table className="data">
          <thead><tr><th scope="col">Professional</th><th scope="col">Specialization</th><th scope="col">Jurisdiction</th><th scope="col">Verification</th><th scope="col">Trust tier</th><th scope="col">Publication</th><th scope="col">Eng.</th></tr></thead>
          <tbody>
            {shown.length === 0 && <tr><td colSpan={7} className="empty-row">{loading ? 'Loading…' : 'No profiles match.'}</td></tr>}
            {shown.map((p) => (
              <tr {...pickRow} key={p.id} className={`pick ${selected?.id === p.id ? 'selected' : ''}`} onClick={() => select(p)}>
                <td><div className="name-cell"><Initials name={p.displayName} /><div><div className="cell-main">{p.displayName}</div>
                  <div className="cell-sub">{p.headline ?? ''}</div></div></div></td>
                <td><div className="cell-main" style={{ fontWeight: 500 }}>{p.specialization ?? '—'}</div><div className="cell-sub">{p.category ?? ''}</div></td>
                <td>{p.country ?? '—'}</td>
                <td><StatusPill status={p.verification.identity} /></td>
                <td>{p.tier ? <Pill tone={TIER_TONE[p.tier]}>Tier {p.tier}</Pill> : <Pill>Unassigned</Pill>}</td>
                <td><StatusPill status={p.publication} /></td>
                <td>{p.lifetimeEngagements}</td>
              </tr>))}
          </tbody>
        </table>
      </div>
      <TableFoot shown={shown.length} total={verif || filters.q || filters.country || tier ? null : tabs.find((t) => t.key === tab)?.count} noun="professional profiles" />
      {next && <div style={{ padding: '0 16px 12px' }}>
        <button type="button" className="btn btn-secondary btn-sm" disabled={loading} onClick={() => loadMore(next)}>{loading ? 'Loading…' : 'Load more'}</button></div>}
    </div>
  )

  const p = selected
  const detail = p && (
    <DetailPanel title={p.displayName} subtitle={p.specialization ?? p.headline ?? undefined} badge={<StatusPill status={p.publication} />}
      onClose={() => select(null)}
      footer={<Link className="btn btn-secondary btn-sm" to={`/professionals/${p.id}`} target="_blank" rel="noreferrer">View public profile ↗</Link>}>
      <Callout tone={p.tier ? 'green' : 'amber'} title={p.tier ? `Trust tier ${p.tier}` : 'No trust tier assigned'}>
        {p.publication === 'PUBLISHED' ? 'Profile is published.' : `Profile is ${label(p.publication).toLowerCase()}.`}
      </Callout>
      <Facts title="Profile governance" rows={[
        ['Primary specialization', p.category ?? '—'],
        ['Professional role', p.specialization ?? '—'],
        ['Primary jurisdiction', p.country ?? '—'],
        ['Profile publication', label(p.publication)],
        ['Active engagements', p.activeEngagements],
        ['Lifetime engagements', p.lifetimeEngagements],
        ['Joined', shortDate(p.createdAt)],
      ]} />
      <Checklist title="Verification & eligibility" items={[
        { label: 'Identity verification', state: stateOf(p.verification.identity), note: label(p.verification.identity) },
        { label: 'Professional credentials', state: stateOf(p.verification.credentials), note: label(p.verification.credentials) },
        { label: `Jurisdiction eligibility${p.country ? ` (${p.country})` : ''}`, state: stateOf(p.verification.jurisdiction), note: label(p.verification.jurisdiction) },
      ]} />
    </DetailPanel>
  )

  return (
    <>
      <AdminHeader crumb="People & Organizations / Governed directory" title="Professional Directory"
        subtitle="Oversee professional profiles, trust tiers, jurisdiction eligibility and publication, without bypassing independent verification decisions." />
      <ErrorAlert error={error} />
      {s && <KpiStrip>
        <AdminKpi icon="team" tone="blue" label="Total profiles" value={s.total.toLocaleString()} sub="Person accounts in the directory" />
        <AdminKpi icon="eye" tone="green" label="Published profiles" value={s.published.toLocaleString()} sub="Publicly discoverable" />
        <AdminKpi icon="clock" tone="amber" label="In review" value={s.inReview.toLocaleString()} sub="Pending governance checks" />
        <AdminKpi icon="folder" tone="violet" label="Draft profiles" value={s.draft.toLocaleString()} sub="Not submitted or published" />
        <AdminKpi icon="alert" tone="red" label="Restricted profiles" value={s.restricted.toLocaleString()} sub="Access or listing restricted" />
        <AdminKpi icon="check" tone="teal" label="Identity verified" value={s.identityVerified.toLocaleString()} sub="Across all publication states" />
      </KpiStrip>}
      <ListDetail list={list} detail={detail || undefined} />
    </>
  )
}
