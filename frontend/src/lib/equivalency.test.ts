import { describe, expect, it } from 'vitest'
import { equivalency } from './equivalency'

const name = (c: string) => ({ US: 'the United States', GB: 'the United Kingdom', IN: 'India' })[c] ?? c

describe('equivalency', () => {
  it('explains a US CPA to a UK buyer with the nearest UK qualifications', () => {
    const e = equivalency({ name: 'CPA', issuingBody: 'AICPA', jurisdiction: 'US', status: 'VERIFIED' }, 'GB', name)
    expect(e.recognisedHere).toBe(false)
    expect(e.explanation).toMatch(/from the United States/)
    expect(e.explanation).toMatch(/In the United Kingdom the nearest equivalent is ACA \(ICAEW\) or ACCA/)
  })

  it('marks a credential recognised only when verified and issued in the buyer country', () => {
    expect(equivalency({ name: 'CA', issuingBody: 'ICAI', jurisdiction: 'IN', status: 'VERIFIED' }, 'IN', name).recognisedHere).toBe(true)
    expect(equivalency({ name: 'CA', issuingBody: 'ICAI', jurisdiction: 'IN', status: 'SELF_REPORTED' }, 'IN', name).recognisedHere).toBe(false)
  })

  it('says nothing when the buyer region is unknown or the credential is local', () => {
    expect(equivalency({ name: 'CPA', issuingBody: 'AICPA', jurisdiction: 'US', status: 'VERIFIED' }, null, name).explanation).toBeNull()
    expect(equivalency({ name: 'CPA', issuingBody: 'AICPA', jurisdiction: null, status: 'SELF_REPORTED' }, 'US', name).explanation).toBeNull()
  })
})
