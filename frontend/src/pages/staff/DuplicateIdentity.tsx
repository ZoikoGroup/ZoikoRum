import { useCallback, useEffect, useState } from 'react'
import { duplicatesApi, type DuplicateCase } from '../../api/duplicates'
import {
  AdminHeader, AdminKpi, Callout, CountTabs, DetailPanel, Facts, FilterBar, KpiStrip, ListDetail,
  Pill, TableFoot, label, shortDate, useSelection, type PillTone,
} from '../../components/admin'
import { ErrorAlert, useStepUp } from '../../components/ui'

type Tab = 'active' | DuplicateCase['status']
const isActive = (d: DuplicateCase) => d.status === 'OPEN' || d.status === 'ANSWERED'
const signalText = (s: string) => (s === 'SAME_ID_DOCUMENT' ? 'Same identity document' : label(s))
const answerText = (a: DuplicateCase['userAnswer']) => (a === 'MERGE_REQUESTED' ? 'Asked to merge' : a === 'NOT_ME' ? 'Says it is not theirs' : 'No answer yet')
const stateText: Record<DuplicateCase['status'], string> = { OPEN: 'New signal', ANSWERED: 'Answered', MERGED: 'Merged', NOT_DUPLICATE: 'Not a duplicate' }
const stateTone: Record<DuplicateCase['status'], PillTone> = { OPEN: 'amber', ANSWERED: 'blue', MERGED: 'green', NOT_DUPLICATE: 'grey' }
const StatePill = ({ d }: { d: DuplicateCase }) => <Pill tone={stateTone[d.status]}>{stateText[d.status]}</Pill>

/* Support: possible duplicate accounts (Onboarding s.20 "merge flow with support path"). Confirming keeps one account and
   closes the other; anything that must move is moved by support. Every decision needs a fresh two-step confirmation. */
