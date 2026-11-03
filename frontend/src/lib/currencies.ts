// ISO 4217 currency codes. Keep in step with backend/src/zoikorum/shared/currencies.py.
export const ISO_4217: ReadonlySet<string> = new Set(
  `
AED AFN ALL AMD ANG AOA ARS AUD AWG AZN BAM BBD BDT BGN
BHD BIF BMD BND BOB BRL BSD BTN BWP BYN BZD CAD CDF CHF
CLP CNY COP CRC CUP CVE CZK DJF DKK DOP DZD EGP ERN ETB
EUR FJD FKP GBP GEL GHS GIP GMD GNF GTQ GYD HKD HNL HTG
HUF IDR ILS INR IQD IRR ISK JMD JOD JPY KES KGS KHR KMF
KPW KRW KWD KYD KZT LAK LBP LKR LRD LSL LYD MAD MDL MGA
MKD MMK MNT MOP MRU MUR MVR MWK MXN MYR MZN NAD NGN NIO
NOK NPR NZD OMR PAB PEN PGK PHP PKR PLN PYG QAR RON RSD
RUB RWF SAR SBD SCR SDG SEK SGD SHP SLE SOS SRD SSP STN
SVC SYP SZL THB TJS TMT TND TOP TRY TTD TWD TZS UAH UGX
USD UYU UZS VES VND VUV WST XAF XCD XOF XPF YER ZAR ZMW
ZWL
`.split(/\s+/).filter(Boolean),
)

export const ISO_CURRENCIES: readonly string[] = [...ISO_4217].sort()

export const isIsoCurrency = (code: string) => ISO_4217.has(code)

/** Letters only, upper case, 3 characters: use in onChange. */
export const keepCurrency = (v: string) => v.replace(/[^A-Za-z]/g, '').toUpperCase().slice(0, 3)

/** Error message for a currency code, or '' when fine. */
export const currencyError = (code: string) => isIsoCurrency(code) ? '' : 'Use a valid currency code, such as USD.'
