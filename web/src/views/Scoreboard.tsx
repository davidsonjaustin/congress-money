import { useEffect, useMemo, useState } from 'react'
import * as d3 from 'd3'
import { api } from '../api'
import type { Coverage, Scored, SectorOption, TimingRow } from '../types'
import { useWidth } from '../hooks'
import { fmtLift, fmtMoney } from '../util'

type Props = { onOpen: (id: string) => void; onMethod: () => void }

const PARTY_VAR: Record<string, string> = { D: 'var(--dem)', R: 'var(--rep)', I: 'var(--muted)' }

export default function Scoreboard({ onOpen, onMethod }: Props) {
  const [data, setData] = useState<Scored[]>([])
  const [cov, setCov] = useState<Coverage | null>(null)
  const [timing, setTiming] = useState<TimingRow[]>([])
  const [chamber, setChamber] = useState('')
  const [party, setParty] = useState('')
  const [era, setEra] = useState('')
  const [q, setQ] = useState('')
  const [showAll, setShowAll] = useState(false)
  const [mode, setMode] = useState<'beyond' | 'raw'>('beyond')
  const [variant, setVariant] = useState<'all' | 'core'>('all')
  const [sector, setSector] = useState('All business')
  const [sectors, setSectors] = useState<SectorOption[]>([])
  const [sort, setSort] = useState<{ key: keyof Scored; dir: 1 | -1 }>({ key: 'lift', dir: -1 })

  useEffect(() => {
    api.scoreboard(variant, sector).then((r) => { setData(r.members); setCov(r.coverage); setSectors(r.sectors) }).catch(() => undefined)
  }, [variant, sector])
  useEffect(() => { api.method().then((r) => setTiming(r.timing)).catch(() => undefined) }, [])

  const filtered = useMemo(() => data.filter((m) =>
    (!chamber || m.chamber === chamber) && (!party || m.party === party) && (!era || (era === 'now' ? m.last_congress === 119 : m.last_congress < 119))), [data, chamber, party, era])
  const ranked = useMemo(() => filtered.filter((m) => m.ranked && m.lift != null), [filtered])
  const loyal = useMemo(() => [...ranked].sort((a, b) => mode === 'beyond' ? (b.lift! - a.lift!) : ((b.loyalty! - a.loyalty!) || ((b.money_at_stake ?? 0) - (a.money_at_stake ?? 0)))).slice(0, 12), [ranked, mode])
  const resist = useMemo(() => [...ranked].filter((m) => (m.weight ?? 0) >= 3).sort((a, b) => mode === 'beyond' ? (a.lift! - b.lift!) : ((a.loyalty! - b.loyalty!) || ((b.money_at_stake ?? 0) - (a.money_at_stake ?? 0)))).slice(0, 12), [ranked, mode])
  const outOfStep = useMemo(() => filtered.filter((m) => (m.const_votes ?? 0) >= 4)
    .sort((a, b) => (b.const_rate! - a.const_rate!) || (b.const_lift! - a.const_lift!)).slice(0, 12), [filtered])
  const matches = useMemo(() => {
    const t = q.trim().toLowerCase()
    return t.length < 2 ? [] : data.filter((m) => m.name.toLowerCase().includes(t)).slice(0, 8)
  }, [data, q])

  const pair = (g: string) => {
    const b = timing.find((r) => r.group === g && r.spec.startsWith('Both, plus') && r.term.includes('before'))
    const a = timing.find((r) => r.group === g && r.spec.startsWith('Both, plus') && r.term.includes('after'))
    return b && a ? { b: b.effect_pts, a: a.effect_pts } : null
  }
  const findings = [['banks', 'Banks'], ['oil and gas', 'Oil and gas'], ['unions', 'Labor (unions)']].map(([lab, g]) => {
    const p = pair(g)
    return p ? { lab, ...p } : null
  }).filter((x): x is { lab: string; b: number; a: number } => !!x)

  return (
    <div className="page">
      <div className="hero">
        <h2>Who votes with their donors, and who doesn’t</h2>
        <p>
          For each member we look at votes where one industry clearly wins or loses, and check two things: did they vote the way the industry that funds them wanted,
          and did they do so more than other members of their own party would have? Members are ranked only when we have enough such votes with real money behind them.
        </p>
        <div className="findbox">
          <strong>Does money come before the votes?</strong> Percentage points more likely to vote an industry’s way per $50K it gave, in the 2 years before vs after the vote:{' '}
          {findings.map((f, i) => (
            <span key={f.lab}>{i ? '; ' : ''}<strong>{f.lab}</strong> {f.b.toFixed(0)} before vs {f.a.toFixed(0)} after</span>
          ))}
          . Where “after” is as big as “before,” the money looks like a reward for friends, not a lever on strangers; unions are the one group where “before” is clearly bigger. <button className="linkbtn" onClick={onMethod}>See the test and its limits</button>
        </div>
        {cov && (
          <div className="coverage">
            <span>This view rests on <strong>{cov.coded_votes}</strong> coded votes (of {cov.roll_calls.toLocaleString()} roll calls since 2005) and ranks <strong>{cov.ranked_members}</strong> members ·
              <strong> {cov.landmark_votes}</strong> landmark votes checked against district opinion. More coded votes sharpen every number below.</span>
          </div>
        )}
      </div>

      <div className="card filterbar">
        <div className="pills" aria-label="Which donor industry">
          {[...sectors].filter((x) => x.label === 'All business' || x.label === 'Labor' || x.members_ranked > 0).sort((a, b) => (a.label === 'All business' ? -1 : b.label === 'All business' ? 1 : b.votes - a.votes)).map((x) => (
            <button key={x.label} className="pill" aria-pressed={sector === x.label} onClick={() => setSector(x.label)} title={`${x.votes} coded votes, ${x.members_ranked} members ranked`}>
              {x.label === 'All business' ? 'All business donors' : x.label === 'Labor' ? 'Labor unions' : x.label}
              <span className="hint"> {x.votes} votes</span>
            </button>
          ))}
        </div>
        <div className="seg" title="Strictly sourced: only votes where the industry's own statements or direct reporting give the side. All coded: also includes sides taken from interest-group scorecards.">
          {[['all', 'All coded votes'], ['core', 'Strictly sourced only']].map(([k, l]) => <button key={k} aria-pressed={variant === k} onClick={() => setVariant(k as 'all' | 'core')}>{l}</button>)}
        </div>
      </div>

      <div className="card filterbar">
        <div className="seg">{[['', 'Both chambers'], ['Senate', 'Senate'], ['House', 'House']].map(([k, l]) =>
          <button key={k} aria-pressed={chamber === k} onClick={() => setChamber(k)}>{l}</button>)}</div>
        <div className="seg">{[['', 'Both parties'], ['D', 'Democrats'], ['R', 'Republicans']].map(([k, l]) =>
          <button key={k} aria-pressed={party === k} onClick={() => setParty(k)}>{l}</button>)}</div>
        <div className="seg">{[['', 'Since 2005'], ['now', 'Serving now']].map(([k, l]) =>
          <button key={k} aria-pressed={era === k} onClick={() => setEra(k)}>{l}</button>)}</div>
        <div className="seg" title="Beyond party: compared with same-party colleagues. Raw loyalty: how often they voted the donors’ way, whatever the reason.">
          {[['beyond', 'Rank: beyond party'], ['raw', 'Rank: raw loyalty']].map(([k, l]) =>
            <button key={k} aria-pressed={mode === k} onClick={() => setMode(k as 'beyond' | 'raw')}>{l}</button>)}</div>
        <div className="searchwrap">
          <input className="search" placeholder="Look up a member…" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Look up a member" />
          {matches.length > 0 && (
            <div className="suggest">{matches.map((m) => (
              <button key={m.id} onClick={() => onOpen(m.id)}><span className={`party ${m.party}`}><i />{m.party}</span> {m.name} <span className="hint">· {m.state}</span></button>
            ))}</div>
          )}
        </div>
      </div>

      <div className="card">
        <h2>Loyal to donors, or just loyal to their party?</h2>
        <div className="sub">
          Each dot is a ranked member. Left to right: how often they voted the way their funding sectors wanted. Up and down: how that compares with same-party colleagues on the same votes.
          The top right is where members vote with donors <em>more than their party peers do</em>.
        </div>
        <Scatter data={ranked} onOpen={onOpen} />
      </div>

      <div className="threecol">
        <Highlights title={mode === 'beyond' ? 'Most donor-loyal beyond their party' : 'Most often with their donors'}
          blurb={mode === 'beyond' ? 'Voted the donors’ way more than same-party colleagues did, on votes where that sector had given them money.' : 'Highest share of funded votes cast the donors’ way, whatever the reason (party-line members score high here).'}
          rows={loyal} valueOf={(m) => mode === 'beyond' ? fmtLift(m.lift) : `${m.n_funded_aligned} of ${m.n_funded}`} widthOf={(m) => mode === 'beyond' ? Math.abs(m.lift!) : m.loyalty!} tone="loyal" onOpen={onOpen} detail={donorDetail} />
        <Highlights title={mode === 'beyond' ? 'Hardest to buy' : 'Least often with their donors'}
          blurb={mode === 'beyond' ? 'Voted against the donors’ side more than same-party colleagues did, despite sector money.' : 'Lowest share of funded votes cast the donors’ way.'}
          rows={resist} valueOf={(m) => mode === 'beyond' ? fmtLift(m.lift) : `${m.n_funded_aligned} of ${m.n_funded}`} widthOf={(m) => mode === 'beyond' ? Math.abs(m.lift!) : Math.max(0.03, 1 - m.loyalty!)} tone="resist" onOpen={onOpen} detail={donorDetail} />
        <Highlights title="Most out of step with their district" blurb="Voted against what a clear majority back home said they wanted, on landmark votes." rows={outOfStep}
          valueOf={(m) => `${m.const_against} of ${m.const_votes}`} widthOf={(m) => m.const_rate!} tone="const" onOpen={onOpen} detail={constDetail} />
      </div>

      <div className="card">
        <h2>Everyone ranked ({ranked.length})</h2>
        <div className="sub">Click a column to sort and a row to open that member’s case file.</div>
        <FullTable rows={ranked} sort={sort} setSort={setSort} onOpen={onOpen} limit={showAll ? 9999 : 25} />
        {ranked.length > 25 && <button className="iconbtn" style={{ marginTop: 8 }} onClick={() => setShowAll((v) => !v)}>{showAll ? 'Show fewer' : `Show all ${ranked.length}`}</button>}
      </div>
    </div>
  )
}

