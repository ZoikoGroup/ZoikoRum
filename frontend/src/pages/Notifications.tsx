import { useCallback, useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { notificationApi, type Notification, type Endpoint, type Delivery, type DeliveryAttempt } from '../api/notifications'
import { orgApi, type Organization } from '../api/orgs'
import { ErrorAlert, useStepUp } from '../components/ui'
import { EmptyTable, PortalHeader, SidePanel, StatCard } from '../components/portal'
import { Icon } from '../components/dashboard'

export function NotificationsPage() {
  const [rows, setRows] = useState<Notification[]>([])
  const [cursor, setCursor] = useState<string | null>(null)
  const initialLoad = useRef(false)
  const [error, setError] = useState<unknown>(null)

  const load = useCallback(async () => {
    const page = await notificationApi.inbox()
    setRows((previous) => {
      const ids = new Set(page.items.map((row) => row.id))
      return [...page.items, ...previous.filter((row) => !ids.has(row.id))]
    })
    if (!initialLoad.current) {
      setCursor(page.nextCursor)
      initialLoad.current = true
    }
  }, [])

  useEffect(() => {
    load().catch(setError)
    const timer = window.setInterval(() => load().catch(setError), 15000)
    return () => window.clearInterval(timer)
  }, [load])

  async function open(row: Notification) {
    try {
      const result = await notificationApi.read(row.id)
      setRows((list) => list.map((r) => (r.id === row.id ? result : r)))
    } catch (err) {
      setError(err)
    }
  }

  const unreadCount = rows.filter((r) => !r.readAt).length

  return (
    <>
      <PortalHeader
        eyebrow="Communications"
        title="Notifications"
        subtitle="Important activity updates, contractual notifications, and mandatory security notices."
        actions={
          <button className="btn btn-secondary" onClick={() => load().catch(setError)}>
            <Icon name="clock" /> Refresh
          </button>
        }
      />

      <ErrorAlert error={error} />

      <div className="stat-row three" style={{ marginBottom: 20 }}>
        <StatCard
          icon="bell"
          tone={unreadCount > 0 ? 'amber' : 'green'}
          value={unreadCount}
          label="Unread Notices"
          sub={unreadCount > 0 ? 'Require your attention' : 'All caught up'}
        />
        <StatCard
          icon="shield"
          tone="blue"
          value="Mandatory"
          label="Security & Compliance"
          sub="Direct delivery cannot be opted out"
        />
        <StatCard
          icon="gear"
          tone="violet"
          value="Settings"
          label="Channel Preferences"
          sub="Manage in Settings"
          to="/app/settings"
        />
      </div>

      <section className="card panel">
        <div className="panel-head">
          <h2>Inbox Activity</h2>
          <span className="small muted">
            Manage channel preferences in <Link to="/app/settings">Settings</Link>. Security and safety notices are mandatory.
          </span>
        </div>

        {rows.length === 0 ? (
          <EmptyTable columns={['Status', 'Title', 'Details', 'Date', 'Action']}>
            No notifications in your inbox.
          </EmptyTable>
        ) : (
          <div style={{ display: 'grid', gap: 12 }}>
            {rows.map((row) => (
              <article
                key={row.id}
                className="card panel"
                style={{
                  margin: 0,
                  borderLeft: !row.readAt ? '4px solid var(--zk-green)' : undefined,
                  background: !row.readAt ? 'var(--zk-surface)' : 'var(--zk-bg-soft)',
                }}
              >
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 12 }}>
                  <div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
                      {!row.readAt && <span className="badge green">Unread</span>}
                      <h3 style={{ margin: 0 }}>{row.title}</h3>
                    </div>
                    <span className="small muted">{new Date(row.createdAt).toLocaleString()}</span>
                  </div>
                  <div className="row" style={{ gap: 8 }}>
                    <Link
                      className="btn btn-primary btn-sm"
                      to={row.url.startsWith('/app/') ? row.url : '/app/notifications'}
                      onClick={() => open(row)}
                    >
                      View Update
                    </Link>
                    {!row.readAt && (
                      <button type="button" className="btn btn-secondary btn-sm" onClick={() => open(row)}>
                        Mark Read
                      </button>
                    )}
                  </div>
                </div>

                {row.notice ? (
                  <dl className="facts" style={{ marginTop: 12 }}>
                    {Object.entries(row.notice).map(([key, value]) => (
                      <div key={key}>
                        <dt>{key.replace(/([A-Z])/g, ' $1')}</dt>
                        <dd>{value}</dd>
                      </div>
                    ))}
                  </dl>
                ) : (
                  <p style={{ marginTop: 8, marginBottom: 0, fontSize: 14 }}>{row.body}</p>
                )}
              </article>
            ))}
          </div>
        )}

        {cursor && (
          <div style={{ textAlign: 'center', marginTop: 16 }}>
            <button
              type="button"
              className="btn btn-secondary btn-sm"
              onClick={async () => {
                try {
                  const page = await notificationApi.inbox(cursor)
                  setRows((r) => [...r, ...page.items])
                  setCursor(page.nextCursor)
                } catch (err) {
                  setError(err)
                }
              }}
            >
              Load Older Notifications
            </button>
          </div>
        )}
      </section>
    </>
  )
}

