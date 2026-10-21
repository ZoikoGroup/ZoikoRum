import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { adminConsoleApi, type AdminConfig } from '../../api/adminConsole'
import { ErrorAlert } from '../../components/ui'
import { Icon } from '../../components/dashboard'
import {
  AdminHeader, AdminKpi, Callout, DetailPanel, Facts, FilterBar, FilterSelect, HBars, KpiStrip, ListDetail, MetricList, Panel, PanelRow,
  TableFoot,
} from '../../components/admin'

/* Platform Configuration (design 76): the published, read-only configuration from GET /v1/admin/config. Secrets are
   never returned by the server. Operational switches and feature flags are changed in Feature Controls. */

interface Row { id: string; key: string; value: string; description: string | null; domain: string }

export default function PlatformConfig() {
  const [config, setConfig] = useState<AdminConfig | null>(null)
  const [error, setError] = useState<unknown>(null)
  const [q, setQ] = useState('')
  const [domain, setDomain] = useState('')
  const [selectedId, setSelectedId] = useState<string | null>(null)

  const reload = useCallback(async () => setConfig(await adminConsoleApi.config()), [])
  useEffect(() => { reload().catch(setError) }, [reload])

  const groups = config?.groups ?? []
  const rows: Row[] = groups.flatMap((g) => g.settings.map((st) => ({ ...st, domain: g.domain, id: `${g.domain}:${st.key}` })))
  const s = q.trim().toLowerCase()
  const shown = rows.filter((r) => (!domain || r.domain === domain)
    && (!s || [r.key, r.value, r.description ?? '', r.domain].some((v) => v.toLowerCase().includes(s))))
  const selected = rows.find((r) => r.id === selectedId) ?? null
  const largest = [...groups].sort((a, b) => b.settings.length - a.settings.length)[0]

  return (
    <>
      <AdminHeader crumb="Administration & support / Controlled configuration" title="Platform Configuration"
        subtitle="Review the published settings the platform is running with. Values are read-only here; secrets are never shown."
        actions={<>
          <Link className="btn btn-secondary" to="/app/ops/switches"><Icon name="sliders" /> Feature controls</Link>
          <button type="button" className="btn btn-secondary" onClick={() => reload().catch(setError)}><Icon name="refresh" /> Refresh</button>
        </>}
        meta={config && <span className="live">{config.environment}{config.version ? ` · version ${config.version}` : ''}</span>} />
      <ErrorAlert error={error} />

      <KpiStrip>
        <AdminKpi icon="list" tone="blue" label="Published keys" value={config ? rows.length : '—'} sub={config ? `${groups.length} domains` : undefined} />
        <AdminKpi icon="layers" tone="violet" label="Domains" value={config ? groups.length : '—'} sub={largest ? `Largest: ${largest.domain}` : undefined} />
        <AdminKpi icon="globe" tone="green" label="Environment" value={config ? config.environment : '—'} />
        <AdminKpi icon="bookmark" tone="teal" label="Version" value={config ? config.version ?? 'Not set' : '—'} />
        <AdminKpi icon="help" tone="amber" label="Keys without description" value={config ? rows.filter((r) => !r.description).length : '—'} />
      </KpiStrip>

      <PanelRow cols={3}>
        <Panel title="Published configuration domains" meta={`${rows.length} keys · read-only`}>
          <HBars rows={groups.map((g) => ({ label: g.domain, value: g.settings.length }))} />
        </Panel>
        <Panel title="Environment and release">
          <MetricList rows={[
            { label: 'Environment', value: config?.environment ?? '—' },
            { label: 'Running version', value: config?.version ?? '—' },
          ]} />
        </Panel>
        <Panel title="Switches and feature flags">
          <p className="small" style={{ marginTop: 0 }}>Pausing an action or rolling out a feature is done in Feature Controls, with two-step sign-in, a reason and an audit record.</p>
          <Link className="btn btn-secondary btn-sm" to="/app/ops/switches">Open Feature Controls</Link>
        </Panel>
      </PanelRow>

      <ListDetail
        list={
          <div className="card">
            <FilterBar search={q} onSearch={setQ} placeholder="Search key, value, description or domain…">
              <FilterSelect label="Domain" value={domain} onChange={setDomain} options={groups.map((g) => [g.domain, `${g.domain} (${g.settings.length})`])} />
            </FilterBar>
            <div className="adm-note">Published values are read-only · secrets are never returned</div>
            <div className="adm-table-wrap">
              <table className="data">
                <thead><tr><th>Configuration key</th><th>Domain</th><th>Live value</th></tr></thead>
                <tbody>
                  {config === null && !error && <tr><td colSpan={3} className="empty-row">Loading configuration…</td></tr>}
                  {config && shown.length === 0 && <tr><td colSpan={3} className="empty-row">No keys match.</td></tr>}
                  {shown.map((r) => (
                    <tr key={r.id} className={`pick ${r.id === selectedId ? 'selected' : ''}`} onClick={() => setSelectedId(r.id)}>
                      <td><div className="cell-id"><code>{r.key}</code></div>{r.description && <div className="cell-sub">{r.description}</div>}</td>
                      <td className="small">{r.domain}</td>
                      <td style={{ fontWeight: 600, overflowWrap: 'anywhere', maxWidth: 280 }}>{r.value}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <TableFoot shown={shown.length} total={rows.length} noun="published keys" />
          </div>
        }
        detail={selected && (
          <DetailPanel title={selected.key} subtitle={selected.domain} onClose={() => setSelectedId(null)}
            footer={<Link className="btn btn-secondary btn-sm" to="/app/ops/switches">Feature controls</Link>}>
            <Callout tone="blue" title="Read-only">Published values cannot be changed from this console.</Callout>
            {selected.description && <p className="small" style={{ margin: 0 }}>{selected.description}</p>}
            <Facts title="Effective configuration" rows={[
              ['Key', <code key="k">{selected.key}</code>], ['Domain', selected.domain], ['Live value', selected.value],
              ['Environment', config?.environment ?? '—'], ['Version', config?.version ?? '—'],
            ]} />
          </DetailPanel>
        )}
      />
    </>
  )
}
