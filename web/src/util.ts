export const fmtMoney = (v: number): string => {
  const a = Math.abs(v), s = v < 0 ? '-' : ''
  if (a >= 1e9) return `${s}$${(a / 1e9).toFixed(2)}B`
  if (a >= 1e6) return `${s}$${(a / 1e6).toFixed(a >= 1e7 ? 1 : 2)}M`
  if (a >= 1e3) return `${s}$${(a / 1e3).toFixed(a >= 1e5 ? 0 : 1)}K`
  return `${s}$${Math.round(a)}`
}
export const fmtPct = (v: number | null | undefined, d = 1): string => (v == null ? '–' : `${v.toFixed(d)}%`)
export const ordinal = (n: number): string => {
  const s = ['th', 'st', 'nd', 'rd'], v = n % 100
  return `${n}${s[(v - 20) % 10] || s[v] || s[0]}`
}

// Fixed sector -> categorical slot. Colour follows the entity, never its rank: a sector keeps its hue whatever else is shown.
export const SECTOR_SLOT: Record<string, number> = {
  'Finance, Insurance & Real Estate': 1, 'Health': 2, 'Lawyers & Lobbyists': 3, 'Tech, Telecom & Media': 4,
  'Labor': 5, 'Energy & Natural Resources': 6, 'Agribusiness & Food': 7, 'Defense & Aerospace': 8,
}
export const SOURCES: { key: string; label: string; short: string; help: string }[] = [
  { key: 'pac_direct', label: 'PAC contributions (direct gifts)', short: 'PAC gifts', help: 'Money a PAC gave directly to the member’s campaign (FEC type 24K).' },
  { key: 'indiv', label: 'Individual donors (itemized, $200+)', short: 'Individual gifts', help: 'Sector is inferred from the donor’s stated employer/occupation, so it is an estimate.' },
  { key: 'ie_support', label: 'Outside spending FOR the member', short: 'Spent for', help: 'Independent expenditures supporting the member. Not a gift to them; they cannot coordinate it.' },
  { key: 'ie_oppose', label: 'Outside spending AGAINST the member', short: 'Spent against', help: 'Independent expenditures opposing the member. Benefits their rivals, not them.' },
]
export const CATEGORY_LABEL: Record<string, string> = {
  industry: 'Business sectors', labor: 'Labor', other: 'Education / government / ideological',
  political: 'Politicians’ & party committees', unknown: 'Unclassified / not identifiable',
}

// What voters were asked, in plain words, for each survey item behind a landmark vote.
export const ITEM_LABEL: Record<string, string> = {
  healthcare_aca: 'Repeal the Affordable Care Act', guns_bgchecks: 'Background checks on all gun sales', guns_assaultban: 'Ban assault rifles',
  abortion_20weeks: 'Ban abortion after 20 weeks', enviro_carbon: 'Let the EPA regulate CO2 emissions',
  immig_legalize: 'Legal status for undocumented immigrants who work and pay taxes', cces10_stimulus: '2009 stimulus (Recovery Act)',
  cces10_schip: 'Children’s health insurance (CHIP) renewal', cces10_cleanenergy: 'Cap-and-trade climate bill',
  cces10_aca: '2010 health reform (ACA)', cces10_kagan: 'Confirm Elena Kagan to the Supreme Court',
  cces10_finreform: 'Wall Street reform (Dodd-Frank)', cces10_dadt: 'Let gays serve openly (end Don’t Ask, Don’t Tell)',
}

export const fmtLift = (l: number | null | undefined): string => (l == null ? '–' : `${l >= 0 ? '+' : '−'}${Math.abs(l * 100).toFixed(0)} pts`)

export type Tier = { key: 'far_more' | 'more' | 'same' | 'less' | 'far_less' | 'unclear'; label: string; short: string; color: string }
/** Plain-language tier from the member's lift over same-party peers and how sure we are (z). */
export function tierOf(m: { lift: number | null; z: number | null }): Tier | null {
  if (m.lift == null || m.z == null) return null
  const l = m.lift * 100
  if (m.z >= 3 && l >= 20) return { key: 'far_more', label: 'Far more donor-loyal than party peers', short: 'Far more loyal', color: 'var(--s2)' }
  if (m.z >= 2 && l >= 8) return { key: 'more', label: 'More donor-loyal than party peers', short: 'More loyal', color: 'var(--s2)' }
  if (m.z <= -3 && l <= -20) return { key: 'far_less', label: 'Far less donor-loyal than party peers', short: 'Far less loyal', color: 'var(--s3)' }
  if (m.z <= -2 && l <= -8) return { key: 'less', label: 'Less donor-loyal than party peers', short: 'Less loyal', color: 'var(--s3)' }
  if (Math.abs(m.z) < 2) return { key: 'unclear', label: 'No clear difference from party peers', short: 'No clear difference', color: 'var(--muted)' }
  return { key: 'same', label: 'About the same as party peers', short: 'About the same', color: 'var(--muted)' }
}
/** "+37 pts (+22 to +52)": the gap with a 90% range. */
export function liftRange(lift: number | null, se: number | null): string {
  if (lift == null) return '–'
  const f = (v: number) => `${v >= 0 ? '+' : '−'}${Math.abs(v * 100).toFixed(0)}`
  return se == null ? `${f(lift)} pts` : `${f(lift)} pts (${f(lift - 1.64 * se)} to ${f(lift + 1.64 * se)})`
}

/** One display name per industry label, used everywhere (the stored labels mix 'oil gas', 'Labor' and 'banks'). */
const INDUSTRY_NAME: Record<string, string> = {
  Labor: 'Labor unions', 'oil gas': 'Oil and gas', 'coal mining': 'Coal mining', 'electric utilities': 'Electric utilities',
  'physicians clinicians': 'Physicians and clinicians', banks: 'Banks', insurance: 'Insurance', pharma: 'Pharma',
}
export const industryName = (l: string): string => INDUSTRY_NAME[l] ?? l.replace(/^./, (c) => c.toUpperCase())

/** "Rep. Ellzey" / "Sen. Cassidy": last name without suffixes, with the chamber's title. */
export function shortName(name: string, chamber: string): string {
  const clean = name.replace(/,?\s+(Jr\.?|Sr\.?|II|III|IV)$/i, '').trim()
  return `${chamber === 'Senate' ? 'Sen.' : 'Rep.'} ${clean.split(/\s+/).slice(-1)[0]}`
}

/** Fix the stored lowercase labels inside free text such as "oil gas $38K, banks $40K". */
export const tidyLabels = (t: string | null | undefined): string => (t ?? '').replace(/(oil gas|coal mining|electric utilities|physicians clinicians|banks|insurance|pharma)/g, (m) => industryName(m))

/** Money categories that are not an industry with an interest of its own. */
export const NOT_INDUSTRY = ['Candidate committee', 'Leadership PAC', 'Ideological / Single-Issue / Unsorted', 'Business (sector not yet assigned)']
