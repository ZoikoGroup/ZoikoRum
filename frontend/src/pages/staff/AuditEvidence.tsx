import { useCallback, useEffect, useState } from 'react'
import { api } from '../../api/client'
import { openStoredFile } from '../../api/files'
import { verifyAuditChain, type ChainCheck } from '../../api/audit'
import { useAuth } from '../../auth/AuthContext'
import {
  AdminHeader, AdminKpi, Callout, CountTabs, DetailPanel, Facts, FilterBar, FilterSelect, KpiStrip, ListDetail, MetricList,
  Panel, PanelRow, Pill, StatusPill, TableFoot, label, shortDate, shortDateTime,
} from '../../components/admin'
import { Icon } from '../../components/dashboard'
import { ErrorAlert, useStepUp } from '../../components/ui'

/* Audit & Evidence (staff design 53). Replaces AuditExportsPage and the AuditArchives panel: ledger integrity check,
   export requests (step-up), write-once archives, and the audit record stream from /v1/audit/records. Figures shown
   are only those the API returns; the chain check result is from the check run on this page. */

interface AuditRow {
  id: string; seq: number; action: string; actorId: string | null; actorType?: string | null; authStrength?: string | null
  objectType: string; objectId: string; tenantId?: string | null; correlationId?: string | null; causationId?: string | null
  policyVersion?: string | null; evidenceHash?: string | null; sourceEventId?: string | null
  details: Record<string, unknown>; occurredAt: string; prevHash?: string; hash?: string
}
interface AuditExport { id: string; status: string; format: string; recordCount: number | null; contentSha256: string | null; chainHeadHash: string | null; createdAt?: string }
interface Archive { id: string; fromSeq: number; toSeq: number; records: number; sha256: string; objectKey: string; locked: boolean; archivedAt: string; lastVerifiedAt: string | null }

type Tab = 'events' | 'exports' | 'archives'
type Sel = { kind: Tab; id: string } | null

