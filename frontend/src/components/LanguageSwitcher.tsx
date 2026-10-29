import { useEffect, useState } from 'react'
import { accountApi } from '../api/account'
import { LANGUAGES } from '../pages/customer/Settings'

function stored(): string {
  try { return localStorage.getItem('zk:language') || 'en' } catch { return 'en' }
}

/** Compact language picker for the top bar. Same preference as Settings: saved on the account and in 'zk:language'. */
export function LanguageSwitcher() {
  const [lang, setLang] = useState(stored)
  useEffect(() => {
    let live = true
    accountApi.me().then((me) => { if (live && me.language) setLang(me.language) }).catch(() => {})
    return () => { live = false }
  }, [])
  async function change(next: string) {
    const before = lang
    setLang(next)
    try {
      await accountApi.update({ language: next })
      try { localStorage.setItem('zk:language', next) } catch { /* per-viewer convenience only */ }
    } catch { setLang(before) }
  }
  return (
    <select className="input" aria-label="Language" value={lang} onChange={(e) => { void change(e.target.value) }}
      style={{ width: 'auto', padding: '4px 8px', fontSize: 13 }}>
      {LANGUAGES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
    </select>
  )
}