function donorDetail(m: Scored): string {
  const peers = (m.peers_funded_aligned ?? 0).toFixed(1)
  return `Voted donors’ way on ${m.n_funded_aligned} of ${m.n_funded} funded votes (same-party peers: about ${peers}) · ${m.top_sectors || ''}`
}
function constDetail(m: Scored): string {
  return `${m.party === 'R' ? 'Republican' : m.party === 'D' ? 'Democrat' : 'Independent'}, ${m.state} · same-party colleagues did so on about ${((m.const_votes ?? 0) * ((m.const_rate ?? 0) - (m.const_lift ?? 0))).toFixed(1)} of those votes`
}

function Highlights({ title, blurb, rows, valueOf, widthOf, tone, onOpen, detail }: {
  title: string; blurb: string; rows: Scored[]; valueOf: (m: Scored) => string; widthOf: (m: Scored) => number
  tone: 'loyal' | 'resist' | 'const'; onOpen: (id: string) => void; detail: (m: Scored) => string
}) {
  const max = Math.max(0.0001, ...rows.map(widthOf))
  const color = tone === 'loyal' ? 'var(--s2)' : tone === 'resist' ? 'var(--s3)' : 'var(--s5)'
  return (
    <div className="card">
      <h2>{title}</h2>
      <div className="sub">{blurb}</div>
      {rows.length === 0 && <div className="hint">Nobody meets the evidence bar with these filters.</div>}
      <ol className="hl">
        {rows.map((m, i) => (
          <li key={m.id}>
            <button onClick={() => onOpen(m.id)} title={detail(m)}>
              <span className="rk">{i + 1}</span>
              <span className="who"><span className={`party ${m.party}`}><i />{m.party}</span> {m.name} <span className="hint">· {m.state}{m.chamber === 'Senate' ? ' Sen.' : ''}</span></span>
              <span className="val">{valueOf(m)}</span>
              <span className="bar"><i style={{ width: `${(100 * widthOf(m)) / max}%`, background: color }} /></span>
              <span className="dt">{detail(m)}</span>
            </button>
          </li>
        ))}
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
          {th('Member', 'name', true)}{th('Index', 'index')}{th('Beyond peers', 'lift')}{th('Voted donors’ way', 'loyalty')}{th('Funded votes', 'n_funded')}{th('Money at stake', 'money_at_stake')}{th('Against district', 'const_rate')}
          <th style={{ textAlign: 'left' }}>Top donor sectors</th>
        </tr></thead>
        <tbody>
          {sorted.map((m) => (
            <tr key={m.id} className="clickrow" onClick={() => onOpen(m.id)}>
              <td><span className={`party ${m.party}`}><i />{m.party}</span> {m.name} <span className="hint">· {m.state}</span></td>
              <td>{m.index?.toFixed(0)}</td><td>{fmtLift(m.lift)}</td>
              <td>{m.n_funded_aligned} of {m.n_funded}</td><td>{m.n_funded}</td><td>{fmtMoney(m.money_at_stake ?? 0)}</td>
              <td>{m.const_votes ? `${m.const_against} of ${m.const_votes}` : '–'}</td>
              <td style={{ textAlign: 'left' }}>{m.top_sectors}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function Scatter({ data, onOpen }: { data: Scored[]; onOpen: (id: string) => void }) {
  const [ref, width] = useWidth<HTMLDivElement>()
  const [hover, setHover] = useState<Scored | null>(null)
  const H = 420, M = { l: 58, r: 18, t: 18, b: 46 }
  const pts = useMemo(() => data.map((m) => ({ m, lx: (m.loyalty ?? 0) * 100, ly: (m.lift ?? 0) * 100 })), [data])
  const x = useMemo(() => d3.scaleLinear().domain([0, 100]).range([M.l, width - M.r]), [width])
  const ext = d3.extent(pts, (p) => p.ly) as [number, number]
  const y = useMemo(() => d3.scaleLinear().domain([Math.min(-10, (ext[0] ?? -10) - 5), Math.max(10, (ext[1] ?? 10) + 5)]).nice().range([H - M.b, M.t]), [ext[0], ext[1]])
  const delaunay = useMemo(() => d3.Delaunay.from(pts, (p) => x(p.lx), (p) => y(p.ly)), [pts, x, y])
  const labeled = useMemo(() => {
    const byLift = [...pts].sort((a, b) => b.ly - a.ly)
    const cand = [...byLift.slice(0, 6), ...byLift.slice(-6)]
    const kept: { px: number; py: number; p: (typeof pts)[number] }[] = []
    for (const p of cand) {
      const px = x(p.lx), py = y(p.ly)
      if (kept.every((k) => Math.hypot(k.px - px, k.py - py) > 70)) kept.push({ px, py, p })
    }
    return kept
  }, [pts, x, y])

  function onMove(e: React.PointerEvent<SVGRectElement>) {
    if (!pts.length) return
    const r = (e.currentTarget as SVGRectElement).getBoundingClientRect()
    const mx = e.clientX - r.left + M.l, my = e.clientY - r.top + M.t
    const i = delaunay.find(mx, my)
    const p = pts[i]
    setHover(p && Math.hypot(x(p.lx) - mx, y(p.ly) - my) < 24 ? p.m : null)
  }
  const hp = hover ? pts.find((p) => p.m.id === hover.id) : undefined
  return (
    <div className="chart" ref={ref}>
      <svg width={width} height={H} role="img" aria-label="Scatter of ranked members: share of funded votes cast the donors' way against lift over same-party peers">
        {y.ticks(6).map((t) => (
          <g key={t}>
            <line x1={M.l} x2={width - M.r} y1={y(t)} y2={y(t)} stroke={t === 0 ? 'var(--axis)' : 'var(--grid)'} />
            <text x={M.l - 8} y={y(t) + 4} textAnchor="end" fontSize={11} fill="var(--muted)">{t > 0 ? `+${t}` : t}</text>
          </g>
        ))}
        {[0, 25, 50, 75, 100].map((t) => (
          <g key={t}>
            <line x1={x(t)} x2={x(t)} y1={M.t} y2={H - M.b} stroke="var(--grid)" />
            <text x={x(t)} y={H - M.b + 16} textAnchor="middle" fontSize={11} fill="var(--muted)">{t}%</text>
          </g>
        ))}
        <text x={(M.l + width - M.r) / 2} y={H - 6} textAnchor="middle" fontSize={12} fill="var(--ink-2)">Voted the donors’ way, share of votes weighted by sector money →</text>
        <text transform={`translate(14 ${(M.t + H - M.b) / 2}) rotate(-90)`} textAnchor="middle" fontSize={12} fill="var(--ink-2)">Points above same-party peers →</text>
        <text x={width - M.r - 6} y={M.t + 12} textAnchor="end" fontSize={11} fill="var(--ink-2)">More donor-loyal than peers</text>
        <text x={width - M.r - 6} y={H - M.b - 8} textAnchor="end" fontSize={11} fill="var(--ink-2)">Loyal, but so are their peers</text>
        <text x={M.l + 6} y={H - M.b - 8} fontSize={11} fill="var(--ink-2)">Votes against donors</text>
        {pts.map((p) => (
          <circle key={p.m.id} cx={x(p.lx)} cy={y(p.ly)} r={hover?.id === p.m.id ? 6 : 4} fill={PARTY_VAR[p.m.party]} stroke="var(--surface)" strokeWidth={2} opacity={hover && hover.id !== p.m.id ? 0.45 : 0.9} />
        ))}
        {labeled.map(({ px, py, p }) => (
          <text key={p.m.id} x={px + 8} y={py + 4} fontSize={11} fill="var(--ink)">{p.m.name.split(' ').slice(-1)[0].replace(',', '')}</text>
        ))}
        <rect x={M.l} y={M.t} width={width - M.l - M.r} height={H - M.t - M.b} fill="transparent" style={{ cursor: hover ? 'pointer' : 'default' }}
          onPointerMove={onMove} onPointerLeave={() => setHover(null)} onClick={() => hover && onOpen(hover.id)} />
      </svg>
      {hover && hp && (
        <div className="tooltip" style={{ left: Math.min(Math.max(x(hp.lx) + 14, 0), width - 280), top: Math.max(0, y(hp.ly) - 70) }}>
          <div className="t-title"><span className={`party ${hover.party}`}><i />{hover.party}</span> {hover.name} · {hover.state}</div>
          <div className="t-r"><span className="n">Voted donors’ way</span><span className="v">{hover.n_funded_aligned} of {hover.n_funded}</span></div>
          <div className="t-r"><span className="n">Same-party peers would</span><span className="v">≈ {(hover.peers_funded_aligned ?? 0).toFixed(1)}</span></div>
          <div className="t-r"><span className="n">Index (50 = peers)</span><span className="v">{hover.index?.toFixed(0)}</span></div>
          <div className="t-d">{hover.top_sectors}</div>
          <div className="t-d">Click for the case file</div>
        </div>
      )}
      <div className="legend"><span><i className="dot" style={{ background: 'var(--dem)' }} />Democrat</span><span><i className="dot" style={{ background: 'var(--rep)' }} />Republican</span><span><i className="dot" style={{ background: 'var(--muted)' }} />Independent</span></div>
    </div>
  )
}
