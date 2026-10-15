import { useCallback, useEffect, useState } from 'react'
import { proApi, type EnterpriseReadiness } from '../api/professional'
import { PortalHeader } from '../components/portal'
import { ErrorAlert, Loading, useStepUp } from '../components/ui'

const STATUS: Record<string, [string, string]> = {
  NONE: ['', 'Not applied'], PENDING: ['', 'Under review'], READY: ['green', 'Enterprise Ready'],
  REJECTED: ['warn', 'Declined'], LAPSED: ['warn', 'Lapsed: a requirement no longer holds'],
}

/** A professional applies for the Enterprise Ready designation. */
export function EnterpriseReadinessPage() {
  const [data, setData] = useState<EnterpriseReadiness | null>(null)
  const [error, setError] = useState<unknown>(null)
  const [ticked, setTicked] = useState<Record<string, boolean>>({})
  const { run, modal } = useStepUp(setError)
  const load = useCallback(() => { proApi.enterprise().then(setData).catch(setError) }, [])
  useEffect(() => { load() }, [load])
  if (!data) return error ? <ErrorAlert error={error} /> : <Loading />
  const [tone, label] = STATUS[data.status] ?? ['', data.status]
  const canApply = (data.status === 'NONE' || data.status === 'REJECTED' || data.status === 'LAPSED') && data.requirements.every((r) => r.met)
  return (
    <>
      <PortalHeader eyebrow="Professional" title="Enterprise readiness"
        subtitle="Enterprise buyers look for professionals who meet a higher bar. Once approved, an Enterprise Ready badge shows on your profile and buyers can filter for it." />
      <ErrorAlert error={error} />
      {modal}
      <section className="card panel">
        <div className="panel-head"><h2>Status</h2><span className={`badge ${tone}`}>{label}</span></div>
        {data.decisionReason && <p className="small">{data.decisionReason}</p>}
        <h3>Requirements</h3>
        <ul className="checklist">{data.requirements.map((r) => <li key={r.key}><span>{r.label}</span>
          <span className={`badge ${r.met ? 'green' : 'warn'}`}>{r.met ? 'done' : 'to do'}</span></li>)}</ul>
        <p className="muted small">Verification is under Verification &amp; Trust; two-step sign-in is under Security.</p>
      </section>
      {canApply && <section className="card panel">
        <h2>Security statements</h2>
        <p className="muted small">Confirm each one. They are recorded with the date and version {data.attestationVersion}.</p>
        {data.attestationItems.map((i) => <label key={i.key} className="checkbox">
          <input type="checkbox" checked={!!ticked[i.key]} onChange={(e) => setTicked({ ...ticked, [i.key]: e.target.checked })} />
          <span>{i.text}</span></label>)}
        <button className="btn btn-primary" style={{ marginTop: 12 }} disabled={data.attestationItems.some((i) => !ticked[i.key])}
          onClick={() => run(async () => { setData(await proApi.applyEnterprise(ticked)) })}>Apply for Enterprise Ready</button>
      </section>}
    </>
  )
}

/** Compliance officers review applications. */
export function EnterpriseApplicationsPage() {
  const [items, setItems] = useState<Awaited<ReturnType<typeof proApi.enterpriseApplications>> | null>(null)
  const [error, setError] = useState<unknown>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const { run, modal } = useStepUp(setError)
  const load = useCallback(() => { proApi.enterpriseApplications().then(setItems).catch(setError) }, [])
  useEffect(() => { load() }, [load])
  function decide(id: string, approve: boolean) {
    const reason = prompt(approve ? 'Note for the record (shown to the professional)' : 'Why is it declined? (shown to the professional)')
    if (!reason || reason.trim().length < 5) return
    run(async () => { await proApi.decideEnterprise(id, approve, reason.trim()); setNotice(approve ? 'Approved.' : 'Declined.'); load() })
  }
  return (
    <>
      <PortalHeader eyebrow="Compliance" title="Enterprise Ready applications" subtitle="Approve only when every requirement holds and the statements are complete." />
      <ErrorAlert error={error} />
      {modal}
      {notice && <div className="alert alert-success" role="status">{notice}</div>}
      {!items ? <Loading /> : items.length === 0 ? <p className="muted">No applications waiting.</p> : items.map((a) => (
        <section key={a.professionalId} className="card panel">
          <div className="panel-head"><h2>{a.name}</h2><span className="muted small">applied {new Date(a.appliedAt).toLocaleDateString()}</span></div>
          {a.headline && <p className="muted">{a.headline}</p>}
          <ul className="checklist small">{a.requirements.map((r) => <li key={r.key}><span>{r.label}</span>
            <span className={`badge ${r.met ? 'green' : 'warn'}`}>{r.met ? 'holds' : 'missing'}</span></li>)}</ul>
          <p className="small">Statements: version {a.attestation?.version}, confirmed {a.attestation?.attestedAt?.slice(0, 10)}.</p>
          <div className="row">
            <button className="btn btn-primary btn-sm" disabled={!a.requirements.every((r) => r.met)} onClick={() => decide(a.professionalId, true)}>Approve</button>
            <button className="btn btn-ghost btn-sm" onClick={() => decide(a.professionalId, false)}>Decline</button>
          </div>
        </section>))}
    </>
  )
}
