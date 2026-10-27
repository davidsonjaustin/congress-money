import { useEffect, useMemo, useState } from 'react'
import * as d3 from 'd3'
import { api } from '../api'
import type { DefMember, DefOverview, DefReported, DefRevolving, DefState, MethodData, PromisesData, WarData } from '../types'
import { useWidth } from '../hooks'
import { fmtMoney } from '../util'

const bn = (v: number) => `$${(v / 1e9).toFixed(v >= 1e11 ? 0 : 1)}B`
const mn = (v: number) => `$${(v / 1e6).toFixed(v >= 1e8 ? 0 : 1)}M`
const pct = (v: number, d = 0) => `${(100 * v).toFixed(d)}%`
const sgn = (v: number, d = 1) => `${v >= 0 ? '+' : '−'}${Math.abs(v).toFixed(d)}`

type Series = { name: string; color: string; pts: [number, number][] }

function Line({ series, fmt, height = 190 }: { series: Series[]; fmt: (v: number) => string; height?: number }) {
  const [ref, width] = useWidth<HTMLDivElement>()
  const M = { l: 52, r: 12, t: 10, b: 24 }
  const xs = series.flatMap((s) => s.pts.map((p) => p[0]))
  const ys = series.flatMap((s) => s.pts.map((p) => p[1]))
  if (!xs.length) return <div ref={ref} className="hint">Loading…</div>
  const x = d3.scaleLinear().domain([d3.min(xs)!, d3.max(xs)!]).range([M.l, width - M.r])
  const y = d3.scaleLinear().domain([0, d3.max(ys)! * 1.08]).nice().range([height - M.b, M.t])
  const line = d3.line<[number, number]>().x((p) => x(p[0])).y((p) => y(p[1]))
  return (
    <div ref={ref}>
      <svg width={width} height={height} role="img" aria-label={series.map((s) => s.name).join(', ')}>
        {y.ticks(4).map((t) => (
          <g key={t}><line x1={M.l} x2={width - M.r} y1={y(t)} y2={y(t)} stroke="var(--grid)" /><text x={M.l - 6} y={y(t) + 4} textAnchor="end" fontSize={11} fill="var(--ink-2)">{fmt(t)}</text></g>
        ))}
        {x.ticks(6).map((t) => <text key={t} x={x(t)} y={height - 6} textAnchor="middle" fontSize={11} fill="var(--ink-2)">{t}</text>)}
        {series.map((s) => <path key={s.name} d={line(s.pts) ?? ''} fill="none" stroke={s.color} strokeWidth={2} />)}
      </svg>
      <div className="legend3">{series.map((s) => <span key={s.name}><i style={{ background: s.color }} /> {s.name}</span>)}</div>
    </div>
  )
}

function corr(a: number[], b: number[]): number {
  const n = a.length
  const ma = d3.mean(a)!, mb = d3.mean(b)!
  let sab = 0, saa = 0, sbb = 0
  for (let i = 0; i < n; i++) { sab += (a[i] - ma) * (b[i] - mb); saa += (a[i] - ma) ** 2; sbb += (b[i] - mb) ** 2 }
  return sab / Math.sqrt(saa * sbb)
}

