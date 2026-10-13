import { useEffect, useState, type ReactNode } from 'react'
import { api } from '../api/client'
import { Link } from 'react-router-dom'

/* Building blocks shared by every role's dashboard: icons, summary cards, the pending-actions list. */

export type IconName =
  | 'request' | 'proposal' | 'contract' | 'shield' | 'check' | 'bell' | 'team' | 'mail' | 'building' | 'search'
  | 'user' | 'star' | 'clock' | 'bookmark' | 'wallet' | 'message' | 'gear' | 'help' | 'lock' | 'compare' | 'folder'
  | 'plus' | 'download' | 'trash' | 'filter' | 'globe' | 'home' | 'briefcase'

const PATHS: Record<IconName, string> = {
  bookmark: 'M6 3h12v18l-6-4-6 4z',
  wallet: 'M3 6h18v13H3zM3 10h18M16 15h2',
  message: 'M4 5h16v11H8l-4 4z',
  gear: 'M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM19 12a7 7 0 0 0-.1-1.2l2-1.6-2-3.4-2.4 1a7 7 0 0 0-2-1.2L14 3h-4l-.5 2.6a7 7 0 0 0-2 1.2l-2.4-1-2 3.4 2 1.6a7 7 0 0 0 0 2.4l-2 1.6 2 3.4 2.4-1a7 7 0 0 0 2 1.2L10 21h4l.5-2.6a7 7 0 0 0 2-1.2l2.4 1 2-3.4-2-1.6c.1-.4.1-.8.1-1.2z',
  help: 'M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM9.1 9a3 3 0 0 1 5.8 1c0 2-3 3-3 3M12 17h.01',
  lock: 'M5 11h14v10H5zM8 11V7a4 4 0 0 1 8 0v4',
  compare: 'M4 20V10M10 20V4M16 20v-7M2 20h20',
  folder: 'M3 6h6l2 2h10v11H3z',
  plus: 'M12 5v14M5 12h14',
  download: 'M12 3v12M7 10l5 5 5-5M5 21h14',
  trash: 'M4 7h16M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3',
  filter: 'M3 5h18l-7 8v6l-4 2v-8z',
  globe: 'M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM3 12h18M12 3a14 14 0 0 1 0 18M12 3a14 14 0 0 0 0 18',
  home: 'M3 11l9-7 9 7v9h-6v-6H9v6H3z',
  briefcase: 'M3 8h18v12H3zM8 8V5h8v3M3 13h18',
  request: 'M7 3h7l5 5v13H7zM14 3v5h5M10 13h6M10 17h6',
  proposal: 'M4 5h16v11H8l-4 4zM8 9h8M8 12h5',
  contract: 'M6 3h9l4 4v14H6zM9 12h7M9 16h4M15 3v4h4',
  shield: 'M12 3l7 3v6c0 4.5-3 7.5-7 9-4-1.5-7-4.5-7-9V6zM9 12l2 2 4-4',
  check: 'M5 12l4 4L19 7',
  bell: 'M6 16V11a6 6 0 1 1 12 0v5l2 2H4zM10 20a2 2 0 0 0 4 0',
  team: 'M9 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM2 21v-1a7 7 0 0 1 14 0v1M17 11a3 3 0 1 0 0-6M22 21v-1a5 5 0 0 0-4-4.9',
  mail: 'M3 6h18v12H3zM3 7l9 6 9-6',
  building: 'M4 21V5l8-3v19M12 9h8v12M7 8h2M7 12h2M7 16h2M15 13h2M15 17h2',
  search: 'M11 18a7 7 0 1 0 0-14 7 7 0 0 0 0 14zM21 21l-5-5',
  user: 'M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM4 21v-1a8 8 0 0 1 16 0v1',
  star: 'M12 3l2.8 5.7 6.2.9-4.5 4.4 1 6.2L12 17.3 6.5 20.2l1-6.2L3 9.6l6.2-.9z',
  clock: 'M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM12 7v5l3 3',
}

