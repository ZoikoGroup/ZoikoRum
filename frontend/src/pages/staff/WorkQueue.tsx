import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react'
import { Link } from 'react-router-dom'
import type { CaseKind } from '../../api/assignments'
import { useAuth } from '../../auth/AuthContext'
import { useCapabilities } from '../../auth/capabilities'
import { api } from '../../api/client'
import { disputeApi, OPEN_PHASES } from '../../api/disputes'
import { duplicatesApi } from '../../api/duplicates'
import { paymentsApi, type OpsItem } from '../../api/escrow'
import { formatMoney } from '../../api/orgs'
import { proApi, taxonomyApi } from '../../api/professional'
import { supportApi } from '../../api/support'
import { verificationApi } from '../../api/verification'
import {
  AdminHeader, AdminKpi, Callout, CountTabs, DetailPanel, Facts, FilterBar, FilterSelect, KpiStrip, ListDetail, Pill, StatusPill,
  TableFoot, label, shortDate, shortDateTime, type PillTone,pickRow } from '../../components/admin'
import { CaseOwner, OwnerCell, useAssignments } from '../../components/CaseOwner'
import { Icon } from '../../components/dashboard'
import { Loading } from '../../components/ui'

/* One work queue across every staff workstream the signed-in person can work. Each item comes from that workstream's own
   queue endpoint; decisions are never made here, only in the source case screen. */

export type Workstream = 'verification' | 'appeals' | 'enforcement' | 'disputes' | 'support' | 'payments' | 'deadletters' | 'incidents'
  | 'duplicates' | 'taxonomy' | 'enterprise'
export type Priority = 'HIGH' | 'MEDIUM' | 'LOW'

export interface WorkItem {
  id: string            // unique across workstreams
  ref: string           // the case reference shown to staff
  subject: string
  subjectSub?: string
  stream: Workstream
  priority: Priority
  priorityWhy: string
  due: string | null
  overdue: boolean
  created: string | null
  status: string
  awaitingOthers: boolean
  to: string
  action: string
  facts: [string, ReactNode][]
  /** The case behind the task, for its owner (admin/assignments.py). Incidents have their own owner instead. */
  caseKind?: CaseKind
  caseId?: string
  /** An owner kept by the case itself: support requests (assignee) and incidents (owner name only). */
  nativeOwner?: { id: string | null; name: string | null }
}

interface StreamDef { key: Workstream; label: string; to: string; cap: string; load: () => Promise<WorkItem[]> }

/** Each workstream's case kind for owners (incidents keep their own owner). */
const STREAM_KIND: Partial<Record<Workstream, CaseKind>> = {
  verification: 'VERIFICATION_CASE', appeals: 'VERIFICATION_APPEAL', enforcement: 'ENFORCEMENT_CASE', disputes: 'DISPUTE', support: 'SUPPORT_REQUEST',
  payments: 'PAYMENT_EXCEPTION', deadletters: 'DEAD_LETTER', duplicates: 'DUPLICATE', taxonomy: 'TAXONOMY_SUGGESTION', enterprise: 'ENTERPRISE_APPLICATION',
}
type Scope = 'mine' | 'team' | 'unassigned' | 'escalated'

const PAGE = '100'
const short = (id: string) => id.replace(/-/g, '').slice(0, 8).toUpperCase()
const isPast = (d: string | null | undefined) => !!d && new Date(d).getTime() < Date.now()

interface EnforcementRow { id: string; subjectType: string; summary: string; signalSource: string; level: number; status: string
  triageDueAt: string | null; overdue: boolean; createdAt: string }
interface DeadLetter { id: string; eventType: string; consumer: string; attempts: number; financial: boolean; lastError: string }
interface IncidentRow { id: string; reference: string; title: string; kind: string; severity: string; status: string; owner: string; detectedAt: string }