export default function DefenseView({ onOpen }: { onOpen: (id: string) => void }) {
  const [ov, setOv] = useState<DefOverview | null>(null)
  const [states, setStates] = useState<DefState[]>([])
  const [mem, setMem] = useState<DefMember[]>([])
  const [rev, setRev] = useState<DefRevolving | null>(null)
  const [method, setMethod] = useState<MethodData | null>(null)
  const [war, setWar] = useState<WarData | null>(null)
  const [prom, setProm] = useState<PromisesData | null>(null)
  const [err, setErr] = useState('')
  useEffect(() => {
    api.defOverview().then(setOv).catch((e) => setErr(String(e)))
    api.defStates().then(setStates).catch(() => undefined)
    api.defMembers().then(setMem).catch(() => undefined)
    api.defRevolving().then(setRev).catch(() => undefined)
    api.method().then(setMethod).catch(() => undefined)
    api.defWar().then(setWar).catch(() => undefined)
    api.defPromises().then(setProm).catch(() => undefined)
  }, [])

  const fy = useMemo(() => {
    const m = new Map<number, { dod: number; all: number }>()
    for (const r of ov?.fy ?? []) {
      const e = m.get(r.fy) ?? { dod: 0, all: 0 }
      if (r.scope === 'dod') e.dod = r.amount; else e.all = r.amount
      m.set(r.fy, e)
    }
    return m
  }, [ov])
  const tracked = ov?.tracked ?? []
  const pc = (x: number) => (x >= 0.995 && x < 1 ? pct(x, 1) : pct(x))
  const rp = (company: string, year: number) => { const r = ov?.reported.find((x) => x.company === company && x.year === year); return r ? pc(r.share) : 'n/a' }
  const rpf = (company: string, year: number) => { const r = ov?.reported.find((x) => x.company === company && x.year === year); return r?.share_with_fms != null ? pct(r.share_with_fms) : 'n/a' }
  const last = tracked.find((t) => t.year === 2025)
  const dodTotal25 = fy.get(2025)?.dod ?? 0

  const companies = useMemo(() => {
    if (!ov) return []
    const by = new Map<string, typeof ov.companies>()
    for (const r of ov.companies) { if (r.year >= 2019 && r.year <= 2025) { const a = by.get(r.company) ?? []; a.push(r); by.set(r.company, a) } }
    const out = [...by.entries()].map(([company, rs]) => {
      const both = rs.filter((r) => r.revenue != null && r.contracts_all != null)
      const sum = (f: (r: (typeof rs)[number]) => number | null, set = rs) => set.reduce((a, r) => a + (f(r) ?? 0), 0)
      const rep = ov.reported.filter((x) => x.company === company).sort((a, b) => b.year - a.year)[0] as DefReported | undefined
      return { company, kind: rs[0].kind, contracts: sum((r) => r.contracts_all), contractsPaired: sum((r) => r.contracts_all, both), revenue: sum((r) => r.revenue, both), lobbying: sum((r) => r.lobbying), pac: sum((r) => r.pac), indiv: sum((r) => r.indiv), rep }
    })
    return out.sort((a, b) => b.contracts - a.contracts)
  }, [ov])

  const contractSeries: Series[] = [
    { name: 'DoD prime contracts to these companies', color: 'var(--s2)', pts: tracked.filter((t) => t.dod != null).map((t) => [t.year, (t.dod ?? 0) / 1e9]) },
  ]
  const influenceSeries: Series[] = [
    { name: 'Lobbying spend', color: 'var(--s2)', pts: tracked.map((t) => [t.year, (t.lobbying ?? 0) / 1e6]) },
    { name: 'PAC gifts', color: 'var(--s4, #6b7bb3)', pts: tracked.map((t) => [t.year, (t.pac ?? 0) / 1e6]) },
    { name: 'Individual gifts by employees', color: 'var(--muted)', pts: tracked.map((t) => [t.year, (t.indiv ?? 0) / 1e6]) },
  ]

  const voters = useMemo(() => mem.filter((m) => m.n >= 20 && m.state_pc != null), [mem])
  const r1 = voters.length > 10 ? corr(voters.map((m) => m.state_pc!), voters.map((m) => m.aligned / m.n)) : null
  const r2 = voters.length > 10 ? corr(voters.map((m) => Math.log1p(Math.max(0, m.pac_all ?? 0) / 1000)), voters.map((m) => m.aligned / m.n)) : null
  const own = method?.placebo.find((p) => p.vote_group === 'defense votes' && p.is_own)
  const other = [...(method?.placebo.filter((p) => p.vote_group === 'defense votes' && !p.is_own) ?? [])].sort((a, b) => b.effect_pts - a.effect_pts)[0]
  const cm = method?.committee.find((c) => c.industry === 'defense' && c.outcome.startsWith('sector money'))
  const cv = method?.committee.find((c) => c.industry === 'defense' && c.outcome.startsWith('votes'))
  const tspec = method?.timing.filter((t) => t.group === 'Defense' && t.spec.startsWith('Both, plus')) ?? []
  const tb = tspec.find((t) => t.term.includes('before'))
  const ta = tspec.find((t) => t.term.includes('after'))
  const topDistricts = useMemo(() => mem.filter((m) => m.district_dod != null && m.last_congress === 119).sort((a, b) => b.district_dod! - a.district_dod!).slice(0, 12), [mem])
  const [sortKey, setSortKey] = useState<'rate' | 'money' | 'contracts'>('rate')
  const voterRows = useMemo(() => [...voters].sort((a, b) => sortKey === 'rate' ? (b.aligned / b.n - a.aligned / a.n) || ((b.pac_all ?? 0) - (a.pac_all ?? 0)) : sortKey === 'money' ? (b.pac_all ?? 0) - (a.pac_all ?? 0) : (b.state_pc ?? 0) - (a.state_pc ?? 0)).slice(0, 25), [voters, sortKey])

  if (err) return <div className="card hint">Could not load the contracts data ({err}). Run pipeline steps 23 and 24, then restart the server.</div>
  return (
    <div className="page">
      <div className="card prose">
        <h2>Defense: who pays the industry, and what it spends on Washington</h2>
        {ov && last ? (
          <>
            <p>
              The Defense Department obligated <strong>{bn(dodTotal25)}</strong> in prime contracts in fiscal 2025 (<strong>{bn(fy.get(2008)?.dod ?? 0)}</strong> in 2008). The defense primes, defense services firms and Boeing we track received <strong>{bn(last.dod ?? 0)}</strong>{' '}
              of it ({pct((last.dod ?? 0) / dodTotal25)}). In 2025 those companies spent about <strong>{mn(last.lobbying ?? 0)}</strong> on lobbying, their PACs gave <strong>{mn(last.pac ?? 0)}</strong> to candidates, and their employees gave <strong>{mn(last.indiv ?? 0)}</strong> to members.
              That is roughly <strong>$1 spent on Washington for every ${Math.round((last.dod ?? 0) / ((last.lobbying ?? 0) + (last.pac ?? 0) + (last.indiv ?? 0))).toLocaleString()} in DoD contracts</strong>.
            </p>
            <p className="hint">
              Contracts here are prime awards in obligated dollars (USAspending), performed in the 50 states, DC and territories. They leave out classified awards, subcontracts and direct sales to foreign governments, so the totals are floors.
              Lobbying is Senate lobbying disclosures (outside firms’ income or the company’s own expenses). Gifts are FEC data to federal candidates. None of this shows that the spending buys the contracts; it shows the scale.
            </p>
          </>
        ) : <p className="hint">Loading…</p>}
        <div className="threecol">
          <div><div className="fh">DoD prime contracts to the tracked companies, $B per year</div><Line series={contractSeries} fmt={(v) => `$${v.toFixed(0)}B`} /></div>
          <div><div className="fh">What they spend on influence, $M per year</div><Line series={influenceSeries} fmt={(v) => `$${v.toFixed(0)}M`} /></div>
        </div>
      </div>

      <div className="card">
        <h2>How dependent is each company on federal contracts?</h2>
        <div className="sub">
          Two measures that should not be mixed up. <strong>Prime contracts ÷ revenue</strong> is computed here from official data and is a floor: it misses classified awards, subcontracts and direct foreign sales, and obligations are not the same as revenue booked that year.
          <strong> Company-reported share</strong> comes from the company’s own annual report and counts subcontracts to other contractors where the end customer is the government. Both are shown for 2019 to 2025 where available.
        </div>
        <div className="scroll-x">
          <table className="data">
            <thead><tr>
              <th style={{ textAlign: 'left' }}>Company</th><th>Prime contracts, 2019–25</th><th>Prime contracts ÷ revenue</th><th style={{ textAlign: 'left' }}>Company-reported US government share</th>
              <th>Lobbying, 2019–25</th><th>PAC gifts</th><th>Employee gifts</th><th>Lobbying per $1B of contracts</th>
            </tr></thead>
            <tbody>
              {companies.map((c) => (
                <tr key={c.company}>
                  <td style={{ textAlign: 'left' }}>{c.company}<div className="hint">{c.kind}</div></td>
                  <td>{bn(c.contracts)}</td>
                  <td>{c.revenue > 0 ? pct(c.contractsPaired / c.revenue) : '–'}</td>
                  <td style={{ textAlign: 'left' }}>{c.rep ? <><strong>{pc(c.rep.share)}</strong> ({c.rep.year}){c.rep.share_with_fms != null && <> · about <strong>{pct(c.rep.share_with_fms)}</strong> counting foreign military sales</>} <a href={c.rep.source_url} target="_blank" rel="noreferrer">10-K</a><div className="hint">{c.rep.basis}</div></> : <span className="hint">{c.company.startsWith('BAE') ? 'UK parent: no SEC annual report' : 'not in an SEC filing'}</span>}</td>
                  <td>{c.lobbying ? mn(c.lobbying) : '–'}</td><td>{c.pac ? mn(c.pac) : '–'}</td><td>{c.indiv ? mn(c.indiv) : '–'}</td>
                  <td>{c.lobbying && c.contracts ? `$${Math.round((c.lobbying / (c.contracts / 1e9)) / 1000).toLocaleString()}K` : '–'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="hint" style={{ marginTop: 8 }}>
          Company-reported shares were read directly from each company’s 10-K on SEC EDGAR (fiscal years 2020 to 2026 where the filing gives them; the link goes to the filing). Where a filing gives only dollars, the share is computed from its own dollar figures.
          The definitions differ and the basis line says which: some include foreign military sales (General Dynamics, Boeing, L3Harris, Textron), RTX excludes them, and Lockheed and Northrop report them inside an “international” line. Diversified companies (Boeing, RTX, GE, Honeywell, Textron) show a lower share because commercial business is counted in revenue.
          The “counting FMS” figure for Lockheed is derived (its US Government sales plus the FMS percentage of international sales that the filing states) and is approximate.
        </div>
      </div>

      <div className="card prose">
        <h2>Checking the numbers you’ve heard</h2>
        <h3>“Up to 90% of revenue from government contracts”</h3>
        <ul>
          <li>For the pure defense and government-services companies, high shares are real, and these come from the companies’ own 10-Ks for 2025 (fiscal 2025): Huntington Ingalls {rp('Huntington Ingalls', 2025)}, Booz Allen {rp('Booz Allen Hamilton', 2025)}, SAIC {rp('Science Applications International (SAIC)', 2025)}, CACI {rp('CACI', 2025)}, Leidos {rp('Leidos (and SAIC before 2014)', 2025)}, Northrop Grumman {rp('Northrop Grumman', 2025)} ({rp('Northrop Grumman', 2024)} in 2024), L3Harris {rp('L3Harris (Harris / L3)', 2025)}, Lockheed Martin {rp('Lockheed Martin', 2025)}, General Dynamics {rp('General Dynamics', 2025)}.</li>
          <li>Lockheed shows why the “foreign contracts paid by the US government” point matters. Its 10-K counts only {rp('Lockheed Martin', 2025)} of 2025 sales as US Government, but about 77% of its $21.3 billion in international sales were foreign military sales, which are contracts with and paid through the US government. Counting those brings it to about <strong>{rpf('Lockheed Martin', 2025)}</strong> (derived, approximate), which is where the “as high as 90%” figure comes from.</li>
          <li>It is much lower for companies with big commercial businesses: Boeing {rp('Boeing', 2025)} in 2025 ({rp('Boeing', 2024)} in 2024; its defense segment alone is 91%), RTX {rp('RTX (Raytheon / United Technologies)', 2025)} (excluding foreign military sales), Textron {rp('Textron', 2025)}, Honeywell {rp('Honeywell', 2025)}, GE {rp('General Electric', 2025)}.</li>
          <li>Whether “foreign contracts paid by the US government” count matters. Sales to other countries made through the Pentagon’s Foreign Military Sales program are generally awarded as DoD contracts and so appear in the DoD totals above; direct sales from a company to a foreign government do not.</li>
          <li>So the honest answer is a range by company and definition, not one number. The table above gives each company’s figure, with its source.</li>
        </ul>
        <h3>“$1.1 trillion for the Pentagon this year”</h3>
        <ul>
          <li>The administration’s fiscal 2026 request was about <strong>$1.01 trillion</strong> for national defense, of which a Pentagon discretionary request of <strong>$961.6B</strong> included <strong>$113.3B from a reconciliation bill</strong> on top of an <strong>$848.3B</strong> base. The base figure cited by the Senate Armed Services chair was <strong>$892.6B</strong>. Sources: <a href="https://www.airandspaceforces.com/trump-proposes-1-trillion-defense-budget-2026/" target="_blank" rel="noreferrer">Air & Space Forces</a>, <a href="https://breakingdefense.com/2025/05/trump-administration-to-request-1t-defense-budget-using-reconciliation-funds/" target="_blank" rel="noreferrer">Breaking Defense</a>, <a href="https://www.armscontrol.org/act/2025-06/news/trump-proposes-trillion-dollar-defense-budget" target="_blank" rel="noreferrer">Arms Control Association</a>.</li>
          <li>I could not confirm a final enacted figure of $1.1 trillion. Which figure applies depends on whether it counts the Pentagon alone or all national defense, and whether reconciliation money is included.</li>
        </ul>
      </div>

      <div className="card">
        <h2>Where the contract money lands</h2>
        <div className="sub">DoD prime contract dollars performed in each state, average of fiscal 2023 to 2025. A member whose state or district gets a lot of this has a local reason to vote for defense spending that has nothing to do with donations, so the votes below are read next to it.</div>
        <div className="twocol">
          <div>
            <div className="fh">Per resident, by state</div>
            <table className="data">
              <thead><tr><th style={{ textAlign: 'left' }}>State</th><th>Per resident</th><th>Total per year</th></tr></thead>
              <tbody>{states.filter((s) => s.pop > 0).slice(0, 12).map((s) => <tr key={s.state}><td style={{ textAlign: 'left' }}>{s.state}</td><td>${Math.round(s.per_capita).toLocaleString()}</td><td>{bn(s.dod)}</td></tr>)}</tbody>
            </table>
          </div>
          <div>
            <div className="fh">Top House districts today</div>
            <table className="data">
              <thead><tr><th style={{ textAlign: 'left' }}>Member</th><th>DoD contracts per year</th><th>Defense PAC gifts, all years</th></tr></thead>
              <tbody>
                {topDistricts.map((m) => (
                  <tr key={m.bioguide} className="clickrow" onClick={() => onOpen(m.bioguide)}>
                    <td style={{ textAlign: 'left' }}><span className={`party ${m.party}`}><i />{m.party}</span> {m.name} <span className="hint">· {m.state}</span></td>
                    <td>{bn(m.district_dod!)}</td><td>{m.pac_all ? fmtMoney(m.pac_all) : '–'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <div className="hint">District totals follow the districts USAspending reports today and are approximate.</div>
          </div>
        </div>
      </div>

      <div className="card">
        <h2>Votes with the industry, money and local contracts</h2>
        <div className="sub">
          The votes are 147 documented defense votes since 2008: every passage and conference-report vote on the defense authorization and appropriations bills (industry side Yea), plus, for 2013 to 2024, amendments to cut or add Pentagon money or weapons programs and resolutions to block arms sales.
          For those, the industry’s side is the opposite of Peace Action’s position (a fiscal rule: Peace Action backs cuts and limits). Members with at least 20 of these votes are shown.
        </div>
        {r1 != null && r2 != null && (
          <p>
            Across {voters.length} members, voting with the industry’s side tracks <strong>defense PAC money</strong> (correlation {r2.toFixed(2)}) {Math.abs(r2) > Math.abs(r1) ? 'more closely than' : 'about as closely as'} it tracks <strong>contract dollars in their state</strong> ({r1.toFixed(2)}).
            Both are strongly shaped by party.
            {own && other && ` In the formal test that holds ideology, district lean and the defense contracts in the state fixed, defense PAC money predicts these votes (${sgn(own.effect_pts)} points per $50K), but ${other.money_from} money does nearly as well (${sgn(other.effect_pts)}), so it does not point to defense money in particular.`}
            {tb && ta && ` On these votes, defense money from the two years before a vote predicts voting with the industry more (${sgn(tb.effect_pts)} points per $50K) than money from the two years after (${sgn(ta.effect_pts)}). That is the order influence would produce, but steady year-to-year giving and donors choosing like-minded members produce it too, and the every-vote screen over 14,952 votes shows no before-versus-after gap for defense money.`}
            {cm && cv && ` Members who joined the Armed Services committees saw defense PAC money change by ${sgn(100 * (Math.exp(cm.effect) - 1), 0)}%, and their votes on defense measures did not meaningfully shift (${sgn(cv.effect)} ± ${(1.64 * cv.se).toFixed(1)} points).`}
          </p>
        )}
        <div className="seg" style={{ marginBottom: 8 }}>
          {([['rate', 'Most with the industry'], ['money', 'Most defense PAC money'], ['contracts', 'Most contracts in state']] as const).map(([k, l]) => <button key={k} aria-pressed={sortKey === k} onClick={() => setSortKey(k)}>{l}</button>)}
        </div>
        <div className="scroll-x">
          <table className="data">
            <thead><tr><th style={{ textAlign: 'left' }}>Member</th><th>Votes with the industry’s side</th><th>Defense PAC gifts, all years</th><th>Employee gifts</th><th>DoD contracts per resident in state</th></tr></thead>
            <tbody>
              {voterRows.map((m) => (
                <tr key={m.bioguide} className="clickrow" onClick={() => onOpen(m.bioguide)}>
                  <td style={{ textAlign: 'left' }}><span className={`party ${m.party}`}><i />{m.party}</span> {m.name} <span className="hint">· {m.state}{m.chamber === 'Senate' ? ' Sen.' : ''}</span></td>
                  <td>{m.aligned} of {m.n} ({pct(m.aligned / m.n)})</td><td>{m.pac_all ? fmtMoney(m.pac_all) : '–'}</td><td>{m.ind_all ? fmtMoney(m.ind_all) : '–'}</td><td>${Math.round(m.state_pc ?? 0).toLocaleString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <div className="card">
        <h2>No new wars: what Congress did about it</h2>
        {!war && <div className="hint">Loading…</div>}
        {war && (() => {
          const v119 = war.votes.filter((v) => v.congress === 119)
          const sh = (ch: string, p: string) => war.by_party.find((x) => x.chamber === ch && x.party === p)
          const rebels = war.members.filter((m) => m.party === 'R' && m.constrain > 0).sort((a, b) => b.constrain / b.n - a.constrain / a.n)
          const dem = war.members.filter((m) => m.party === 'D' && m.constrain / m.n < 0.5).sort((a, b) => a.constrain / a.n - b.constrain / b.n)
                    return (
            <>
              <div className="sub">
                The only votes that force the question are resolutions directing the President to remove US forces from hostilities that Congress has not authorized. We count every vote on such a resolution since 2008 ({war.votes.length} votes, {v119.length} of them in 2025 and 2026).
                A Yea is a vote to constrain military action; it says nothing about any industry. Procedural votes (rules, tabling, points of order) are left out.
              </div>
              <div className="scroll-x">
                <table className="data">
                  <thead><tr><th style={{ textAlign: 'left' }}>2025–26</th><th>Republicans voting to constrain</th><th>Democrats voting to constrain</th></tr></thead>
                  <tbody>
                    {['House', 'Senate'].map((ch) => <tr key={ch}><td style={{ textAlign: 'left' }}>{ch}</td><td>{sh(ch, 'R') ? pct(sh(ch, 'R')!.share, 1) : '–'} of votes ({sh(ch, 'R')?.members} members)</td><td>{sh(ch, 'D') ? pct(sh(ch, 'D')!.share, 1) : '–'} of votes ({sh(ch, 'D')?.members} members)</td></tr>)}
                  </tbody>
                </table>
              </div>
              <div className="threecol" style={{ marginTop: 10 }}>
                <div>
                  <div className="fh">Republicans who voted to constrain</div>
                  <ul className="facts">{rebels.map((m) => <li key={m.id}><a onClick={() => onOpen(m.id)} style={{ cursor: 'pointer' }}>{m.name}</a> ({m.state}): {m.constrain} of {m.n} <span className="hint">· defense PAC {fmtMoney(m.pac_6y)} in 6 years</span></li>)}</ul>
                </div>
                <div>
                  <div className="fh">Democrats who voted to constrain on fewer than half</div>
                  <ul className="facts">{dem.length ? dem.map((m) => <li key={m.id}><a onClick={() => onOpen(m.id)} style={{ cursor: 'pointer' }}>{m.name}</a> ({m.state}): {m.constrain} of {m.n}</li>) : <li className="hint">None</li>}</ul>
                </div>
                <div>
                  <div className="fh">Does defense money line up with it?</div>
                  <p style={{ margin: 0, fontSize: 13.5 }}>
                    Within each party, a negative correlation means members who received more defense-industry PAC money voted to constrain less often
                    {war.association.map((a) => ` (${a.party === 'R' ? 'Republicans' : 'Democrats'}, ${a.chamber}: correlation ${a.corr.toFixed(2)} across ${a.members} members)`).join(',')}. Votes follow party so closely that these are small effects on a small spread, and the members who take little defense money are also the ones most often breaking with the party; it does not show the money caused anything.
                  </p>
                </div>
              </div>
            </>
          )
        })()}
      </div>

      <div className="card">
        <h2>What they said, what they did</h2>
        {!prom && <div className="hint">Loading…</div>}
        {prom && (
          <>
            <div className="sub">
              Each statement links to its source and sits next to the member’s record on the matching votes. This is a small set where we found a sourced public statement on defense money or war, from both parties. It is not a representative sample, and a record that differs from a statement is a fact to look at, not a verdict.
            </div>
            <div className="scroll-x">
              <table className="data">
                <thead><tr><th style={{ textAlign: 'left' }}>Member</th><th style={{ textAlign: 'left' }}>Said (source)</th><th>Voted to constrain war (2025–26)</th><th>Voted with the industry on defense money votes</th><th>Defense PAC gifts</th></tr></thead>
                <tbody>
                  {prom.items.map((p, i) => (
                    <tr key={i}>
                      <td style={{ textAlign: 'left' }}><a onClick={() => onOpen(p.bioguide)} style={{ cursor: 'pointer' }}>{p.name}</a><div className="hint">{p.record.member?.party}-{p.record.member?.state}</div></td>
                      <td style={{ textAlign: 'left', maxWidth: 440 }}>{p.statement} <a href={p.source_url} target="_blank" rel="noreferrer">{p.source_name}</a> <span className="hint">({p.date})</span></td>
                      <td>{p.record.war && p.record.war.n119 ? `${p.record.war.constrain119} of ${p.record.war.n119}` : '–'}</td>
                      <td>{p.record.defense && p.record.defense.n ? `${p.record.defense.aligned} of ${p.record.defense.n}` : '–'}</td>
                      <td>{p.record.pac_all ? fmtMoney(p.record.pac_all) : '$0'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <h3>The executive branch</h3>
            <div className="sub">Presidents act through orders, not roll calls, so there is no vote to measure. These are statements and military actions as reported by the cited outlets; read the sources for the wording and the context.</div>
            <ul className="facts">
              {prom.executive.map((e, i) => <li key={i}><strong>{e.kind === 'said' ? 'Said' : 'Did'}</strong> <span className="hint">({e.date})</span>: {e.text} <a href={e.source_url} target="_blank" rel="noreferrer">{e.source_name}</a></li>)}
            </ul>
          </>
        )}
      </div>

      <div className="card">
        <h2>The revolving door</h2>
        {!rev && <div className="hint">Loading…</div>}
        {rev && rev.per_company.length === 0 && <div className="hint">Lobbyist data has not been built yet (pipeline step 26).</div>}
        {rev && rev.per_company.length > 0 && (() => {
          const tot = rev.per_company.reduce((a, r) => ({ l: a.l + r.lobbyists, p: a.p + r.with_position, c: a.c + r.congress_roles, e: a.e + r.executive_roles }), { l: 0, p: 0, c: 0, e: 0 })
          return (
            <>
              <div className="sub">
                Lobbyists must report any “covered” government position they held in the past 20 years. Across the defense companies we track, <strong>{pct(tot.c / tot.l)}</strong> of lobbyist-company pairs ({tot.c.toLocaleString()} of {tot.l.toLocaleString()}) list a prior job in Congress (member, committee or personal staff),
                and <strong>{pct(tot.e / tot.l)}</strong> list a defense, military, White House or other executive-branch role. Some people list both, and the classification reads free-text titles, so treat these as counts of roles reported, not precise totals.
                A lobbyist who works for several companies is counted once per company.
              </div>
              <div className="scroll-x">
                <table className="data">
                  <thead><tr><th style={{ textAlign: 'left' }}>Company</th><th>Lobbyists</th><th>Prior Congress job</th><th>Prior defense / executive job</th><th>Outside firms hired</th></tr></thead>
                  <tbody>
                    {rev.per_company.map((r) => {
                      const sp = rev.spend.find((x) => x.company === r.company)
                      return <tr key={r.company}><td style={{ textAlign: 'left' }}>{r.company}</td><td>{r.lobbyists.toLocaleString()}</td><td>{pct(r.congress_roles / r.lobbyists)}</td><td>{pct(r.executive_roles / r.lobbyists)}</td><td>{sp?.firms ?? '–'}</td></tr>
                    })}
                  </tbody>
                </table>
              </div>
              <div className="threecol" style={{ marginTop: 10 }}>
                <div><div className="fh">Most common prior positions</div><ul className="facts">{rev.common_positions.slice(0, 10).map((p) => <li key={p.position}>{p.position} <span className="hint">({p.people})</span></li>)}</ul></div>
                <div><div className="fh">Who they lobby</div><ul className="facts">{rev.entities.map((e) => <li key={e.entity}>{e.entity} <span className="hint">({e.filings.toLocaleString()} filings)</span></li>)}</ul></div>
              </div>
              <h3>From the Pentagon to the contractors</h3>
              <div className="sub">The other direction is not in lobbying filings, so these are reported findings with sources rather than something we computed. Read each source for context.</div>
              <ul className="facts">{rev.door_facts.map((d, i) => <li key={i}><span className="hint">({d.date})</span> {d.text} <a href={d.source_url} target="_blank" rel="noreferrer">{d.source_name}</a></li>)}</ul>
            </>
          )
        })()}
      </div>
    </div>
  )
}
