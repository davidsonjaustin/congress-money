import { useEffect, useMemo, useState } from 'react'
import { api } from '../api'
import type { AllVotesSummary, Coverage, MemberRow, MethodData, Scored, SectorOption } from '../types'
import Scatter from '../charts/Scatter'
import { NOT_INDUSTRY, fmtLift, fmtMoney, industryName, liftRange, tidyLabels } from '../util'

type Props = { onOpen: (id: string) => void; onMethod: () => void }

const pct = (v: number) => `${v >= 0 ? '+' : '−'}${Math.abs(v * 100).toFixed(0)}%`
const pts = (v: number) => `${v >= 0 ? '+' : '−'}${Math.abs(v).toFixed(1)}`

export default function Scoreboard({ onOpen, onMethod }: Props) {
  const [data, setData] = useState<Scored[]>([])
  const [cov, setCov] = useState<Coverage | null>(null)
  const [method, setMethod] = useState<MethodData | null>(null)
  const [chamber, setChamber] = useState('')
  const [party, setParty] = useState('')
  const [era, setEra] = useState('now')
  const [q, setQ] = useState('')
  const [showAll, setShowAll] = useState(false)
  const [variant, setVariant] = useState<'all' | 'core' | 'inferred' | 'lobbied'>('lobbied')
  const [sector, setSector] = useState('All business')
  const [sum, setSum] = useState<AllVotesSummary | null>(null)
  const [roster, setRoster] = useState<MemberRow[]>([])
  const [sectors, setSectors] = useState<SectorOption[]>([])
  const [sort, setSort] = useState<{ key: keyof Scored; dir: 1 | -1 }>({ key: 'loyalty', dir: -1 })

  useEffect(() => {
    api.scoreboard(variant, sector).then((r) => { setData(r.members); setCov(r.coverage); setSectors(r.sectors) }).catch(() => undefined)
  }, [variant, sector])
  useEffect(() => { api.method().then(setMethod).catch(() => undefined) }, [])
  useEffect(() => { api.allVotesSummary().then(setSum).catch(() => undefined); api.members().then(setRoster).catch(() => undefined) }, [])

  const filtered = useMemo(() => data.filter((m) =>
    (!chamber || m.chamber === chamber) && (!party || m.party === party) && (!era || (era === 'now' ? m.last_congress === 119 : m.last_congress < 119))), [data, chamber, party, era])
  const ranked = useMemo(() => filtered.filter((m) => m.ranked && m.lift != null), [filtered])
  const minW = variant === 'inferred' || variant === 'lobbied' ? 10 : 3     // many more votes per member in the every-vote views, so ask for a longer record
  // Named lists rank by the gap over same-party peers (lift), and only include gaps whose 90% range excludes zero. Raw "voted the industry's way" shares mostly show who is in the majority party.
  const evidence = useMemo(() => ranked.filter((m) => (m.weight ?? 0) >= minW && m.se != null), [ranked, minW])
  const beyond = useMemo(() => evidence.filter((m) => m.lift! - 1.64 * m.se! > 0)
    .sort((a, b) => ((b.lift! - 1.64 * b.se!) - (a.lift! - 1.64 * a.se!)) || ((b.money_at_stake ?? 0) - (a.money_at_stake ?? 0))).slice(0, 10), [evidence])
  const against = useMemo(() => evidence.filter((m) => m.lift! + 1.64 * m.se! < 0)
    .sort((a, b) => ((a.lift! + 1.64 * a.se!) - (b.lift! + 1.64 * b.se!)) || ((b.money_at_stake ?? 0) - (a.money_at_stake ?? 0))).slice(0, 10), [evidence])
  const overHome = useMemo(() => filtered.filter((m) => (m.donors_over_district ?? 0) >= 1)
    .sort((a, b) => (b.donors_over_district! - a.donors_over_district!) || (b.donors_over_district! / (b.donor_district_votes || 1) - a.donors_over_district! / (a.donor_district_votes || 1))).slice(0, 10), [filtered])
  const overHomeProxy = useMemo(() => filtered.filter((m) => (m.proxy_votes ?? 0) >= 10 && (m.proxy_donors_over ?? 0) >= 1)
    .sort((a, b) => (b.proxy_donors_over! / b.proxy_votes! - a.proxy_donors_over! / a.proxy_votes!) || ((b.money_at_stake ?? 0) - (a.money_at_stake ?? 0))).slice(0, 10), [filtered])
  const matches = useMemo(() => {
    const t = q.trim().toLowerCase()
    return t.length < 2 ? [] : data.filter((m) => m.name.toLowerCase().includes(t)).slice(0, 8)
  }, [data, q])
  const pillSectors = [...sectors].filter((x) => x.members_ranked > 0 || x.label === 'Labor').sort((a, b) => b.votes - a.votes)

  return (
    <div className="page">
      <div className="hero">
        <h2>Follow the money to the vote</h2>
        <Answer sum={sum} />
        <FindYours roster={roster} onOpen={onOpen} />
        {cov && (() => {
          const byLabel = Object.entries(cov.coded_by_label ?? {}).filter(([k]) => k)
          const well = byLabel.filter(([, n]) => n >= 50).map(([k, n]) => `${k} ${n}`).join(', ')
          const thin = byLabel.filter(([, n]) => n < 25).map(([k, n]) => `${k} ${n}`).join(', ')
          return (
            <p className="hint">
              Votes where the industry’s side is documented from its own statements, scorecards or the spending rule: <strong>{cov.coded_since_2008.toLocaleString()}</strong> of the <strong>{cov.votes_since_2008.toLocaleString()}</strong> roll calls since 2008 ({(100 * cov.coded_since_2008 / cov.votes_since_2008).toFixed(1)}%).
              Well covered: {well || 'none'}. Thin: {thin || 'none'}. The “Lobbied votes” and “Every vote” views reach the rest without needing a stated side.
            </p>
          )
        })()}
        {method && <Findings method={method} board={data} onMethod={onMethod} />}
      </div>

      <div className="card filterbar">
        <div className="pills" aria-label="Which industry">
          {pillSectors.map((x) => (
            <button key={x.label} className="pill" aria-pressed={sector === x.label} onClick={() => setSector(x.label)} title={`${x.votes} coded votes, ${x.members_ranked} members ranked`}>
              {industryName(x.label)}
              <span className="hint"> · {x.votes} votes</span>
            </button>
          ))}
        </div>
        <div className="seg">{[['', 'Both chambers'], ['Senate', 'Senate'], ['House', 'House']].map(([k, l]) =>
          <button key={k} aria-pressed={chamber === k} onClick={() => setChamber(k)}>{l}</button>)}</div>
        <div className="seg">{[['', 'Both parties'], ['D', 'Democrats'], ['R', 'Republicans']].map(([k, l]) =>
          <button key={k} aria-pressed={party === k} onClick={() => setParty(k)}>{l}</button>)}</div>
        <div className="seg">{[['', 'Since 2005'], ['now', 'Serving now']].map(([k, l]) =>
          <button key={k} aria-pressed={era === k} onClick={() => setEra(k)}>{l}</button>)}</div>
        <div className="searchwrap">
          <input className="search" placeholder="Look up a member…" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Look up a member" />
          {matches.length > 0 && (
            <div className="suggest">{matches.map((m) => (
              <button key={m.id} onClick={() => onOpen(m.id)}><span className={`party ${m.party}`}><i />{m.party}</span> {m.name} <span className="hint">· {m.state}</span></button>
            ))}</div>
          )}
        </div>
        <div className="seg" title="Lobbied votes: every-vote links on bills that industry lobbied on, from lobbying filings. Every vote: any roll call where this industry's money lines up strongly with how members voted, taking the side its money pulls toward. Documented side: votes where the industry's position is known from scorecards or its own statements. Strictly sourced: only the industry's own statements.">
          {[['lobbied', 'Lobbied votes'], ['inferred', 'Every vote since 2008'], ['all', 'Documented side'], ['core', 'Strictly sourced']].map(([k, l]) => <button key={k} aria-pressed={variant === k} onClick={() => setVariant(k as 'all' | 'core' | 'inferred' | 'lobbied')}>{l}</button>)}
        </div>
        {(variant === 'inferred' || variant === 'lobbied') && <div className="coverage">{variant === 'lobbied' ? `Lobbied votes: only votes on bills this industry’s own lobbyists named in Senate filings (2008 to ${cov?.lobbied_through ? new Date(cov.lobbied_through + 'T00:00:00').toLocaleDateString('en-US', { month: 'short', year: 'numeric' }) : 'now'}). ` : ''}Every-vote view: a vote counts for an industry when its money lines up strongly with how members voted, and the industry’s side is the side that money pulls toward. That side is inferred from the money pattern, not stated by the industry, so use this to find leads and check the case file.</div>}
        {cov && <div className="coverage">This view: <strong>{cov.coded_votes}</strong> coded votes · <strong>{cov.ranked_members}</strong> members ranked · {cov.landmark_votes} landmark votes checked against district opinion.</div>}
      </div>

      <div className="threecol">
        <OverHome rows={overHome} onOpen={onOpen} kind="direct" />
        <OverHome rows={overHomeProxy} onOpen={onOpen} kind="proxy" />
        <Highlights title="Furthest beyond their politics" blurb="Funded by the industry and voted its way more often than same-party colleagues with the same ideology and district did. Ranked by the low end of the range, so only gaps we are fairly sure of are listed."
          rows={beyond} onOpen={onOpen} inferred={variant === 'inferred' || variant === 'lobbied'} dir="with" />
        <Highlights title="Funded, but voted against the money" blurb="Funded by the industry and voted against what its money pulls toward more often than same-party colleagues did. Party is already allowed for, so this is not a list of one party."
          rows={against} onOpen={onOpen} inferred={variant === 'inferred' || variant === 'lobbied'} dir="against" />
      </div>

      <div className="card">
        <details>
          <summary><strong>Check: is it just their politics?</strong> Compare each member with same-party colleagues</summary>
          <div className="sub" style={{ marginTop: 8 }}>
            A member who always votes with their party will often vote the donors’ way because the donors back that party, not because of the member. This chart asks how far each member sits from
            what same-party colleagues did on the same votes. It cannot show party-wide capture, which is why it is a check and not the ranking. Across: share of money-backed votes cast the industry’s way.
            Up: more than same-party colleagues. Click a dot to open that member’s case file.
          </div>
          <Scatter data={ranked} onOpen={onOpen} />
        </details>
      </div>

      <div className="card">
        <h2>Everyone with enough money-backed votes ({ranked.length})</h2>
        <div className="sub">Click a column to sort and a row to open that member’s case file.</div>
        <FullTable rows={ranked} sort={sort} setSort={setSort} onOpen={onOpen} limit={showAll ? 9999 : 25} />
        {ranked.length > 25 && <button className="iconbtn" style={{ marginTop: 8 }} onClick={() => setShowAll((v) => !v)}>{showAll ? 'Show fewer' : `Show all ${ranked.length}`}</button>}
      </div>
    </div>
  )
}