const OPS_KIND: Record<OpsItem['kind'], string> = { PAYOUT: 'Payout to a professional', REFUND: 'Refund to a buyer', CHARGEBACK_LOSS: 'Chargeback loss' }

export const STREAMS: StreamDef[] = [
  { key: 'verification', label: 'Verification', to: '/platform-admin/verification-center', cap: 'verification.read',
    load: async () => (await verificationApi.queue()).items.map((q) => ({
      id: `verification:${q.id}`, caseKind: 'VERIFICATION_CASE', caseId: q.id, ref: `VER-${short(q.id)}`, subject: q.subjectName ?? 'Unknown subject',
      subjectSub: [q.label, q.jurisdiction].filter(Boolean).join(' · '), stream: 'verification',
      priority: q.overdue ? 'HIGH' : q.flaggedEvidence ? 'MEDIUM' : 'LOW',
      priorityWhy: q.overdue ? 'Past its published service level' : q.flaggedEvidence ? `${q.flaggedEvidence} file(s) flagged by the automatic check` : 'Within service level',
      due: q.estimatedCompletion, overdue: q.overdue, created: q.createdAt, status: q.status,
      awaitingOthers: q.status === 'NEEDS_INFO' || q.hostedStatus === 'pending', to: '/platform-admin/verification-center', action: 'Review case',
      facts: [['Check', q.label], ['Subject type', label(q.subjectType)], ['Jurisdiction', q.jurisdiction ?? '—'], ['Documents', q.evidenceCount],
        ['Provider result', q.providerResult ?? '—']],
    })) },
  { key: 'appeals', label: 'Appeals', to: '/platform-admin/verification-center', cap: 'verification.read',
    load: async () => (await verificationApi.appeals()).filter((a) => a.status === 'OPEN').map((a) => ({
      id: `appeals:${a.id}`, caseKind: 'VERIFICATION_APPEAL', caseId: a.id, ref: `APL-${short(a.id)}`, subject: a.subjectName ?? 'Unknown subject', subjectSub: a.caseLabel, stream: 'appeals',
      priority: a.canDecide ? 'MEDIUM' : 'LOW', priorityWhy: a.canDecide ? 'Waiting for an independent decision' : 'You made the original decision: another officer decides',
      due: null, overdue: false, created: a.filedAt, status: a.status, awaitingOthers: !a.canDecide, to: '/platform-admin/verification-center', action: 'Review appeal',
      facts: [['Check', a.caseLabel], ['Original reason', a.originalReason ?? '—'], ['Evidence', a.evidenceCount], ['You can decide', a.canDecide ? 'Yes' : 'No']],
    })) },
  { key: 'enforcement', label: 'Trust & safety', to: '/platform-admin/trust-safety', cap: 'safety.read',
    load: async () => {
      const q = (status: string) => api<EnforcementRow[]>('/v1/admin/enforcement-cases', { query: { status, limit: PAGE } })
      return (await Promise.all([q('TRIAGE'), q('ASSESSED')])).flat().map((c) => ({
        id: `enforcement:${c.id}`, caseKind: 'ENFORCEMENT_CASE' as const, caseId: c.id, ref: `SAFE-${short(c.id)}`, subject: c.summary, subjectSub: `${label(c.subjectType)} · Level ${c.level}`, stream: 'enforcement',
        priority: c.overdue || c.level >= 3 ? 'HIGH' : c.level >= 2 ? 'MEDIUM' : 'LOW',
        priorityWhy: c.overdue ? 'Past its triage target' : `Level ${c.level} case`,
        due: c.triageDueAt, overdue: c.overdue, created: c.createdAt, status: c.status, awaitingOthers: false, to: '/platform-admin/trust-safety', action: 'Open case',
        facts: [['Subject type', label(c.subjectType)], ['Signal source', label(c.signalSource)], ['Level', c.level]],
      }))
    } },
  { key: 'disputes', label: 'Disputes', to: '/platform-admin/dispute-resolution', cap: 'disputes.read',
    load: async () => (await disputeApi.list('operator')).filter((d) => OPEN_PHASES.includes(d.status)).map((d) => {
      const due = d.status === 'EVIDENCE_COLLECTION' ? d.evidenceDeadline : d.status === 'DIRECT_RESOLUTION' ? d.directDeadline : null
      const overdue = isPast(due)
      return {
        id: `disputes:${d.id}`, caseKind: 'DISPUTE' as const, caseId: d.id, ref: d.reference, subject: d.contractReference, subjectSub: label(d.category), stream: 'disputes' as const,
        priority: (overdue || d.status === 'MEDIATION' ? 'HIGH' : 'MEDIUM') as Priority,
        priorityWhy: overdue ? 'Deadline for this phase has passed' : d.status === 'MEDIATION' ? 'In mediation: needs the mediator' : 'Parties are working on it',
        due, overdue, created: d.createdAt, status: d.status, awaitingOthers: d.status !== 'MEDIATION', to: '/platform-admin/dispute-resolution', action: 'Open case',
        facts: [['Amount in dispute', formatMoney(d.disputed)], ['Raised by', label(d.initiatorParty)], ['Desired outcome', label(d.desiredOutcome)],
          ['Mediator assigned', d.mediatorAssigned ? 'Yes' : 'No'], ['Next step', d.nextStep]] as [string, ReactNode][],
      }
    }) },
  { key: 'support', label: 'Support', to: '/platform-admin/support-cases', cap: 'support.read',
    load: async () => (await supportApi.queue('OPEN')).map((r) => ({
      id: `support:${r.id}`, caseKind: 'SUPPORT_REQUEST', caseId: r.id, nativeOwner: { id: r.assignedTo ?? null, name: r.assignedToName }, ref: r.reference, subject: r.subject, subjectSub: [r.requesterName, label(r.topic)].filter(Boolean).join(' · '), stream: 'support',
      priority: r.overdue ? 'HIGH' : !r.firstRespondedAt && new Date(r.firstResponseDueAt).getTime() - Date.now() < 86_400_000 ? 'MEDIUM' : 'LOW',
      priorityWhy: r.overdue ? 'Past its first-response target' : r.firstRespondedAt ? 'Answered, still open' : 'Waiting for a first response',
      due: r.firstRespondedAt ? null : r.firstResponseDueAt, overdue: r.overdue, created: r.createdAt, status: r.status, awaitingOthers: false,
      to: '/platform-admin/support-cases', action: 'Reply',
      facts: [['Requester', r.requesterName ?? '—'], ['Topic', label(r.topic)], ['Assigned to', r.assignedToName ?? 'Unassigned'], ['Messages', r.messages.length]],
    })) },
  { key: 'payments', label: 'Payments', to: '/platform-admin/financial-exceptions', cap: 'finexceptions.read',
    load: async () => (await paymentsApi.opsWorklist()).items.filter((i) => !i.resolvedAt).map((i) => ({
      id: `payments:${i.kind}:${i.id}`, caseKind: 'PAYMENT_EXCEPTION', caseId: i.id, ref: `PAY-${short(i.id)}`, subject: OPS_KIND[i.kind], subjectSub: `${i.engagement} · ${formatMoney(i.amount)}`, stream: 'payments',
      priority: i.kind === 'CHARGEBACK_LOSS' || !i.canRetry ? 'HIGH' : 'MEDIUM',
      priorityWhy: i.kind === 'CHARGEBACK_LOSS' ? 'Money lost to a chargeback' : i.canRetry ? 'Can be retried' : 'Cannot be retried automatically',
      due: null, overdue: false, created: i.since, status: i.canRetry ? 'RETRY_AVAILABLE' : 'NEEDS_RESOLUTION', awaitingOthers: false,
      to: '/platform-admin/financial-exceptions', action: 'Investigate',
      facts: [['Amount', formatMoney(i.amount)], ['Problem', i.problem], ['Buyer', i.buyer], ['Professional', i.professional]],
    })) },
  { key: 'deadletters', label: 'Failed deliveries', to: '/platform-admin/failed-event-deliveries', cap: 'dlq.read',
    load: async () => (await api<DeadLetter[]>('/v1/admin/dead-letters', { query: { limit: PAGE } })).map((r) => ({
      id: `deadletters:${r.id}`, caseKind: 'DEAD_LETTER', caseId: r.id, ref: `DLQ-${short(r.id)}`, subject: r.eventType, subjectSub: r.consumer, stream: 'deadletters',
      priority: r.financial ? 'HIGH' : 'MEDIUM', priorityWhy: r.financial ? 'Affects money' : 'Delivery stopped after retries',
      due: null, overdue: false, created: null, status: 'DEAD', awaitingOthers: false, to: '/platform-admin/failed-event-deliveries', action: 'Replay',
      facts: [['Consumer', r.consumer], ['Attempts', r.attempts], ['Affects money', r.financial ? 'Yes' : 'No'], ['Last error', r.lastError]],
    })) },
  { key: 'incidents', label: 'Incidents', to: '/platform-admin/incident-command', cap: 'incidents.read',
    load: async () => (await api<IncidentRow[]>('/v1/admin/incidents')).filter((i) => i.status !== 'CLOSED').map((i) => ({
      id: `incidents:${i.id}`, nativeOwner: { id: null, name: i.owner }, ref: i.reference, subject: i.title, subjectSub: `${label(i.kind)} · ${i.severity}`, stream: 'incidents',
      priority: i.severity === 'SEV1' || i.severity === 'SEV2' ? 'HIGH' : i.severity === 'SEV3' ? 'MEDIUM' : 'LOW', priorityWhy: `Severity ${i.severity}`,
      due: null, overdue: false, created: i.detectedAt, status: i.status, awaitingOthers: false, to: '/platform-admin/incident-command', action: 'Open incident',
      facts: [['Severity', i.severity], ['Kind', label(i.kind)], ['Owner', i.owner]],
    })) },
  { key: 'duplicates', label: 'Duplicate identities', to: '/platform-admin/duplicate-identity-cases', cap: 'identity_cases.read',
    load: async () => (await duplicatesApi.queue()).filter((d) => d.status === 'OPEN' || d.status === 'ANSWERED').map((d) => ({
      id: `duplicates:${d.id}`, caseKind: 'DUPLICATE', caseId: d.id, ref: `DUP-${short(d.id)}`, subject: [d.accountName, d.otherAccountName].filter(Boolean).join(' / ') || 'Two accounts', subjectSub: label(d.signal),
      stream: 'duplicates', priority: d.status === 'ANSWERED' ? 'MEDIUM' : 'LOW',
      priorityWhy: d.status === 'ANSWERED' ? 'The person has answered: ready to resolve' : 'Waiting for the person to answer',
      due: null, overdue: false, created: d.createdAt, status: d.status, awaitingOthers: d.status === 'OPEN', to: '/platform-admin/duplicate-identity-cases', action: 'Review',
      facts: [['Signal', label(d.signal)], ['Answer', d.userAnswer ? label(d.userAnswer) : '—'], ['Note', d.userNote ?? '—']],
    })) },
  { key: 'taxonomy', label: 'Taxonomy', to: '/platform-admin/taxonomy-standards', cap: 'taxonomy.read',
    load: async () => (await taxonomyApi.queue()).filter((s) => s.status === 'PENDING').map((s) => ({
      id: `taxonomy:${s.id}`, caseKind: 'TAXONOMY_SUGGESTION', caseId: s.id, ref: `TAX-${short(s.id)}`, subject: s.name, subjectSub: s.professionalName ?? label(s.source), stream: 'taxonomy',
      priority: 'LOW', priorityWhy: 'Specialization suggestion', due: null, overdue: false, created: s.createdAt, status: s.status, awaitingOthers: false,
      to: '/platform-admin/taxonomy-standards', action: 'Review',
      facts: [['Their words', s.text], ['Category', s.categorySlug ?? '—'], ['Credential likely', s.credentialLikely ? 'Yes' : 'No']],
    })) },
  { key: 'enterprise', label: 'Enterprise readiness', to: '/platform-admin/enterprise-readiness', cap: 'enterprise.read',
    load: async () => (await proApi.enterpriseApplications()).map((a) => {
      const met = a.requirements.filter((r) => r.met).length
      return {
        id: `enterprise:${a.professionalId}`, caseKind: 'ENTERPRISE_APPLICATION' as const, caseId: a.professionalId, ref: `ENT-${short(a.professionalId)}`, subject: a.name, subjectSub: a.headline ?? undefined, stream: 'enterprise' as const,
        priority: (met === a.requirements.length ? 'MEDIUM' : 'LOW') as Priority,
        priorityWhy: `${met} of ${a.requirements.length} requirements met`, due: null, overdue: false, created: a.appliedAt, status: 'PENDING_REVIEW',
        awaitingOthers: false, to: '/platform-admin/enterprise-readiness', action: 'Review case',
        facts: [['Requirements met', `${met} of ${a.requirements.length}`], ['Attestation', a.attestation ? shortDate(a.attestation.attestedAt) : 'Missing']] as [string, ReactNode][],
      }
    }) },
]