export function Icon({ name }: { name: IconName }) {
  return (
    <svg viewBox="0 0 24 24" width="20" height="20" aria-hidden fill="none" stroke="currentColor" strokeWidth="1.8"
      strokeLinecap="round" strokeLinejoin="round"><path d={PATHS[name]} /></svg>
  )
}

export type Tone = 'blue' | 'green' | 'teal' | 'violet' | 'amber' | 'red'

export function Kpi({ icon, tone, label, value, note }: { icon: IconName; tone: Tone; label: string; value: ReactNode; note: ReactNode }) {
  return (
    <div className="card kpi">
      <span className={`kpi-icon ${tone}`}><Icon name={icon} /></span>
      <div>
        <div className="label">{label}</div>
        <div className="value">{value}</div>
        <div className="note">{note}</div>
      </div>
    </div>
  )
}

export type Priority = 'High' | 'Medium' | 'Low'
export interface Action { title: string; detail: string; priority: Priority; to: string; icon: IconName }

export function ActionList({ actions, empty = 'Nothing needs your attention right now.' }: { actions: Action[]; empty?: ReactNode }) {
  if (actions.length === 0) return <p className="muted small" style={{ margin: 0 }}>{empty}</p>
  return (
    <ul className="action-list">
      {actions.map((a) => (
        <li key={a.title}>
          <span className={`kpi-icon ${a.priority === 'High' ? 'red' : a.priority === 'Medium' ? 'amber' : 'blue'}`}><Icon name={a.icon} /></span>
          <Link to={a.to}><strong>{a.title}</strong><span className="muted small">{a.detail}</span></Link>
          <span className={`badge prio-${a.priority.toLowerCase()}`}>{a.priority}</span>
        </li>
      ))}
    </ul>
  )
}

/** One line that says what is coming, instead of cards full of dashes. */
export function ComingSoon({ children }: { children: ReactNode }) {
  return <div className="coming-soon"><span className="badge">Coming soon</span><span>{children}</span></div>
}

/** Photo when there is one, otherwise initials. */
export function Avatar({ name, photoUrl, size = 40 }: { name: string; photoUrl?: string | null; size?: number }) {
  const initials = name.split(/\s+/).map((w) => w[0]).slice(0, 2).join('').toUpperCase()
  // Photos of published profiles load directly. A draft profile's photo is only served to its owner (and staff), and a
  // plain <img> request carries no sign-in, so on failure the photo is fetched again with the session and shown from memory.
  const [img, setImg] = useState<{ url: string | null | undefined; src: string | null; failed: boolean }>({ url: photoUrl, src: null, failed: false })
  if (img.url !== photoUrl) setImg({ url: photoUrl, src: null, failed: false })  // a new photo starts fresh
  const { src, failed } = img
  useEffect(() => () => { if (src?.startsWith('blob:')) URL.revokeObjectURL(src) }, [src])
  async function retryWithSession() {
    if (!photoUrl || src) { setImg((x) => ({ ...x, failed: true })); return }
    try {
      const blob = URL.createObjectURL(await api<Blob>(photoUrl, { blob: true }))
      setImg((x) => ({ ...x, src: blob }))
    } catch { setImg((x) => ({ ...x, failed: true })) }
  }
  return photoUrl && !failed
    ? <img className="avatar-img" src={src ?? photoUrl} alt="" width={size} height={size} style={{ width: size, height: size }} onError={retryWithSession} />
    : <span className="avatar" aria-hidden style={{ width: size, height: size, fontSize: size / 2.6 }}>{initials}</span>
}

export function greeting(name: string): string {
  const h = new Date().getHours()
  return `${h < 12 ? 'Good morning' : h < 18 ? 'Good afternoon' : 'Good evening'}, ${name.split(/\s+/)[0]}`
}
