import { useParams } from 'react-router-dom'
import { SiteFooter, SiteHeader } from '../components/ui'

const PAGES: Record<string, { title: string; points: string[] }> = {
  terms: {
    title: 'Terms of Service',
    points: [
      'Zoikorum provides marketplace infrastructure, verification, contracting facilitation and payment protection mechanisms.',
      'Professional services are delivered by independent professionals and firms. Zoikorum does not employ professionals and does not provide regulated professional services.',
    ],
  },
  privacy: {
    title: 'Privacy Policy',
    points: [
      'Zoikorum collects only what it needs to verify identities, run engagements and keep audit-grade records.',
      'Verification documents and engagement records are access-controlled and every access is logged.',
    ],
  },
}

/** Placeholder legal pages: the final, approved texts are published here before launch. */
export default function Legal() {
  const page = PAGES[useParams().page ?? ''] ?? PAGES.terms
  return (
    <>
      <SiteHeader />
      <main className="profile-wrap" style={{ maxWidth: 760 }}>
        <section className="card panel">
          <h1>{page.title}</h1>
          <div className="alert alert-warn">The full, legally approved text will be published here before launch.</div>
          {page.points.map((p) => <p key={p}>{p}</p>)}
        </section>
      </main>
      <SiteFooter />
    </>
  )
}