export default function AuditEvidence() {
  const { user } = useAuth()
  const canVerify = !!user?.platformRoles.some((r) => r === 'COMPLIANCE_OFFICER' || r === 'PLATFORM_ADMIN')
  const [error, setError] = useState<unknown>(null)
  const [tab, setTab] = useState<Tab>('events')
  const [sel, setSel] = useState<Sel>(null)

  // Ledger integrity
  const [check, setCheck] = useState<(ChainCheck & { at: Date }) | null>(null)
  const [checking, setChecking] = useState(false)
  async function verify() {
    setChecking(true); setError(null)
    try { setCheck({ ...(await verifyAuditChain()), at: new Date() }) } catch (err) { setError(err) } finally { setChecking(false) }
  }

  // Records
  const [records, setRecords] = useState<AuditRow[] | null>(null)
  const [scope, setScope] = useState({ objectType: '', objectId: '', tenantId: '', correlationId: '' })
  const [applied, setApplied] = useState(scope)
  const [limit, setLimit] = useState('200')
  const [q, setQ] = useState('')
  const [action, setAction] = useState('')
  const [actorType, setActorType] = useState('')
  const [page, setPage] = useState(1)
  const loadRecords = useCallback(() => {
    setRecords(null)
    const query: Record<string, string> = { limit, newestFirst: 'true' }
    for (const [k, v] of Object.entries(applied)) if (v.trim()) query[k] = v.trim()
    api<{ items: AuditRow[] }>('/v1/audit/records', { query }).then((r) => setRecords(r.items)).catch((e) => { setRecords([]); setError(e) })
  }, [applied, limit])
  useEffect(() => { loadRecords() }, [loadRecords])

  // Archives
  const [archives, setArchives] = useState<Archive[] | null>(null)
  const [archiveResult, setArchiveResult] = useState<Record<string, { ok: boolean; text: string }>>({})
  useEffect(() => { api<Archive[]>('/v1/admin/audit/archives').then(setArchives).catch(() => setArchives(null)) }, [])
  const verifyArchive = (a: Archive) => api<{ ok: boolean; problems: string[] }>(`/v1/admin/audit/archives/${a.id}/verify`, { method: 'POST' })
    .then((r) => setArchiveResult((prev) => ({ ...prev, [a.id]: { ok: r.ok, text: r.ok ? 'Unchanged and the chain holds' : r.problems.join('; ') } }))).catch(setError)

  // Exports (requested in this session: the API has no list of past exports)
  const [jobs, setJobs] = useState<AuditExport[]>([])
  const [showExport, setShowExport] = useState(false)
  const [busy, setBusy] = useState(false)
  const { run, modal } = useStepUp(setError)

  const rows = records ?? []
  const actions = [...new Set(rows.map((r) => r.action))].sort()
  const actorTypes = [...new Set(rows.map((r) => r.actorType).filter((x): x is string => !!x))].sort()
  const term = q.trim().toLowerCase()
  const filtered = rows.filter((r) => (!action || r.action === action) && (!actorType || r.actorType === actorType)
    && (!term || `${r.seq} ${r.action} ${r.actorId ?? ''} ${r.objectType} ${r.objectId} ${r.correlationId ?? ''}`.toLowerCase().includes(term)))
  const PER = 25
  const pages = Math.max(1, Math.ceil(filtered.length / PER))
  const shown = filtered.slice((page - 1) * PER, page * PER)
  const head = rows[0]
  const archivedRecords = archives?.reduce((n, a) => n + a.records, 0) ?? null
  const lastArchive = archives?.[0] ?? null
  const legalHolds = archives?.filter((a) => a.locked).length ?? null

  const selRecord = sel?.kind === 'events' ? rows.find((r) => r.id === sel.id) ?? null : null
  const selJob = sel?.kind === 'exports' ? jobs.find((j) => j.id === sel.id) ?? null : null
  const selArchive = sel?.kind === 'archives' ? archives?.find((a) => a.id === sel.id) ?? null : null

  return (
    <>
      <AdminHeader crumb="Trust, risk & compliance / Governance and forensic assurance" title="Audit & Evidence"
        subtitle="Verify record integrity, supervise evidence preservation, and generate verifiable export packages."
        actions={<>
          {canVerify && <button type="button" className="btn btn-secondary" onClick={verify} disabled={checking}>
            <Icon name="shield" /> {checking ? 'Verifying…' : 'Verify ledger integrity'}</button>}
          <button type="button" className="btn btn-primary" onClick={() => setShowExport((v) => !v)}><Icon name="download" /> Request export</button>
        </>}
        meta={<>{check && <span>Last checked {check.at.toLocaleTimeString()}</span>}{head && <span>Ledger head #{head.seq.toLocaleString()}</span>}</>} />
      <ErrorAlert error={error} />
      {modal}

      <KpiStrip>
        <AdminKpi icon="shield" tone={check ? (check.valid ? 'green' : 'red') : 'blue'} label="Latest chain check"
          value={check ? (check.valid ? 'PASS' : 'BROKEN') : 'Not run'} sub={check ? `Verified ${check.at.toLocaleTimeString()}` : canVerify ? 'Run a check to see the result' : 'Compliance Officers and Platform Admins'} />
        <AdminKpi icon="list" tone="blue" label="Records checked" value={check ? check.checked.toLocaleString() : '—'} sub="Whole ledger, in order" />
        <AdminKpi icon="alert" tone={check && !check.valid ? 'red' : 'green'} label="Integrity mismatches" value={check ? (check.valid ? 0 : 1) : '—'}
          sub={check && !check.valid ? `Broken at record #${check.brokenAtSeq}` : 'A check stops at the first break'} />
        <AdminKpi icon="download" tone="amber" label="Export requests" value={jobs.length} sub="Requested in this session" />
        <AdminKpi icon="lock" tone="violet" label="Legal holds" value={legalHolds ?? '—'} sub="Archive batches locked" />
        <AdminKpi icon="layers" tone="teal" label="Archived records" value={archivedRecords != null ? archivedRecords.toLocaleString() : '—'}
          sub={archives ? `${archives.length} write-once batches` : 'Not available to your role'} />
      </KpiStrip>

      <PanelRow cols={3}>
        <Panel title="Integrity & provenance" action={check && <Pill tone={check.valid ? 'green' : 'red'}>Run: {check.valid ? 'pass' : 'broken'}</Pill>}>
          <p className="muted small" style={{ marginTop: 0 }}>Recomputes every record's SHA-256 hash in order and checks it links to the one before. The worker also re-checks it hourly.</p>
          <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap', marginBottom: 10 }}>
            <Pill tone="green">Ledger</Pill><span aria-hidden>→</span><Pill tone="green">SHA-256 links</Pill><span aria-hidden>→</span><Pill tone="green">Head hash</Pill>
          </div>
          {!check ? (canVerify ? <button type="button" className="btn btn-secondary btn-sm" onClick={verify} disabled={checking}>{checking ? 'Verifying…' : 'Verify ledger integrity'}</button>
            : <p className="muted small" style={{ margin: 0 }}>Only Compliance Officers and Platform Admins can run the check.</p>)
            : check.valid ? <div className="alert alert-success" role="status" style={{ margin: 0 }}>
              Intact: all {check.checked.toLocaleString()} records verified at {check.at.toLocaleTimeString()}.
              {check.headHash && <span className="ref">Head hash <code style={{ overflowWrap: 'anywhere' }}>{check.headHash}</code></span>}</div>
              : <div className="alert alert-error" role="alert" style={{ margin: 0 }}>
                Broken at record #{check.brokenAtSeq} ({check.checked.toLocaleString()} records verified before it). A HashChainBroken incident was raised;
                treat the ledger after that point as untrusted until investigated.</div>}
        </Panel>
        <Panel title="Evidence export governance" action={<Pill tone="amber">Step-up required</Pill>}>
          <p className="muted small" style={{ marginTop: 0 }}>Exports are generated on demand from the append-only ledger and carry the chain head hash and a content fingerprint.</p>
          <MetricList rows={[
            { label: 'Requested this session', value: jobs.length },
            { label: 'Records exported this session', value: jobs.reduce((n, j) => n + (j.recordCount ?? 0), 0).toLocaleString() },
          ]} />
          <button type="button" className="btn btn-secondary btn-sm" style={{ marginTop: 10 }} onClick={() => setShowExport(true)}>New export request</button>
        </Panel>
        <Panel title="Retention & archives">
          <p className="muted small" style={{ marginTop: 0 }}>Records older than 90 days are copied daily to write-once storage; the database keeps them too.</p>
          {archives ? <MetricList rows={[
            { label: 'Latest archive', value: lastArchive ? shortDateTime(lastArchive.archivedAt) : 'Nothing archived yet' },
            { label: 'Latest batch', value: lastArchive ? `#${lastArchive.fromSeq}–#${lastArchive.toSeq}` : '—' },
            { label: 'Last read-back check', value: lastArchive?.lastVerifiedAt ? shortDateTime(lastArchive.lastVerifiedAt) : '—' },
          ]} /> : <p className="muted small" style={{ margin: 0 }}>Archive details are not available to your role.</p>}
        </Panel>
      </PanelRow>

      {showExport && <ExportForm busy={busy} onCancel={() => setShowExport(false)} onSubmit={(body) => {
        setBusy(true)
        run(async () => {
          try {
            const job = await api<AuditExport>('/v1/audit/exports', { method: 'POST', body })
            setJobs((list) => [job, ...list]); setTab('exports'); setSel({ kind: 'exports', id: job.id }); setShowExport(false)
          } finally { setBusy(false) }
        })
      }} />}

      <ListDetail list={
        <div className="card">
          <CountTabs tabs={[
            { key: 'events' as Tab, label: 'Audit events', count: records ? rows.length : null },
            { key: 'exports' as Tab, label: 'Export requests', count: jobs.length },
            { key: 'archives' as Tab, label: 'Archives', count: archives ? archives.length : null },
          ]} value={tab} onChange={(t) => { setTab(t); setSel(null) }} />

          {tab === 'events' && <>
            <form className="adm-filters" onSubmit={(e) => { e.preventDefault(); setPage(1); setApplied(scope) }}>
              <input className="adm-filter" aria-label="Object type" placeholder="Object type" value={scope.objectType} onChange={(e) => setScope({ ...scope, objectType: e.target.value })} />
              <input className="adm-filter" aria-label="Object ID" placeholder="Object ID" value={scope.objectId} onChange={(e) => setScope({ ...scope, objectId: e.target.value })} />
              <input className="adm-filter" aria-label="Organisation ID" placeholder="Organisation ID" value={scope.tenantId} onChange={(e) => setScope({ ...scope, tenantId: e.target.value })} />
              <input className="adm-filter" aria-label="Correlation ID" placeholder="Correlation ID" value={scope.correlationId} onChange={(e) => setScope({ ...scope, correlationId: e.target.value })} />
              <select className="adm-filter" aria-label="Records to load" value={limit} onChange={(e) => { setLimit(e.target.value); setPage(1) }}>
                {['50', '200', '1000'].map((n) => <option key={n} value={n}>Latest {n}</option>)}</select>
              <button className="btn btn-secondary btn-sm">Apply scope</button>
            </form>
            <FilterBar search={q} onSearch={(v) => { setQ(v); setPage(1) }} placeholder="Search action, actor, object or record #…">
              <FilterSelect label="Event type" value={action} onChange={(v) => { setAction(v); setPage(1) }} options={actions.map((a) => [a, a])} />
              <FilterSelect label="Actor type" value={actorType} onChange={(v) => { setActorType(v); setPage(1) }} options={actorTypes.map((a) => [a, label(a)])} />
            </FilterBar>
            <div className="adm-note">Latest records · newest first · timestamps in your local time</div>
            <div className="adm-table-wrap">
              <table className="data">
                <thead><tr><th>Time</th><th>Record</th><th>Event / action</th><th>Actor</th><th>Object</th><th><span className="sr-only">Actions</span></th></tr></thead>
                <tbody>
                  {!records && <tr><td colSpan={6} className="empty-row"><span role="status">Loading records…</span></td></tr>}
                  {records && filtered.length === 0 && <tr><td colSpan={6} className="empty-row">No audit records in this scope.</td></tr>}
                  {shown.map((r) => (
                    <tr key={r.id} className={`pick ${sel?.id === r.id ? 'selected' : ''}`} onClick={() => setSel({ kind: 'events', id: r.id })}>
                      <td className="small">{shortDateTime(r.occurredAt)}</td>
                      <td><div className="cell-id">#{r.seq}</div>{r.hash && <div className="cell-sub"><code>{r.hash.slice(0, 10)}…</code></div>}</td>
                      <td className="cell-main">{r.action}</td>
                      <td><div>{r.actorType ? label(r.actorType) : '—'}</div>{r.actorId && <div className="cell-sub"><code>{r.actorId.slice(0, 8)}</code></div>}</td>
                      <td><div>{r.objectType}</div><div className="cell-sub"><code>{r.objectId.slice(0, 12)}</code></div></td>
                      <td style={{ textAlign: 'right' }}><button type="button" className="btn btn-ghost btn-sm" onClick={(e) => { e.stopPropagation(); setSel({ kind: 'events', id: r.id }) }}>Inspect</button></td>
                    </tr>))}
                </tbody>
              </table>
            </div>
            <TableFoot shown={shown.length} total={filtered.length} noun="records" page={page} pages={pages} onPage={setPage} />
          </>}

          {tab === 'exports' && <>
            <div className="adm-note">Exports requested in this session · each carries its content fingerprint and chain head hash</div>
            <div className="adm-table-wrap">
              <table className="data">
                <thead><tr><th>Export</th><th>Status</th><th>Format</th><th>Records</th><th>Content fingerprint</th><th><span className="sr-only">Actions</span></th></tr></thead>
                <tbody>
                  {jobs.length === 0 && <tr><td colSpan={6} className="empty-row">No export bundles requested in this session. Use “Request export” to generate an audit package.</td></tr>}
                  {jobs.map((j) => (
                    <tr key={j.id} className={`pick ${sel?.id === j.id ? 'selected' : ''}`} onClick={() => setSel({ kind: 'exports', id: j.id })}>
                      <td><div className="cell-id">{j.id.slice(0, 8)}</div>{j.createdAt && <div className="cell-sub">{shortDateTime(j.createdAt)}</div>}</td>
                      <td><StatusPill status={j.status} /></td>
                      <td>{j.format.toUpperCase()}</td>
                      <td>{j.recordCount ?? '—'}</td>
                      <td><code>{j.contentSha256 ? `${j.contentSha256.slice(0, 16)}…` : '—'}</code></td>
                      <td style={{ textAlign: 'right' }}><button type="button" className="btn btn-secondary btn-sm"
                        onClick={(e) => { e.stopPropagation(); openStoredFile(`/v1/audit/exports/${j.id}/download`).catch(setError) }}>
                        <Icon name="download" /> Download {j.format.toUpperCase()}</button></td>
                    </tr>))}
                </tbody>
              </table>
            </div>
            <TableFoot shown={jobs.length} noun="exports" />
          </>}

          {tab === 'archives' && <>
            <div className="adm-note">Write-once copies of records older than 90 days</div>
            <div className="adm-table-wrap">
              <table className="data">
                <thead><tr><th>Records</th><th>Archived</th><th>Lock</th><th>Fingerprint</th><th>Check</th></tr></thead>
                <tbody>
                  {!archives && <tr><td colSpan={5} className="empty-row">Archives are not available to your role.</td></tr>}
                  {archives && archives.length === 0 && <tr><td colSpan={5} className="empty-row">Nothing archived yet.</td></tr>}
                  {archives?.map((a) => (
                    <tr key={a.id} className={`pick ${sel?.id === a.id ? 'selected' : ''}`} onClick={() => setSel({ kind: 'archives', id: a.id })}>
                      <td><div className="cell-main">#{a.fromSeq}–#{a.toSeq}</div><div className="cell-sub">{a.records.toLocaleString()} records</div></td>
                      <td>{shortDate(a.archivedAt)}</td>
                      <td><Pill tone={a.locked ? 'violet' : 'grey'}>{a.locked ? 'Legal hold' : 'Write-once'}</Pill></td>
                      <td><code>{a.sha256.slice(0, 12)}…</code></td>
                      <td>{archiveResult[a.id] ? <Pill tone={archiveResult[a.id].ok ? 'green' : 'red'}>{archiveResult[a.id].ok ? 'Verified' : 'Problem'}</Pill>
                        : <button type="button" className="btn btn-ghost btn-sm" onClick={(e) => { e.stopPropagation(); void verifyArchive(a) }}>Verify</button>}</td>
                    </tr>))}
                </tbody>
              </table>
            </div>
            <TableFoot shown={archives?.length ?? 0} noun="archive batches" />
          </>}
        </div>
      } detail={
        selRecord ? <RecordDetail r={selRecord} onClose={() => setSel(null)} />
          : selJob ? <DetailPanel title={`Export ${selJob.id.slice(0, 8)}`} subtitle={selJob.createdAt ? shortDateTime(selJob.createdAt) : undefined}
            badge={<StatusPill status={selJob.status} />} onClose={() => setSel(null)}
            footer={<button type="button" className="btn btn-primary btn-sm" onClick={() => openStoredFile(`/v1/audit/exports/${selJob.id}/download`).catch(setError)}>
              <Icon name="download" /> Download {selJob.format.toUpperCase()}</button>}>
            <Facts rows={[['Format', selJob.format.toUpperCase()], ['Records', selJob.recordCount ?? '—']]} />
            <Facts title="Fingerprints" rows={[
              ['Content SHA-256', <code key="c" style={{ overflowWrap: 'anywhere' }}>{selJob.contentSha256 ?? '—'}</code>],
              ['Chain head hash', <code key="h" style={{ overflowWrap: 'anywhere' }}>{selJob.chainHeadHash ?? '—'}</code>],
            ]} />
          </DetailPanel>
            : selArchive ? <DetailPanel title={`Archive #${selArchive.fromSeq}–#${selArchive.toSeq}`} subtitle={`Archived ${shortDateTime(selArchive.archivedAt)}`}
              badge={<Pill tone={selArchive.locked ? 'violet' : 'grey'}>{selArchive.locked ? 'Legal hold' : 'Write-once'}</Pill>} onClose={() => setSel(null)}
              footer={<button type="button" className="btn btn-secondary btn-sm" onClick={() => void verifyArchive(selArchive)}>Verify archive</button>}>
              {archiveResult[selArchive.id] && <Callout tone={archiveResult[selArchive.id].ok ? 'green' : 'red'} title={archiveResult[selArchive.id].ok ? 'Verified' : 'Problem found'}>
                {archiveResult[selArchive.id].text}</Callout>}
              <Facts rows={[
                ['Records', selArchive.records.toLocaleString()],
                ['Sequence', `#${selArchive.fromSeq}–#${selArchive.toSeq}`],
                ['Last read-back check', shortDateTime(selArchive.lastVerifiedAt)],
                ['Storage key', <code key="k" style={{ overflowWrap: 'anywhere' }}>{selArchive.objectKey}</code>],
                ['SHA-256', <code key="s" style={{ overflowWrap: 'anywhere' }}>{selArchive.sha256}</code>],
              ]} />
            </DetailPanel>
              : undefined
      } />
    </>
  )
}

function RecordDetail({ r, onClose }: { r: AuditRow; onClose: () => void }) {
  const code = (v: string | null | undefined) => (v ? <code style={{ overflowWrap: 'anywhere' }}>{v}</code> : '—')
  return (
    <DetailPanel title={r.action} subtitle={`Record #${r.seq} · ${shortDateTime(r.occurredAt)}`} onClose={onClose}>
      <Facts title="Record" rows={[
        ['Occurred', new Date(r.occurredAt).toLocaleString()],
        ['Actor', r.actorId ? code(r.actorId) : '—'],
        ['Actor type', r.actorType ? label(r.actorType) : '—'],
        ['Authentication', r.authStrength ? label(r.authStrength) : '—'],
        ['Object', `${r.objectType}`],
        ['Object ID', code(r.objectId)],
        ['Organisation', code(r.tenantId)],
        ['Correlation', code(r.correlationId)],
        ['Policy version', r.policyVersion ?? '—'],
      ]} />
      <Facts title="Provenance" rows={[
        ['Record hash', code(r.hash)],
        ['Previous hash', code(r.prevHash)],
        ['Evidence hash', code(r.evidenceHash)],
        ['Source event', code(r.sourceEventId)],
      ]} />
      <div>
        <h3 style={{ fontSize: 13.5, margin: '0 0 6px' }}>Details</h3>
        {Object.keys(r.details ?? {}).length === 0 ? <p className="muted small" style={{ margin: 0 }}>No details recorded.</p>
          : <pre className="small" style={{ margin: 0, whiteSpace: 'pre-wrap', overflowWrap: 'anywhere', background: 'var(--zk-bg-soft)', padding: 10, borderRadius: 8 }}>
            {JSON.stringify(r.details, null, 2)}</pre>}
      </div>
    </DetailPanel>
  )
}

function ExportForm({ busy, onSubmit, onCancel }: { busy: boolean; onSubmit: (body: Record<string, unknown>) => void; onCancel: () => void }) {
  return (
    <form className="card adm-panel" style={{ marginBottom: 16 }} onSubmit={(e) => {
      e.preventDefault()
      const d = new FormData(e.currentTarget)
      onSubmit({
        format: d.get('format'),
        tenantId: d.get('tenantId') || null,
        objectId: d.get('objectId') || null,
        since: d.get('since') ? new Date(String(d.get('since'))).toISOString() : null,
        until: d.get('until') ? new Date(String(d.get('until'))).toISOString() : null,
      })
    }}>
      <div className="adm-panel-head"><h2>Request export bundle</h2><span className="muted small">Step-up authenticated</span></div>
      <div className="row" style={{ marginBottom: 12 }}>
        <div className="field" style={{ flex: 1, minWidth: 220 }}>
          <label htmlFor="auditexports-tenantId">Organisation Scope</label>
          <input id="auditexports-tenantId" className="input" name="tenantId" placeholder="Optional organisation UUID" />
        </div>
        <div className="field" style={{ flex: 1, minWidth: 220 }}>
          <label htmlFor="auditexports-objectId">Subject / Record Scope</label>
          <input id="auditexports-objectId" className="input" name="objectId" placeholder="Optional engagement or dispute ID" />
        </div>
      </div>
      <div className="row" style={{ marginBottom: 16 }}>
        <div className="field" style={{ flex: 1, minWidth: 180 }}>
          <label htmlFor="auditexports-since">From Timestamp</label>
          <input id="auditexports-since" className="input" name="since" type="datetime-local" />
        </div>
        <div className="field" style={{ flex: 1, minWidth: 180 }}>
          <label htmlFor="auditexports-until">To Timestamp</label>
          <input id="auditexports-until" className="input" name="until" type="datetime-local" />
        </div>
        <div className="field" style={{ width: 140 }}>
          <label htmlFor="auditexports-format">Export Format</label>
          <select id="auditexports-format" className="input" name="format"><option value="json">JSON</option><option value="csv">CSV</option></select>
        </div>
      </div>
      <div className="row">
        <button type="submit" className="btn btn-primary" disabled={busy}>Generate Authorised Export (Step-Up Authenticated)</button>
        <button type="button" className="btn btn-ghost" onClick={onCancel}>Cancel</button>
      </div>
    </form>
  )
}