function Answer({ sum }: { sum: AllVotesSummary | null }) {
  if (!sum) return <p className="hint">Loading…</p>
  const lo = sum.dose.find((d) => d.k === '1'), hi = sum.dose.find((d) => d.k === '5')
  const inds = sum.industries.filter((r) => !NOT_INDUSTRY.includes(r.label) && r.link_before != null && r.link_after != null)
  const beforeWins = inds.filter((r) => (r.link_before ?? 0) - (r.link_after ?? 0) >= 0.01)
  const p = (v: number) => `${(100 * v).toFixed(0)}%`
  const g = (v: number) => `${v >= 0 ? '+' : '−'}${Math.abs(100 * v).toFixed(1)} points`
  return (
    <div className="answer">
      <h3>The short answer</h3>
      <p>
        We tested <strong>{sum.tested.toLocaleString()}</strong> House and Senate votes since 2008 against the PAC money each industry had given every member.
        {lo && hi ? <> Members who had received <strong>$200,000 or more</strong> from an industry voted the way its money pulls <strong>{p(hi.aligned)}</strong> of the time; their ideology, party and district predict {p(hi.expected)} ({g(hi.aligned - hi.expected)}).
        Members who had received <strong>under $1,000</strong> voted that way {p(lo.aligned)}, against {p(lo.expected)} predicted ({g(lo.aligned - lo.expected)}).</> : null}{' '}
        The more an industry gave, the more members voted its way.
      </p>
      <p>
        <strong>What this does not prove:</strong> for {inds.length - beforeWins.length} of {inds.length} industries, money that arrived <em>after</em> the vote predicts it about as well as money before, which fits donors rewarding members who already vote their way as much as money moving votes.
        {beforeWins.length > 0 ? <> Money before beats money after for {beforeWins.map((r) => industryName(r.label).toLowerCase()).join(', ')}, the pattern influence would leave.</> : null}{' '}
        The lists below point to members to look at, not verdicts.
      </p>
    </div>
  )
}