export const streamsFor = (caps: readonly string[]) => STREAMS.filter((s) => caps.includes(s.cap))
export const STREAM_LABEL = Object.fromEntries(STREAMS.map((s) => [s.key, s.label])) as Record<Workstream, string>

const RANK: Record<Priority, number> = { HIGH: 0, MEDIUM: 1, LOW: 2 }
/** Most urgent first: priority, then overdue, then the soonest due date, then the oldest. */
export function byUrgency(a: WorkItem, b: WorkItem) {
  return RANK[a.priority] - RANK[b.priority] || Number(b.overdue) - Number(a.overdue)
    || (a.due ? new Date(a.due).getTime() : Infinity) - (b.due ? new Date(b.due).getTime() : Infinity)
    || (a.created ? new Date(a.created).getTime() : Infinity) - (b.created ? new Date(b.created).getTime() : Infinity)
}

export const PRIORITY_TONE: Record<Priority, PillTone> = { HIGH: 'red', MEDIUM: 'amber', LOW: 'green' }
export const PriorityPill = ({ p }: { p: Priority }) => <Pill tone={PRIORITY_TONE[p]}>{label(p)}</Pill>

/** Loads every queue the staff capabilities can work. Failed queues are reported by name, never shown as zero. */
export function useWorkItems(caps: readonly string[]) {
  const key = caps.join(',')
  const [items, setItems] = useState<WorkItem[] | null>(null)
  const [failed, setFailed] = useState<string[]>([])
  const [loadedAt, setLoadedAt] = useState<Date | null>(null)
  const [tick, setTick] = useState(0)
  useEffect(() => {
    let live = true
    const streams = streamsFor(key.split(','))
    Promise.allSettled(streams.map((s) => s.load())).then((results) => {
      if (!live) return
      setItems(results.flatMap((r) => (r.status === 'fulfilled' ? r.value : [])).sort(byUrgency))
      setFailed(results.flatMap((r, i) => (r.status === 'rejected' ? [streams[i].label] : [])))
      setLoadedAt(new Date())
    })
    return () => { live = false }
  }, [key, tick])
  const reload = useCallback(() => setTick((t) => t + 1), [])
  return { items, failed, loadedAt, reload }
}

