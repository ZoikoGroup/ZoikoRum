import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { proApi } from '../../api/professional'
import {
  AdminHeader, AdminKpi, Callout, Checklist, CountTabs, DetailPanel, Facts, FilterBar, Initials, KpiStrip, ListDetail,
  Pill, Progress, TableFoot, shortDate, useSelection,pickRow } from '../../components/admin'
import { CaseOwner, OwnerCell, useAssignments } from '../../components/CaseOwner'
import { ErrorAlert, useStepUp } from '../../components/ui'

type Application = Awaited<ReturnType<typeof proApi.enterpriseApplications>>[number] & { id: string }
type Tab = 'all' | 'ready' | 'missing'

/** Compliance officers review Enterprise Ready applications. Approve only when every requirement holds and the
 *  statements are complete; every decision carries a reason shown to the professional. */
export default function EnterpriseReadinessAdmin() {
  const [items, setItems] = useState<Application[] | null>(null)
  const [error, setError] = useState<unknown>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [tab, setTab] = useState<Tab>('all')
  const [q, setQ] = useState('')
  const [reason, setReason] = useState('')
  const { run, modal } = useStepUp(setError)
  const { selected, select } = useSelection(items)
  const owners = useAssignments(['ENTERPRISE_APPLICATION'])  // keyed by the applying professional

  const load = useCallback(() => {
    proApi.enterpriseApplications().then((list) => setItems(list.map((a) => ({ ...a, id: a.professionalId })))).catch(setError)
  }, [])
  useEffect(() => { load() }, [load])

  const allMet = (a: Application) => a.requirements.every((r) => r.met)
  const ready = useMemo(() => (items ?? []).filter(allMet), [items])
  const missing = (items?.length ?? 0) - ready.length
  const needle = q.trim().toLowerCase()
  const rows = (items ?? [])
    .filter((a) => tab === 'all' || (tab === 'ready') === allMet(a))
    .filter((a) => !needle || a.name.toLowerCase().includes(needle) || (a.headline ?? '').toLowerCase().includes(needle))

  function decide(a: Application, approve: boolean) {
    const text = reason.trim()
    if (text.length < 5) return
    run(async () => {
      await proApi.decideEnterprise(a.professionalId, approve, text)
      setNotice(`${a.name}: ${approve ? 'approved' : 'declined'}.`)
      setReason('')
      select(null)
      load()
    })
  }

  const list = (
    <div className="card">
      <CountTabs tabs={[
        { key: 'all' as Tab, label: 'Awaiting decision', count: items?.length },
        { key: 'ready' as Tab, label: 'All requirements met', count: items ? ready.length : null },
        { key: 'missing' as Tab, label: 'Requirements missing', count: items ? missing : null },
      ]} value={tab} onChange={setTab} />
      <FilterBar search={q} onSearch={setQ} placeholder="Search applicant…" />
      <div className="adm-table-wrap">
        <table className="data">
          <thead><tr><th scope="col">Applicant</th><th scope="col">Subject</th><th scope="col">Requirements</th><th scope="col">Statements</th><th scope="col">Applied</th><th scope="col">Owner</th></tr></thead>
          <tbody>
            {rows.length === 0 && <tr><td colSpan={6} className="empty-row">{items ? 'No applications waiting.' : 'Loading…'}</td></tr>}
            {rows.map((a) => {
              const met = a.requirements.filter((r) => r.met).length
              const total = a.requirements.length
              return (
                <tr {...pickRow} key={a.id} className={`pick ${selected?.id === a.id ? 'selected' : ''}`} onClick={() => { select(a); setReason('') }}>
                  <td><div className="name-cell"><Initials name={a.name} /><div><div className="cell-main">{a.name}</div>
                    <div className="cell-sub">{a.headline ?? ''}</div></div></div></td>
                  <td>Professional</td>
                  <td><div style={{ display: 'flex', alignItems: 'center', gap: 8, minWidth: 110 }}>
                    <div style={{ flex: 1 }}><Progress value={met} max={total} tone={met === total ? 'green' : 'amber'} /></div>
                    <strong className="small">{met}/{total}</strong></div></td>
                  <td>{a.attestation ? <span className="small">v{a.attestation.version}</span> : <Pill tone="red">Missing</Pill>}</td>
                  <td>{shortDate(a.appliedAt)}</td>
                  <td><OwnerCell assignment={owners.get('ENTERPRISE_APPLICATION', a.professionalId)} /></td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
      <TableFoot shown={rows.length} total={items?.length} noun="applications" />
    </div>
  )

  const a = selected
  const detail = a && (() => {
    const met = a.requirements.filter((r) => r.met).length
    const blocked = a.requirements.length - met
    const ok = reason.trim().length >= 5
    return (
      <DetailPanel title={a.name} subtitle={`Professional · applied ${shortDate(a.appliedAt)}`}
        badge={<Pill tone={blocked ? 'amber' : 'blue'}>{blocked ? 'Requirements missing' : 'In review'}</Pill>} onClose={() => select(null)}
        footer={<>
          <button type="button" className="btn btn-primary btn-sm" disabled={!ok || blocked > 0} onClick={() => decide(a, true)}>Approve</button>
          <button type="button" className="btn btn-secondary btn-sm" disabled={!ok} onClick={() => decide(a, false)}>Decline</button>
        </>}>
        {blocked > 0 && <Callout title={`Approval blocked · ${blocked} required item${blocked === 1 ? '' : 's'} incomplete`}>
          Approval is possible only once every requirement holds.</Callout>}
        <Facts title="Application context" rows={[
          ['Applicant type', 'Professional'],
          ['Headline', a.headline ?? '—'],
          ['Submitted', shortDate(a.appliedAt)],
          ['Statements version', a.attestation?.version ?? '—'],
          ['Statements confirmed', shortDate(a.attestation?.attestedAt)],
          ['Public profile', <Link key="profile" to={`/professionals/${a.professionalId}`} target="_blank" rel="noreferrer">Open ↗</Link>],
        ]} />
        <CaseOwner key={a.professionalId} kind="ENTERPRISE_APPLICATION" caseId={a.professionalId}
          assignment={owners.get('ENTERPRISE_APPLICATION', a.professionalId)} onChange={owners.put} />
        <Checklist title="Readiness evidence" items={a.requirements.map((r) => ({
          label: r.label, state: r.met ? 'done' : 'missing', note: r.met ? 'Holds' : 'Missing',
        }))} />
        <label className="small" style={{ display: 'grid', gap: 6 }}>
          <strong>Decision reason (shown to the professional)</strong>
          <textarea className="input" rows={3} maxLength={1000} value={reason} onChange={(e) => setReason(e.target.value)}
            placeholder="Note for the record, or why it is declined (at least 5 characters)" />
        </label>
      </DetailPanel>
    )
  })()

  return (
    <>
      {modal}
      <AdminHeader crumb="People & Organizations / Enterprise eligibility" title="Enterprise Readiness"
        subtitle="Review Enterprise Ready applications. Approve only when every requirement holds and the security statements are complete." />
      <ErrorAlert error={error} />
      {notice && <div className="alert alert-success" role="status">{notice}</div>}
      {items && <KpiStrip>
        <AdminKpi icon="list" tone="blue" label="Awaiting decision" value={items.length} sub="Applications in review" />
        <AdminKpi icon="check" tone="green" label="All requirements met" value={ready.length} sub="Ready for a decision" />
        <AdminKpi icon="alert" tone="amber" label="Requirements missing" value={missing} sub="Approval blocked until they hold" />
      </KpiStrip>}
      <ListDetail list={list} detail={detail || undefined} />
    </>
  )
}
