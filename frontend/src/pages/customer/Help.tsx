import { useCallback, useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { SUPPORT_STATUS, SUPPORT_TOPICS, supportApi, type SupportRequest, type SupportTopic } from '../../api/support'
import { SupportThread } from '../../components/SupportThread'
import { ErrorAlert } from '../../components/ui'
import { Icon, type IconName } from '../../components/dashboard'
import { EmptyTable, PortalHeader, SidePanel } from '../../components/portal'

interface Topic { icon: IconName; title: string; summary: string; answers: [string, string][] }

// Plain-language help drawn from the product docs. No invented phone numbers, SLAs or chat agents.
const TOPICS: Topic[] = [
  { icon: 'search', title: 'Finding professionals', summary: 'Search, filters, trust lights and compare.', answers: [
    ['How is search ranked?', 'By relevance to your words, then verification, availability and fit. Nobody can pay to rank higher. Each result shows why it matched.'],
    ['What does a trust light mean?', 'Green (fully verified): identity, credentials and eligibility verified. Amber (identity verified): identity verified and restrictions clear. Red (not verified yet): verification not complete.'],
    ['How many can I compare?', 'Up to three professionals side by side.'],
  ] },
  { icon: 'shield', title: 'Verification & trust', summary: 'What is checked, and by whom.', answers: [
    ['Who verifies professionals?', 'A verification provider or a compliance reviewer. AI never decides a verification outcome.'],
    ['Why can’t I see a trust score?', 'The raw score is internal. You see the trust light and each verified dimension, which is what matters for a decision.'],
  ] },
  { icon: 'request', title: 'Requests & proposals', summary: 'From a need to a selected professional.', answers: [
    ['How do I ask for a proposal?', 'Open a verified professional’s profile (or a search result) and choose Request proposal. Describe the work, deliverables and budget; the professional answers with a proposal you can compare, revise or accept.'],
    ['Can I require an NDA?', 'Yes — a request can require an NDA before the professional sees its details.'],
  ] },
  { icon: 'contract', title: 'Contracts & engagements', summary: 'Signing, milestones and changes.', answers: [
    ['Can the terms change after signing?', 'Only through a versioned change order that both parties accept.'],
    ['When does work start?', 'After the contract is signed and the first milestone is funded.'],
  ] },
  { icon: 'lock', title: 'Payments & protection', summary: 'Escrow, release and refunds.', answers: [
    ['When is the professional paid?', 'Only after you accept a milestone. Until then the funds are held in escrow for that engagement.'],
    ['Does Zoikorum store my card?', 'No. Only a token from the payment partner is stored. Zoikorum is not a bank and holds no balance for you.'],
  ] },
  { icon: 'team', title: 'Organisation & access', summary: 'Members, roles and approvals.', answers: [
    ['Who can approve spending?', 'Approvers up to their spend limit. Requesters cannot approve their own requests.'],
    ['How do I add a colleague?', 'Org Admins invite members and assign roles from Organisation → Members & access.'],
  ] },
  { icon: 'user', title: 'Account & security', summary: 'Sign-in, two-step verification, privacy.', answers: [
    ['How do I turn on two-step verification?', 'Settings → Security → Two-step verification. Admin roles must use it.'],
    ['How do I get or delete my data?', 'Settings → Privacy & data. Legally required records are kept and anonymised where possible.'],
  ] },
  { icon: 'bell', title: 'Disputes', summary: 'When something goes wrong.', answers: [
    ['What happens in a dispute?', 'The milestone’s funds are frozen and a mediator reviews the evidence. Direct messages are replaced by the dispute thread.'],
  ] },
]

/** Help & Support (management design 13): searchable answers, service status, support cases. */
export default function HelpPage() {
  const [q, setQ] = useState('')
  const [open, setOpen] = useState<string | null>(null)
  const [status, setStatus] = useState<'checking' | 'ok' | 'down'>('checking')
  useEffect(() => {
    fetch('/health').then((r) => setStatus(r.ok ? 'ok' : 'down')).catch(() => setStatus('down'))
  }, [])

  const term = q.trim().toLowerCase()
  const matches = term
    ? TOPICS.flatMap((t) => t.answers.filter(([qq, a]) => `${qq} ${a}`.toLowerCase().includes(term)).map((a) => ({ topic: t.title, a })))
    : []

  return (
    <>
      <PortalHeader eyebrow="Help & support" title="How can we help?" subtitle="Answers about finding, verifying, contracting and paying professionals on Zoikorum." />
      <section className="card panel search-panel">
        <form className="search-bar" role="search" onSubmit={(e) => e.preventDefault()}>
          <input className="input" aria-label="Search help" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search help (e.g. escrow, trust light, NDA)" />
        </form>
        {term && (
          matches.length === 0 ? <p className="muted small" style={{ marginBottom: 0 }}>No answers match “{q}”.</p> : (
            <ul className="help-answers">{matches.map(({ topic, a: [qq, ans] }) => <li key={qq}><span className="muted small">{topic}</span><strong>{qq}</strong><span>{ans}</span></li>)}</ul>
          )
        )}
      </section>

      <div className="home-grid wide">
        <div>
          <div className="help-grid">
            {TOPICS.map((t) => (
              <section key={t.title} className={`card help-card ${open === t.title ? 'open' : ''}`}>
                <button className="help-head" aria-expanded={open === t.title} onClick={() => setOpen(open === t.title ? null : t.title)}>
                  <span className="kpi-icon blue"><Icon name={t.icon} /></span>
                  <span><strong>{t.title}</strong><br /><span className="muted small">{t.summary}</span></span>
                </button>
                {open === t.title && <dl className="help-answers">{t.answers.map(([qq, a]) => <div key={qq}><dt>{qq}</dt><dd>{a}</dd></div>)}</dl>}
              </section>
            ))}
          </div>
          <SupportRequests />
        </div>
        <aside>
          <SidePanel title="Service status">
            <div className="status-line">
              <span className={`status-dot ${status}`} aria-hidden />
              <span>{status === 'checking' ? 'Checking…' : status === 'ok' ? 'All systems operational' : 'We can’t reach the service right now'}</span>
            </div>
          </SidePanel>
          <SidePanel title="Quick links">
            <ul className="quick-actions">
              <li><Link to="/app/settings?tab=security"><Icon name="lock" /><span>Security settings</span><span aria-hidden>›</span></Link></li>
              <li><Link to="/app/settings?tab=privacy"><Icon name="download" /><span>Privacy &amp; your data</span><span aria-hidden>›</span></Link></li>
              <li><Link to="/legal/terms"><Icon name="contract" /><span>Terms of service</span><span aria-hidden>›</span></Link></li>
              <li><Link to="/legal/privacy"><Icon name="shield" /><span>Privacy notice</span><span aria-hidden>›</span></Link></li>
            </ul>
          </SidePanel>
        </aside>
      </div>
    </>
  )
}


/** Ask Zoikorum for help and follow the conversation (the error reference and engagement come from the link, if any). */
function SupportRequests() {
  const [params, setParams] = useSearchParams()
  const [rows, setRows] = useState<SupportRequest[] | null>(null)
  const [selected, setSelected] = useState<SupportRequest | null>(null)
  const [asking, setAsking] = useState(!!params.get('ref'))
  const [topic, setTopic] = useState<SupportTopic>(params.get('ref') ? 'TECHNICAL' : 'ACCOUNT')
  const [subject, setSubject] = useState('')
  const [message, setMessage] = useState('')
  const [error, setError] = useState<unknown>(null)
  const [busy, setBusy] = useState(false)
  const load = useCallback(() => supportApi.mine().then(setRows).catch(setError), [])
  useEffect(() => { load() }, [load])
  const openId = params.get('request')
  useEffect(() => { if (openId) supportApi.get(openId).then(setSelected).catch(setError) }, [openId])

  async function submit() {
    setBusy(true); setError(null)
    try {
      const r = await supportApi.open({ topic, subject: subject.trim(), message: message.trim(), context: {
        page: params.get('from') ?? undefined, contractId: params.get('contract') ?? undefined, errorReference: params.get('ref') ?? undefined } })
      setAsking(false); setSubject(''); setMessage(''); setSelected(r); await load()
      setParams({ request: r.id })
    } catch (err) { setError(err) } finally { setBusy(false) }
  }

  return <>
    {selected && <SupportThread request={selected}
      onReply={async (m) => { setSelected(await supportApi.reply(selected.id, m)); await load() }}
      onResolve={async () => { setSelected(await supportApi.resolve(selected.id)); await load() }} />}
    <section className="card panel">
      <div className="panel-head"><h2>Your help requests</h2>
        {!asking && <button className="btn btn-primary btn-sm" onClick={() => setAsking(true)}>Ask for help</button>}</div>
      <ErrorAlert error={error} />
      {asking && <form onSubmit={(e) => { e.preventDefault(); void submit() }} style={{ marginBottom: 16 }}>
        {params.get('ref') && <p className="muted small">Error reference <code>{params.get('ref')}</code> will be attached, so our team can find what happened.</p>}
        <label className="label" htmlFor="support-topic">What is it about?</label>
        <select id="support-topic" className="input" value={topic} onChange={(e) => setTopic(e.target.value as SupportTopic)}>
          {SUPPORT_TOPICS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select>
        <label className="label" htmlFor="support-subject" style={{ marginTop: 10 }}>Short summary</label>
        <input id="support-subject" className="input" maxLength={200} value={subject} onChange={(e) => setSubject(e.target.value)} required />
        <label className="label" htmlFor="support-message" style={{ marginTop: 10 }}>What happened, and what did you expect?</label>
        <textarea id="support-message" className="input" rows={4} maxLength={5000} value={message} onChange={(e) => setMessage(e.target.value)} required />
        <p className="muted small">We answer within one business day. For disagreements about delivered work, raise a dispute from the engagement instead.</p>
        <div className="row"><button className="btn btn-primary" disabled={busy || subject.trim().length < 5 || message.trim().length < 10}>Send</button>
          <button type="button" className="btn btn-ghost" onClick={() => setAsking(false)}>Cancel</button></div>
      </form>}
      {rows && rows.length === 0 && !asking ? (
        <EmptyTable columns={['Request', 'Topic', 'Status', 'Opened', 'Last update']}><strong>No help requests.</strong> Choose “Ask for help”
          when something is not working or you cannot find an answer above.</EmptyTable>
      ) : rows && rows.length > 0 && (
        <table className="data"><thead><tr><th>Request</th><th>Topic</th><th>Status</th><th>Opened</th><th>Last update</th></tr></thead>
          <tbody>{rows.map((r) => <tr key={r.id}><td><button className="link-button" onClick={() => setParams({ request: r.id })}><strong>{r.subject}</strong></button>
            <div className="muted small"><code>{r.reference}</code></div></td>
            <td className="small">{SUPPORT_TOPICS.find(([v]) => v === r.topic)?.[1]}</td>
            <td><span className={`badge ${SUPPORT_STATUS[r.status].tone}`}>{SUPPORT_STATUS[r.status].label}</span></td>
            <td className="small">{new Date(r.createdAt).toLocaleDateString()}</td><td className="small">{new Date(r.updatedAt).toLocaleString()}</td></tr>)}</tbody></table>
      )}
    </section>
  </>
}
