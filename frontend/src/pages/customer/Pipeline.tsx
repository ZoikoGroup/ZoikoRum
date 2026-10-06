import { useState, type ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { Icon, type IconName, type Tone } from '../../components/dashboard'
import { EmptyTable, PortalHeader, SidePanel, StatCard, Tabs } from '../../components/portal'

/* Engagements, Payments & Protection, Messages (management designs 6–8).
   Their records arrive with the contract, escrow and messaging steps: until then each screen has
   its final layout with real zero counts, and side panels explain how the step works (from the product docs). */

interface Config {
  eyebrow: string
  title: string
  subtitle: string
  actions: ReactNode
  stats: { icon: IconName; tone: Tone; value: ReactNode; label: string; sub: string }[]
  tabs: string[]
  columns: string[]
  empty: ReactNode
  side: { title: string; body: ReactNode }[]
}

const findBtn = <Link className="btn btn-primary" to="/app/find"><Icon name="search" /> Find a Professional</Link>
const steps = (items: [string, string][]) => (
  <ol className="side-steps">{items.map(([t, d], i) => <li key={t}><span className="n">{i + 1}</span><span><strong>{t}</strong><br /><span className="muted small">{d}</span></span></li>)}</ol>
)
const checks = (items: string[]) => <ul className="assurance compact">{items.map((t) => <li key={t}><Icon name="check" /><span>{t}</span></li>)}</ul>

const CONFIGS: Record<'engagements' | 'payments', Config> = {
  engagements: {
    eyebrow: 'Engagements', title: 'Your engagements',
    subtitle: 'Manage active and past engagements, contracts, deliverables, payments and communications in one place.',
    actions: findBtn,
    stats: [
      { icon: 'briefcase', tone: 'green', value: 0, label: 'Active', sub: 'In progress' },
      { icon: 'clock', tone: 'amber', value: 0, label: 'Awaiting action', sub: 'Your attention needed' },
      { icon: 'check', tone: 'blue', value: 0, label: 'Completed', sub: 'Delivered and closed' },
      { icon: 'shield', tone: 'red', value: 0, label: 'Disputed', sub: 'Under resolution' },
    ],
    tabs: ['All engagements', 'Active', 'Awaiting action', 'Completed', 'Disputed', 'Archived'],
    columns: ['Engagement', 'Professional', 'Value & model', 'Status', 'Progress', 'Key dates', 'Next action'],
    empty: <><strong>No engagements yet.</strong> An engagement starts when you accept a proposal and both parties sign the contract.</>,
    side: [
      { title: 'Engagement lifecycle', body: steps([
        ['Contract signed', 'Terms are locked; any change needs a versioned change order.'],
        ['Escrow funded', 'No work starts before funding.'],
        ['Milestones delivered', 'The professional submits each deliverable.'],
        ['You accept', 'Approve or request a revision against the acceptance criteria.'],
        ['Payment released', 'Funds move only after acceptance.'],
      ]) },
    ],
  },
  payments: {
    eyebrow: 'Payments & protection', title: 'Secure payments. Protected work.',
    subtitle: 'Manage escrow, milestones, invoices and refunds with complete transparency and control.',
    actions: <Link className="btn btn-secondary" to="/app/engagements"><Icon name="briefcase" /> Engagements</Link>,
    stats: [
      { icon: 'lock', tone: 'amber', value: '—', label: 'In escrow', sub: 'Across your engagements' },
      { icon: 'clock', tone: 'blue', value: '—', label: 'Pending release', sub: 'Awaiting your approval' },
      { icon: 'check', tone: 'green', value: '—', label: 'Released', sub: 'Paid for accepted work' },
      { icon: 'download', tone: 'violet', value: '—', label: 'Refunded', sub: 'Returned to you' },
    ],
    tabs: ['All transactions', 'Escrow & milestones', 'Invoices', 'Refunds', 'Disputes'],
    columns: ['Date', 'Type', 'Engagement', 'Professional', 'Amount', 'Status', 'Next action'],
    empty: <><strong>No transactions yet.</strong> Protected payments launch with escrow: you fund each milestone, and money is
      released to the professional only when you accept the work.</>,
    side: [
      { title: 'Protected by Zoikorum', body: checks(['Funds held in escrow, per engagement', 'Released on milestone acceptance',
        'Work verified before release', 'Disputes freeze the funds until resolved', 'Full transaction audit trail']) },
      { title: 'Good to know', body: <p className="muted small" style={{ margin: 0 }}>Zoikorum is not a bank: there is no stored balance.
        Card details are never stored by Zoikorum — only a token from the payment partner.</p> },
    ],
  },
}

export function PipelinePage({ kind }: { kind: keyof typeof CONFIGS }) {
  const c = CONFIGS[kind]
  const [tab, setTab] = useState(c.tabs[0])
  return (
    <>
      <PortalHeader eyebrow={c.eyebrow} title={c.title} subtitle={c.subtitle} actions={c.actions} />
      <div className="stat-row four">{c.stats.map((s) => <StatCard key={s.label} {...s} />)}</div>
      <div className="home-grid wide">
        <section className="card panel">
          <Tabs tabs={c.tabs.map((t) => ({ key: t, label: t, count: 0 }))} value={tab} onChange={setTab} />
          <EmptyTable columns={c.columns}>{c.empty}</EmptyTable>
        </section>
        <aside>{c.side.map((s) => <SidePanel key={s.title} title={s.title}>{s.body}</SidePanel>)}</aside>
      </div>
    </>
  )
}

/** Messages (management design 8): engagement-bound threads. Messaging arrives with contracts. */
export function MessagesPage() {
  const [tab, setTab] = useState('All')
  return (
    <>
      <PortalHeader eyebrow="Messages" title="Communicate with confidence" subtitle="Keep all conversations, files and decisions in one secure place." />
      <div className="messages">
        <section className="card panel">
          <Tabs tabs={['All', 'Engagements', 'Requests', 'Professionals', 'System'].map((t) => ({ key: t, label: t }))} value={tab} onChange={setTab} />
          <p className="muted small" style={{ marginTop: 16 }}>No conversations yet.</p>
        </section>
        <section className="card panel message-empty">
          <Icon name="message" />
          <h2>No conversation selected</h2>
          <p className="muted">Every conversation is tied to a request, proposal or engagement, with files versioned and decisions on the
            record. Messaging opens with proposals and contracts.</p>
          <Link className="btn btn-primary" to="/app/find"><Icon name="search" /> Find a Professional</Link>
        </section>
        <aside className="card panel">
          <h2>Why messages stay on Zoikorum</h2>
          <ul className="why">
            <li>Conversations are part of the engagement record.</li>
            <li>Files are versioned and fingerprinted.</li>
            <li>During a dispute, the dispute thread replaces direct messages.</li>
          </ul>
        </aside>
      </div>
    </>
  )
}

export const EngagementsPage = () => <PipelinePage kind="engagements" />
export const PaymentsPage = () => <PipelinePage kind="payments" />
