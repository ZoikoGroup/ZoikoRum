import { useCallback, useEffect, useState } from 'react'
import { SUPPORT_STATUS, SUPPORT_TOPICS, supportApi, type SupportRequest } from '../../api/support'
import { CaseOwner, OwnerCell, useAssignments } from '../../components/CaseOwner'
import { SupportThread } from '../../components/SupportThread'
import { ErrorAlert } from '../../components/ui'
import { Icon } from '../../components/dashboard'
import {
  AdminHeader, AdminKpi, Callout, CountTabs, DetailPanel, Facts, FilterBar, FilterSelect, HBars, KpiStrip, ListDetail, MetricList, Panel,
  PanelRow, Pill, StackBar, TableFoot, shortDateTime, type PillTone, pickRow, useSelectedParam } from '../../components/admin'

/* Support Cases (design 74): the support agents' queue. Sources: GET /v1/admin/support/requests (open: with our team
   and awaiting the customer; ?status=RESOLVED for resolved, newest 200), GET /v1/admin/support/requests/{id} and
   POST .../messages (reply, optionally resolving). Agents explain and point to the right place; money, verification
   and safety decisions stay with their teams. */

type TabKey = 'active' | 'OPEN' | 'WAITING_ON_YOU' | 'late' | 'RESOLVED'
const STATUS_TONE: Record<SupportRequest['status'], PillTone> = { OPEN: 'blue', WAITING_ON_YOU: 'amber', RESOLVED: 'green' }
const AGENT_STATUS: Record<SupportRequest['status'], string> = { OPEN: 'With our team', WAITING_ON_YOU: 'Awaiting customer', RESOLVED: 'Resolved' }
const topicLabel = (t: string) => SUPPORT_TOPICS.find(([v]) => v === t)?.[1] ?? t