export function WebhooksPage() {
  const [orgs, setOrgs] = useState<Organization[]>([])
  const [orgId, setOrgId] = useState('')
  const [endpoints, setEndpoints] = useState<Endpoint[]>([])
  const [events, setEvents] = useState<{ eventType: string; label: string }[]>([])
  const [eventsLoading, setEventsLoading] = useState(true)
  const [selected, setSelected] = useState<string[]>([])
  const [secret, setSecret] = useState<string | null>(null)
  const [deliveries, setDeliveries] = useState<Delivery[]>([])
  const [deliveryCursor, setDeliveryCursor] = useState<string | null>(null)
  const [deliveryEndpoint, setDeliveryEndpoint] = useState('')
  const [activeEndpointForLogs, setActiveEndpointForLogs] = useState<Endpoint | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<unknown>(null)
  const { run, modal } = useStepUp(setError)

  // Group events by domain prefix for easier navigation (e.g. "zoikorum.contract.*")
  const eventGroups = events.reduce<Record<string, { eventType: string; label: string }[]>>((acc, e) => {
    const parts = e.eventType.split('.')
    const domain = parts[1] ?? 'other'
    if (!acc[domain]) acc[domain] = []
    acc[domain].push(e)
    return acc
  }, {})

  async function showDeliveries(endpointId: string, cursor?: string) {
    const page = await notificationApi.deliveries(endpointId, cursor)
    setDeliveries((previous) => (cursor ? [...previous, ...page.items] : page.items))
    setDeliveryCursor(page.nextCursor)
    setDeliveryEndpoint(endpointId)
    const ep = endpoints.find((e) => e.id === endpointId) ?? null
    setActiveEndpointForLogs(ep)
  }

  useEffect(() => {
    orgApi
      .mine()
      .then((list) => {
        const admins = list.filter((o) => o.myRoles.includes('ORG_ADMIN'))
        setOrgs(admins)
        setOrgId(admins[0]?.id || '')
      })
      .catch(setError)
    notificationApi
      .eventTypes()
      .then(setEvents)
      .catch(setError)
      .finally(() => setEventsLoading(false))
  }, [])

  const reload = useCallback(async () => {
    if (orgId) setEndpoints(await notificationApi.endpoints(orgId))
  }, [orgId])

  useEffect(() => {
    reload().catch(setError)
  }, [reload])

  const enabledEndpoints = endpoints.filter((e) => e.enabled)
  const totalSubscribed = endpoints.reduce((acc, e) => acc + e.eventTypes.length, 0)

  return (
    <>
      <PortalHeader
        eyebrow="Integrations & Security"
        title="Enterprise Webhooks"
        subtitle="Register HTTPS endpoints to receive signed real-time platform events with exponential backoff and replay protection."
        actions={
          <button className="btn btn-secondary" onClick={() => reload().catch(setError)} disabled={busy}>
            <Icon name="clock" /> Refresh
          </button>
        }
      />

      <ErrorAlert error={error} />
      {modal}

      <div className="stat-row four">
        <StatCard
          icon="globe"
          tone="green"
          value={enabledEndpoints.length}
          label="Active Endpoints"
          sub={`${endpoints.length} configured endpoint${endpoints.length === 1 ? '' : 's'}`}
        />
        <StatCard
          icon="bell"
          tone="violet"
          value={totalSubscribed}
          label="Subscribed Events"
          sub="Across all configured destinations"
        />
        <StatCard
          icon="shield"
          tone="blue"
          value="HMAC-SHA256"
          label="Signature Security"
          sub="Header: X-Zoikorum-Signature"
        />
        <StatCard
          icon="clock"
          tone="amber"
          value="24h Retry"
          label="Delivery Guarantee"
          sub="90+ day immutable logs retained"
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
              className="input"
              aria-label="Organisation"
              style={{ maxWidth: 360 }}
              value={orgId}
              onChange={(e) => {
                setOrgId(e.target.value)
                setDeliveries([])
                setDeliveryCursor(null)
                setDeliveryEndpoint('')
                setSecret(null)
                setActiveEndpointForLogs(null)
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
            <span className="badge green">
              <Icon name="shield" /> Org Admin Only
            </span>
          </div>
        </div>
      </div>

      {secret && (
        <section
          className="attention-banner"
          style={{ background: 'var(--zk-ok-bg)', borderColor: '#abefc6', marginBottom: 20 }}
        >
          <span className="kpi-icon green" style={{ width: 34, height: 34 }}>
            <Icon name="lock" />
          </span>
          <div style={{ flex: 1 }}>
            <h3 style={{ margin: '0 0 4px', color: '#05603a' }}>Signing Secret — Shown Once</h3>
            <p className="small" style={{ margin: '0 0 8px', color: '#05603a' }}>
              Store this secret in your vault immediately. Zoikorum encrypts webhook secrets at rest and will not display this plaintext secret again.
            </p>
            <div className="secret">{secret}</div>
            <p className="small muted" style={{ margin: '6px 0 0' }}>
              Verify <code>X-Zoikorum-Signature</code>: HMAC-SHA256 signature calculated over timestamp + &ldquo;.&rdquo; + raw request payload.
            </p>
          </div>
          <button type="button" className="btn btn-secondary btn-sm" onClick={() => setSecret(null)}>
            Dismiss Secret
          </button>
        </section>
      )}

      <div className="home-grid wide">
        <div>
          <section className="card panel">
            <div className="panel-head">
              <h2>Registered Endpoints</h2>
              <span className="small muted">{endpoints.length} configured</span>
            </div>

            {endpoints.length === 0 ? (
              <EmptyTable columns={['Endpoint URL', 'Status', 'Events', 'Actions']}>
                No webhook endpoints configured yet. Register a destination on the right to receive events.
              </EmptyTable>
            ) : (
              <div style={{ display: 'grid', gap: 14 }}>
                {endpoints.map((endpoint) => (
                  <div
                    key={endpoint.id}
                    className="card panel"
                    style={{
                      margin: 0,
                      background: 'var(--zk-surface)',
                      border: '1px solid var(--zk-border)',
                      borderLeft: endpoint.enabled ? '4px solid var(--zk-green)' : '4px solid var(--zk-subtle)',
                    }}
                  >
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 12, flexWrap: 'wrap' }}>
                      <div>
                        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
                          <h3 style={{ margin: 0, fontFamily: 'ui-monospace, monospace', fontSize: 15 }}>
                            {endpoint.url}
                          </h3>
                          <span className={`badge ${endpoint.enabled ? 'green' : 'warn'}`}>
                            {endpoint.enabled ? 'Enabled' : 'Disabled'}
                          </span>
                        </div>
                        <div className="chips" style={{ marginTop: 8 }}>
                          {endpoint.eventTypes.map((t) => (
                            <span key={t} className="chip">
                              {t}
                            </span>
                          ))}
                        </div>
                      </div>

                      <div className="row" style={{ gap: 6 }}>
                        <button
                          type="button"
                          className="btn btn-secondary btn-sm"
                          disabled={busy}
                          onClick={() =>
                            run(async () => {
                              setBusy(true)
                              try {
                                await notificationApi.enable(endpoint.id, !endpoint.enabled)
                                await reload()
                              } finally {
                                setBusy(false)
                              }
                            })
                          }
                        >
                          {endpoint.enabled ? 'Disable' : 'Enable'}
                        </button>
                        <button
                          type="button"
                          className="btn btn-secondary btn-sm"
                          disabled={busy}
                          onClick={() =>
                            run(async () => {
                              setBusy(true)
                              try {
                                await notificationApi.test(endpoint.id)
                                await showDeliveries(endpoint.id)
                              } finally {
                                setBusy(false)
                              }
                            })
                          }
                        >
                          Test Delivery
                        </button>
                        <button
                          type="button"
                          className="btn btn-ghost btn-sm"
                          onClick={() => showDeliveries(endpoint.id).catch(setError)}
                        >
                          Delivery Logs ›
                        </button>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </section>

          {deliveries.length > 0 && (
            <section className="card panel" style={{ marginTop: 20 }}>
              <div className="panel-head">
                <h2>
                  Delivery Logs {activeEndpointForLogs && `for ${activeEndpointForLogs.url}`}
                </h2>
                <span className="small muted">Retained for at least 90 days</span>
              </div>

              <table className="data">
                <thead>
                  <tr>
                    <th>Event Type</th>
                    <th>Status</th>
                    <th>Attempts</th>
                    <th>Timestamp</th>
                    <th>Action</th>
                  </tr>
                </thead>
                <tbody>
                  {deliveries.map((delivery) => (
                    <tr key={delivery.id}>
                      <td>
                        <strong>{delivery.eventType}</strong>
                        <div style={{ marginTop: 4 }}>
                          <DeliveryAttempts id={delivery.id} />
                        </div>
                      </td>
                      <td>
                        <span
                          className={`badge ${
                            delivery.status === 'DELIVERED'
                              ? 'green'
                              : delivery.status === 'PENDING'
                              ? 'warn'
                              : 'prio-high'
                          }`}
                        >
                          {delivery.status}
                        </span>
                      </td>
                      <td>{delivery.attempts} attempt{delivery.attempts === 1 ? '' : 's'}</td>
                      <td className="small">{new Date(delivery.createdAt).toLocaleString()}</td>
                      <td>
                        {delivery.status !== 'PENDING' && (
                          <button
                            type="button"
                            className="btn btn-secondary btn-sm"
                            disabled={busy}
                            onClick={() =>
                              run(async () => {
                                setBusy(true)
                                try {
                                  await notificationApi.replay(delivery.id)
                                  await showDeliveries(delivery.endpointId)
                                } finally {
                                  setBusy(false)
                                }
                              })
                            }
                          >
                            Replay
                          </button>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>

              {deliveryCursor && (
                <div style={{ textAlign: 'center', marginTop: 14 }}>
                  <button
                    type="button"
                    className="btn btn-secondary btn-sm"
                    onClick={() => showDeliveries(deliveryEndpoint, deliveryCursor).catch(setError)}
                  >
                    Load Older Deliveries
                  </button>
                </div>
              )}
            </section>
          )}
        </div>

        <aside>
          <form
            className="card panel"
            onSubmit={(e) => {
              e.preventDefault()
              const url = String(new FormData(e.currentTarget).get('url'))
              run(async () => {
                setBusy(true)
                try {
                  const result = await notificationApi.createEndpoint(orgId, url, selected)
                  setSecret(result.secret)
                  setSelected([])
                  await reload()
                } finally {
                  setBusy(false)
                }
              })
            }}
          >
            <div className="panel-head">
              <h2>Add Endpoint</h2>
            </div>
            <p className="muted small">
              Register a public HTTPS URL. Zoikorum will sign payloads with a dedicated shared secret.
            </p>

            <div className="field">
              <label>Endpoint Destination URL</label>
              <input
                className="input"
                name="url"
                type="url"
                required
                placeholder="https://events.yourdomain.com/webhook"
                aria-label="Webhook URL"
              />
              <span className="hint">Must use secure HTTPS with public DNS resolution</span>
            </div>

            <div className="field">
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
                <label style={{ margin: 0 }}>Subscribed Event Types ({selected.length} selected)</label>
                <div style={{ display: 'flex', gap: 6 }}>
                  <button
                    type="button"
                    className="btn btn-ghost btn-sm"
                    style={{ padding: '2px 8px', fontSize: 12 }}
                    onClick={() => setSelected(events.map((e) => e.eventType))}
                  >
                    Select All
                  </button>
                  <button
                    type="button"
                    className="btn btn-ghost btn-sm"
                    style={{ padding: '2px 8px', fontSize: 12 }}
                    onClick={() => setSelected([])}
                  >
                    Clear
                  </button>
                </div>
              </div>
              <div
                style={{
                  maxHeight: 300,
                  overflowY: 'auto',
                  border: '1px solid var(--zk-border)',
                  borderRadius: 'var(--radius-sm)',
                  padding: 8,
                  background: 'var(--zk-bg-soft)',
                }}
              >
                {eventsLoading ? (
                  <p className="muted small" style={{ margin: '12px 6px' }}>Loading available event types…</p>
                ) : events.length === 0 ? (
                  <p className="muted small" style={{ margin: '12px 6px' }}>No webhook-eligible event types configured.</p>
                ) : (
                  Object.entries(eventGroups)
                    .sort(([a], [b]) => a.localeCompare(b))
                    .map(([domain, domainEvents]) => (
                      <div key={domain} style={{ marginBottom: 10 }}>
                        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 2 }}>
                          <span
                            style={{
                              fontSize: 11,
                              fontWeight: 700,
                              color: 'var(--zk-muted)',
                              textTransform: 'uppercase',
                              letterSpacing: '0.06em',
                            }}
                          >
                            {domain.replace(/_/g, ' ')}
                          </span>
                          <button
                            type="button"
                            className="btn btn-ghost btn-sm"
                            style={{ padding: '1px 6px', fontSize: 11 }}
                            onClick={() => {
                              const domainTypes = domainEvents.map((e) => e.eventType)
                              const allSelected = domainTypes.every((t) => selected.includes(t))
                              setSelected((list) =>
                                allSelected
                                  ? list.filter((v) => !domainTypes.includes(v))
                                  : [...new Set([...list, ...domainTypes])]
                              )
                            }}
                          >
                            {domainEvents.every((e) => selected.includes(e.eventType)) ? 'Deselect' : 'Select'} {domain}
                          </button>
                        </div>
                        {domainEvents.map((event) => (
                          <label
                            key={event.eventType}
                            style={{
                              display: 'flex',
                              alignItems: 'flex-start',
                              gap: 8,
                              fontSize: 13,
                              padding: '4px 6px',
                              cursor: 'pointer',
                            }}
                          >
                            <input
                              type="checkbox"
                              checked={selected.includes(event.eventType)}
                              onChange={() =>
                                setSelected((list) =>
                                  list.includes(event.eventType)
                                    ? list.filter((v) => v !== event.eventType)
                                    : [...list, event.eventType]
                                )
                              }
                              style={{ marginTop: 2, flexShrink: 0 }}
                            />
                            <span>
                              <span style={{ fontWeight: 500 }}>{event.label}</span>
                              <span className="muted" style={{ fontSize: 11, display: 'block' }}>{event.eventType}</span>
                            </span>
                          </label>
                        ))}
                      </div>
                    ))
                )}
              </div>
            </div>

            <button
              type="submit"
              className="btn btn-primary btn-block"
              disabled={!orgId || !selected.length || busy}
            >
              Create Endpoint (Step-Up)
            </button>
          </form>

          <SidePanel title="Security & Verification">
            <ul className="assurance compact">
              <li>
                <Icon name="shield" />
                <span>
                  <strong>HMAC-SHA256 Signing:</strong> Every POST request carries the <code>X-Zoikorum-Signature</code> header.
                </span>
              </li>
              <li>
                <Icon name="clock" />
                <span>
                  <strong>Replay Protection:</strong> Timestamps older than 5 minutes or duplicate delivery IDs should be rejected.
                </span>
              </li>
              <li>
                <Icon name="check" />
                <span>
                  <strong>24-Hour Retry:</strong> Unreachable endpoints retry with exponential backoff before being marked failed.
                </span>
              </li>
              <li>
                <Icon name="folder" />
                <span>
                  <strong>SSRF Safe:</strong> Private IP ranges (RFC 1918) and DNS rebinding attacks are filtered at egress.
                </span>
              </li>
            </ul>
          </SidePanel>
        </aside>
      </div>
    </>
  )
}

function DeliveryAttempts({ id }: { id: string }) {
  const [rows, setRows] = useState<DeliveryAttempt[] | null>(null)
  const [error, setError] = useState<unknown>(null)
  const [open, setOpen] = useState(false)

  return (
    <div>
      <button
        type="button"
        className="btn btn-ghost btn-sm"
        style={{ padding: '2px 6px', height: 26, fontSize: 12 }}
        onClick={() => {
          if (!open && !rows) {
            notificationApi.attempts(id).then(setRows).catch(setError)
          }
          setOpen((v) => !v)
        }}
      >
        {open ? 'Hide attempts ▲' : 'View attempt history ▼'}
      </button>

      <ErrorAlert error={error} />

      {open && rows && (
        <div style={{ marginTop: 8, background: 'var(--zk-bg)', padding: 8, borderRadius: 'var(--radius-sm)' }}>
          <table className="data" style={{ fontSize: 12 }}>
            <thead>
              <tr>
                <th>#</th>
                <th>Time</th>
                <th>Status</th>
                <th>Error</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.attempt}>
                  <td>{row.attempt}</td>
                  <td>{new Date(row.createdAt).toLocaleTimeString()}</td>
                  <td>
                    <code>{row.responseStatus ?? 'None'}</code>
                  </td>
                  <td className="small muted">{row.error || 'None'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