function FindYours({ roster, onOpen }: { roster: MemberRow[]; onOpen: (id: string) => void }) {
  const [state, setState] = useState('')
  const now = useMemo(() => roster.filter((m) => m.last_congress === 119), [roster])
  const states = useMemo(() => [...new Set(now.map((m) => m.state))].sort(), [now])
  const mine = useMemo(() => now.filter((m) => m.state === state).sort((a, b) => (a.chamber === b.chamber ? (a.district ?? 0) - (b.district ?? 0) : a.chamber === 'Senate' ? -1 : 1)), [now, state])
  return (
    <div className="findyours">
      <label>
        <strong>Find your members of Congress</strong>{' '}
        <select value={state} onChange={(e) => setState(e.target.value)} aria-label="Your state">
          <option value="">Choose your state…</option>
          {states.map((s) => <option key={s}>{s}</option>)}
        </select>
      </label>
      {state && (
        <div className="mine">
          {mine.map((m) => (
            <button key={m.id} className="pill" onClick={() => onOpen(m.id)}>
              <span className={`party ${m.party}`}><i />{m.party}</span> {m.name} <span className="hint">· {m.chamber === 'Senate' ? 'Senate' : `District ${m.district ?? '–'}`}</span>
            </button>
          ))}
          {state && <span className="hint"> Not sure of your district? <a href="https://www.house.gov/representatives/find-your-representative" target="_blank" rel="noreferrer">The House’s lookup</a> takes a ZIP code.</span>}
        </div>
      )}
    </div>
  )
}

