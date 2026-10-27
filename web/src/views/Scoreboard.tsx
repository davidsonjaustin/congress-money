import { useEffect, useMemo, useState } from 'react'
import { api } from '../api'
import type { Coverage, MethodData, Scored, SectorOption } from '../types'
import Scatter from '../charts/Scatter'
import { fmtMoney, liftRange } from '../util'

type Props = { onOpen: (id: string) => void; onMethod: () => void }

const pct = (v: number) => `${v >= 0 ? '+' : '−'}${Math.abs(v * 100).toFixed(0)}%`
const pts = (v: number) => `${v >= 0 ? '+' : '−'}${Math.abs(v).toFixed(1)}`

export default function Scoreboard({ onOpen, onMethod }: Props) {
  const [data, setData] = useState<Scored[]>([])
  const [cov, setCov] = useState<Coverage | null>(null)
  const [method, setMethod] = useState<MethodData | null>(null)
  const [chamber, setChamber] = useState('')
  const [party, setParty] = useState('')
  const [era, setEra] = useState('')
  const [q, setQ] = useState('')
  const [showAll, setShowAll] = useState(false)
  const [variant, setVariant] = useState<'all' | 'core' | 'inferred' | 'lobbied'>('lobbied')
  const [sector, setSector] = useState('All business')
  const [sectors, setSectors] = useState<SectorOption[]>([])
  const [sort, setSort] = useState<{ key: keyof Scored; dir: 1 | -1 }>({ key: 'loyalty', dir: -1 })

  useEffect(() => {
    api.scoreboard(variant, sector).then((r) => { setData(r.members); setCov(r.coverage); setSectors(r.sectors) }).catch(() => undefined)
  }, [variant, sector])
  useEffect(() => { api.method().then(setMethod).catch(() => undefined) }, [])

  const filtered = useMemo(() => data.filter((m) =>
    (!chamber || m.chamber === chamber) && (!party || m.party === party) && (!era || (era === 'now' ? m.last_congress === 119 : m.last_congress < 119))), [data, chamber, party, era])
  const ranked = useMemo(() => filtered.filter((m) => m.ranked && m.lift != null), [filtered])
  const loyal = useMemo(() => [...ranked].sort((a, b) => (b.loyalty! - a.loyalty!) || ((b.money_at_stake ?? 0) - (a.money_at_stake ?? 0))).slice(0, 10), [ranked])
  const resist = useMemo(() => [...ranked].filter((m) => (m.weight ?? 0) >= 3).sort((a, b) => (a.loyalty! - b.loyalty!) || ((b.money_at_stake ?? 0) - (a.money_at_stake ?? 0))).slice(0, 10), [ranked])
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
        <p>
          Pick an industry. For every vote where that industry clearly won or lost, we show how often each member voted its way, how much that industry’s PACs had given them,
          and whether they did it against what their own district wanted. Patterns, not proof: a vote that matches the donors may also be what the member believes.
        </p>
        {cov && <p className="hint">Coded so far: an industry side for <strong>{cov.coded_since_2008.toLocaleString()}</strong> of the <strong>{cov.votes_since_2008.toLocaleString()}</strong> roll call votes since 2008 ({(100 * cov.coded_since_2008 / cov.votes_since_2008).toFixed(1)}%). Coverage is uneven: oil, gas, coal and labor are well covered; banks, pharma, tech, farming and defense are thin or missing.</p>}
        {method && <Findings method={method} board={data} onMethod={onMethod} />}
      </div>

      <div className="card filterbar">
        <div className="pills" aria-label="Which industry">
          {pillSectors.map((x) => (
            <button key={x.label} className="pill" aria-pressed={sector === x.label} onClick={() => setSector(x.label)} title={`${x.votes} coded votes, ${x.members_ranked} members ranked`}>
              {x.label === 'All business' ? 'All business' : x.label === 'Labor' ? 'Labor unions' : x.label.replace(/^./, (c) => c.toUpperCase())}
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
        {(variant === 'inferred' || variant === 'lobbied') && <div className="coverage">{variant === 'lobbied' ? 'Lobbied votes: only votes on bills this industry’s own lobbyists named in Senate filings (2008 to 2024; 2025 on not yet loaded). ' : ''}Every-vote view: a vote counts for an industry when its money lines up strongly with how members voted, and the industry’s side is the side that money pulls toward. That side is inferred from the money pattern, not stated by the industry, so use this to find leads and check the case file.</div>}
        {cov && <div className="coverage">This view: <strong>{cov.coded_votes}</strong> coded votes · <strong>{cov.ranked_members}</strong> members ranked · {cov.landmark_votes} landmark votes checked against district opinion.</div>}
      </div>

      <div className="threecol">
        <OverHome rows={overHome} onOpen={onOpen} kind="direct" />
        <OverHome rows={overHomeProxy} onOpen={onOpen} kind="proxy" />
        <Highlights title="Most often with their donors" blurb="Highest share of money-backed votes cast the industry’s way, weighted by how much it had given."
          rows={loyal} onOpen={onOpen} inferred={variant === 'inferred' || variant === 'lobbied'} />
        <Highlights title="Took the money, voted the other way" blurb="Lowest share of money-backed votes cast the industry’s way. These members were funded by the industry and still went against it."
          rows={resist} onOpen={onOpen} inferred={variant === 'inferred' || variant === 'lobbied'} />
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
      <div className="flink"><button className="linkbtn" onClick={onMethod}>How we tested this, and what it can’t show</button></div>
    </div>
  )
}

function Highlights({ title, blurb, rows, onOpen, inferred }: { title: string; blurb: string; rows: Scored[]; onOpen: (id: string) => void; inferred: boolean }) {
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
              <span className="val">{m.n_funded_aligned} of {m.n_funded}</span>
              <span className="dt">
                Voted {inferred ? 'the way its money pulls' : 'the industry’s way'} {m.n_funded_aligned} of {m.n_funded} times while it had given $10K or more
                {m.money_at_stake ? `; ${fmtMoney(m.money_at_stake)} from ${m.top_sectors || 'these industries'}` : ''}.
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
                <td style={{ textAlign: 'left' }}>{m.top_sectors}</td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
