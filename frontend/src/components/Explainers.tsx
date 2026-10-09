import { useState, type ReactNode } from 'react'
import { Icon, type IconName } from './dashboard'

/* Education module (Finance & Accounting category s.8): three short explainers shown after the first filter or
   ~20 results. Plain language, a simple step diagram each, no policy tone. */

interface Explainer { key: string; icon: IconName; title: string; teaser: string; steps: string[]; body: ReactNode }

const EXPLAINERS: Explainer[] = [
  {
    key: 'choose', icon: 'search', title: 'Choosing the right finance specialist', teaser: 'Start from the outcome, not the job title.',
    steps: ['Describe the outcome', 'Filter by specialization', 'Check verification', 'Compare up to 3', 'Request proposals'],
    body: <>
      <p>Finance work covers very different skills. A fractional CFO runs planning, cash and board reporting; a transfer-pricing
        specialist documents intercompany pricing for tax authorities; an automation specialist rebuilds month-end processes.
        Begin with the result you need ("audit-ready accounts by March", "a 13-week cash forecast") and pick the specialization
        that produces it.</p>
      <p>Then narrow by what your situation requires. Regulated or filed work (audit, tax returns, statutory accounts) usually
        needs a licensed professional in the right jurisdiction: use the Jurisdiction filter and look for verified credentials.
        Advisory and analysis work rarely does. Check engagement type (project, retainer, fractional) and delivery mode so the way
        they work matches yours.</p>
      <p>Shortlist two or three, compare them side by side, and send one request to all of them. Each replies with a structured
        proposal (deliverables, milestones, price), so you can compare like for like before you commit.</p>
    </>,
  },
  {
    key: 'tiers', icon: 'shield', title: 'Understanding Trust Tiers', teaser: 'What A, B and C mean, and who decides.',
    steps: ['Tier C: profile only', 'Tier B: identity + screening', 'Tier A: + credentials, eligibility, insurance'],
    body: <>
      <p>Every professional has a Trust Tier based only on checks that have actually been completed. <strong>Tier C</strong> is a
        published profile with no completed verification: it can be discovered but cannot take contract-required work.
        <strong> Tier B</strong> means identity has been verified and restrictions screening is clear. <strong>Tier A</strong> adds
        the credentials, jurisdiction eligibility and insurance their specialization requires.</p>
      <p>Checks are made by a verification provider or a compliance reviewer, never by AI, and every decision is recorded.
        Credentials marked "self-reported" have not been checked yet; expired ones are shown as expired. A tier can go down if a
        credential expires or a check is revoked, so the badge always reflects today.</p>
      <p>Pick the tier your work needs: Tier B is often enough for advisory work; regulated work should use Tier A.</p>
    </>,
  },
  {
    key: 'protection', icon: 'lock', title: 'Contracts & payment protection explained', teaser: 'No work without funding; no payment without acceptance.',
    steps: ['Accept proposal', 'Both sign', 'Fund milestone (escrow)', 'Work delivered', 'You accept → released'],
    body: <>
      <p>When you accept a proposal, Zoikorum generates a contract from it: scope, deliverables with acceptance criteria, milestones
        and price. You sign first, the professional countersigns, and each signature is confirmed with two-step verification.</p>
      <p>You then fund each milestone. The money is held in escrow: neither side can take it. Work starts once a milestone is
        funded. When the professional submits the work you review it against the acceptance criteria, then accept it or ask for a
        revision. Only your acceptance releases the money to the professional, minus the platform fee, and you receive a receipt.</p>
      <p>If something goes wrong, raise a dispute: the money is frozen immediately, both sides add evidence, and the case is
        settled directly or by a mediator. The outcome is carried out exactly through escrow and recorded.</p>
    </>,
  },
]

export function EducationCards() {
  const [open, setOpen] = useState<Explainer | null>(null)
  return (
    <section className="education" aria-label="Guides">
      {EXPLAINERS.map((e) => (
        <button key={e.key} className="card edu-card" onClick={() => setOpen(e)}>
          <Icon name={e.icon} /><strong>{e.title}</strong><span className="muted small">{e.teaser}</span>
        </button>
      ))}
      {open && <div className="modal-backdrop" role="dialog" aria-modal="true" aria-labelledby="edu-title" onClick={() => setOpen(null)}>
        <div className="card modal" onClick={(e) => e.stopPropagation()}>
          <div className="panel-head"><h2 id="edu-title">{open.title}</h2><button className="icon-btn" aria-label="Close" onClick={() => setOpen(null)}>×</button></div>
          <ol className="edu-steps">{open.steps.map((s) => <li key={s}>{s}</li>)}</ol>
          {open.body}
        </div>
      </div>}
    </section>
  )
}
