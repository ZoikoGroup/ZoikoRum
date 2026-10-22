import { api } from './client'

/* Staff console federated search (GET /v1/admin/search). The server searches only the kinds the signed-in staff
   member's roles may see and masks every email address; the console just shows what comes back. */

export type StaffSearchKind = 'accounts' | 'organizations' | 'professionals' | 'contracts' | 'disputes' | 'support' | 'enforcement' | 'incidents'

export interface StaffSearchHit {
  kind: StaffSearchKind
  id: string
  title: string
  subtitle: string | null
  link: string  // path in the staff console
}

export interface StaffSearchGroup { kind: StaffSearchKind; label: string; items: StaffSearchHit[] }

export interface StaffSearchResult {
  query: string
  scopes: StaffSearchKind[]  // the kinds this person may search
  groups: StaffSearchGroup[]  // only kinds with matches
}

export const STAFF_SEARCH_MIN = 2

export const staffSearchApi = {
  search: (q: string, limit = 5) => api<StaffSearchResult>('/v1/admin/search', { query: { q, limit: String(limit) } }),
}

/* Keyboard model of the staff search combobox (WAI-ARIA combobox with a listbox popup, focus stays in the input and the
   highlighted option is announced through aria-activedescendant). Pure, so it can be unit-tested without a DOM.
   `active` is the highlighted option's index in the flattened result list, -1 for none. */
export interface ComboState { open: boolean; active: number }
export interface ComboOutcome { state: ComboState; handled: boolean; choose?: number; clear?: boolean }

export function comboKey(key: string, s: ComboState, count: number): ComboOutcome {
  switch (key) {
    case 'ArrowDown':
      if (!count) return { state: { open: true, active: -1 }, handled: true }
      return { state: { open: true, active: !s.open || s.active < 0 ? 0 : (s.active + 1) % count }, handled: true }
    case 'ArrowUp':
      if (!count) return { state: { open: true, active: -1 }, handled: true }
      return { state: { open: true, active: !s.open || s.active <= 0 ? count - 1 : s.active - 1 }, handled: true }
    case 'Enter':
      if (s.open && s.active >= 0 && s.active < count) return { state: { open: false, active: -1 }, handled: true, choose: s.active }
      return { state: s, handled: true }
    case 'Escape':
      // First Escape closes the popup; a second one clears the box (APG combobox).
      return s.open ? { state: { open: false, active: -1 }, handled: true } : { state: s, handled: true, clear: true }
    case 'Tab':
      return { state: { open: false, active: -1 }, handled: false }
    default:
      return { state: s, handled: false }
  }
}
