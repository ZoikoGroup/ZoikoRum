import { useState } from 'react'
import { api } from '../api/client'
import { openStoredFile } from '../api/files'
import { ErrorAlert, useStepUp } from '../components/ui'
import { EmptyTable, PortalHeader, StatCard } from '../components/portal'
import { Icon } from '../components/dashboard'
import { AuditArchives } from '../components/AuditArchives'
import { verifyAuditChain, type ChainCheck } from '../api/audit'
import { useAuth } from '../auth/AuthContext'

interface AuditExport {
  id: string
  status: string
  format: string
  recordCount: number
  contentSha256: string
  chainHeadHash: string
}

/** Recomputes the whole hash chain on demand (the worker also re-checks it hourly). */
function LedgerIntegrity({ onError }: { onError: (err: unknown) => void }) {
  const [result, setResult] = useState<(ChainCheck & { at: Date }) | null>(null)
  const [busy, setBusy] = useState(false)
  async function verify() {
    setBusy(true)
    onError(null)
    try {
      setResult({ ...(await verifyAuditChain()), at: new Date() })
    } catch (err) {
      onError(err)
    } finally {
      setBusy(false)
    }
  }
  return (
    <section className="card panel" style={{ marginBottom: 20 }}>
      <div className="panel-head">
        <h2>Ledger integrity</h2>
        <button type="button" className="btn btn-primary btn-sm" onClick={verify} disabled={busy}>
          <Icon name="shield" /> {busy ? 'Verifying…' : 'Verify ledger integrity'}
        </button>
      </div>
      {!result ? (
        <p className="muted small" style={{ margin: 0 }}>Recomputes every record's SHA-256 hash in order and checks it links to the one before.</p>
      ) : result.valid ? (
        <div className="alert alert-success" role="status" style={{ margin: 0 }}>
          Intact: all {result.checked.toLocaleString()} records verified at {result.at.toLocaleTimeString()}.
          {result.headHash && <span className="ref">Head hash <code>{result.headHash}</code></span>}
        </div>
      ) : (
        <div className="alert alert-error" role="alert" style={{ margin: 0 }}>
          Broken at record #{result.brokenAtSeq} ({result.checked.toLocaleString()} records verified before it). A
          HashChainBroken incident was raised; treat the ledger after that point as untrusted until investigated.
        </div>
      )}
    </section>
  )
}

export default function AuditExportsPage() {
  const [jobs, setJobs] = useState<AuditExport[]>([])
  const [error, setError] = useState<unknown>(null)
  const [busy, setBusy] = useState(false)
  const { run, modal } = useStepUp(setError)
  const { user } = useAuth()
  const canVerify = !!user?.platformRoles.some((r) => r === 'COMPLIANCE_OFFICER' || r === 'PLATFORM_ADMIN')

  return (
    <>
      <PortalHeader
        eyebrow="Compliance & Audit"
        title="Audit Ledger Exports"
        subtitle="Generate verifiable cryptographic audit bundles with SHA-256 chain integrity hashes."
      />

      <ErrorAlert error={error} />
      {modal}
      {canVerify && <LedgerIntegrity onError={setError} />}
      <AuditArchives />

      <div className="stat-row three" style={{ marginBottom: 20 }}>
        <StatCard
          icon="shield"
          tone="green"
          value="SHA-256 Chain"
          label="Tamper Evident"
          sub="Hourly continuous re-validation"
        />
        <StatCard
          icon="folder"
          tone="blue"
          value={jobs.length}
          label="Generated Bundles"
          sub="Downloadable authorized exports"
        />
        <StatCard
          icon="lock"
          tone="amber"
          value="Append-Only"
          label="Storage Guarantee"
          sub="Database triggers block modifications"
        />
      </div>

      <form
        className="card panel"
        onSubmit={(e) => {
          e.preventDefault()
          const d = new FormData(e.currentTarget)
          setBusy(true)
          run(async () => {
            try {
              const job = await api<AuditExport>('/v1/audit/exports', {
                method: 'POST',
                body: {
                  format: d.get('format'),
                  tenantId: d.get('tenantId') || null,
                  objectId: d.get('objectId') || null,
                  since: d.get('since') ? new Date(String(d.get('since'))).toISOString() : null,
                  until: d.get('until') ? new Date(String(d.get('until'))).toISOString() : null,
                },
              })
              setJobs((list) => [job, ...list])
            } finally {
              setBusy(false)
            }
          })
        }}
        style={{ marginBottom: 20 }}
      >
        <div className="panel-head">
          <h2>Request Cryptographic Export Bundle</h2>
        </div>
        <p className="muted small">
          Exports are generated on demand from the append-only audit ledger and signed with the current chain head hash.
        </p>

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
            <select id="auditexports-format" className="input" name="format">
              <option value="json">JSON</option>
              <option value="csv">CSV</option>
            </select>
          </div>
        </div>

        <button type="submit" className="btn btn-primary" disabled={busy}>
          Generate Authorised Export (Step-Up Authenticated)
        </button>
      </form>

      <section className="card panel">
        <div className="panel-head">
          <h2>Export History &amp; Chain Evidence</h2>
        </div>

        {jobs.length === 0 ? (
          <EmptyTable columns={['Status', 'Records', 'Content Fingerprint', 'Chain Head Hash', 'Action']}>
            No export bundles requested in this session. Configure filters above to generate an audit package.
          </EmptyTable>
        ) : (
          <div style={{ display: 'grid', gap: 14 }}>
            {jobs.map((job) => (
              <div
                key={job.id}
                className="card panel"
                style={{
                  margin: 0,
                  background: 'var(--zk-surface)',
                  border: '1px solid var(--zk-border)',
                }}
              >
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 12 }}>
                  <div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
                      <h3 style={{ margin: 0 }}>
                        {job.status} · {job.recordCount} Audit Records
                      </h3>
                      <span className="badge green">{job.format.toUpperCase()}</span>
                    </div>
                    <p className="small muted" style={{ margin: '4px 0 2px' }}>
                      Content Fingerprint (SHA-256): <code>{job.contentSha256}</code>
                    </p>
                    <p className="small muted" style={{ margin: 0 }}>
                      Chain Head Hash: <code>{job.chainHeadHash}</code>
                    </p>
                  </div>
                  <button
                    type="button"
                    className="btn btn-secondary btn-sm"
                    onClick={() => openStoredFile(`/v1/audit/exports/${job.id}/download`).catch(setError)}
                  >
                    <Icon name="download" /> Download {job.format.toUpperCase()}
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </section>
    </>
  )
}