function Findings({ method, board, onMethod }: { method: MethodData; board: Scored[]; onMethod: () => void }) {
  const sum = (f: (m: Scored) => number | null | undefined) => board.reduce((a, m) => a + (f(m) ?? 0), 0)
  const dO = sum((m) => m.donors_over_district), dD = sum((m) => m.district_over_donors)
  const pO = sum((m) => m.proxy_donors_over), pD = sum((m) => m.proxy_district_over)
  const share = (a: number, b: number) => (a + b > 0 ? `${((100 * a) / (a + b)).toFixed(0)}%` : '–')
  const money = (ind: string) => method.committee.find((c) => c.industry === ind && c.outcome.startsWith('sector money'))
  const votes = (ind: string) => method.committee.find((c) => c.industry === ind && c.outcome.startsWith('votes'))
  const own = (g: string) => method.placebo.find((p) => p.vote_group === g && p.is_own)
  const bestOther = (g: string) => [...method.placebo.filter((p) => p.vote_group === g && !p.is_own)].sort((a, b) => b.effect_pts - a.effect_pts)[0]
  const lab = own('labor votes'), labO = bestOther('labor votes'), oil = own('oil and gas votes'), oilO = bestOther('oil and gas votes')
  const mDef = money('defense'), vDef = votes('defense')
  const mOil = money('oil and gas'), mBank = money('banks'), mLab = money('labor'), vOil = votes('oil and gas'), vLab = votes('labor')
  return (
    <div className="findings">
      <div className="fcard">
        <div className="fh">When donors and home disagree</div>
        <p>
          {dO + dD > 0 ? `When a funded industry and a clear majority at home wanted opposite things, members sided with the industry ${share(dO, dD)} of the time on the few votes with a direct survey measure of district opinion (${(dO + dD).toLocaleString()} cases) and ${share(pO, pD)} on fossil votes judged by district climate opinion (${(pO + pD).toLocaleString()} cases, a looser proxy). ` : 'Loading… '}
          That is close to even, so on this evidence donors beat home about as often as home beat donors.
        </p>
      </div>
      <div className="fcard">
        <div className="fh">Money follows power</div>
        <p>
          {mOil && mBank && mLab ? `When a member joins a committee that oversees an industry, that industry’s PAC money to them jumps (oil ${pct(Math.exp(mOil.effect) - 1)}, banks ${pct(Math.exp(mBank.effect) - 1)}, unions ${pct(Math.exp(mLab.effect) - 1)})` : ''}
          {vOil && vLab ? `, yet how they vote barely moves (${pts(vOil.effect)} points for oil, ${pts(vLab.effect)} for unions).` : '.'}
        </p>
      </div>
      <div className="fcard">
        <div className="fh">Unions are the clearest case</div>
        <p>
          {lab && labO ? `Union PAC money predicts pro-union votes (+${lab.effect_pts.toFixed(0)} points per $50K) far more than any other industry’s money (best other: ${labO.money_from}, ${pts(labO.effect_pts)}). ` : ''}
          {oil && oilO ? `For oil and gas votes, ${oilO.money_from} money (${pts(oilO.effect_pts)}) predicts as well as oil’s own (${pts(oil.effect_pts)}).` : ''}
        </p>
      </div>
      {mDef && vDef && (
        <div className="fcard">
          <div className="fh">Defense: the biggest contracts, a small share of the money</div>
          <p>
            Members who joined the Armed Services committees saw defense PAC money rise {pct(Math.exp(mDef.effect) - 1)}, yet their votes on defense measures did not shift ({pts(vDef.effect)} points).
            The industry gives members millions a year against hundreds of billions in DoD contracts.{' '}
            <button className="linkbtn" onClick={() => { location.hash = '#/defense' }}>See the Defense tab</button>
          </p>
        </div>
      )}
      <div className="flink"><button className="linkbtn" onClick={onMethod}>How we tested this, and what it can’t show</button></div>
    </div>
  )
}