function dueCell(i: WorkItem) {
  if (!i.due) return <span className="muted small">{i.created ? `Opened ${shortDate(i.created)}` : '—'}</span>
  const ms = new Date(i.due).getTime() - Date.now()
  const hours = Math.round(ms / 3_600_000)
  const text = i.overdue || ms < 0 ? `${Math.max(1, Math.round(-ms / 86_400_000))} day(s) overdue` : hours < 24 ? `Due in ${Math.max(0, hours)} h` : `${Math.round(hours / 24)} day(s) left`
  return <><div className="cell-main">{shortDate(i.due)}</div><div className="cell-sub" style={i.overdue || ms < 0 ? { color: 'var(--zk-danger)' } : undefined}>{text}</div></>
}

const dueSoon = (i: WorkItem) => !!i.due && !i.overdue && new Date(i.due).getTime() - Date.now() <= 86_400_000 && new Date(i.due).getTime() >= Date.now()
const PER_PAGE = 25

export default function WorkQueue() {
  const { user } = useAuth()
  const { caps: held } = useCapabilities()
  const roles = useMemo(() => [...held].sort(), [held])
  const { items, failed, loadedAt, reload } = useWorkItems(roles)
  const [scope, setScope] = useState<Scope>('team')
  const [tab, setTab] = useState<'all' | Workstream>('all')
  const [search, setSearch] = useState('')
  const [priority, setPriority] = useState('')
  const [due, setDue] = useState('')
  const [status, setStatus] = useState('')
  const [page, setPage] = useState(1)
  const [selectedId, setSelectedId] = useState<string | null>(null)

  const all = useMemo(() => items ?? [], [items])
  const streams = streamsFor(roles)
  const kinds = useMemo(() => streamsFor(roles).flatMap((s) => STREAM_KIND[s.key] ?? []), [roles])
  const assigned = useAssignments(kinds)
  const assignmentOf = (i: WorkItem) => (i.caseKind && i.caseId ? assigned.get(i.caseKind, i.caseId) : undefined)
  // The shared record wins once it exists (it already carries a support request's own owner); otherwise the case's own owner.
  const ownerOf = (i: WorkItem) => { const a = assignmentOf(i); return a ? { id: a.ownerId, name: a.ownerName } : i.nativeOwner ?? null }
  const ownerIdOf = (i: WorkItem) => ownerOf(i)?.id ?? null
  const hasOwner = (i: WorkItem) => !!(ownerOf(i)?.id || ownerOf(i)?.name)
  const inScope = (i: WorkItem, s: Scope) => s === 'team' ? true : s === 'mine' ? !!user && ownerIdOf(i) === user.id
    : s === 'unassigned' ? !hasOwner(i) : !!assignmentOf(i)?.escalated
  const scoped = all.filter((i) => inScope(i, scope))
  const ready = !!items && !!assigned.map
  const scopeCount = (s: Scope) => (ready ? all.filter((i) => inScope(i, s)).length : null)
  const counts = (s: Workstream) => scoped.filter((i) => i.stream === s).length
  const q = search.trim().toLowerCase()
  const shown = scoped.filter((i) => (tab === 'all' || i.stream === tab) && (!priority || i.priority === priority)
    && (!status || i.status === status)
    && (!due || (due === 'overdue' ? i.overdue : due === '24h' ? dueSoon(i) : due === 'none' ? !i.due : !!i.due && !i.overdue && !dueSoon(i)))
    && (!q || `${i.ref} ${i.subject} ${i.subjectSub ?? ''}`.toLowerCase().includes(q)))
  const pages = Math.max(1, Math.ceil(shown.length / PER_PAGE))
  const current = Math.min(page, pages)
  const pageRows = shown.slice((current - 1) * PER_PAGE, current * PER_PAGE)
  const selected = all.find((i) => i.id === selectedId) ?? null
  const statuses = [...new Set(all.map((i) => i.status))].sort()

  const overdue = all.filter((i) => i.overdue).length
  const soon = all.filter(dueSoon)
  const high = all.filter((i) => i.priority === 'HIGH')
  const awaiting = all.filter((i) => i.awaitingOthers).length
  const mine = all.filter((i) => inScope(i, 'mine'))
  const breakdown = (rows: WorkItem[]) => {
    const by = new Map<string, number>()
    rows.forEach((r) => by.set(STREAM_LABEL[r.stream], (by.get(STREAM_LABEL[r.stream]) ?? 0) + 1))
    return [...by.entries()].slice(0, 2).map(([k, n]) => `${n} ${k.toLowerCase()}`).join(' · ') || 'None'
  }

  if (!user) return null
  return (
    <>
      <AdminHeader crumb="Overview / Operational workspace" title="My Work Queue"
        subtitle="Prioritise open cases across every workstream your roles can work, then act in the source case."
        actions={<button type="button" className="btn btn-secondary" onClick={() => { setSelectedId(null); reload() }}><Icon name="refresh" /> Refresh</button>}
        meta={loadedAt && <span className="live">Queues you can work · Updated {loadedAt.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' })}</span>} />

      {failed.length > 0 && <Callout tone="red" title="Some queues could not be loaded">{failed.join(', ')}: open those screens directly. Their items are not counted below.</Callout>}
      {streams.length === 0 && <Callout tone="blue" title="No work queues for your roles">Your staff roles do not include a case queue.</Callout>}

      <KpiStrip>
        <AdminKpi icon="list" tone="blue" label="Active tasks" value={items ? all.length : '—'} sub={items ? `Across ${streams.length} workstream${streams.length === 1 ? '' : 's'}` : ' '} />
        <AdminKpi icon="user" tone="green" label="Assigned to me" value={ready ? mine.length : '—'} sub={ready ? breakdown(mine) : ' '} />
        <AdminKpi icon="clock" tone="amber" label="Due in 24 hours" value={items ? soon.length : '—'} sub={items ? breakdown(soon) : ' '} />
        <AdminKpi icon="alert" tone="red" label="Overdue" value={items ? overdue : '—'} sub="Past the published target" />
        <AdminKpi icon="shield" tone="red" label="High priority" value={items ? high.length : '—'} sub={items ? breakdown(high) : ' '} />
        <AdminKpi icon="team" tone="violet" label="Awaiting others" value={items ? awaiting : '—'} sub="Evidence, answers or another reviewer" />
      </KpiStrip>

      <ListDetail
        list={
          <div className="card">
            <CountTabs value={scope} onChange={(s) => { setScope(s); setPage(1) }}
              tabs={[{ key: 'mine' as const, label: 'Assigned to me', count: scopeCount('mine') },
                { key: 'team' as const, label: 'Team queue', count: scopeCount('team') },
                { key: 'unassigned' as const, label: 'Unassigned', count: scopeCount('unassigned') },
                { key: 'escalated' as const, label: 'Escalations', count: scopeCount('escalated') }]} />
            <CountTabs value={tab} onChange={(t) => { setTab(t); setPage(1) }}
              tabs={[{ key: 'all' as const, label: 'All workstreams', count: items ? scoped.length : null },
                ...streams.map((s) => ({ key: s.key, label: s.label, count: items ? counts(s.key) : null }))]} />
            <FilterBar search={search} onSearch={(v) => { setSearch(v); setPage(1) }} placeholder="Search case ID or subject">
              <FilterSelect label="Any priority" value={priority} onChange={(v) => { setPriority(v); setPage(1) }} options={[['HIGH', 'High'], ['MEDIUM', 'Medium'], ['LOW', 'Low']]} />
              <FilterSelect label="Any due date" value={due} onChange={(v) => { setDue(v); setPage(1) }}
                options={[['overdue', 'Overdue'], ['24h', 'Due in 24 hours'], ['later', 'Due later'], ['none', 'No due date']]} />
              <FilterSelect label="Any status" value={status} onChange={(v) => { setStatus(v); setPage(1) }} options={statuses.map((s) => [s, label(s)])} />
            </FilterBar>
            {assigned.failed && <div className="adm-note">Case owners could not be loaded: owners and escalations are not shown.</div>}
            <div className="adm-note">Showing {shown.length} of {all.length} tasks · sorted by urgency</div>
            {items === null ? <div style={{ padding: 16 }}><Loading lines={4} /></div> : (
              <div className="adm-table-wrap">
                <table className="data">
                  <thead><tr><th scope="col">Case / subject</th><th scope="col">Workstream</th><th scope="col">Priority</th><th scope="col">Due / SLA</th><th scope="col">Workflow status</th><th scope="col">Owner</th><th scope="col">Action</th></tr></thead>
                  <tbody>
                    {pageRows.length === 0 ? <tr><td colSpan={7} className="empty-row muted">{all.length ? 'No tasks match these filters.' : 'Nothing waiting in your queues.'}</td></tr>
                      : pageRows.map((i) => (
                        <tr {...pickRow} key={i.id} className={`pick ${i.id === selectedId ? 'selected' : ''}`} onClick={() => setSelectedId(i.id)}>
                          <td><div className="cell-id">{i.ref}</div><div className="cell-main">{i.subject}</div>{i.subjectSub && <div className="cell-sub">{i.subjectSub}</div>}</td>
                          <td>{STREAM_LABEL[i.stream]}</td>
                          <td><PriorityPill p={i.priority} /></td>
                          <td>{dueCell(i)}</td>
                          <td><StatusPill status={i.status} /></td>
                          <td><OwnerCell assignment={assignmentOf(i)} name={ownerOf(i)?.name ?? null} /></td>
                          <td><Link className="btn btn-secondary btn-sm" to={i.to} onClick={(e) => e.stopPropagation()}>{i.action}</Link></td>
                        </tr>))}
                  </tbody>
                </table>
              </div>
            )}
            <TableFoot shown={pageRows.length} total={shown.length} noun="tasks" page={current} pages={pages} onPage={setPage} />
          </div>
        }
        detail={selected && (
          <DetailPanel title={selected.subject} subtitle={<>{STREAM_LABEL[selected.stream]} · {selected.ref}</>}
            badge={<PriorityPill p={selected.priority} />} onClose={() => setSelectedId(null)}
            footer={<Link className="btn btn-primary" to={selected.to}>Open case <Icon name="arrow" /></Link>}>
            <Facts title="Task" rows={[
              ['Workstream', STREAM_LABEL[selected.stream]],
              ['Status', <StatusPill key="s" status={selected.status} />],
              ['Priority', selected.priorityWhy],
              ['Due', selected.due ? <span key="d" style={selected.overdue ? { color: 'var(--zk-danger)' } : undefined}>{shortDateTime(selected.due)}{selected.overdue ? ' · overdue' : ''}</span> : '—'],
              ['Opened', selected.created ? shortDateTime(selected.created) : '—'],
              ['Awaiting others', selected.awaitingOthers ? 'Yes' : 'No'],
            ]} />
            {selected.caseKind && selected.caseId
              ? <CaseOwner key={selected.id} kind={selected.caseKind} caseId={selected.caseId} assignment={assignmentOf(selected)}
                nativeOwner={selected.nativeOwner} onChange={assigned.put}
                note={selected.stream === 'disputes' ? 'The operational owner is separate from the neutral mediator assigned in the case.' : undefined} />
              : selected.nativeOwner && <Facts title="Owner" rows={[['Incident owner', selected.nativeOwner.name ?? '—']]} />}
            <Facts title="Case details" rows={selected.facts} />
            <Callout tone="blue" title="Decide in the source case">Sensitive decisions are made in the source case, with a reason, evidence, the right authority and an audit record.</Callout>
          </DetailPanel>
        )}
      />
      <p className="adm-foot-note">The work queue shows task metadata only: no bulk approvals, payment releases or enforcement happen here.</p>
    </>
  )
}