export default function SupportCases() {
  const [open, setOpen] = useState<SupportRequest[] | null>(null)
  const [resolved, setResolved] = useState<SupportRequest[] | null>(null)
  const [error, setError] = useState<unknown>(null)
  const [tab, setTab] = useState<TabKey>('active')
  const [q, setQ] = useState('')
  const [topic, setTopic] = useState('')
  const [selected, setSelected] = useState<SupportRequest | null>(null)
  const [linkedId, setLinkedId] = useState<string | null>(null)
  useSelectedParam(setLinkedId)
  // Owner = the request's own assignee (assignedTo); the shared assignments add escalations and write the owner back to it.
  const assigned = useAssignments(['SUPPORT_REQUEST'])

  const reload = useCallback(async () => {
    const [o, r] = await Promise.all([supportApi.queue(), supportApi.queue('RESOLVED')])
    setOpen(o); setResolved(r)
  }, [])
  useEffect(() => { reload().catch(setError) }, [reload])

  useEffect(() => {  // a search result: open that request once the lists have loaded
    const hit = linkedId ? [...(open ?? []), ...(resolved ?? [])].find((r) => r.id === linkedId) : undefined
    if (hit) { setSelected(hit); setLinkedId(null) }
  }, [linkedId, open, resolved])

  const active = open ?? []
  const done = resolved ?? []
  const withTeam = active.filter((r) => r.status === 'OPEN')
  const waiting = active.filter((r) => r.status === 'WAITING_ON_YOU')
  const late = active.filter((r) => r.overdue)
  const unanswered = active.filter((r) => !r.firstRespondedAt)
  const [now] = useState(() => Date.now())
  const since7 = now - 7 * 86_400_000
  const resolved7 = done.filter((r) => r.resolvedAt && new Date(r.resolvedAt).getTime() >= since7).length
  const source = tab === 'RESOLVED' ? done : tab === 'OPEN' ? withTeam : tab === 'WAITING_ON_YOU' ? waiting : tab === 'late' ? late : active
  const s = q.trim().toLowerCase()
  const shown = source.filter((r) => (!topic || r.topic === topic)
    && (!s || [r.reference, r.subject, r.requesterName ?? '', r.assignedToName ?? ''].some((v) => v.toLowerCase().includes(s))))
  const topics = SUPPORT_TOPICS.map(([v, l]) => ({ label: l, value: active.filter((r) => r.topic === v).length })).filter((x) => x.value > 0)
  const owners = new Map<string, number>()
  for (const r of active) owners.set(r.assignedToName ?? 'Unassigned', (owners.get(r.assignedToName ?? 'Unassigned') ?? 0) + 1)

  const pick = (r: SupportRequest) => supportApi.agentGet(r.id).then(setSelected).catch(setError)

  return (
    <>
      <AdminHeader crumb="Administration & support / Customer operations" title="Support Cases"
        subtitle="Answer within one business day. Explain and point to the right place; money, verification and safety decisions stay with their teams."
        actions={<button type="button" className="btn btn-secondary" onClick={() => reload().catch(setError)}><Icon name="refresh" /> Refresh</button>} />
      <ErrorAlert error={error} />

      <KpiStrip>
        <AdminKpi icon="message" tone="blue" label="Active cases" value={open ? active.length : '—'} sub={open ? `${withTeam.length} with our team · ${waiting.length} awaiting customer` : undefined} />
        <AdminKpi icon="alert" tone={late.length ? 'red' : 'green'} label="Late first answers" value={open ? late.length : '—'} sub="First-answer time passed" />
        <AdminKpi icon="clock" tone="amber" label="Not yet answered" value={open ? unanswered.length : '—'} />
        <AdminKpi icon="user" tone="violet" label="Awaiting customer" value={open ? waiting.length : '—'} sub="Answered; their reply next" />
        <AdminKpi icon="check" tone="green" label="Resolved · 7 days" value={resolved ? resolved7 : '—'} sub={done.length >= 200 ? 'From the newest 200 resolved' : undefined} />
      </KpiStrip>

      <PanelRow cols={3}>
        <Panel title="Intake by support topic" meta={`${active.length} active`}>
          <HBars rows={topics} />
        </Panel>
        <Panel title="Workflow and first-answer discipline" meta={`${late.length} late`}>
          <StackBar segments={[
            { label: 'With our team', value: withTeam.length, color: '#2f80ed' },
            { label: 'Awaiting customer', value: waiting.length, color: '#f79009' },
          ]} />
          <MetricList rows={[
            { label: 'Late first answers', value: late.length, tone: late.length ? 'red' : undefined },
            { label: 'Not yet answered', value: unanswered.length },
            { label: 'Resolved (newest 200)', value: done.length },
          ]} />
        </Panel>
        <Panel title="Ownership" meta="Active cases per agent">
          <HBars rows={[...owners.entries()].sort((a, b) => b[1] - a[1]).map(([label, value]) => ({ label, value }))} />
        </Panel>
      </PanelRow>

      <ListDetail
        list={
          <div className="card">
            <CountTabs tabs={[
              { key: 'active' as TabKey, label: 'Active cases', count: active.length },
              { key: 'OPEN' as TabKey, label: 'With our team', count: withTeam.length },
              { key: 'WAITING_ON_YOU' as TabKey, label: 'Awaiting customer', count: waiting.length },
              { key: 'late' as TabKey, label: 'Late first answer', count: late.length },
              { key: 'RESOLVED' as TabKey, label: 'Resolved', count: done.length },
            ]} value={tab} onChange={setTab} />
            <FilterBar search={q} onSearch={setQ} placeholder="Search reference, subject, customer or owner…">
              <FilterSelect label="Topic" value={topic} onChange={setTopic} options={SUPPORT_TOPICS} />
            </FilterBar>
            <div className="adm-note">Late first answers first · no impersonation or financial actions</div>
            <div className="adm-table-wrap">
              <table className="data">
                <thead><tr><th scope="col">Request</th><th scope="col">From</th><th scope="col">Topic</th><th scope="col">Status</th><th scope="col">Owner</th><th scope="col">First answer due</th></tr></thead>
                <tbody>
                  {open === null && <tr><td colSpan={6} className="empty-row">Loading requests…</td></tr>}
                  {open && shown.length === 0 && <tr><td colSpan={6} className="empty-row">No requests here.</td></tr>}
                  {shown.map((r) => (
                    <tr {...pickRow} key={r.id} className={`pick ${r.id === selected?.id ? 'selected' : ''}`} onClick={() => void pick(r)}>
                      <td><div className="cell-id">{r.reference}</div><div className="cell-main">{r.subject}</div></td>
                      <td className="small">{r.requesterName ?? '—'}</td>
                      <td className="small">{topicLabel(r.topic)}</td>
                      <td><Pill tone={STATUS_TONE[r.status]}>{AGENT_STATUS[r.status]}</Pill></td>
                      <td><OwnerCell assignment={assigned.get('SUPPORT_REQUEST', r.id)} name={r.assignedToName} /></td>
                      <td className="small">{r.firstRespondedAt ? 'Answered'
                        : <span className={r.overdue ? 'late' : ''}>{shortDateTime(r.firstResponseDueAt)}{r.overdue ? ' · late' : ''}</span>}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <TableFoot shown={shown.length} total={source.length} noun={tab === 'RESOLVED' ? 'resolved requests' : 'requests'} />
          </div>
        }
        detail={selected && (
          <DetailPanel title={selected.reference} subtitle={selected.subject} badge={<Pill tone={STATUS_TONE[selected.status]}>{AGENT_STATUS[selected.status]}</Pill>}
            onClose={() => setSelected(null)}>
            {selected.overdue && !selected.firstRespondedAt && <Callout tone="red" title="First answer is late">It was due {shortDateTime(selected.firstResponseDueAt)}.</Callout>}
            <Facts title="Case context" rows={[
              ['Customer', selected.requesterName ?? '—'], ['Topic', topicLabel(selected.topic)], ['Owner', selected.assignedToName ?? 'Unassigned'],
              ['Opened', shortDateTime(selected.createdAt)], ['First answer', selected.firstRespondedAt ? shortDateTime(selected.firstRespondedAt) : `due ${shortDateTime(selected.firstResponseDueAt)}`],
              ...(selected.context.engagement ? [['Engagement', selected.context.engagement] as [string, string]] : []),
              ...(selected.context.page ? [['Page', selected.context.page] as [string, string]] : []),
              ...(selected.context.errorReference ? [['Error reference', selected.context.errorReference] as [string, string]] : []),
              ['Customer sees', SUPPORT_STATUS[selected.status].label],
            ]} />
            <CaseOwner key={selected.id} kind="SUPPORT_REQUEST" caseId={selected.id} assignment={assigned.get('SUPPORT_REQUEST', selected.id)}
              nativeOwner={{ id: selected.assignedTo ?? null, name: selected.assignedToName }}
              onChange={(a) => { assigned.put(a); void supportApi.agentGet(selected.id).then(setSelected).catch(setError); void reload().catch(setError) }} />
            <Callout tone="blue" title="Support boundary">No impersonation, forced acceptance or ledger edits. Point money, verification and safety questions to their teams.</Callout>
            <SupportThread request={selected} agent onReply={async (m, resolve) => {
              setSelected(await supportApi.agentReply(selected.id, m, resolve)); await reload(); assigned.reload()
            }} />
          </DetailPanel>
        )}
      />
    </>
  )
}
