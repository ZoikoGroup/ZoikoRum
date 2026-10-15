import { Link, useParams } from 'react-router-dom'
import { SiteFooter, SiteHeader } from '../components/ui'

interface Page { title: string; draft?: boolean; intro?: string; points?: string[]; sections?: { heading: string; points: string[] }[] }

const PAGES: Record<string, Page> = {
  terms: {
    title: 'Terms of Service',
    draft: true,
    points: [
      'Zoikorum provides marketplace infrastructure, verification, contracting facilitation and payment protection mechanisms.',
      'Professional services are delivered by independent professionals and firms. Zoikorum does not employ professionals and does not provide regulated professional services.',
    ],
  },
  privacy: {
    title: 'Privacy Policy',
    draft: true,
    points: [
      'Zoikorum collects only what it needs to verify identities, run engagements and keep audit-grade records.',
      'Verification documents and engagement records are access-controlled and every access is logged.',
    ],
  },
  // Public commitments from the Trust & Safety Governance Charter v1.0 (docs/product/trust-and-safety-charter.docx).
  'trust-and-safety': {
    title: 'Trust & Safety Charter',
    intro: 'Trust is not assumed. It is demonstrated, verified and maintained. This charter is a binding commitment on how trust, safety and governance work on Zoikorum.',
    sections: [
      { heading: 'Trust Tiers', points: [
        'Tier A, fully verified: identity verified, credentials validated where they apply, jurisdiction eligibility confirmed, enhanced checks where required. Eligible for all engagements.',
        'Tier B, verified identity: identity verified; credentials may be partial or not required. Eligible for standard engagements.',
        'Tier C, discovery: the profile is visible; engagement eligibility is limited while verification is in progress.',
        'Tiers are enforced by the system, not cosmetic, and every tier explains why it was given.'] },
      { heading: 'Verification', points: [
        'Verification is evidence-based, carried out by a verification partner or a compliance reviewer, and a negative partner result always goes to a person.',
        'Credentials, insurance and jurisdiction rights are monitored continuously; when one lapses, eligibility changes at once and cannot be hidden.'] },
      { heading: 'Contracts, payments and disputes', points: [
        'Every engagement runs under a signed agreement with defined deliverables and acceptance criteria.',
        'Money is held in escrow for each milestone and released only when the buyer accepts the work.',
        'Disputes follow a structured process with evidence, timed stages, a neutral mediator, documented reasoning and an independent appeal. Money stays frozen meanwhile.'] },
      { heading: 'Proportional, explainable enforcement', points: [
        'Every action is proportional to the risk, logged, explained in a plain-language notice and reviewable on appeal. There are no silent penalties.',
        'Nobody both opens and approves a serious action; senior actions need independent approval.',
        'Anyone can report a profile, person, review or message. The person reported is never told who reported them.'] },
      { heading: 'Transparency, privacy and security', points: [
        'Clear explanations for restrictions or actions, visible trust indicators, accessible policies and plain-language disclosures.',
        'Role-based access, encryption in transit and at rest, minimal data exposure, audit logging, and the right to a copy or deletion of your personal data.'] },
      { heading: 'Limits', points: [
        'Zoikorum provides marketplace infrastructure, verification, contracting and payment protection. It does not employ professionals or provide regulated professional services, and verification is not a guarantee of outcome.'] },
    ],
  },
  // Public commitments from the Zoikorum Ethics Code (docs/product/ethics-code.docx).
  ethics: {
    title: 'Ethics Code',
    intro: 'Fairness, transparency, human authority and governed technology: the principles every decision on Zoikorum follows.',
    sections: [
      { heading: 'Core principles', points: [
        'Human authority first: people make and own every consequential decision.',
        'Fair access, not equal outcomes: everyone gets the same rules and the same chance to qualify.',
        'Transparency over convenience, proportional power, evidence over assertion, and dignity in every interaction.'] },
      { heading: 'AI and automation', points: [
        'AI may assist with search relevance, summaries, pattern detection, risk flags and operational efficiency. Its outputs are non-binding, explainable and reviewable by people.',
        'AI never makes final engagement decisions, approves verification, releases or withholds payments, resolves disputes or imposes sanctions.',
        'You can always see why a result is shown and how it was ranked. Nobody can pay to rank higher.'] },
      { heading: 'Fairness for professionals and buyers', points: [
        'Professionals are judged on verified facts and delivered work, and are told why anything changes about their standing.',
        'Buyers get structured, comparable proposals and protected payments; enterprise controls apply equally to everyone they cover.'] },
      { heading: 'Speaking up, disputes and enforcement', points: [
        'Reporting is safe: reports are confidential on request and retaliatory reports are watched for.',
        'Disputes are decided on evidence by neutral people, with an independent appeal.',
        'Enforcement is proportional, explained and reviewable; staff never act on cases that involve them.'] },
      { heading: 'Data, accessibility and review', points: [
        'Personal data is used only for the purpose it was given for, kept secure and minimal.',
        'The platform is built to be usable by everyone, including with keyboard and screen readers.',
        'This code is reviewed regularly; its limits are stated plainly and decisions remain accountable to named people.'] },
    ],
  },
}

export default function Legal() {
  const page = PAGES[useParams().page ?? ''] ?? PAGES.terms
  return (
    <>
      <SiteHeader />
      <main className="profile-wrap" style={{ maxWidth: 760 }}>
        <section className="card panel">
          <h1>{page.title}</h1>
          {page.draft && <div className="alert alert-warn">The full, legally approved text will be published here before launch.</div>}
          {page.intro && <p className="lead">{page.intro}</p>}
          {page.points?.map((p) => <p key={p}>{p}</p>)}
          {page.sections?.map((s) => <section key={s.heading}><h2>{s.heading}</h2><ul className="why">{s.points.map((p) => <li key={p}>{p}</li>)}</ul></section>)}
          <p className="muted small">Also see: <Link to="/legal/trust-and-safety">Trust &amp; Safety Charter</Link> · <Link to="/legal/ethics">Ethics Code</Link> ·{' '}
            <Link to="/legal/terms">Terms</Link> · <Link to="/legal/privacy">Privacy</Link></p>
        </section>
      </main>
      <SiteFooter />
    </>
  )
}
