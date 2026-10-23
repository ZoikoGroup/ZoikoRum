import { useState, type ReactNode } from 'react'
import { Icon, type IconName } from './dashboard'
import { useDialog } from './ui'

/* Education module (Finance & Accounting category s.8): three explainers (300-500 words each) shown after the first
   filter or ~20 results. Plain language, a simple step diagram each, no policy tone. */

interface Explainer { key: string; icon: IconName; title: string; teaser: string; steps: string[]; body: ReactNode }

// eslint-disable-next-line react-refresh/only-export-components
export const EXPLAINERS: Explainer[] = [
  {
    key: 'choose', icon: 'search', title: 'Choosing the right finance specialist', teaser: 'Start from the outcome, not the job title.',
    steps: ['Describe the outcome', 'Filter by specialization', 'Check verification', 'Compare up to 3', 'Request proposals'],
    body: <>
      <p>Finance work covers very different skills. A fractional CFO runs planning, cash and board reporting; a transfer-pricing
        specialist documents intercompany pricing for tax authorities; an automation specialist rebuilds month-end processes.
        Two people with the same job title can be strong in completely different areas, so begin with the result you need
        ("audit-ready accounts by March", "a 13-week cash forecast", "a clean close in five working days") and pick the
        specialization that produces it. If you are unsure, describe the need in your own words and use the suggested filters
        as a starting point you can change.</p>
      <p>Then narrow by what your situation requires. Regulated or filed work (audit, tax returns, statutory accounts) usually
        needs a licensed professional in the right jurisdiction: use the Jurisdiction filter and look for credentials marked as
        validated rather than self-reported. Advisory and analysis work rarely needs a licence, and a broader pool will often
        give you better availability and price. Check the engagement type (advisory, project, retainer or fractional) and the
        delivery mode (remote, on-site or hybrid) so the way they work matches the way your team works.</p>
      <p>Look at the evidence each profile shows rather than the adjectives. The Trust Tier tells you which checks are complete;
        the engagement history shows completed work and on-time milestones on Zoikorum; reviews come only from buyers who
        finished a paid engagement. A newer professional with strong verified credentials can be an excellent choice: the
        platform marks them as new so you know there is less history, not because anything is wrong.</p>
      <p>Shortlist two or three, compare them side by side, and send one structured request to all of them. Each replies with a
        proposal that lists deliverables, milestones and price in the same format, so you can compare like for like. You can ask
        questions before you choose, and nothing is paid until you accept a proposal and both sides sign the contract. If your
        organisation has procurement rules, they are applied for you, so you only see professionals you are allowed to engage.</p>
    </>,
  },
  {
    key: 'tiers', icon: 'shield', title: 'Understanding Trust Tiers', teaser: 'What A, B and C mean, and who decides.',
    steps: ['Tier C: profile only', 'Tier B: identity + screening', 'Tier A: + credentials, eligibility, insurance'],
    body: <>
      <p>Every professional has a Trust Tier based only on checks that have actually been completed. <strong>Tier C</strong> is a
        published profile with no completed verification: it can be discovered and can receive questions, but cannot send a
        proposal or take contract work. <strong>Tier B</strong> means identity has been verified against a government ID and
        restrictions screening is clear. <strong>Tier A</strong> adds the credentials, jurisdiction eligibility and professional
        indemnity insurance that the professional's specializations require.</p>
      <p>Checks are made by a verification partner or a Zoikorum compliance reviewer, never by AI, and every decision is recorded
        with its reason. Credentials marked "self-reported" have not been checked yet; validated ones have been confirmed with the
        issuing body or registry; expired ones are shown as expired. Screening details are never shown publicly: you see only
        whether the check is clear.</p>
      <p>A tier is not permanent. Licences, certificates and insurance policies have end dates, and when one lapses the tier goes
        down automatically until it is renewed. That is why the badge always reflects today rather than the day the profile was
        created, and why a profile shows when it was last verified. If a check is revoked, the change is immediate and explained
        to the professional, who can appeal once to an independent reviewer.</p>
      <p>Choose the tier your work needs. Tier B is often enough for advisory, analysis and internal process work, where you mainly
        need to know you are dealing with a real, screened person. Regulated work, such as audit, tax filing and regulatory
        reporting, should use Tier A, and many enterprise policies require it. If you are an enterprise buyer, your organisation's
        minimum tier is applied to search, requests and contracts automatically, and results explain which professionals were
        left out and why.</p>
      <p>Tiers measure verification, not quality. Pair them with the engagement history and verified reviews on each profile.</p>
    </>,
  },
  {
    key: 'protection', icon: 'lock', title: 'Contracts & payment protection explained', teaser: 'No work without funding; no payment without acceptance.',
    steps: ['Accept proposal', 'Both sign', 'Fund milestone (escrow)', 'Work delivered', 'You accept → released'],
    body: <>
      <p>When you accept a proposal, Zoikorum generates a contract from it: scope, deliverables with acceptance criteria, milestones
        and price, plus any clauses your organisation's policy requires. You sign first, the professional countersigns, and each
        signature is confirmed with two-step verification so nobody can sign on your behalf. If the scope changes later, both
        sides agree a new version and the earlier one is kept, so you can always see what was agreed and when.</p>
      <p>You then fund each milestone. The money is held in escrow: neither you nor the professional can take it while the work is
        under way. Work on a milestone starts once it is funded, which protects the professional from doing unpaid work and
        protects you from paying in advance for work that never arrives. Retainers and fractional roles work the same way, period
        by period.</p>
      <p>When the professional submits the work, you review it against the acceptance criteria written into the contract, then
        accept it or ask for a revision with a reason. Only your acceptance releases the money to the professional, minus the
        platform fee, and you receive a receipt for your records. If you do nothing, you are reminded; money is never released
        silently without a clear rule both sides agreed to.</p>
      <p>If something goes wrong, either side can raise a dispute on the milestone. The money is frozen immediately, both sides add
        evidence that cannot be edited afterwards, and the case is settled directly or by a neutral mediator with written reasons.
        One independent appeal is available. The outcome, whether a full release, a refund or a split, is carried out exactly
        through escrow and recorded in the audit ledger.</p>
      <p>Zoikorum facilitates the contract and protects the payment; the professional delivers the work and remains responsible for
        it. Every step is recorded, so finance and procurement teams can export the trail for their own controls.</p>
    </>,
  },
]

export function EducationCards() {
  const [open, setOpen] = useState<Explainer | null>(null)
  const dialog = useDialog(() => setOpen(null), open !== null)
  return (
    <section className="education" aria-label="Guides">
      {EXPLAINERS.map((e) => (
        <button key={e.key} className="card edu-card" onClick={() => setOpen(e)}>
          <Icon name={e.icon} /><strong>{e.title}</strong><span className="muted small">{e.teaser}</span>
        </button>
      ))}
      {open && <div ref={dialog} className="modal-backdrop" role="dialog" aria-modal="true" aria-labelledby="edu-title" onClick={() => setOpen(null)}>
        <div className="card modal modal-wide" onClick={(e) => e.stopPropagation()}>
          <div className="panel-head"><h2 id="edu-title">{open.title}</h2><button className="icon-btn" aria-label="Close" onClick={() => setOpen(null)}>×</button></div>
          <ol className="edu-steps">{open.steps.map((s) => <li key={s}>{s}</li>)}</ol>
          {open.body}
        </div>
      </div>}
    </section>
  )
}
