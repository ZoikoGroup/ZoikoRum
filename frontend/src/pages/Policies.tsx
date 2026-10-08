import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { useSearchParams } from 'react-router-dom'
import { orgApi, type Organization, type BusinessUnit } from '../api/orgs'
import { ApiError } from '../api/client'
import { openStoredFile, toUpload } from '../api/files'
import { policyApi, type Approval, type ExceptionRequest, type PolicyProfile, type PolicyRule } from '../api/policy'
import { ErrorAlert, Field, useStepUp } from '../components/ui'
import { EmptyTable, PortalHeader, StatCard, Tabs } from '../components/portal'
import { Icon } from '../components/dashboard'
import AutomaticDisputeControls from '../components/AutomaticDisputeControls'

type PolicyTab = 'profiles' | 'approvals' | 'exceptions'

export default function PoliciesPage() {
  const [params, setParams] = useSearchParams()
  const [orgs, setOrgs] = useState<Organization[]>([])
  const [units, setUnits] = useState<BusinessUnit[]>([])
  const [simulation, setSimulation] = useState<string | null>(null)
  const [orgId, setOrgId] = useState(params.get('orgId') || '')
  const [profiles, setProfiles] = useState<PolicyProfile[]>([])
  const [approvals, setApprovals] = useState<Approval[]>([])
  const [exceptions, setExceptions] = useState<ExceptionRequest[]>([])
  const tab = (params.get('tab') as PolicyTab) || 'profiles'
  const setTab = (t: PolicyTab) => setParams(t === 'profiles' ? (orgId ? { orgId } : {}) : { tab: t, ...(orgId ? { orgId } : {}) }, { replace: true })
  const [error, setError] = useState<unknown>(null)
  const [busy, setBusy] = useState(false)
  const [selected, setSelected] = useState<PolicyProfile | null>(null)
  const [settings, setSettings] = useState('{}')
  const [rules, setRules] = useState('[]')
  const [impact, setImpact] = useState<string | null>(null)
  const [showCreate, setShowCreate] = useState(false)
  const { run, modal } = useStepUp(setError)

  const org = orgs.find((o) => o.id === orgId)
  const admin = !!org?.myRoles.includes('ORG_ADMIN')

  const reload = useCallback(async () => {
    if (!orgId) return
    async function collect<T>(fetch: (cursor?: string) => Promise<{ items: T[]; nextCursor: string | null }>) {
      const items: T[] = []
      let cursor: string | undefined
      do {
        const page = await fetch(cursor)
        items.push(...page.items)
        cursor = page.nextCursor ?? undefined
      } while (cursor)
      return items
    }
    const [p, a, e] = await Promise.all([
      collect((c) => policyApi.profiles(orgId, c)),
      collect((c) => policyApi.approvals(orgId, c)),
      collect((c) => policyApi.exceptions(orgId, c)),
    ])
    setProfiles(p)
    setApprovals(a)
    setExceptions(e)
  }, [orgId])

  useEffect(() => {
    orgApi
      .mine()
      .then((items) => {
        setOrgs(items)
        setOrgId((current) => current || items[0]?.id || '')
      })
      .catch(setError)
  }, [])

  useEffect(() => {
    reload().catch(setError)
    const timer = window.setInterval(() => reload().catch(setError), 15000)
    return () => window.clearInterval(timer)
  }, [reload])

  useEffect(() => {
    if (orgId) orgApi.businessUnits(orgId).then(setUnits).catch(setError)
  }, [orgId])

  function choose(p: PolicyProfile) {
    setSelected(p)
    setImpact(null)
    const v = p.versions.find((v) => v.id === (p.draftVersionId || p.activeVersionId)) || p.versions[0]
    setSettings(JSON.stringify(v.settings, null, 2))
    setRules(JSON.stringify(v.rules, null, 2))
  }

  async function action(work: () => Promise<unknown>) {
    setBusy(true)
    setError(null)
    try {
      await work()
      await reload()
    } catch (err) {
      if (err instanceof ApiError && err.code === 'STEP_UP_REQUIRED') throw err
      setError(err)
    } finally {
      setBusy(false)
    }
  }

  async function create(e: FormEvent<HTMLFormElement>) {
    e.preventDefault()
    const f = new FormData(e.currentTarget)
    await action(async () => {
      const created = await policyApi.create({
        orgId,
        name: String(f.get('name')),
        description: String(f.get('description')),
        template: String(f.get('template')),
        businessUnitIds: f.getAll('businessUnitIds').map(String),
        riskLevel: String(f.get('riskLevel')),
      })
      choose(created)
      setShowCreate(false)
    })
  }

  async function requestException(e: FormEvent<HTMLFormElement>) {
    e.preventDefault()
    const f = new FormData(e.currentTarget)
    await action(async () => {
      const documents = await Promise.all(
        f
          .getAll('documents')
          .filter((v): v is File => v instanceof File && v.size > 0)
          .map((file) => toUpload(file))
      )
      await policyApi.requestException({
        orgId,
        subjectType: String(f.get('subjectType')),
        subjectId: String(f.get('subjectId')),
        action: String(f.get('action')),
        justification: String(f.get('justification')),
        documents,
        expiresAt: new Date(String(f.get('expiresAt'))).toISOString(),
      })
    })
  }

  const activeProfiles = profiles.filter((p) => p.status === 'ACTIVE' || p.activeVersionId)
  const pendingApprovals = approvals.filter((a) => a.status === 'PENDING')
  const pendingExceptions = exceptions.filter((x) => x.status === 'PENDING')

  return (
    <>
      <PortalHeader
        eyebrow="Governance & Policy"
        title="Policies & Approvals"
        subtitle="Control procurement eligibility, multi-step approval workflows, and documented policy exceptions."
        actions={
          <button className="btn btn-secondary" onClick={() => action(reload)} disabled={busy}>
            <Icon name="clock" /> Refresh
          </button>
        }
      />

      <ErrorAlert error={error} />
      {modal}

      <div className="stat-row four">
        <StatCard
          icon="shield"
          tone="green"
          value={activeProfiles.length}
          label="Active Policies"
          sub={`${profiles.length} total profile${profiles.length === 1 ? '' : 's'}`}
        />
        <StatCard
          icon="clock"
          tone={pendingApprovals.length > 0 ? 'amber' : 'blue'}
          value={pendingApprovals.length}
          label="Pending Approvals"
          sub={pendingApprovals.length > 0 ? 'Action required by reviewer' : 'All workflows resolved'}
        />
        <StatCard
          icon="folder"
          tone="violet"
          value={pendingExceptions.length}
          label="Active Exceptions"
          sub={`${exceptions.length} total recorded`}
        />
        <StatCard
          icon="building"
          tone="blue"
          value={org ? org.name : '—'}
          label="Current Scope"
          sub={admin ? 'Org Admin Authority' : 'Member Authority'}
        />
      </div>

      <div className="card panel" style={{ padding: '14px 18px', marginBottom: 20 }}>
        <div className="row" style={{ alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12, flex: 1, minWidth: 280 }}>
            <span
              style={{
                fontSize: 12.5,
                fontWeight: 600,
                color: 'var(--zk-muted)',
                textTransform: 'uppercase',
                letterSpacing: '0.05em',
              }}
            >
              Organisation Scope:
            </span>
            <select
              id="policy-org"
              className="input"
              style={{ maxWidth: 360 }}
              value={orgId}
              onChange={(e) => {
                setOrgId(e.target.value)
                setSelected(null)
              }}
            >
              {orgs.map((o) => (
                <option key={o.id} value={o.id}>
                  {o.name}
                </option>
              ))}
            </select>
          </div>
          <div className="badges">
            {admin ? (
              <span className="badge green">
                <Icon name="shield" /> Org Admin
              </span>
            ) : (
              <span className="badge">Member View</span>
            )}
            {org && (
              <span className="badge">
                <Icon name="building" /> {org.orgType}
              </span>
            )}
          </div>
        </div>
      </div>

      <Tabs<PolicyTab>
        tabs={[
          { key: 'profiles', label: 'Policy Profiles', count: profiles.length },
          { key: 'approvals', label: 'Approval Requests', count: pendingApprovals.length },
          { key: 'exceptions', label: 'Exceptions & Waivers', count: exceptions.length },
        ]}
        value={tab}
        onChange={setTab}
      />

      {tab === 'profiles' && (
        <div className="home-grid wide">
          <div>
            <div className="panel-head" style={{ marginBottom: 12 }}>
              <h2>Configured Policy Profiles</h2>
              {admin && (
                <button
                  type="button"
                  className="btn btn-primary btn-sm"
                  onClick={() => setShowCreate((v) => !v)}
                >
                  <Icon name="plus" /> {showCreate ? 'Close Form' : 'New Policy Profile'}
                </button>
              )}
            </div>

            {showCreate && admin && (
              <form className="card panel" onSubmit={create} style={{ marginBottom: 20, borderColor: 'var(--zk-green)' }}>
                <div className="panel-head">
                  <h2>Create Policy Profile</h2>
                </div>
                <p className="muted small">
                  Configure an enforceable policy profile to govern talent tiers, spend limits, and mandatory approval chains.
                </p>
                <div className="row" style={{ marginBottom: 12 }}>
                  <div className="field" style={{ flex: 1 }}>
                    <label>Profile Name</label>
                    <input
                      className="input"
                      name="name"
                      placeholder="e.g. Enterprise Financial SOW Policy"
                      required
                      minLength={2}
                      maxLength={80}
                    />
                  </div>
                  <div className="field" style={{ flex: 1 }}>
                    <label>Base Template</label>
                    <select className="input" name="template">
                      {['ENTERPRISE_STANDARD', 'REGULATED', 'CROSS_BORDER', 'GROWTH_ADVISORY'].map((t) => (
                        <option key={t} value={t}>
                          {t.replace(/_/g, ' ')}
                        </option>
                      ))}
                    </select>
                  </div>
                </div>

                <div className="field">
                  <label>Description</label>
                  <input
                    className="input"
                    name="description"
                    placeholder="Describe which departments or spend categories this policy governs"
                  />
                </div>

                <div className="row" style={{ marginBottom: 12 }}>
                  <div className="field" style={{ flex: 1 }}>
                    <label>Risk Level</label>
                    <select className="input" name="riskLevel">
                      <option value="MEDIUM">Medium Risk</option>
                      <option value="LOW">Low Risk</option>
                      <option value="HIGH">High Risk</option>
                    </select>
                  </div>
                  {!!units.length && (
                    <div className="field" style={{ flex: 1 }}>
                      <label>Business Units (optional)</label>
                      <select className="input" name="businessUnitIds" multiple style={{ height: 80 }}>
                        {units.map((u) => (
                          <option key={u.id} value={u.id}>
                            {u.name}
                          </option>
                        ))}
                      </select>
                      <span className="hint">Leave empty for organisation-wide scope</span>
                    </div>
                  )}
                </div>

                <div className="row" style={{ justifyContent: 'flex-end', marginTop: 16 }}>
                  <button type="button" className="btn btn-ghost btn-sm" onClick={() => setShowCreate(false)}>
                    Cancel
                  </button>
                  <button type="submit" className="btn btn-primary" disabled={busy}>
                    Create Draft Profile
                  </button>
                </div>
              </form>
            )}

            {profiles.length === 0 ? (
              <div className="card panel empty-row">
                <strong>No custom policy profiles.</strong> The platform baseline policy currently applies to all procurement actions.
              </div>
            ) : (
              profiles.map((p) => {
                const isCurrent = selected?.id === p.id
                return (
                  <div
                    key={p.id}
                    className="card panel"
                    style={{
                      cursor: 'pointer',
                      transition: 'border-color 0.15s, box-shadow 0.15s',
                      borderColor: isCurrent ? 'var(--zk-green)' : undefined,
                      boxShadow: isCurrent ? 'var(--focus)' : undefined,
                      marginBottom: 14,
                    }}
                    onClick={() => choose(p)}
                  >
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 12 }}>
                      <div>
                        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
                          <h3 style={{ margin: 0 }}>{p.name}</h3>
                          <span className={`badge ${p.status === 'ACTIVE' ? 'green' : 'warn'}`}>
                            {p.status}
                          </span>
                        </div>
                        <p className="muted small" style={{ margin: 0 }}>
                          {p.description || 'No description provided.'}
                        </p>
                      </div>
                      <div style={{ textAlign: 'right', flexShrink: 0 }}>
                        <span className="small muted">
                          v{p.version} · {p.versions.length} version{p.versions.length === 1 ? '' : 's'}
                        </span>
                        <div style={{ marginTop: 4 }}>
                          <span className="chev" style={{ color: isCurrent ? 'var(--zk-green)' : 'var(--zk-subtle)' }}>
                            ›
                          </span>
                        </div>
                      </div>
                    </div>
                  </div>
                )
              })
            )}

            {admin && selected && (
              <form
                className="card panel"
                style={{ marginTop: 24 }}
                onSubmit={(e) => {
                  e.preventDefault()
                  const f = new FormData(e.currentTarget)
                  action(async () => {
                    const result = await policyApi.dryRun({
                      orgId,
                      previewProfileId: selected.id,
                      subjectType: 'Simulation',
                      subjectId: crypto.randomUUID(),
                      action: String(f.get('action')),
                      attributes: JSON.parse(String(f.get('attributes'))),
                    })
                    setSimulation(`${result.decision}: ${result.reasons.map((r) => r.message).join('; ')}`)
                  })
                }}
              >
                <div className="panel-head">
                  <h2>Policy Dry-Run Simulator</h2>
                </div>
                <p className="muted small">
                  Simulate commercial facts against this policy to test rules before activation. Dry-run evaluations record an audit simulation without creating approvals or moving money.
                </p>
                <div className="field">
                  <label>Simulated Action</label>
                  <input className="input" name="action" required defaultValue="PROPOSAL_ACCEPT" />
                </div>
                <div className="field">
                  <label>Simulated Attributes (JSON)</label>
                  <textarea
                    className="input"
                    name="attributes"
                    required
                    rows={5}
                    style={{ fontFamily: 'ui-monospace, monospace', fontSize: 13 }}
                    defaultValue={
                      '{\n  "professional.tier": "B",\n  "professional.dimensions": { "identity": "VERIFIED" },\n  "engagement.valueMinor": 100000,\n  "engagement.currency": "USD",\n  "buyer.country": "US"\n}'
                    }
                  />
                </div>
                <button type="submit" className="btn btn-secondary" disabled={busy}>
                  Run Policy Simulation
                </button>
                {simulation && (
                  <div className="alert alert-info" style={{ marginTop: 14 }}>
                    <strong>Simulation Outcome:</strong> {simulation}
                  </div>
                )}
              </form>
            )}
          </div>

          <aside>
            {selected ? (
              <section className="card panel">
                <div className="panel-head">
                  <h2>{selected.name}</h2>
                </div>
                <div className="badges" style={{ marginBottom: 12 }}>
                  {selected.versions.map((v) => (
                    <span
                      key={v.id}
                      className={`badge ${v.status === 'ACTIVE' ? 'green' : 'warn'}`}
                    >
                      {v.label} ({v.status})
                    </span>
                  ))}
                </div>

                <div className="alert alert-info" style={{ fontSize: 13, padding: '10px 12px' }}>
                  Active policy versions are immutable once enabled. Engagements retain their agreed version for the contract lifetime. Escrow is mandated by the platform baseline.
                </div>

                <Field label="Profile Settings (JSON)" id="policy-settings">
                  <textarea
                    id="policy-settings"
                    className="input"
                    rows={10}
                    style={{ fontFamily: 'ui-monospace, monospace', fontSize: 12.5 }}
                    value={settings}
                    readOnly={!admin || !selected.draftVersionId}
                    onChange={(e) => setSettings(e.target.value)}
                  />
                </Field>

                <AutomaticDisputeControls
                  settings={settings}
                  onChange={setSettings}
                  disabled={!admin || !selected.draftVersionId}
                />

                <Field label="Custom Rules (JSON)" id="policy-rules">
                  <textarea
                    id="policy-rules"
                    className="input"
                    rows={8}
                    style={{ fontFamily: 'ui-monospace, monospace', fontSize: 12.5 }}
                    value={rules}
                    readOnly={!admin || !selected.draftVersionId}
                    onChange={(e) => setRules(e.target.value)}
                  />
                </Field>
                <p className="muted small">
                  Conditions support all/any groups or field/op/value. Approval modes: SINGLE, SEQUENTIAL, PARALLEL. Decisions: REQUIRE_APPROVAL, REQUIRE_EXCEPTION, BLOCK.
                </p>

                <div className="row" style={{ marginTop: 16, gap: 8 }}>
                  {admin &&
                    (selected.draftVersionId ? (
                      <>
                        <button
                          type="button"
                          className="btn btn-secondary btn-sm"
                          disabled={busy}
                          onClick={() =>
                            action(async () =>
                              choose(
                                await policyApi.save(
                                  selected.id,
                                  selected.version,
                                  JSON.parse(settings),
                                  JSON.parse(rules) as PolicyRule[]
                                )
                              )
                            )
                          }
                        >
                          Save Draft
                        </button>
                        <button
                          type="button"
                          className="btn btn-primary btn-sm"
                          disabled={busy}
                          onClick={() =>
                            run(() =>
                              action(async () =>
                                choose(await policyApi.activate(selected.id))
                              )
                            )
                          }
                        >
                          Activate Draft
                        </button>
                      </>
                    ) : (
                      <button
                        type="button"
                        className="btn btn-secondary btn-sm"
                        disabled={busy}
                        onClick={() =>
                          action(async () => choose(await policyApi.draft(selected.id)))
                        }
                      >
                        Create New Draft Version
                      </button>
                    ))}
                  <button
                    type="button"
                    className="btn btn-ghost btn-sm"
                    disabled={busy}
                    onClick={() =>
                      action(async () => {
                        const result = await policyApi.impact(selected.id)
                        setImpact(`${result.eligibleProfessionals} eligible professionals. ${result.scope}`)
                      })
                    }
                  >
                    Preview Impact
                  </button>
                </div>

                {impact && (
                  <div className="alert alert-success" style={{ marginTop: 12 }}>
                    <strong>Marketplace Impact:</strong> {impact}
                  </div>
                )}
              </section>
            ) : (
              <section className="card panel" style={{ textAlign: 'center', padding: '36px 20px' }}>
                <span className="kpi-icon blue" style={{ margin: '0 auto 12px' }}>
                  <Icon name="shield" />
                </span>
                <h3 style={{ margin: '0 0 6px' }}>Select a Policy Profile</h3>
                <p className="muted small" style={{ margin: 0 }}>
                  Choose a policy from the list on the left to inspect its active configuration, edit draft versions, or test simulations.
                </p>
              </section>
            )}
          </aside>
        </div>
      )}

      {tab === 'approvals' && (
        <div>
          <div className="alert alert-info" style={{ marginBottom: 20 }}>
            <strong>Deterministic Resumption:</strong> Approved proposal acceptance, milestone acceptance, and escrow release resume automatically upon final sign-off. Requesters cannot approve their own requests (separation of duties).
          </div>

          {approvals.length === 0 ? (
            <section className="card panel">
              <EmptyTable columns={['Action', 'Subject', 'Status', 'Workflow / Steps', 'Due Date', 'Decision']}>
                No pending or completed approval requests found for this organisation.
              </EmptyTable>
            </section>
          ) : (
            <div style={{ display: 'grid', gap: 16 }}>
              {approvals.map((a) => (
                <section className="card panel" key={a.id}>
                  <div className="panel-head">
                    <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                      <h2 style={{ margin: 0 }}>{a.action.replaceAll('_', ' ')}</h2>
                      <span className={`badge ${a.status === 'GRANTED' ? 'green' : a.status === 'PENDING' ? 'warn' : 'prio-high'}`}>
                        {a.status}
                      </span>
                    </div>
                    <span className="small muted">
                      Due: {new Date(a.deadline).toLocaleString()}
                    </span>
                  </div>

                  <p className="small muted" style={{ marginBottom: 12 }}>
                    Subject: <strong>{a.subjectType}</strong> (<code>{a.subjectId}</code>) · Requester ID: <code>{a.requesterIdentityId}</code>
                  </p>

                  {a.reasons.length > 0 && (
                    <div style={{ marginBottom: 12 }}>
                      <span style={{ fontSize: 13, fontWeight: 600, color: 'var(--zk-navy)' }}>Triggering Policy Criteria:</span>
                      <ul style={{ margin: '4px 0 0', paddingLeft: 18, fontSize: 13.5, color: 'var(--zk-muted)' }}>
                        {a.reasons.map((r, i) => (
                          <li key={i}>{r.message}</li>
                        ))}
                      </ul>
                    </div>
                  )}

                  {a.workflows.length > 0 && (
                    <div style={{ marginBottom: 12 }}>
                      <span style={{ fontSize: 13, fontWeight: 600, color: 'var(--zk-navy)' }}>Required Approval Chain:</span>
                      <div className="badges" style={{ marginTop: 4 }}>
                        {a.workflows.map((w, i) => (
                          <span key={i} className="badge">
                            {w.mode}: {w.steps.map((s) => `${s.role} × ${s.count}`).join(' → ')}
                          </span>
                        ))}
                      </div>
                    </div>
                  )}

                  {a.votes.length > 0 && (
                    <div style={{ marginBottom: 14 }}>
                      <span style={{ fontSize: 13, fontWeight: 600, color: 'var(--zk-navy)' }}>Audit Trail &amp; Decisions:</span>
                      <div style={{ display: 'grid', gap: 6, marginTop: 4 }}>
                        {a.votes.map((v) => (
                          <div
                            key={v.id}
                            style={{
                              background: 'var(--zk-bg-soft)',
                              padding: '8px 12px',
                              borderRadius: 'var(--radius-sm)',
                              fontSize: 13,
                              display: 'flex',
                              justifyContent: 'space-between',
                              alignItems: 'center',
                            }}
                          >
                            <span>
                              <strong>{v.role}</strong>: {v.decision} {v.reason && `— "${v.reason}"`}
                            </span>
                            {!v.valid && v.decision === 'GRANT' && (
                              <span className="badge prio-high">Authority Invalidated</span>
                            )}
                          </div>
                        ))}
                      </div>
                    </div>
                  )}

                  {a.status === 'PENDING' && (
                    <form
                      onSubmit={(e) => {
                        e.preventDefault()
                        const f = new FormData(e.currentTarget)
                        run(() =>
                          action(() =>
                            policyApi.decide(
                              a.id,
                              String(f.get('decision')) as 'GRANT' | 'DENY',
                              String(f.get('reason')),
                              String(f.get('stepId'))
                            )
                          )
                        )
                      }}
                      style={{
                        background: 'var(--zk-bg)',
                        padding: 16,
                        borderRadius: 'var(--radius-sm)',
                        marginTop: 14,
                        border: '1px solid var(--zk-border)',
                      }}
                    >
                      <h3 style={{ margin: '0 0 10px', fontSize: 14 }}>Record Approval Decision</h3>
                      <div className="row" style={{ marginBottom: 10 }}>
                        <div className="field" style={{ flex: 1 }}>
                          <label>Approval Step</label>
                          <select className="input" name="stepId">
                            {a.workflows
                              .flatMap((w) => w.steps)
                              .map((s) => (
                                <option key={s.id} value={s.id}>
                                  {s.role} (Step {s.id})
                                </option>
                              ))}
                          </select>
                        </div>
                        <div className="field" style={{ flex: 1 }}>
                          <label>Decision</label>
                          <select className="input" name="decision">
                            <option value="GRANT">Approve (Grant)</option>
                            <option value="DENY">Deny (Reject)</option>
                          </select>
                        </div>
                      </div>
                      <div className="field">
                        <label>Justification / Reason</label>
                        <textarea
                          className="input"
                          name="reason"
                          required
                          minLength={3}
                          maxLength={1000}
                          rows={3}
                          placeholder="State the commercial or compliance basis for your decision..."
                        />
                      </div>
                      <button type="submit" className="btn btn-primary" disabled={busy}>
                        Submit Decision (Step-Up Authenticated)
                      </button>
                    </form>
                  )}
                </section>
              ))}
            </div>
          )}
        </div>
      )}

      {tab === 'exceptions' && (
        <div className="home-grid wide">
          <div>
            <div className="panel-head" style={{ marginBottom: 12 }}>
              <h2>Active Policy Exceptions</h2>
            </div>
            {exceptions.length === 0 ? (
              <div className="card panel empty-row">
                <strong>No policy exceptions.</strong> Documented waivers and emergency exceptions will appear here once requested.
              </div>
            ) : (
              <div style={{ display: 'grid', gap: 14 }}>
                {exceptions.map((x) => (
                  <section className="card panel" key={x.id}>
                    <div className="panel-head">
                      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                        <h3 style={{ margin: 0 }}>{x.action.replaceAll('_', ' ')}</h3>
                        <span className={`badge ${x.status === 'GRANTED' ? 'green' : x.status === 'PENDING' ? 'warn' : 'prio-high'}`}>
                          {x.status}
                        </span>
                      </div>
                      <span className="small muted">
                        Expires: {new Date(x.expiresAt).toLocaleDateString()}
                      </span>
                    </div>

                    <p style={{ margin: '8px 0 12px', fontSize: 14 }}>{x.justification}</p>

                    {x.documents.length > 0 && (
                      <div style={{ marginBottom: 12 }}>
                        <span className="small muted" style={{ display: 'block', marginBottom: 4 }}>Supporting Documents:</span>
                        <div className="row" style={{ gap: 6 }}>
                          {x.documents.map((d) => (
                            <button
                              type="button"
                              className="btn btn-secondary btn-sm"
                              key={d.sha256}
                              onClick={() =>
                                openStoredFile(`/v1/policy/exceptions/${x.id}/documents/${d.sha256}`).catch(setError)
                              }
                            >
                              <Icon name="download" /> {d.name}
                            </button>
                          ))}
                        </div>
                      </div>
                    )}

                    {x.decisionReason && (
                      <div className="alert alert-info" style={{ marginTop: 8, fontSize: 13 }}>
                        <strong>Decision Reason:</strong> {x.decisionReason}
                      </div>
                    )}

                    {x.status === 'PENDING' && org?.myRoles.includes('EXCEPTION_AUTHORITY') && (
                      <form
                        onSubmit={(e) => {
                          e.preventDefault()
                          const f = new FormData(e.currentTarget)
                          run(() =>
                            action(() =>
                              policyApi.decideException(
                                x.id,
                                String(f.get('decision')) as 'GRANT' | 'DENY',
                                String(f.get('reason'))
                              )
                            )
                          )
                        }}
                        style={{
                          background: 'var(--zk-bg)',
                          padding: 14,
                          borderRadius: 'var(--radius-sm)',
                          marginTop: 12,
                          border: '1px solid var(--zk-border)',
                        }}
                      >
                        <h4 style={{ margin: '0 0 8px', fontSize: 13.5 }}>Exception Authority Action</h4>
                        <div className="row" style={{ marginBottom: 8 }}>
                          <div className="field" style={{ flex: 1 }}>
                            <label>Decision</label>
                            <select className="input" name="decision">
                              <option value="GRANT">Grant Exception</option>
                              <option value="DENY">Deny Exception</option>
                            </select>
                          </div>
                        </div>
                        <div className="field">
                          <label>Authority Justification</label>
                          <textarea
                            className="input"
                            name="reason"
                            required
                            minLength={3}
                            rows={2}
                            placeholder="Reason for granting or denying exception..."
                          />
                        </div>
                        <button type="submit" className="btn btn-primary btn-sm" disabled={busy}>
                          Record Exception Decision
                        </button>
                      </form>
                    )}
                  </section>
                ))}
              </div>
            )}
          </div>

          <aside>
            <form className="card panel" onSubmit={requestException}>
              <div className="panel-head">
                <h2>Request Exception</h2>
              </div>
              <p className="muted small">
                Exceptions apply to a recorded policy evaluation, require documented justification, and are time-bound.
              </p>

              <div className="field">
                <label>Subject Type</label>
                <input
                  className="input"
                  name="subjectType"
                  required
                  placeholder="e.g. Proposal, Milestone, Contract"
                  defaultValue={params.get('subjectType') || ''}
                />
              </div>

              <div className="field">
                <label>Subject ID / Reference</label>
                <input
                  className="input"
                  name="subjectId"
                  required
                  placeholder="UUID reference"
                  defaultValue={params.get('subjectId') || ''}
                />
              </div>

              <div className="field">
                <label>Policy Action</label>
                <input
                  className="input"
                  name="action"
                  required
                  placeholder="e.g. PROPOSAL_ACCEPT, ESCROW_RELEASE"
                  defaultValue={params.get('action') || ''}
                />
              </div>

              <div className="field">
                <label>Business Justification</label>
                <textarea
                  className="input"
                  name="justification"
                  required
                  minLength={10}
                  maxLength={4000}
                  rows={4}
                  placeholder="Provide full legal/commercial rationale for overriding the standard policy rule..."
                />
              </div>

              <div className="field">
                <label>Supporting Documents</label>
                <input
                  name="documents"
                  type="file"
                  multiple
                  accept=".pdf,.docx,.xlsx,.csv,.jpg,.jpeg,.png"
                />
                <span className="hint">PDF, Word, Excel, CSV or images up to 10 MB</span>
              </div>

              <div className="field">
                <label>Exception Expiration Date</label>
                <input
                  className="input"
                  name="expiresAt"
                  type="datetime-local"
                  required
                />
              </div>

              <button type="submit" className="btn btn-primary btn-block" disabled={busy}>
                Submit Exception Request
              </button>
            </form>
          </aside>
        </div>
      )}
    </>
  )
}
