/* Regional equivalency (Finance & Accounting category s.11.2): when a buyer in one region sees a credential from
   another, explain where it comes from and the nearest local concepts. Explanatory only (Homepage: "no implied
   equivalence"): recognition for a given piece of work is the buyer's decision.
   "Recognised in your region" is shown only when it is true: a verified credential issued in the buyer's country. */

interface Designation { match: RegExp; what: string; home: string | null; nearest: Record<string, string> }

const ACCOUNTANT = {
  US: 'CPA (state boards / AICPA)', GB: 'ACA (ICAEW) or ACCA', IE: 'ACA (Chartered Accountants Ireland) or ACCA',
  IN: 'CA (ICAI)', CA: 'CPA (CPA Canada)', AU: 'CA ANZ or CPA Australia', SG: 'CA (Singapore)', AE: 'a CPA, ACA or ACCA holder registered locally',
  ZA: 'CA(SA) (SAICA)', DE: 'Wirtschaftsprüfer or Steuerberater', FR: 'Expert-comptable', NL: 'Registeraccountant (RA)',
}

const DESIGNATIONS: Designation[] = [
  { match: /\bCPA\b/i, what: 'a licensed public accountant qualification', home: 'US', nearest: ACCOUNTANT },
  { match: /\bACA\b|ICAEW/i, what: 'the ICAEW chartered accountant qualification', home: 'GB', nearest: ACCOUNTANT },
  { match: /\bACCA\b/i, what: 'the ACCA chartered certified accountant qualification', home: 'GB', nearest: ACCOUNTANT },
  { match: /\bICAI\b|\bCA\b|chartered accountant/i, what: 'a chartered accountant qualification', home: null, nearest: ACCOUNTANT },
  { match: /\bCIMA\b|\bCGMA\b/i, what: 'a management accounting qualification', home: 'GB',
    nearest: { US: 'CMA (IMA)', IN: 'CMA (ICMAI)', GB: 'CIMA', CA: 'CPA (CPA Canada)', AU: 'CPA Australia' } },
  { match: /\bCMA\b/i, what: 'a management accounting qualification', home: null,
    nearest: { US: 'CMA (IMA)', IN: 'CMA (ICMAI)', GB: 'CIMA', CA: 'CPA (CPA Canada)', AU: 'CPA Australia' } },
  { match: /\bCFA\b/i, what: 'an international investment analysis designation (CFA Institute)', home: null, nearest: {} },
  { match: /\bCIA\b/i, what: 'an international internal audit certification (IIA)', home: null, nearest: {} },
  { match: /\bEA\b|enrolled agent/i, what: 'a US federal tax practitioner licence (IRS)', home: 'US',
    nearest: { GB: 'CTA (Chartered Tax Adviser)', IN: 'a CA practising in tax', CA: 'a CPA practising in tax', AU: 'a registered tax agent' } },
  { match: /\bCTA\b|chartered tax/i, what: 'the UK Chartered Tax Adviser qualification', home: 'GB',
    nearest: { US: 'EA or a CPA practising in tax', IN: 'a CA practising in tax', IE: 'AITI Chartered Tax Adviser' } },
]

export interface Equivalency { recognisedHere: boolean; explanation: string | null }

export function equivalency(credential: { name: string; issuingBody: string; jurisdiction: string | null; status: string },
                            buyerCountry: string | null, countryName: (c: string) => string): Equivalency {
  const issued = credential.jurisdiction?.slice(0, 2).toUpperCase() ?? null
  const recognisedHere = !!buyerCountry && !!issued && issued === buyerCountry && credential.status === 'VERIFIED'
  const d = DESIGNATIONS.find((x) => x.match.test(`${credential.name} ${credential.issuingBody}`))
  if (!buyerCountry || recognisedHere) return { recognisedHere, explanation: null }
  const from = issued ?? d?.home
  if (from && from === buyerCountry) return { recognisedHere, explanation: null }
  const parts: string[] = []
  if (d) parts.push(`${credential.name} is ${d.what}${from ? ` from ${countryName(from)}` : ''}.`)
  else if (from) parts.push(`This credential was issued in ${countryName(from)}.`)
  const near = d?.nearest[buyerCountry]
  if (near) parts.push(`In ${countryName(buyerCountry)} the nearest equivalent is ${near}.`)
  if (!parts.length) return { recognisedHere, explanation: null }
  parts.push('Whether it is accepted for your work is your decision.')
  return { recognisedHere, explanation: parts.join(' ') }
}
