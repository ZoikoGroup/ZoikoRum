import { useEffect, useState } from 'react'
import { api } from '../api/client'
import { ErrorAlert, useStepUp } from './ui'
export function SearchAdministration() {
  const [config, setConfig] = useState<{ provider: string; index: string; modelConfigured: boolean; pipelineConfigured: boolean } | null>(null)
  const [error, setError] = useState<unknown>(null)
  const [notice, setNotice] = useState('')
  const [busy, setBusy] = useState(false)
  const { run, modal } = useStepUp(setError)
  useEffect(() => { api<typeof config>('/v1/admin/search/configuration').then(setConfig).catch(setError) }, [])
  function action(path: string, message: string) {
    run(async () => {
      setBusy(true); setNotice('')
      try { await api(`/v1/admin/search/${path}`, { method: 'POST' }); setNotice(message) }
      finally { setBusy(false) }
    })
  }
  return <section className="card panel"><h2>Search infrastructure</h2>{modal}<ErrorAlert error={error} />
    {notice && <p role="status">{notice}</p>}
    {config && <><p>Provider: {config.provider} · Index: {config.index}</p>
      {config.provider === 'opensearch' && <button className="btn btn-secondary" disabled={busy || !config.modelConfigured || !config.pipelineConfigured}
        onClick={() => action('bootstrap', 'Embedding pipeline and index validated. Rebuild the catalogue next.')}>Validate model and configure index</button>}
      <button className="btn btn-secondary" disabled={busy} onClick={() => action('reindex', 'Catalogue rebuilt.')}>Rebuild search catalogue</button>
    </>}
  </section>
}
