import { describe, expect, it, vi } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'

vi.mock('react-router-dom', () => ({ useNavigate: () => () => {} }))
import { GlobalSearch } from './GlobalSearch'
import { comboKey, staffSearchApi } from '../api/staffSearch'

describe('staff search keyboard model', () => {
  const closed = { open: false, active: -1 }

  it('ArrowDown opens and moves through the results, wrapping at the end', () => {
    let s = comboKey('ArrowDown', closed, 3).state
    expect(s).toEqual({ open: true, active: 0 })
    s = comboKey('ArrowDown', s, 3).state
    s = comboKey('ArrowDown', s, 3).state
    expect(s.active).toBe(2)
    expect(comboKey('ArrowDown', s, 3).state.active).toBe(0)
  })

  it('ArrowUp moves back and wraps to the last result', () => {
    expect(comboKey('ArrowUp', { open: true, active: 0 }, 3).state.active).toBe(2)
    expect(comboKey('ArrowUp', { open: true, active: 2 }, 3).state.active).toBe(1)
    expect(comboKey('ArrowUp', closed, 4).state).toEqual({ open: true, active: 3 })
  })

  it('arrows with no results highlight nothing', () => {
    expect(comboKey('ArrowDown', closed, 0).state).toEqual({ open: true, active: -1 })
  })

  it('Enter chooses the highlighted result and closes; without one it does nothing', () => {
    expect(comboKey('Enter', { open: true, active: 1 }, 3)).toMatchObject({ choose: 1, state: closed, handled: true })
    expect(comboKey('Enter', { open: true, active: -1 }, 3).choose).toBeUndefined()
    expect(comboKey('Enter', { open: false, active: 1 }, 3).choose).toBeUndefined()
  })

  it('Escape closes first, then clears the box', () => {
    const first = comboKey('Escape', { open: true, active: 2 }, 3)
    expect(first.state).toEqual(closed)
    expect(first.clear).toBeUndefined()
    expect(comboKey('Escape', first.state, 3).clear).toBe(true)
  })

  it('Tab closes the popup without trapping focus; other keys are left to the input', () => {
    expect(comboKey('Tab', { open: true, active: 1 }, 3)).toEqual({ state: closed, handled: false })
    expect(comboKey('a', { open: true, active: 1 }, 3)).toEqual({ state: { open: true, active: 1 }, handled: false })
  })
})

describe('GlobalSearch', () => {
  it('staff mode renders an ARIA combobox bound to a listbox, with the staff placeholder', () => {
    const html = renderToStaticMarkup(<GlobalSearch side={null} staff />)
    expect(html).toContain('placeholder="Search accounts, cases, contracts, disputes…"')
    expect(html).toContain('role="combobox"')
    expect(html).toContain('aria-controls="staff-search-results"')
    expect(html).toContain('aria-expanded="false"')
    expect(html).toContain('id="staff-search-results" role="listbox"')
    expect(html).toContain('role="status"')
  })

  it('buyer and professional search is unchanged', () => {
    const html = renderToStaticMarkup(<GlobalSearch side="buyer" />)
    expect(html).toContain('placeholder="Search engagements, requests, messages…"')
    expect(html).not.toContain('staff-search-results')
  })

  it('the staff search calls the scoped admin endpoint', async () => {
    const fetch = vi.fn().mockImplementation(async () => new Response(JSON.stringify({ query: 'ac', scopes: [], groups: [] }),
      { status: 200, headers: { 'Content-Type': 'application/json' } }))
    vi.stubGlobal('fetch', fetch)
    await staffSearchApi.search('acme corp')
    expect(String(fetch.mock.calls[0][0])).toBe('/v1/admin/search?q=acme+corp&limit=5')
    vi.unstubAllGlobals()
  })
})
