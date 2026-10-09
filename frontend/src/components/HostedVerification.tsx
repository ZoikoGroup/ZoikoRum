import { useEffect, useState } from 'react'
import { verificationApi, type VerificationCase } from '../api/verification'
import { ErrorAlert, useStepUp } from './ui'

type Configuration = Awaited<ReturnType<typeof verificationApi.configuration>>

/** Identity check in the identity partner's hosted flow (Persona or Veriff): photo of the ID, then a selfie.
 *  An approval verifies automatically; a decline goes to a compliance officer. With the development simulator
 *  (ZK_VERIFICATION_PROVIDER=simulated) the page offers the answers a partner can give. */
export function HostedVerification({ c, onChange }: { c: VerificationCase; onChange: (c: VerificationCase) => void }) {
  const [configuration, setConfiguration] = useState<Configuration | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<unknown>(null)
  const { run, modal } = useStepUp(setError)
  useEffect(() => { verificationApi.configuration().then(setConfiguration).catch(setError) }, [])
  if (!configuration?.hostedIdentity) return <ErrorAlert error={error} />
  if (!configuration.configured) return <p className="muted small">Online identity verification is unavailable. Submit documents below for review.</p>

  const name = configuration.partnerName ?? 'our identity partner'
  const status = c.hostedStatus ?? null
  const waiting = c.status === 'PENDING' || c.status === 'NEEDS_INFO'
  const started = status === 'pending'
  const act = (fn: () => Promise<void>) => () => {
    setBusy(true)
    setError(null)
    run(fn).finally(() => setBusy(false))
  }
  const start = act(async () => {
    const result = await verificationApi.hosted(c.id)
    if (result.url) window.location.assign(result.url)  // the partner sends the person back to this page
    else onChange(await verificationApi.get(c.id))
  })
  const refresh = act(async () => onChange(await verificationApi.hostedRefresh(c.id)))
  const simulate = (answer: Parameters<typeof verificationApi.hostedSimulate>[1]) =>
    act(async () => onChange(await verificationApi.hostedSimulate(c.id, answer)))

  return (
    <div className="kyc-panel">
      {modal}
      <ErrorAlert error={error} />
      {waiting && !started && <>
        <p className="small" style={{ margin: '0 0 8px' }}>Takes about 2 minutes with {name}: a photo of your passport, national ID
          (e.g. Aadhaar) or driving licence, then a short selfie. Most checks are decided in minutes.</p>
        <button className="btn btn-primary btn-sm" disabled={busy} onClick={start}>Verify identity securely</button>
      </>}
      {waiting && started && configuration.provider !== 'simulated' && <div className="row">
        <button className="btn btn-primary btn-sm" disabled={busy} onClick={start}>Continue with {name}</button>
        <button className="btn btn-ghost btn-sm" disabled={busy} onClick={refresh}>I have finished — check result</button>
      </div>}
      {waiting && started && configuration.provider === 'simulated' && <>
        <p className="small" style={{ margin: '0 0 8px' }}><span className="badge warn">Development</span> No identity partner is connected.
          Choose the answer the partner would give:</p>
        <div className="row">
          <button className="btn btn-primary btn-sm" disabled={busy} onClick={simulate('approved')}>Approved</button>
          <button className="btn btn-secondary btn-sm" disabled={busy} onClick={simulate('resubmission_requested')}>Retake photo</button>
          <button className="btn btn-secondary btn-sm" disabled={busy} onClick={simulate('needs_review')}>Needs a person</button>
          <button className="btn btn-secondary btn-sm" disabled={busy} onClick={simulate('declined')}>Declined</button>
        </div>
      </>}
      {c.status === 'IN_REVIEW' && status === 'submitted' && <div className="row">
        <span className="small">{name} is checking your photos. This usually takes a few minutes.</span>
        <button className="btn btn-ghost btn-sm" disabled={busy} onClick={refresh}>Check result</button>
      </div>}
      {c.status === 'IN_REVIEW' && status && !['pending', 'submitted'].includes(status) &&
        <p className="small" style={{ margin: 0 }}>{name} could not confirm your identity automatically, so a compliance reviewer is checking it.
          You will hear back within about 24 hours.</p>}
    </div>
  )
}
