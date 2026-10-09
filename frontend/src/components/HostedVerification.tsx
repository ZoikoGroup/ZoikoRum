import { useEffect, useState } from 'react'
import { verificationApi } from '../api/verification'
import { ErrorAlert, useStepUp } from './ui'

export function HostedVerification({ caseId }: { caseId: string }) {
  const [configuration, setConfiguration] = useState<Awaited<ReturnType<typeof verificationApi.configuration>> | null>(null)
  const [error, setError] = useState<unknown>(null)
  const { run, modal } = useStepUp(setError)
  useEffect(() => { verificationApi.configuration().then(setConfiguration).catch(setError) }, [])
  if (!configuration?.hostedIdentity) return <ErrorAlert error={error} />
  return <div>{modal}<ErrorAlert error={error} />
    {configuration.configured ? <button className="btn btn-secondary" onClick={() => run(async () => {
      const result = await verificationApi.hosted(caseId)
      window.location.assign(result.url)
    })}>Verify identity securely</button> : <p className="muted">Online identity verification is unavailable. Submit documents below for review.</p>}
  </div>
}
