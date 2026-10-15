import { useCallback, useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { api } from '../api/client'
import { formatMoney, orgApi, type Organization } from '../api/orgs'
import { useAuth } from '../auth/AuthContext'
import { ErrorAlert, useStepUp } from '../components/ui'
import { openStoredFile } from '../api/files'
import { downloadFile } from '../lib/exports'
import { EmptyTable, PortalHeader, StatCard } from '../components/portal'
import { Icon } from '../components/dashboard'

interface Case {
  id: string
  subjectType: string
  subjectId: string
  summary: string
  signalSource: string
  evidenceRefs: string[];
  approvals: { identityId: string; role: string; at: string }[]
  status: string
  level: number
  action: string | null
  notice: Record<string, string> | null
  appeal: { status: string; reason: string; decisionReason?: string } | null
  expiresAt: string | null
}
const noticeFields = ['whatHappened', 'whyItHappened', 'whatChanged', 'whatYouCanDo', 'whatHappensNext', 'howToGetHelp']
const actions: Record<number, string[]> = {
  1: ['WARNING'],
  2: ['VISIBILITY_REDUCTION'],
  3: ['ENGAGEMENT_SUSPENSION', 'CREDENTIAL_ENFORCEMENT', 'VERIFICATION_RESET'],
  4: ['SUSPEND_ACCOUNT', 'OFFBOARD'],
}

export function SafetyPage({ operator = false }: { operator?: boolean }) {
  const { user } = useAuth()
  const can = (...roles: string[]) => roles.some((role) => user?.platformRoles.some((held) => held === role))
  const [rows, setRows] = useState<Case[]>([])
  const [params] = useSearchParams()  // the Users page links here with ?subjectType=IDENTITY&subjectId=<id>
  const [offset, setOffset] = useState(0)
  const [error, setError] = useState<unknown>(null)
  const [busy, setBusy] = useState(false)
  const { run, modal } = useStepUp(setError)

  const reload = useCallback(
    async () =>
      setRows(
        await api<Case[]>(operator ? '/v1/admin/enforcement-cases' : '/v1/enforcement-cases', {
          query: operator ? { offset: String(offset) } : {},
        })
      ),
    [operator, offset]
  )

  useEffect(() => {
    reload().catch(setError)
  }, [reload])

  async function act(path: string, body?: unknown) {
    setBusy(true)
    try {
      await run(async () => {
        await api(path, { method: 'POST', body, headers: { 'Idempotency-Key': crypto.randomUUID() } })
        await reload()
      })
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      <PortalHeader
        eyebrow="Trust & Safety"
        title={operator ? 'Safety Case Management' : 'Account Safety & Appeals'}
        subtitle="Governed enforcement proceedings, documented six-field notices, and independent appeal workflows."
        actions={
          <button className="btn btn-secondary" onClick={() => reload().catch(setError)} disabled={busy}>
            <Icon name="clock" /> Refresh Cases
          </button>
        }
      />

      <ErrorAlert error={error} />
      {modal}

      {operator && can('TS_ANALYST') && (
        <form
          className="card panel"
          onSubmit={(e) => {
            e.preventDefault()
            const data = new FormData(e.currentTarget)
            act('/v1/admin/enforcement-cases', {
              subjectType: data.get('subjectType'),
              subjectId: data.get('subjectId'),
              signalSource: data.get('signalSource'),
              summary: data.get('summary'),
              evidenceRefs: String(data.get('evidenceRefs'))
                .split('\n')
                .map((s) => s.trim())
                .filter(Boolean),
            })
          }}
          style={{ marginBottom: 20 }}
        >
          <div className="panel-head">
            <h2>Open Evidence-Based Case</h2>
          </div>
          <div className="row" style={{ marginBottom: 12 }}>
            <div className="field" style={{ flex: 1 }}>
              <label htmlFor="operations-subjectType">Subject Type</label>
              <select id="operations-subjectType" className="input" name="subjectType" defaultValue={params.get('subjectType') ?? 'IDENTITY'}>
                <option value="IDENTITY">Identity</option>
                <option value="PROFESSIONAL">Professional</option>
                <option value="ORGANIZATION">Organization</option>
              </select>
            </div>
            <div className="field" style={{ flex: 1 }}>
              <label htmlFor="operations-subjectId">Subject UUID</label>
              <input id="operations-subjectId" className="input" name="subjectId" required placeholder="Subject UUID" defaultValue={params.get('subjectId') ?? ''} />
            </div>
            <div className="field" style={{ flex: 1 }}>
              <label htmlFor="operations-signalSource">Signal Source</label>
              <input id="operations-signalSource" className="input" name="signalSource" required minLength={3} placeholder="Signal source" />
            </div>
          </div>
          <div className="field">
            <label htmlFor="operations-summary">Case Summary</label>
            <textarea id="operations-summary" className="input" name="summary" required minLength={10} maxLength={2000} placeholder="Case summary" rows={3} />
          </div>
          <div className="field">
            <label htmlFor="operations-evidenceRefs">Evidence References (one per line)</label>
            <textarea id="operations-evidenceRefs" className="input" name="evidenceRefs" placeholder="e.g. SHA-256 hashes, dispute IDs, message IDs" rows={2} />
          </div>
          <button className="btn btn-primary" disabled={busy}>
            Open Safety Case
          </button>
        </form>
      )}

      {rows.length === 0 ? (
        <section className="card panel">
          <EmptyTable columns={['Case Reference', 'Level', 'Subject', 'Action', 'Status']}>
            No active safety cases in this view.
          </EmptyTable>
        </section>
      ) : (
        <div style={{ display: 'grid', gap: 16 }}>
          {rows.map((c) => (
            <section className="card panel" key={c.id}>
              <div className="panel-head">
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <h2 style={{ margin: 0 }}>Level {c.level} Incident</h2>
                  <span className={`badge ${c.status === 'ACTIVE' ? 'warn' : c.status === 'REVERSED' ? 'green' : 'prio-high'}`}>
                    {c.status}
                  </span>
                </div>
                <span className="small muted">Case: <code>{c.id.slice(0, 8)}</code></span>
              </div>
              <p style={{ fontSize: 14.5, margin: '6px 0 10px' }}>{c.summary}</p>
              <p className="small muted" style={{ margin: 0 }}>
                Subject: <strong>{c.subjectType}</strong> (<code>{c.subjectId}</code>) · Source: {c.signalSource}
              </p>
              {c.action && (
                <p className="small" style={{ marginTop: 6, fontWeight: 600 }}>
                  Applied Action: {c.action.replaceAll('_', ' ')}
                  {c.expiresAt && ` · Ends ${new Date(c.expiresAt).toLocaleString()}`}
                </p>
              )}

              {operator && !!c.evidenceRefs?.length && (
                <div style={{ marginTop: 12 }}>
                  <span className="small muted" style={{ fontWeight: 600 }}>Evidence References:</span>
                  <ul style={{ margin: '4px 0 0', paddingLeft: 18, fontSize: 12.5 }}>
                    {c.evidenceRefs.map((ref) => (
                      <li key={ref}><code>{ref}</code></li>
                    ))}
                  </ul>
                </div>
              )}

              {!!c.approvals?.length && (
                <div style={{ marginTop: 10 }}>
                  <span className="small muted" style={{ fontWeight: 600 }}>Recorded Approvals:</span>
                  {c.approvals.map((vote) => (
                    <div key={vote.identityId} className="small" style={{ marginTop: 2 }}>
                      {vote.role.replaceAll('_', ' ')} · {new Date(vote.at).toLocaleString()}
                      {operator && ` · Reviewer ${vote.identityId}`}
                    </div>
                  ))}
                </div>
              )}

              {c.status === 'REVERSED' && (
                <div className="alert alert-success" style={{ marginTop: 10, fontSize: 13 }}>
                  This enforcement action has ended. The notice below records the original action; other active cases may still apply.
                </div>
              )}

              {c.notice && (
                <dl className="facts" style={{ marginTop: 14 }}>
                  {Object.entries(c.notice).map(([key, value]) => (
                    <div key={key}>
                      <dt>{key.replace(/([A-Z])/g, ' $1')}</dt>
                      <dd>{value}</dd>
                    </div>
                  ))}
                </dl>
              )}

              {operator && can('RISK_LEAD') && ['TRIAGE', 'ASSESSED'].includes(c.status) && (
                <form
                  onSubmit={(e) => {
                    e.preventDefault()
                    const d = new FormData(e.currentTarget)
                    act(`/v1/admin/enforcement-cases/${c.id}/assess`, {
                      level: Number(d.get('level')),
                      reasonCode: d.get('reasonCode'),
                    })
                  }}
                  style={{ marginTop: 14, background: 'var(--zk-bg-soft)', padding: 12, borderRadius: 'var(--radius-sm)' }}
                >
                  <div className="row">
                    <div className="field" style={{ flex: 1 }}>
                      <label htmlFor="operations-level">Risk Level</label>
                      <select id="operations-level" className="input" name="level">
                        {[0, 1, 2, 3, 4].map((n) => (
                          <option key={n} value={n}>Level {n}</option>
                        ))}
                      </select>
                    </div>
                    <div className="field" style={{ flex: 2 }}>
                      <label htmlFor="operations-reasonCode">Reason Code</label>
                      <input id="operations-reasonCode" className="input" name="reasonCode" required minLength={3} placeholder="Reason code" />
                    </div>
                  </div>
                  <button className="btn btn-secondary btn-sm" disabled={busy}>Record Assessment</button>
                </form>
              )}

              {operator && can('TS_ANALYST', 'RISK_LEAD') && c.status === 'ASSESSED' && c.level > 0 && (
                <form
                  onSubmit={(e) => {
                    e.preventDefault()
                    const d = new FormData(e.currentTarget)
                    act(`/v1/admin/enforcement-cases/${c.id}/propose-action`, {
                      action: d.get('action'),
                      durationDays: d.get('durationDays') ? Number(d.get('durationDays')) : null,
                      notice: Object.fromEntries(noticeFields.map((key) => [key, d.get(key)])),
                    })
                  }}
                  style={{ marginTop: 14, background: 'var(--zk-bg-soft)', padding: 14, borderRadius: 'var(--radius-sm)' }}
                >
                  <h3 style={{ margin: '0 0 10px', fontSize: 14 }}>Propose Notified Enforcement Action</h3>
                  <div className="row" style={{ marginBottom: 10 }}>
                    <div className="field" style={{ flex: 1 }}>
                      <label htmlFor="operations-action">Action</label>
                      <select id="operations-action" className="input" name="action">
                        {actions[c.level]?.map((a) => (
                          <option key={a} value={a}>{a.replace(/_/g, ' ')}</option>
                        ))}
                      </select>
                    </div>
                    <div className="field" style={{ flex: 1 }}>
                      <label htmlFor="operations-durationDays">Duration in Days (if temporary)</label>
                      <input id="operations-durationDays" className="input" name="durationDays" type="number" min={1} max={365} required={c.level === 2} placeholder="e.g. 14" />
                    </div>
                  </div>
                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: 10 }}>
                    {noticeFields.map((key) => (
                      <div className="field" key={key}>
                        <label>{key.replace(/([A-Z])/g, ' $1')}</label>
                        <textarea className="input" name={key} required minLength={10} maxLength={2000} rows={2} />
                      </div>
                    ))}
                  </div>
                  <button className="btn btn-primary btn-sm" disabled={busy}>Propose Action with Notice</button>
                </form>
              )}

              {operator && (c.level === 4 ? can('EXECUTIVE', 'LEGAL') : can('RISK_LEAD', 'LEGAL')) && c.status === 'AWAITING_APPROVAL' && (
                <div style={{ marginTop: 14 }}>
                  <button className="btn btn-primary" disabled={busy} onClick={() => act(`/v1/admin/enforcement-cases/${c.id}/approve-action`)}>
                    Approve Enforcement as Independent Reviewer
                  </button>
                </div>
              )}

              {operator && can('RISK_LEAD', 'LEGAL') && c.status === 'ACTIVE' && (
                <div style={{ marginTop: 12 }}>
                  <ReasonForm label="Reverse Action" busy={busy} submit={(reason) => act(`/v1/admin/enforcement-cases/${c.id}/reverse`, { reason })} />
                </div>
              )}

              {!operator && c.status === 'ACTIVE' && c.level >= 2 && !c.appeal && (
                <div style={{ marginTop: 12 }}>
                  <ReasonForm label="File Appeal" busy={busy} submit={(reason) => act(`/v1/enforcement-cases/${c.id}/appeal`, { reason })} />
                </div>
              )}

              {c.appeal && (
                <div style={{ marginTop: 14, background: 'var(--zk-bg-soft)', padding: 12, borderRadius: 'var(--radius-sm)' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
                    <h3 style={{ margin: 0, fontSize: 14 }}>Appeal Case</h3>
                    <span className="badge">{c.appeal.status}</span>
                  </div>
                  <p style={{ margin: '0 0 6px', fontSize: 13.5 }}>{c.appeal.reason}</p>
                  {c.appeal.decisionReason && <p className="small muted">Decision Reason: {c.appeal.decisionReason}</p>}
                  {operator && can('LEGAL') && c.appeal.status === 'PENDING' && (
                    <form
                      onSubmit={(e) => {
                        e.preventDefault()
                        const d = new FormData(e.currentTarget)
                        act(`/v1/admin/enforcement-cases/${c.id}/appeal/decision`, {
                          upheld: d.get('upheld') === 'true',
                          reason: d.get('reason'),
                        })
                      }}
                      style={{ marginTop: 10 }}
                    >
                      <div className="row" style={{ marginBottom: 8 }}>
                        <div className="field" style={{ flex: 1 }}>
                          <label htmlFor="operations-upheld">Decision</label>
                          <select id="operations-upheld" className="input" name="upheld">
                            <option value="false">Reject appeal</option>
                            <option value="true">Uphold appeal and reverse action</option>
                          </select>
                        </div>
                      </div>
                      <div className="field">
                        <label htmlFor="operations-reason">Independent Review Justification</label>
                        <textarea id="operations-reason" className="input" name="reason" required minLength={20} maxLength={4000} rows={2} placeholder="Legal review rationale" />
                      </div>
                      <button className="btn btn-primary btn-sm" disabled={busy}>Decide Appeal</button>
                    </form>
                  )}
                </div>
              )}
            </section>
          ))}
        </div>
      )}

      {operator && (
        <div className="row" style={{ justifyContent: 'center', marginTop: 16 }}>
          <button className="btn btn-secondary btn-sm" disabled={!offset} onClick={() => setOffset((n) => Math.max(0, n - 50))}>
            Previous
          </button>
          <button className="btn btn-secondary btn-sm" disabled={rows.length < 50} onClick={() => setOffset((n) => n + 50)}>
            Next
          </button>
        </div>
      )}
    </>
  )
}

function ReasonForm({ label, busy, submit }: { label: string; busy: boolean; submit: (reason: string) => void }) {
  return (
    <form
      onSubmit={(e) => {
        e.preventDefault()
        submit(String(new FormData(e.currentTarget).get('reason')))
      }}
      style={{ marginTop: 8 }}
    >
      <div className="field">
        <label>{label} Reason</label>
        <textarea name="reason" className="input" required minLength={20} maxLength={4000} rows={2} placeholder={`${label}: state reason clearly`} />
      </div>
      <button className="btn btn-secondary btn-sm" disabled={busy}>{label}</button>
    </form>
  )
}

interface Prompt {
  id: string
  promptKey: string
  version: number
  targetModel: string
  instructions: string
  status: string
}

export function AIAdminPage() {
  const [rows, setRows] = useState<Prompt[]>([])
  const [error, setError] = useState<unknown>(null)
  const { run, modal } = useStepUp(setError)

  const reload = useCallback(async () => setRows(await api<Prompt[]>('/v1/ai/prompts')), [])
  useEffect(() => {
    reload().catch(setError)
  }, [reload])

  return (
    <>
      <PortalHeader
        eyebrow="AI Governance"
        title="AI Prompt Safety Registry"
        subtitle="Versioned prompt registry with mandatory AI Safety Reviewer approval and golden test validation."
        actions={
          <button className="btn btn-secondary" onClick={() => reload().catch(setError)}>
            <Icon name="clock" /> Refresh
          </button>
        }
      />

      <ErrorAlert error={error} />
      {modal}

      <form
        className="card panel"
        onSubmit={(e) => {
          e.preventDefault()
          const d = new FormData(e.currentTarget)
          let goldenTests: unknown
          try {
            goldenTests = JSON.parse(String(d.get('goldenTests')))
          } catch (err) {
            setError(err)
            return
          }
          run(async () => {
            await api('/v1/ai/prompts', {
              method: 'POST',
              headers: { 'Idempotency-Key': crypto.randomUUID() },
              body: {
                promptKey: d.get('promptKey'),
                targetModel: d.get('targetModel'),
                instructions: d.get('instructions'),
                goldenTests,
              },
            })
            await reload()
          })
        }}
        style={{ marginBottom: 20 }}
      >
        <div className="panel-head">
          <h2>Create Draft Prompt Version</h2>
        </div>
        <div className="row" style={{ marginBottom: 12 }}>
          <div className="field" style={{ flex: 1 }}>
            <label htmlFor="operations-promptKey">Prompt Purpose Key</label>
            <select id="operations-promptKey" className="input" name="promptKey">
              {['proposal-draft', 'contract-summary', 'dispute-summary', 'match-intent'].map((p) => (
                <option key={p} value={p}>{p}</option>
              ))}
            </select>
          </div>
          <div className="field" style={{ flex: 1 }}>
            <label htmlFor="operations-targetModel">Target Model</label>
            <input id="operations-targetModel" className="input" name="targetModel" defaultValue="offline:v1" required placeholder="Configured model identifier" />
          </div>
        </div>
        <div className="field">
          <label htmlFor="operations-instructions">Advisory Instructions</label>
          <textarea id="operations-instructions"
            className="input"
            name="instructions"
            required
            minLength={30}
            rows={3}
            placeholder="Advisory instructions; strictly prohibit decisions and invented facts"
          />
        </div>
        <div className="field">
          <label htmlFor="operations-goldenTests">Golden Test Expectations (JSON)</label>
          <textarea id="operations-goldenTests"
            className="input"
            name="goldenTests"
            required
            rows={2}
            style={{ fontFamily: 'ui-monospace, monospace', fontSize: 13 }}
            defaultValue={'[{"input":"Evidence supplied by a party", "mustContain":["Evidence"]}]'}
          />
        </div>
        <button className="btn btn-primary btn-sm">Create Draft Version</button>
      </form>

      <div style={{ display: 'grid', gap: 14 }}>
        {rows.map((p) => (
          <section key={p.id} className="card panel">
            <div className="panel-head">
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <h3 style={{ margin: 0 }}>{p.promptKey} v{p.version}</h3>
                <span className={`badge ${p.status === 'APPROVED' ? 'green' : 'warn'}`}>{p.status}</span>
              </div>
              <span className="small muted">Target Model: {p.targetModel}</span>
            </div>
            <pre style={{ whiteSpace: 'pre-wrap', background: 'var(--zk-bg-soft)', padding: 12, borderRadius: 'var(--radius-sm)', fontSize: 13 }}>
              {p.instructions}
            </pre>
            <div className="row" style={{ gap: 8, marginTop: 12 }}>
              {p.status === 'DRAFT' && (
                <button
                  type="button"
                  className="btn btn-primary btn-sm"
                  onClick={() =>
                    run(async () => {
                      await api(`/v1/ai/prompts/${p.id}/approve`, {
                        method: 'POST',
                        headers: { 'Idempotency-Key': crypto.randomUUID() },
                      })
                      await reload()
                    })
                  }
                >
                  Validate Golden Tests &amp; Approve
                </button>
              )}
              {p.status === 'APPROVED' && (
                <button
                  type="button"
                  className="btn btn-danger btn-sm"
                  onClick={() =>
                    run(async () => {
                      await api(`/v1/ai/prompts/${p.id}/retire`, {
                        method: 'POST',
                      })
                      await reload()
                    })
                  }
                >
                  Retire Prompt Version
                </button>
              )}
            </div>
          </section>
        ))}
      </div>
    </>
  )
}

interface Report {
  items: {
    eventId: string
    date: string
    eventType: string
    currency: string
    grossMinor: number
    feeMinor: number
    netMinor: number
  }[]
  summary: {
    lastEventAt: string | null
    activeEngagements: number
    pendingActions: number
  }
}

export function ReportsPage() {
  const { user } = useAuth()
  const [orgs, setOrgs] = useState<Organization[]>([])
  const [orgId, setOrgId] = useState('')
  const [role, setRole] = useState<'buyer' | 'professional'>('buyer')
  const [report, setReport] = useState<Report | null>(null)
  const [error, setError] = useState<unknown>(null)
  const [since, setSince] = useState('')
  const [until, setUntil] = useState('')
  const [busy, setBusy] = useState(false)

  const query: Record<string, string> = {
    ...(role === 'buyer' ? { organizationId: orgId } : {}),
    ...(since ? { from: `${since}T00:00:00Z` } : {}),
    ...(until ? { to: `${until}T23:59:59Z` } : {}),
  }

  useEffect(() => {
    orgApi
      .mine()
      .then((list) => {
        setOrgs(list)
        setOrgId(list[0]?.id ?? '')
        if (!list.length && user?.personas.includes('PROFESSIONAL')) setRole('professional')
      })
      .catch(setError)
  }, [user])

  async function loadReport() {
    setBusy(true)
    setError(null)
    try {
      const data = await api<Report>(`/v1/reports/${role}`, { query })
      setReport(data)
    } catch (err) {
      setError(err)
    } finally {
      setBusy(false)
    }
  }

  function downloadReport(format: string) {
    const params = new URLSearchParams(
      Object.entries({ ...query, format }).filter(
        (entry): entry is [string, string] => typeof entry[1] === 'string'
      )
    )
    openStoredFile(`/v1/reports/${role}?${params}`).catch(setError)
  }

  return (
    <>
      <PortalHeader
        eyebrow="Financial Intelligence & Analytics"
        title="Financial & Activity Reports"
        subtitle="Currency-safe projections reconstructed from immutable event logs, with multi-format audit-grade exports."
        actions={
          <div className="row" style={{ gap: 8 }}>
            {['csv', 'pdf'].map((format) => (
              <button
                type="button"
                className="btn btn-secondary"
                key={format}
                onClick={() => downloadReport(format)}
              >
                <Icon name="download" /> Export {format.toUpperCase()}
              </button>
            ))}
          </div>
        }
      />

      <ErrorAlert error={error} />

      <div className="stat-row four">
        <StatCard
          icon="contract"
          tone="blue"
          value={report ? report.summary.activeEngagements : '—'}
          label="Active Engagements"
          sub="Live contracts in projection"
        />
        <StatCard
          icon="clock"
          tone={report && report.summary.pendingActions > 0 ? 'amber' : 'green'}
          value={report ? report.summary.pendingActions : '—'}
          label="Pending Actions"
          sub={report && report.summary.pendingActions > 0 ? 'Signatures or reviews awaiting action' : 'All workflows resolved'}
        />
        <StatCard
          icon="check"
          tone="teal"
          value={
            report?.summary.lastEventAt
              ? new Date(report.summary.lastEventAt).toLocaleTimeString()
              : 'Up to Date'
          }
          label="Projection Freshness"
          sub={
            report?.summary.lastEventAt
              ? new Date(report.summary.lastEventAt).toLocaleDateString()
              : 'No projection lag detected'
          }
        />
        <StatCard
          icon="wallet"
          tone="violet"
          value={role === 'buyer' ? 'Customer Spend' : 'Earnings'}
          label="Reporting Perspective"
          sub={
            role === 'buyer'
              ? orgs.find((o) => o.id === orgId)?.name || 'Buyer Organisation'
              : 'Professional Practice'
          }
        />
      </div>

      <div className="card panel" style={{ marginBottom: 20 }}>
        <div className="panel-head">
          <h2>Report Parameters</h2>
        </div>
        <div className="row" style={{ alignItems: 'flex-end', gap: 14 }}>
          <div className="field" style={{ minWidth: 200, flex: 1 }}>
            <label htmlFor="operations-reporting-perspective">Reporting Perspective</label>
            <select id="operations-reporting-perspective"
              className="input"
              value={role}
              onChange={(e) => {
                setRole(e.target.value as 'buyer' | 'professional')
                setReport(null)
              }}
            >
              {orgs.length > 0 && <option value="buyer">Customer Spend (Buyer Organisation)</option>}
              {user?.personas.includes('PROFESSIONAL') && (
                <option value="professional">Professional Earnings (Self)</option>
              )}
            </select>
          </div>

          {role === 'buyer' && (
            <div className="field" style={{ minWidth: 200, flex: 1 }}>
              <label htmlFor="operations-organisation">Organisation</label>
              <select id="operations-organisation"
                className="input"
                value={orgId}
                onChange={(e) => {
                  setOrgId(e.target.value)
                  setReport(null)
                }}
              >
                {orgs.map((o) => (
                  <option value={o.id} key={o.id}>
                    {o.name}
                  </option>
                ))}
              </select>
            </div>
          )}

          <div className="field" style={{ minWidth: 160, flex: 1 }}>
            <label htmlFor="operations-from-date">From Date</label>
            <input id="operations-from-date"
              type="date"
              className="input"
              value={since}
              onChange={(e) => setSince(e.target.value)}
            />
          </div>

          <div className="field" style={{ minWidth: 160, flex: 1 }}>
            <label htmlFor="operations-to-date">To Date</label>
            <input id="operations-to-date"
              type="date"
              className="input"
              value={until}
              onChange={(e) => setUntil(e.target.value)}
            />
          </div>

          <div style={{ paddingBottom: 16 }}>
            <button
              type="button"
              className="btn btn-primary"
              disabled={busy}
              onClick={loadReport}
            >
              Generate Report
            </button>
          </div>
        </div>
      </div>

      <section className="card panel">
        <div className="panel-head">
          <h2>Financial Movement Ledger</h2>
          {report && (
            <span className="small muted">
              {report.items.length} recorded movement{report.items.length === 1 ? '' : 's'}
            </span>
          )}
        </div>

        <div className="alert alert-info" style={{ fontSize: 13, padding: '10px 14px', marginBottom: 16 }}>
          <strong>Accounting Invariant:</strong> Projections strictly segregate currencies without synthetic conversions. Figures are derived from double-entry escrow and payout ledgers.
        </div>

        {!report || report.items.length === 0 ? (
          <EmptyTable columns={['Date', 'Event Type', 'Currency', 'Gross Amount', 'Platform Fee', 'Net Settlement']}>
            {report
              ? 'No financial transactions recorded for the selected parameters and date window.'
              : 'Choose filters above and click "Generate Report" to reconstruct the financial statement.'}
          </EmptyTable>
        ) : (
          <table className="data">
            <thead>
              <tr>
                <th>Date</th>
                <th>Event Type</th>
                <th>Currency</th>
                <th>Gross Amount</th>
                <th>Platform Fee</th>
                <th>Net Settlement</th>
              </tr>
            </thead>
            <tbody>
              {report.items.map((r) => (
                <tr key={r.eventId}>
                  <td className="small">{new Date(r.date).toLocaleDateString()}</td>
                  <td>
                    <span className="badge">
                      {r.eventType.split('.').slice(-2, -1)[0]?.replace(/_/g, ' ') || r.eventType}
                    </span>
                  </td>
                  <td>
                    <strong>{r.currency}</strong>
                  </td>
                  <td>{formatMoney({ amountMinor: r.grossMinor, currency: r.currency })}</td>
                  <td className="muted">{formatMoney({ amountMinor: r.feeMinor, currency: r.currency })}</td>
                  <td>
                    <strong>{formatMoney({ amountMinor: r.netMinor, currency: r.currency })}</strong>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </>
  )
}

interface DailyHealth {
  date: string
  searches: number
  zeroResultSearches: number
  proposalsSubmitted: number
  contractsGenerated: number
  activations: number
  releases: number
  disputesOpened: number
  disputesResolved: number
}

interface MarketplaceHealth {
  window: { from: string | null; to: string | null }
  eventCounts: Record<string, number>
  searches: number
  daily: DailyHealth[]
  activations: number
  disputesOpened: number
  disputesResolved: number
  zeroResultSearches: number
  proposalContractConversionBps: number | null
  medianReleaseLatencySeconds: number | null
  trustTierDistribution: Record<string, number>
  lastEventAt: string | null
}

const EVENT_AREAS: [string, string][] = [
  ['search', 'Search'],
  ['verification', 'Verification'],
  ['trust', 'Trust'],
  ['policy', 'Policy'],
  ['proposal', 'Proposals'],
  ['contract', 'Contracts & Milestones'],
  ['escrow', 'Escrow'],
  ['payments', 'Payments'],
  ['dispute', 'Disputes'],
  ['marketplace', 'Marketplace'],
]

const sentence = (s: string) => s.charAt(0).toUpperCase() + s.slice(1)

/** "zoikorum.escrow.account.funding_requested.v1" -> area "escrow", label "Account funding requested". */
function readableEvent(name: string) {
  const [, area = 'other', ...rest] = name.split('.')
  const words = rest.filter((part) => !/^v\d+$/.test(part)).join(' ').replaceAll('_', ' ')
  return { area, label: sentence(words || name) }
}

function groupEventCounts(counts: Record<string, number>) {
  const groups = new Map<string, { name: string; label: string; count: number }[]>()
  for (const [name, count] of Object.entries(counts)) {
    const { area, label } = readableEvent(name)
    groups.set(area, [...(groups.get(area) ?? []), { name, label, count }])
  }
  const order = EVENT_AREAS.map(([key]) => key)
  return [...groups.entries()]
    .sort(([a], [b]) => (order.indexOf(a) + 1 || order.length + 1) - (order.indexOf(b) + 1 || order.length + 1))
    .map(([area, events]) => ({
      area,
      title: EVENT_AREAS.find(([key]) => key === area)?.[1] ?? sentence(area),
      events,
      total: events.reduce((sum, e) => sum + e.count, 0),
    }))
}

const duration = (s: number) => (s < 5400 ? ago(s) : s < 172800 ? `${(s / 3600).toFixed(1)} h` : `${(s / 86400).toFixed(1)} days`)

const percent = (part: number, whole: number) => `${(Math.round((1000 * part) / whole) / 10).toLocaleString()}%`

const DAILY_COLUMNS: [keyof Omit<DailyHealth, 'date'>, string][] = [
  ['searches', 'Searches'],
  ['zeroResultSearches', 'Zero Results'],
  ['proposalsSubmitted', 'Proposals'],
  ['contractsGenerated', 'Contracts'],
  ['activations', 'Activations'],
  ['releases', 'Releases'],
  ['disputesOpened', 'Disputes Opened'],
  ['disputesResolved', 'Disputes Resolved'],
]

type HealthPreset = '7' | '30' | '90' | 'all' | 'custom'
const HEALTH_PRESETS: [HealthPreset, string][] = [['7', 'Last 7 days'], ['30', 'Last 30 days'], ['90', 'Last 90 days'], ['all', 'All time'], ['custom', 'Custom range']]

/** Dates are whole UTC days, matching how the server buckets the daily series. */
const utcToday = () => new Date().toISOString().slice(0, 10)
function addDays(date: string, days: number) {
  const d = new Date(`${date}T00:00:00Z`)
  d.setUTCDate(d.getUTCDate() + days)
  return d.toISOString().slice(0, 10)
}
const utcDayLabel = (date: string) => new Date(`${date}T00:00:00Z`).toLocaleDateString(undefined, { timeZone: 'UTC', day: 'numeric', month: 'short', year: 'numeric' })

export function PlatformAnalyticsPage() {
  const { user } = useAuth()
  const isPlatformAdmin = !!user?.platformRoles.includes('PLATFORM_ADMIN')
  const [data, setData] = useState<MarketplaceHealth | null>(null)
  const [error, setError] = useState<unknown>(null)
  const [busy, setBusy] = useState(false)
  const [preset, setPreset] = useState<HealthPreset>('30')
  const [since, setSince] = useState(() => addDays(utcToday(), -29))
  const [until, setUntil] = useState(utcToday)
  const { run, modal } = useStepUp(setError)

  const bounded = preset !== 'all'
  const invalidRange = bounded && (!since || !until || since > until)

  const reload = useCallback(async () => {
    if (invalidRange) return
    setBusy(true)
    try {
      setData(await api<MarketplaceHealth>('/v1/analytics/marketplace-health', {
        query: bounded ? { from: `${since}T00:00:00Z`, to: `${addDays(until, 1)}T00:00:00Z` } : {},
      }))
      setError(null)
    } finally {
      setBusy(false)
    }
  }, [bounded, invalidRange, since, until])

  useEffect(() => {
    reload().catch(setError)
  }, [reload])

  function choosePreset(next: HealthPreset) {
    setPreset(next)
    if (next === '7' || next === '30' || next === '90') {
      setUntil(utcToday())
      setSince(addDays(utcToday(), 1 - Number(next)))
    }
  }

  const windowLabel = !bounded
    ? 'All time'
    : preset === 'custom'
      ? `${utcDayLabel(since)} – ${utcDayLabel(until)}`
      : HEALTH_PRESETS.find(([key]) => key === preset)?.[1] ?? ''
  const tiers = Object.entries(data?.trustTierDistribution ?? {}).sort(([a], [b]) => a.localeCompare(b))
  const tieredProfessionals = tiers.reduce((sum, [, n]) => sum + n, 0)

  function downloadJson() {
    if (!data) return
    const exportedAt = new Date().toISOString()
    const range = bounded ? `${since}_to_${until}` : 'all-time'
    downloadFile(
      `zoikorum-marketplace-health-${range}.json`,
      JSON.stringify({ exportedAt, ...data }, null, 2),
      'application/json'
    )
  }

  return (
    <>
      <PortalHeader
        eyebrow="Marketplace Operations"
        title="Platform Analytics"
        subtitle="Marketplace liquidity, search conversion, and system health projections."
        actions={
          <div className="row" style={{ gap: 8 }}>
            <button className="btn btn-secondary" onClick={() => reload().catch(setError)} disabled={busy || invalidRange}>
              <Icon name="clock" /> Refresh
            </button>
            <button className="btn btn-secondary" onClick={downloadJson} disabled={!data}>
              <Icon name="download" /> Download JSON
            </button>
            {isPlatformAdmin && (
              <button
                className="btn btn-primary"
                disabled={busy}
                onClick={() =>
                  run(async () => {
                    await api('/v1/admin/analytics/rebuild', { method: 'POST' })
                    await reload()
                  })
                }
              >
                Rebuild Projections from Audit Ledger
              </button>
            )}
          </div>
        }
      />

      <ErrorAlert error={error} />
      {modal}

      <div className="card panel" style={{ marginBottom: 20 }}>
        <div className="row" style={{ alignItems: 'flex-end', gap: 14 }}>
          <div className="field" style={{ minWidth: 180, flex: 1 }}>
            <label htmlFor="analytics-period">Period</label>
            <select id="analytics-period" className="input" value={preset} onChange={(e) => choosePreset(e.target.value as HealthPreset)}>
              {HEALTH_PRESETS.map(([key, label]) => <option key={key} value={key}>{label}</option>)}
            </select>
          </div>
          {bounded && (
            <>
              <div className="field" style={{ minWidth: 160, flex: 1 }}>
                <label htmlFor="analytics-from">From (UTC)</label>
                <input id="analytics-from" type="date" className="input" value={since} max={until || undefined}
                  onChange={(e) => { setPreset('custom'); setSince(e.target.value) }} />
              </div>
              <div className="field" style={{ minWidth: 160, flex: 1 }}>
                <label htmlFor="analytics-to">To (UTC)</label>
                <input id="analytics-to" type="date" className="input" value={until} min={since || undefined}
                  onChange={(e) => { setPreset('custom'); setUntil(e.target.value) }} />
              </div>
            </>
          )}
        </div>
        {invalidRange && <p className="small" style={{ color: 'var(--zk-danger)', margin: 0 }}>Choose a start date on or before the end date.</p>}
      </div>

      {data ? (
        <>
          <div className="stat-row four">
            <StatCard
              icon="search"
              tone={data.searches && data.zeroResultSearches / data.searches > 0.1 ? 'amber' : 'green'}
              value={data.searches ? percent(data.zeroResultSearches, data.searches) : '—'}
              label="Zero-Result Searches"
              sub={`${data.zeroResultSearches.toLocaleString()} of ${data.searches.toLocaleString()} searches found nothing`}
            />
            <StatCard
              icon="proposal"
              tone="blue"
              value={data.proposalContractConversionBps === null ? '—' : percent(data.proposalContractConversionBps, 10000)}
              label="Proposal → Contract"
              sub="Contracts generated per proposal submitted"
            />
            <StatCard
              icon="wallet"
              tone="teal"
              value={data.medianReleaseLatencySeconds === null ? '—' : duration(data.medianReleaseLatencySeconds)}
              label="Median Release Time"
              sub="From escrow funding to release"
            />
            <StatCard
              icon="shield"
              tone={data.disputesOpened > data.disputesResolved ? 'amber' : 'green'}
              value={`${data.disputesOpened} / ${data.disputesResolved}`}
              label="Disputes Opened / Resolved"
              sub={windowLabel}
            />
          </div>

          <div className="stat-row three">
            <StatCard icon="contract" tone="violet" value={data.activations.toLocaleString()} label="Contract Activations" sub={`Contracts that went live · ${windowLabel}`} />
            <StatCard
              icon="star"
              tone="blue"
              value={tieredProfessionals.toLocaleString()}
              label="Professionals with a Trust Tier"
              sub={`Current · ${tiers.length ? tiers.map(([tier, n]) => `Tier ${tier}: ${n}`).join(' · ') : 'No tiers assigned yet'}`}
            />
            <StatCard
              icon="clock"
              tone="green"
              value={data.lastEventAt ? new Date(data.lastEventAt).toLocaleTimeString() : '—'}
              label="Latest Event"
              sub={data.lastEventAt ? new Date(data.lastEventAt).toLocaleDateString() : 'No events recorded yet'}
            />
          </div>

          <section className="card panel" style={{ marginBottom: 20 }}>
            <div className="panel-head">
              <h2>Daily Activity</h2>
              <span className="small muted">UTC days with activity · {windowLabel}</span>
            </div>
            {data.daily.length === 0 ? (
              <EmptyTable columns={['Date', ...DAILY_COLUMNS.map(([, label]) => label)]}>No activity in this period.</EmptyTable>
            ) : (
              <div style={{ overflowX: 'auto' }}>
                <table className="data">
                  <thead>
                    <tr>
                      <th>Date</th>
                      {DAILY_COLUMNS.map(([key, label]) => <th key={key} style={{ textAlign: 'right' }}>{label}</th>)}
                    </tr>
                  </thead>
                  <tbody>
                    {[...data.daily].reverse().map((day) => (
                      <tr key={day.date}>
                        <td className="small">{utcDayLabel(day.date)}</td>
                        {DAILY_COLUMNS.map(([key]) => (
                          <td key={key} style={{ textAlign: 'right' }} className={day[key] ? undefined : 'muted'}>{day[key].toLocaleString()}</td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                  <tfoot>
                    <tr>
                      <th>Total</th>
                      {DAILY_COLUMNS.map(([key]) => (
                        <th key={key} style={{ textAlign: 'right' }}>{data.daily.reduce((sum, day) => sum + day[key], 0).toLocaleString()}</th>
                      ))}
                    </tr>
                  </tfoot>
                </table>
              </div>
            )}
          </section>

          <section className="card panel">
            <div className="panel-head">
              <h2>Event Counts by Area</h2>
              <span className="small muted">
                {Object.values(data.eventCounts).reduce((sum, n) => sum + n, 0).toLocaleString()} events recorded
              </span>
            </div>
            {Object.keys(data.eventCounts).length === 0 ? (
              <EmptyTable columns={['Event', 'Count']}>No events recorded yet.</EmptyTable>
            ) : (
              <table className="data">
                <thead>
                  <tr>
                    <th>Event</th>
                    <th style={{ textAlign: 'right' }}>Count</th>
                  </tr>
                </thead>
                {groupEventCounts(data.eventCounts).map((group) => (
                  <tbody key={group.area}>
                    <tr style={{ background: 'var(--zk-bg-soft)' }}>
                      <th scope="rowgroup">{group.title}</th>
                      <th style={{ textAlign: 'right' }}>{group.total.toLocaleString()}</th>
                    </tr>
                    {group.events.map((e) => (
                      <tr key={e.name}>
                        <td title={e.name} style={{ paddingLeft: 28 }}>{e.label}</td>
                        <td style={{ textAlign: 'right' }}>{e.count.toLocaleString()}</td>
                      </tr>
                    ))}
                  </tbody>
                ))}
              </table>
            )}
          </section>
        </>
      ) : (
        <p className="muted">Loading health metrics…</p>
      )}
    </>
  )
}

interface Failure {
  id: string
  eventType: string
  consumer: string
  attempts: number
  financial: boolean
  lastError: string
}

export function DeadLettersPage() {
  const [rows, setRows] = useState<Failure[]>([])
  const [error, setError] = useState<unknown>(null)
  const { run, modal } = useStepUp(setError)

  const reload = useCallback(async () => setRows(await api('/v1/admin/dead-letters')), [])
  useEffect(() => {
    reload().catch(setError)
  }, [reload])

  return (
    <>
      <PortalHeader
        eyebrow="Resilience Engineering"
        title="Dead Letter Deliveries"
        subtitle="Inspect unhandled event consumer failures and trigger authorized replays."
        actions={
          <button className="btn btn-secondary" onClick={() => reload().catch(setError)}>
            <Icon name="clock" /> Refresh
          </button>
        }
      />

      <ErrorAlert error={error} />
      {modal}

      {rows.length === 0 ? (
        <section className="card panel">
          <EmptyTable columns={['Consumer', 'Event Type', 'Attempts', 'Authority Required', 'Actions']}>
            No dead-letter event failures in queue. All subscribers processed cleanly.
          </EmptyTable>
        </section>
      ) : (
        <div style={{ display: 'grid', gap: 14 }}>
          {rows.map((r) => (
            <section className="card panel" key={r.id}>
              <div className="panel-head">
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <h3 style={{ margin: 0 }}>{r.consumer}</h3>
                  <span className={`badge ${r.financial ? 'prio-high' : 'warn'}`}>
                    {r.financial ? 'Financial Ops Authority Required' : 'Standard Ops'}
                  </span>
                </div>
                <span className="small muted">
                  {r.attempts} failed attempt{r.attempts === 1 ? '' : 's'}
                </span>
              </div>
              <p className="small muted" style={{ margin: '4px 0 8px' }}>
                Event Type: <code>{r.eventType}</code>
              </p>
              <pre
                style={{
                  whiteSpace: 'pre-wrap',
                  background: 'var(--zk-bg-soft)',
                  padding: 10,
                  borderRadius: 'var(--radius-sm)',
                  fontSize: 12.5,
                  color: 'var(--zk-danger)',
                }}
              >
                {r.lastError}
              </pre>
              <button
                type="button"
                className="btn btn-secondary btn-sm"
                style={{ marginTop: 10 }}
                onClick={() =>
                  run(async () => {
                    await api(`/v1/admin/dead-letters/${r.id}/replay`, { method: 'POST' })
                    await reload()
                  })
                }
              >
                Replay Event Delivery
              </button>
            </section>
          ))}
        </div>
      )}
    </>
  )
}

interface OpsSwitch {
  key: string
  label: string
  effect: string
  money: boolean
  paused: boolean
  reason: string | null
  changedAt: string | null
}

interface Backlog {
  unpublishedEvents: number
  oldestUnpublishedSeconds: number
  overdueTimers: number
  oldestOverdueTimerSeconds: number
  retryingDeliveries: number
  deadLetters: number
  deadFinancialLetters: number
}

const ago = (s: number) => (s < 90 ? `${Math.round(s)} s` : s < 5400 ? `${Math.round(s / 60)} min` : `${Math.round(s / 3600)} h`)

/** Operational switches (pause one kind of action at once) and how far behind the background worker is. */
export function SwitchesPage() {
  const { user } = useAuth()
  const [rows, setRows] = useState<OpsSwitch[]>([])
  const [backlog, setBacklog] = useState<Backlog | null>(null)
  const [editing, setEditing] = useState<OpsSwitch | null>(null)
  const [reason, setReason] = useState('')
  const [error, setError] = useState<unknown>(null)
  const { run, modal } = useStepUp(setError)
  const admin = !!user?.platformRoles.includes('PLATFORM_ADMIN')

  const reload = useCallback(async () => {
    const [s, b] = await Promise.all([api<OpsSwitch[]>('/v1/admin/switches'), api<Backlog>('/v1/admin/worker')])
    setRows(s)
    setBacklog(b)
  }, [])
  useEffect(() => {
    reload().catch(setError)
  }, [reload])

  const save = (s: OpsSwitch) => run(async () => {
    await api(`/v1/admin/switches/${s.key}`, { method: 'PUT', body: { paused: !s.paused, reason } })
    setEditing(null)
    setReason('')
    await reload()
  })

  return (
    <>
      <PortalHeader eyebrow="Operations" title="Switches and Worker"
        subtitle="Pause one kind of action at once during an incident. Every change needs two-step sign-in and a reason, and is audited."
        actions={<button className="btn btn-secondary" onClick={() => reload().catch(setError)}><Icon name="clock" /> Refresh</button>} />
      <ErrorAlert error={error} />
      {modal}

      {backlog && (
        <div className="stat-row four">
          <StatCard icon="clock" tone={backlog.oldestUnpublishedSeconds > 120 ? 'red' : 'green'} label="Events waiting"
            value={backlog.unpublishedEvents} sub={backlog.unpublishedEvents ? `oldest ${ago(backlog.oldestUnpublishedSeconds)}` : 'worker is up to date'} />
          <StatCard icon="bell" tone={backlog.oldestOverdueTimerSeconds > 300 ? 'red' : 'green'} label="Overdue timers"
            value={backlog.overdueTimers} sub={backlog.overdueTimers ? `oldest ${ago(backlog.oldestOverdueTimerSeconds)}` : 'none'} />
          <StatCard icon="gear" tone={backlog.retryingDeliveries ? 'amber' : 'green'} label="Retrying deliveries" value={backlog.retryingDeliveries} />
          <StatCard icon="shield" tone={backlog.deadLetters ? 'red' : 'green'} label="Failed deliveries" value={backlog.deadLetters}
            sub={backlog.deadFinancialLetters ? `${backlog.deadFinancialLetters} about money` : undefined} to="/app/ops/dead-letters" />
        </div>
      )}

      <section className="card panel">
        <div className="panel-head"><h3 style={{ margin: 0 }}>Switches</h3></div>
        <table className="data">
          <thead><tr><th scope="col">Action</th><th scope="col">While paused</th><th scope="col">State</th><th scope="col"><span className="sr-only">Change</span></th></tr></thead>
          <tbody>
            {rows.map((s) => {
              const allowed = admin || s.money
              return (
                <tr key={s.key}>
                  <td><strong>{s.label}</strong>{s.money && <div className="small muted">Money: Financial Operations may change it too</div>}</td>
                  <td className="small">{s.effect}</td>
                  <td>
                    <span className={`badge ${s.paused ? 'prio-high' : 'green'}`}>{s.paused ? 'Paused' : 'On'}</span>
                    {s.reason && <div className="small muted">{s.reason}{s.changedAt ? ` · ${new Date(s.changedAt).toLocaleString()}` : ''}</div>}
                  </td>
                  <td>
                    {allowed && editing?.key !== s.key && (
                      <button className={`btn btn-sm ${s.paused ? 'btn-primary' : 'btn-secondary'}`} onClick={() => { setEditing(s); setReason('') }}>
                        {s.paused ? 'Switch back on' : 'Pause'}
                      </button>
                    )}
                    {editing?.key === s.key && (
                      <form onSubmit={(e) => { e.preventDefault(); save(s) }} style={{ display: 'grid', gap: 6, minWidth: 220 }}>
                        <label className="small" htmlFor={`reason-${s.key}`}>Reason (recorded in the audit trail)</label>
                        <input id={`reason-${s.key}`} className="input" value={reason} onChange={(e) => setReason(e.target.value)} minLength={10} maxLength={500} required />
                        <div style={{ display: 'flex', gap: 6 }}>
                          <button className="btn btn-primary btn-sm">{s.paused ? 'Switch on' : 'Pause now'}</button>
                          <button type="button" className="btn btn-ghost btn-sm" onClick={() => setEditing(null)}>Cancel</button>
                        </div>
                      </form>
                    )}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </section>
    </>
  )
}
