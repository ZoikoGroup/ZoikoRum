import { useState } from 'react'
import { Link } from 'react-router-dom'
import { Icon } from '../../components/dashboard'
import { PortalHeader, Tabs } from '../../components/portal'

/** Messages (management design 8): engagement-bound threads. Its final layout, until the messaging domain exists. */
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
          <p className="muted">Every conversation will be tied to a request or engagement, with files versioned and decisions on the record.
            Messaging opens in a coming release; until then, revision notes and submissions carry the conversation.</p>
          <Link className="btn btn-primary" to="/app/engagements"><Icon name="briefcase" /> Your engagements</Link>
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