export default function DuplicateIdentity() {
  const [rows, setRows] = useState<DuplicateCase[] | null>(null)
  const [error, setError] = useState<unknown>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [note, setNote] = useState('')
  const [tab, setTab] = useState<Tab>('active')
  const [q, setQ] = useState('')
  const { run, modal } = useStepUp(setError)
  const { selected, select } = useSelection(rows)
  const load = useCallback(() => duplicatesApi.queue().then(setRows).catch(setError), [])
  useEffect(() => { load() }, [load])

  const resolve = (d: DuplicateCase, outcome: 'MERGED' | 'NOT_DUPLICATE', keep?: string) => run(async () => {
    await duplicatesApi.resolve(d.id, { outcome, keepIdentityId: keep, note: note.trim() })
    setNotice(outcome === 'MERGED' ? 'Accounts merged: the duplicate is closed.' : 'Marked as not a duplicate.')
    setNote('')
    await load()
  })

  const all = rows ?? []
  const count = (s: DuplicateCase['status']) => all.filter((d) => d.status === s).length
  const active = all.filter(isActive).length
  const needle = q.trim().toLowerCase()
  const shown = all
    .filter((d) => (tab === 'active' ? isActive(d) : d.status === tab))
    .filter((d) => !needle || [d.id, d.accountName, d.account, d.otherAccountName, d.otherAccount]
      .some((v) => (v ?? '').toLowerCase().includes(needle)))

  const list = (
    <div className="card">
      <CountTabs tabs={[
        { key: 'active' as Tab, label: 'Active cases', count: rows ? active : null },
        { key: 'OPEN' as Tab, label: 'New', count: rows ? count('OPEN') : null },
        { key: 'ANSWERED' as Tab, label: 'Answered', count: rows ? count('ANSWERED') : null },
        { key: 'MERGED' as Tab, label: 'Merged', count: rows ? count('MERGED') : null },
        { key: 'NOT_DUPLICATE' as Tab, label: 'Not a duplicate', count: rows ? count('NOT_DUPLICATE') : null },
      ]} value={tab} onChange={(t) => { setTab(t); select(null) }} />
      <FilterBar search={q} onSearch={setQ} placeholder="Search case ID or account…" />
      <div className="adm-table-wrap">
        <table className="data">
          <thead><tr><th>Case</th><th>Account pair</th><th>Signal</th><th>Their answer</th><th>State</th></tr></thead>
          <tbody>
            {shown.length === 0 && <tr><td colSpan={5} className="empty-row">{rows ? 'Nothing to review.' : 'Loading…'}</td></tr>}
            {shown.map((d) => (
              <tr key={d.id} className={`pick ${selected?.id === d.id ? 'selected' : ''}`} onClick={() => { select(d); setNote('') }}>
                <td><div className="cell-id">{d.id.slice(0, 8)}</div><div className="cell-sub">Raised {shortDate(d.createdAt)}</div></td>
                <td><div className="cell-main">{d.accountName ?? '—'}</div><div className="cell-sub">↔ {d.otherAccountName ?? '—'}</div></td>
                <td>{signalText(d.signal)}</td>
                <td className="small">{answerText(d.userAnswer)}</td>
                <td><StatePill d={d} /></td>
              </tr>))}
          </tbody>
        </table>
      </div>
      <TableFoot shown={shown.length} total={rows?.length} noun="cases" />
    </div>
  )

  const d = selected
  const ok = note.trim().length >= 5
  const account = (tag: string, name: string | null, email: string | null) => (
    <div><div className="lbl">{tag}</div><div className="val" style={{ fontSize: 14 }}>{name ?? '—'}</div>
      <div className="cell-sub" style={{ overflowWrap: 'anywhere' }}>{email ?? '—'}</div></div>
  )
  const detail = d && (
    <DetailPanel title={`Case ${d.id.slice(0, 8)}`} subtitle={`Raised ${shortDate(d.createdAt)}`}
      badge={<StatePill d={d} />} onClose={() => select(null)}
      footer={isActive(d) ? <>
        <input className="input" placeholder="Decision note (required)" maxLength={500} value={note} aria-label="Decision note"
          onChange={(e) => setNote(e.target.value)} style={{ flexBasis: '100%' }} />
        <button type="button" className="btn btn-secondary btn-sm" disabled={!ok} onClick={() => resolve(d, 'MERGED', d.identityId ?? undefined)}>Keep {d.accountName}</button>
        <button type="button" className="btn btn-secondary btn-sm" disabled={!ok} onClick={() => resolve(d, 'MERGED', d.otherIdentityId ?? undefined)}>Keep {d.otherAccountName}</button>
        <button type="button" className="btn btn-ghost btn-sm" disabled={!ok} onClick={() => resolve(d, 'NOT_DUPLICATE')}>Not a duplicate</button>
      </> : undefined}>
      {isActive(d) && <Callout title="Match signal is not a finding">Nothing is merged automatically. Both accounts stay as they are until a decision is recorded here.</Callout>}
      <div>
        <h3 className="small" style={{ margin: '0 0 8px' }}>Accounts under review</h3>
        <div className="adm-mini-stats">
          {account('Account A', d.accountName, d.account)}
          {account('Account B', d.otherAccountName, d.otherAccount)}
        </div>
      </div>
      <Facts title="Signal" rows={[
        ['Correlation signal', signalText(d.signal)],
        ['Their answer', answerText(d.userAnswer)],
        ...(d.userNote ? [['Their note', `“${d.userNote}”`] as [string, string]] : []),
        ['State', stateText[d.status]],
        ...(d.resolvedAt ? [['Resolved', shortDate(d.resolvedAt)] as [string, string]] : []),
        ...(d.resolutionNote ? [['Decision note', d.resolutionNote] as [string, string]] : []),
      ]} />
    </DetailPanel>
  )

  return (
    <>
      {modal}
      <AdminHeader crumb="People & Organizations / Identity governance" title="Duplicate Identity Cases"
        subtitle="Raised when the same identity document is used on two accounts. Nothing is merged automatically; every decision needs a fresh two-step confirmation." />
      <ErrorAlert error={error} />
      {notice && <div className="alert alert-success" role="status">{notice}</div>}
      {rows && <KpiStrip>
        <AdminKpi icon="layers" tone="blue" label="Active cases" value={active} sub={`${count('OPEN')} new + ${count('ANSWERED')} answered`} />
        <AdminKpi icon="bell" tone="amber" label="New signals" value={count('OPEN')} sub="No answer from the account holder yet" />
        <AdminKpi icon="message" tone="violet" label="Answered" value={count('ANSWERED')} sub="Awaiting a support decision" />
        <AdminKpi icon="check" tone="green" label="Merged" value={count('MERGED')} sub="Duplicate account closed" />
        <AdminKpi icon="shield" tone="teal" label="Not a duplicate" value={count('NOT_DUPLICATE')} sub="Documented outcome" />
      </KpiStrip>}
      <ListDetail list={list} detail={detail || undefined} />
    </>
  )
}