function Highlights({ title, blurb, rows, onOpen, inferred, dir }: { title: string; blurb: string; rows: Scored[]; onOpen: (id: string) => void; inferred: boolean; dir: 'with' | 'against' }) {
  return (
    <div className="card">
      <h2>{title}</h2>
      <div className="sub">{blurb}</div>
      {rows.length === 0 && <div className="hint">Nobody meets the evidence bar with these filters.</div>}
      <ol className="hl">
        {rows.map((m, i) => (
          <li key={m.id}>
            <button onClick={() => onOpen(m.id)}>
              <span className="rk">{i + 1}</span>
              <span className="who"><span className={`party ${m.party}`}><i />{m.party}</span> {m.name} <span className="hint">· {m.state}{m.chamber === 'Senate' ? ' Sen.' : ''}</span></span>
              <span className="val">{fmtLift(m.lift)}</span>
              <span className="dt">
                {dir === 'with' ? 'Voted' : 'Voted only'} {inferred ? 'the way its money pulls' : 'the industry’s way'} on {m.n_funded_aligned} of {m.n_funded} votes while it had given $10K or more; same-party colleagues would be expected to on about {Math.round(m.peers_funded_aligned ?? 0)}.
                Gap {liftRange(m.lift, m.se)}{m.money_at_stake ? `; ${fmtMoney(m.money_at_stake)} from ${tidyLabels(m.top_sectors) || 'these industries'}` : ''}.
              </span>
            </button>
          </li>
        ))}
      </ol>
    </div>
  )
}

