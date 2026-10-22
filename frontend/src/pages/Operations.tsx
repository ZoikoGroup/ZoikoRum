import { RiskScores } from '../components/RiskScores'
import { useCallback, useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { api } from '../api/client'
import { formatMoney, orgApi, type Organization } from '../api/orgs'
import { reportApi, type UserReport } from '../api/reports'
import { useAuth } from '../auth/AuthContext'
import { useCapabilities } from '../auth/capabilities'
import { ErrorAlert, useStepUp } from '../components/ui'
import { DOC_ACCEPT, openStoredFile, toUpload, type Upload } from '../api/files'
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
  triageDueAt: string | null
  overdue: boolean
  appealDeadline: string | null
  canAppeal: boolean
  remediation: { task: string; done: boolean; doneAt?: string; note?: string; confirmedBy?: string }[]
}
const noticeFields = ['whatHappened', 'whyItHappened', 'whatChanged', 'whatYouCanDo', 'whatHappensNext', 'howToGetHelp']
const actions: Record<number, string[]> = {
  1: ['WARNING'],
  2: ['VISIBILITY_REDUCTION', 'DISPUTE_ACCESS_RESTRICTION'],
  3: ['ENGAGEMENT_SUSPENSION', 'CREDENTIAL_ENFORCEMENT', 'VERIFICATION_RESET'],
  4: ['SUSPEND_ACCOUNT', 'OFFBOARD'],
}

