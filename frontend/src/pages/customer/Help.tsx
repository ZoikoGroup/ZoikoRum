import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { Icon, type IconName } from '../../components/dashboard'
import { EmptyTable, PortalHeader, SidePanel } from '../../components/portal'

interface Topic { icon: IconName; title: string; summary: string; answers: [string, string][] }

// Plain-language help drawn from the product docs. No invented phone numbers, SLAs or chat agents.
const TOPICS: Topic[] = [
  { icon: 'search', title: 'Finding professionals', summary: 'Search, filters, Trust Tiers and compare.', answers: [
    ['How is search ranked?', 'By relevance to your words, then verification, availability and fit. Nobody can pay to rank higher. Each result shows why it matched.'],
    ['What does a Trust Tier mean?', 'Tier A: identity, credentials and eligibility verified. Tier B: identity verified and restrictions clear. Tier C: verification not complete.'],
    ['How many can I compare?', 'Up to three professionals side by side.'],
  ] },
  { icon: 'shield', title: 'Verification & trust', summary: 'What is checked, and by whom.', answers: [
    ['Who verifies professionals?', 'A verification provider or a compliance reviewer. AI never decides a verification outcome.'],
    ['Why can’t I see a trust score?', 'The raw score is internal. You see the Tier and each verified dimension, which is what matters for a decision.'],
  ] },
  { icon: 'request', title: 'Requests & proposals', summary: 'From a need to a selected professional.', answers: [
    ['How do I ask for a proposal?', 'Requesting proposals opens in the next release. You will send a request from a verified professional’s profile.'],
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
          <input className="input" aria-label="Search help" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search help (e.g. escrow, Trust Tier, NDA)" />
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
          <section className="card panel">
            <div className="panel-head"><h2>Your support cases</h2></div>
            <EmptyTable columns={['Case', 'Topic', 'Status', 'Opened', 'Last update']}>
              <strong>No support cases.</strong> Raising a support case from here arrives with engagements. For a problem with an engagement,
              open a dispute from the engagement itself.
            </EmptyTable>
          </section>
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