function OverHome({ rows, onOpen, kind }: { rows: Scored[]; onOpen: (id: string) => void; kind: 'direct' | 'proxy' }) {
  const g = (m: Scored) => (kind === 'direct'
    ? { over: m.donors_over_district ?? 0, back: m.district_over_donors ?? 0, n: m.donor_district_votes ?? 0 }
    : { over: m.proxy_donors_over ?? 0, back: m.proxy_district_over ?? 0, n: m.proxy_votes ?? 0 })
  return (
    <div className="card">
      <h2>{kind === 'direct' ? 'Donors over home' : 'Fossil votes against home climate opinion'}</h2>
      <div className="sub">
        {kind === 'direct'
          ? 'Most votes cast with a funded industry against what a clear majority of their district said they wanted on that very issue. Only a handful of coded votes have a direct survey measure.'
          : 'Fossil-fuel votes cast against a district where a clear majority backed letting the EPA regulate CO2. One opinion item stands in for every vote, so read it as “the industry’s side was not the district’s general view,” not as a poll on each bill.'}
      </div>
      {rows.length === 0 && <div className="hint">Nobody meets the evidence bar with these filters.</div>}
      <ol className="hl">
        {rows.map((m, i) => {
          const x = g(m)
          return (
            <li key={m.id}>
              <button onClick={() => onOpen(m.id)}>
                <span className="rk">{i + 1}</span>
                <span className="who"><span className={`party ${m.party}`}><i />{m.party}</span> {m.name} <span className="hint">· {m.state}{m.chamber === 'Senate' ? ' Sen.' : ''}</span></span>
                <span className="val">{x.over} of {x.n}</span>
                <span className="dt">
                  Went with the industry against their district on {x.over} of {x.n} coded votes with a district view
                  {x.back > 0 ? `; with the district against the industry on ${x.back}` : ''}.
                </span>
              </button>
            </li>
          )
        })}
      </ol>
    </div>
  )
}

type SortState = { key: keyof Scored; dir: 1 | -1 }
function FullTable({ rows, sort, setSort, onOpen, limit }: { rows: Scored[]; sort: SortState; setSort: (s: SortState) => void; onOpen: (id: string) => void; limit: number }) {
  const sorted = useMemo(() => [...rows].sort((a, b) => {
    const x = a[sort.key] as number | string | null, y = b[sort.key] as number | string | null
    if (x == null) return 1
    if (y == null) return -1
    return (x > y ? 1 : x < y ? -1 : 0) * sort.dir
  }).slice(0, limit), [rows, sort, limit])
  const th = (label: string, key: keyof Scored, first = false) => (
    <th style={first ? { textAlign: 'left' } : undefined}>
      <button className="thbtn" onClick={() => setSort({ key, dir: sort.key === key ? (sort.dir === 1 ? -1 : 1) : -1 })}>{label}{sort.key === key ? (sort.dir === 1 ? ' ▲' : ' ▼') : ''}</button>
    </th>
  )
  return (
    <div className="scroll-x">
      <table className="data">
        <thead><tr>
          {th('Member', 'name', true)}{th('Voted industry’s way', 'loyalty')}{th('Funded votes', 'n_funded')}{th('Industry money', 'money_at_stake')}{th('Donors over home', 'donors_over_district')}{th('District over donors', 'district_over_donors')}{th('Against home (landmark)', 'const_rate')}{th('vs. same-party peers', 'lift')}
          <th style={{ textAlign: 'left' }}>Top donor industries</th>
        </tr></thead>
        <tbody>
          {sorted.map((m) => {
            return (
              <tr key={m.id} className="clickrow" onClick={() => onOpen(m.id)}>
                <td><span className={`party ${m.party}`}><i />{m.party}</span> {m.name} <span className="hint">· {m.state}</span></td>
                <td>{m.n_funded_aligned} of {m.n_funded}</td><td>{m.n_funded}</td><td>{fmtMoney(m.money_at_stake ?? 0)}</td>
                <td>{m.donor_district_votes ? `${m.donors_over_district} of ${m.donor_district_votes}` : '–'}</td>
                <td>{m.donor_district_votes ? m.district_over_donors : '–'}</td>
                <td>{m.const_votes ? `${m.const_against} of ${m.const_votes}` : '–'}</td>
                <td>{liftRange(m.lift, m.se)}</td>
                <td style={{ textAlign: 'left' }}>{tidyLabels(m.top_sectors)}</td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