export function SafetyPage({ operator = false }: { operator?: boolean }) {
  const { has: can } = useCapabilities()  // staff capabilities (none on a customer sign-in)
  const [rows, setRows] = useState<Case[]>([])
  const [params] = useSearchParams()  // the Users page links here with ?subjectType=IDENTITY&subjectId=<id>
  const [offset, setOffset] = useState(0)
  const [filter, setFilter] = useState<{ status: string; level: string; overdue: boolean }>({ status: '', level: '', overdue: false })
  const [error, setError] = useState<unknown>(null)
  const [busy, setBusy] = useState(false)
  const { run, modal } = useStepUp(setError)

  const reload = useCallback(
    async () =>
      setRows(
        await api<Case[]>(operator ? '/v1/admin/enforcement-cases' : '/v1/enforcement-cases', {
          query: operator ? { offset: String(offset), ...(filter.status ? { status: filter.status } : {}),
            ...(filter.level ? { level: filter.level } : {}), ...(filter.overdue ? { overdue: 'true' } : {}) } : {},
        })
      ),
    [operator, offset, filter]
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
      {!operator && <MyReports />}
      {operator && can('safety.risk.read') && <RiskScores />}

      {operator && can('safety.open') && (
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

      {operator && <div className="row card" style={{ padding: 12, marginBottom: 12, gap: 12 }}>
        <label className="filter-box"><span>Status</span><select value={filter.status} onChange={(e) => setFilter({ ...filter, status: e.target.value })}>
          <option value="">Any</option>{['TRIAGE', 'ASSESSED', 'AWAITING_APPROVAL', 'ACTIVE', 'REVERSED', 'EXPIRED', 'CLOSED_NO_ACTION'].map((s) => <option key={s} value={s}>{s.replace(/_/g, ' ').toLowerCase()}</option>)}</select></label>
        <label className="filter-box"><span>Level</span><select value={filter.level} onChange={(e) => setFilter({ ...filter, level: e.target.value })}>
          <option value="">Any</option>{[0, 1, 2, 3, 4].map((l) => <option key={l} value={l}>Level {l}</option>)}</select></label>
        <label className="checkbox"><input type="checkbox" checked={filter.overdue} onChange={(e) => setFilter({ ...filter, overdue: e.target.checked })} /> <span>Past triage target only</span></label>
      </div>}
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
                <span className="small muted">{c.overdue && <span className="badge warn" style={{ marginRight: 6 }}>Past triage target</span>}
                  {c.triageDueAt && !c.overdue && <>Triage by {new Date(c.triageDueAt).toLocaleString()} · </>}Case: <code>{c.id.slice(0, 8)}</code></span>
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

              {operator && c.signalSource === 'USER_REPORT' && <CaseReports caseId={c.id} />}
              {operator && can('safety.act') && ['TRIAGE', 'ASSESSED'].includes(c.status) && (
                <div style={{ marginTop: 10 }}>
                  <ReasonForm label="Close: no action needed" busy={busy} submit={(reason) => act(`/v1/admin/enforcement-cases/${c.id}/close`, { reason })} />
                </div>
              )}
              {operator && can('safety.assess') && ['TRIAGE', 'ASSESSED'].includes(c.status) && (
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

              {operator && can('safety.act') && c.status === 'ASSESSED' && c.level > 0 && (
                <form
                  onSubmit={(e) => {
                    e.preventDefault()
                    const d = new FormData(e.currentTarget)
                    act(`/v1/admin/enforcement-cases/${c.id}/propose-action`, {
                      action: d.get('action'),
                      durationDays: d.get('durationDays') ? Number(d.get('durationDays')) : null,
                      notice: Object.fromEntries(noticeFields.map((key) => [key, d.get(key)])),
                      remediation: String(d.get('remediation') ?? '').split('\n').map((t) => t.trim()).filter(Boolean),
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
                  {c.level === 2 && <div className="field"><label htmlFor={`remediation-${c.id}`}>Remediation the person must complete (one per line, optional)</label>
                    <textarea id={`remediation-${c.id}`} className="input" name="remediation" rows={2} /></div>}
                  <button className="btn btn-primary btn-sm" disabled={busy}>Propose Action with Notice</button>
                </form>
              )}

              {operator && (c.level === 4 ? can('safety.approve_severe') : can('safety.approve')) && c.status === 'AWAITING_APPROVAL' && (
                <div style={{ marginTop: 14 }}>
                  <button className="btn btn-primary" disabled={busy} onClick={() => act(`/v1/admin/enforcement-cases/${c.id}/approve-action`)}>
                    Approve Enforcement as Independent Reviewer
                  </button>
                </div>
              )}

              {operator && can('safety.reverse') && c.status === 'ACTIVE' && (
                <div style={{ marginTop: 12 }}>
                  <ReasonForm label="Reverse Action" busy={busy} submit={(reason) => act(`/v1/admin/enforcement-cases/${c.id}/reverse`, { reason })} />
                </div>
              )}

              {!operator && c.status === 'ACTIVE' && c.level >= 2 && !c.appeal && (
                <div style={{ marginTop: 12 }}>
                  <AppealForm c={c} busy={busy} submit={(reason, evidence) => act(`/v1/enforcement-cases/${c.id}/appeal`, { reason, evidence })} />
                </div>
              )}

              {c.remediation.length > 0 && <div style={{ marginTop: 12 }}><span className="small muted" style={{ fontWeight: 600 }}>Remediation</span>
                <ul className="why">{c.remediation.map((t, i) => <li key={i}>{t.task}{' '}
                  {t.confirmedBy ? <span className="badge green">Confirmed</span> : t.done ? <span className="badge">Done{t.note ? `: ${t.note}` : ''}</span> : <span className="badge warn">To do</span>}
                  {!operator && !t.done && c.status === 'ACTIVE' && <button className="link-button small" style={{ marginLeft: 6 }} onClick={() => {
                    const note = prompt('What did you do?'); if (note && note.trim().length >= 5) act(`/v1/enforcement-cases/${c.id}/remediation/${i}/done`, { note: note.trim() })
                  }}>Mark done</button>}
                  {operator && can('safety.act') && t.done && !t.confirmedBy && <button className="link-button small" style={{ marginLeft: 6 }}
                    onClick={() => act(`/v1/admin/enforcement-cases/${c.id}/remediation/${i}/confirm`)}>Confirm</button>}</li>)}</ul></div>}
              {operator && can('safety.override') && c.status === 'ACTIVE' && <div style={{ marginTop: 10 }}>
                <ReasonForm label="Executive override: end this action" busy={busy} submit={(reason) => act(`/v1/admin/enforcement-cases/${c.id}/executive-override`, { reason })} /></div>}
              {c.appeal && (
                <div style={{ marginTop: 14, background: 'var(--zk-bg-soft)', padding: 12, borderRadius: 'var(--radius-sm)' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
                    <h3 style={{ margin: 0, fontSize: 14 }}>Appeal Case</h3>
                    <span className="badge">{c.appeal.status}</span>
                  </div>
                  <p style={{ margin: '0 0 6px', fontSize: 13.5 }}>{c.appeal.reason}</p>
                  {c.appeal.decisionReason && <p className="small muted">Decision Reason: {c.appeal.decisionReason}</p>}
                  {operator && can('safety.appeals.decide') && c.appeal.status === 'PENDING' && (
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

interface BuiltInPrompt {
  promptKey: string
  version: number
  purpose: string
  owner: string
  targetModel: string
  goldenTests: string
  fallback: string
  status: 'ACTIVE' | 'OFF' | 'NOT_CONFIGURED'
}

const BUILT_IN_STATUS: Record<BuiltInPrompt['status'], [string, string]> = {
  ACTIVE: ['Active', 'green'], OFF: ['Switched off', 'warn'], NOT_CONFIGURED: ['No AI provider: rules only', ''],
}

/** Prompts that ship with the platform: changed only through code review with their golden tests, and switched off
    with ZK_AI_DISABLED_PROMPTS (the feature then uses its non-AI rules). */
function BuiltInPrompts({ onError }: { onError: (err: unknown) => void }) {
  const [rows, setRows] = useState<BuiltInPrompt[] | null>(null)
  useEffect(() => { api<BuiltInPrompt[]>('/v1/ai/prompts/built-in').then(setRows).catch(onError) }, [onError])
  return (
    <section className="card panel" style={{ marginBottom: 20 }}>
      <div className="panel-head"><h2>Built-in prompts</h2>
        <span className="small muted">{rows ? `${rows.length} shipped with the platform` : 'Loading…'}</span></div>
      {rows && rows.length === 0 ? <EmptyTable columns={['Prompt', 'Purpose', 'Without AI', 'Status']}>No built-in prompts.</EmptyTable> : (
        <table className="data">
          <thead><tr><th>Prompt</th><th>Purpose</th><th>Without AI</th><th>Status</th></tr></thead>
          <tbody>{(rows ?? []).map((p) => {
            const [label, tone] = BUILT_IN_STATUS[p.status] ?? [p.status, '']
            return (
              <tr key={p.promptKey}>
                <td><strong>{p.promptKey}</strong><div className="muted small">v{p.version} · {p.targetModel} · owner {p.owner}</div>
                  <div className="muted small">Golden tests: <code>{p.goldenTests}</code></div></td>
                <td className="small">{p.purpose}</td>
                <td className="small">{p.fallback}</td>
                <td><span className={`badge ${tone}`}>{label}</span></td>
              </tr>
            )
          })}</tbody>
        </table>
      )}
    </section>
  )
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
      <BuiltInPrompts onError={setError} />

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



/** The user reports behind a case (staff). Confidential reporters are named only to Risk Lead and Legal. */
function CaseReports({ caseId }: { caseId: string }) {
  const [rows, setRows] = useState<UserReport[] | null>(null)
  const [error, setError] = useState<unknown>(null)
  if (rows === null) return <div style={{ marginTop: 10 }}><ErrorAlert error={error} />
    <button className="btn btn-ghost btn-sm" onClick={() => reportApi.forCase(caseId).then(setRows).catch(setError)}>Show the reports</button></div>
  return (
    <ul className="why" style={{ marginTop: 10 }}>{rows.map((r) => (
      <li key={r.id}><strong>{r.categoryLabel}</strong> · {r.reporter} · {new Date(r.createdAt).toLocaleDateString()}
        {r.possibleRetaliation && <span className="badge warn" style={{ marginLeft: 6 }}>In an open dispute with the subject</span>}
        <div className="small">{r.description}</div></li>))}</ul>
  )
}

/** A person's own reports and what came of them (no details about the other person). */
export function MyReports() {
  const [rows, setRows] = useState<UserReport[] | null>(null)
  useEffect(() => { reportApi.mine().then(setRows).catch(() => setRows([])) }, [])
  if (!rows || rows.length === 0) return null
  return (
    <section className="card panel">
      <div className="panel-head"><h2>Your reports</h2></div>
      <table className="data"><thead><tr><th>Sent</th><th>About</th><th>Problem</th><th>Status</th></tr></thead>
        <tbody>{rows.map((r) => <tr key={r.id}><td className="small">{new Date(r.createdAt).toLocaleDateString()}</td>
          <td className="small">{r.subjectType.toLowerCase()}</td><td className="small">{r.categoryLabel}</td>
          <td><span className={`badge ${r.status === 'CLOSED' ? 'green' : ''}`}>{r.status === 'RECEIVED' ? 'Being reviewed'
            : r.outcome === 'ACTION_TAKEN' ? 'Reviewed: action taken' : 'Reviewed: no action needed'}</span></td></tr>)}</tbody></table>
      <p className="muted small" style={{ margin: 0 }}>For the other person's privacy we do not share what action was taken.</p>
    </section>
  )
}


/** Appeal within the window, with reasons and up to 5 documents. */
function AppealForm({ c, busy, submit }: { c: Case; busy: boolean; submit: (reason: string, evidence: Upload[]) => void }) {
  const [reason, setReason] = useState('')
  const [files, setFiles] = useState<Upload[]>([])
  const [fileError, setFileError] = useState('')
  if (!c.canAppeal) return c.appealDeadline ? <p className="muted small">The appeal window closed on {new Date(c.appealDeadline).toLocaleDateString()}.</p> : null
  return (
    <form onSubmit={(e) => { e.preventDefault(); submit(reason.trim(), files) }}>
      <p className="small" style={{ marginTop: 0 }}>You can appeal until <strong>{c.appealDeadline ? new Date(c.appealDeadline).toLocaleDateString() : ''}</strong>.
        An independent reviewer decides.</p>
      <label className="label" htmlFor={`appeal-${c.id}`}>Why should this be reconsidered?</label>
      <textarea id={`appeal-${c.id}`} className="input" rows={3} minLength={20} maxLength={4000} value={reason} onChange={(e) => setReason(e.target.value)} required />
      <label className="label" htmlFor={`appeal-files-${c.id}`} style={{ marginTop: 8 }}>Documents (optional, up to 5)</label>
      <input id={`appeal-files-${c.id}`} type="file" multiple accept={DOC_ACCEPT} onChange={async (e) => {
        setFileError('')
        try { setFiles(await Promise.all([...(e.target.files ?? [])].slice(0, 5).map((f) => toUpload(f)))) } catch (err) { setFileError(String(err)) }
      }} />
      {fileError && <p className="small warn-text">{fileError}</p>}
      <button className="btn btn-primary btn-sm" style={{ marginTop: 8 }} disabled={busy || reason.trim().length < 20}>File appeal</button>
    </form>
  )
}


