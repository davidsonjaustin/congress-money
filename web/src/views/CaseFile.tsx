import { useEffect, useMemo, useState } from 'react'
import * as d3 from 'd3'
import { api } from '../api'
import type { Constituent, DefMember, DefState, Definitions, DonorVote, InferredVote, MemberInferred, Profile, Scored, SectorLine } from '../types'
import { useWidth } from '../hooks'
import { fmtLift, fmtMoney, industryName, liftRange, ordinal, shortName } from '../util'
import { ConstituentsCard, DonorVotesCard } from './MemberView'

type Props = { id: string; defs: Definitions; onExplore: (id: string) => void }

function verdictWord(ix: number): string {
  return ix >= 65 ? 'far more donor-loyal than' : ix >= 55 ? 'more donor-loyal than' : ix > 45 ? 'about as donor-loyal as' : ix > 35 ? 'less donor-loyal than' : 'far less donor-loyal than'
}

export default function CaseFile({ id, defs, onExplore }: Props) {
  const [me, setMe] = useState<Scored | null>(null)
  const [ranked, setRanked] = useState<Scored[]>([])
  const [profile, setProfile] = useState<Profile | null>(null)
  const [votes, setVotes] = useState<DonorVote[]>([])
  const [sectors, setSectors] = useState<SectorLine[]>([])
  const [cons, setCons] = useState<Constituent[]>([])
  const [sel, setSel] = useState('')
  const [inf, setInf] = useState<MemberInferred | null>(null)
  const [dm, setDm] = useState<DefMember | null>(null)
  const [dStates, setDStates] = useState<DefState[]>([])

  useEffect(() => { setInf(null); api.inferred(id).then(setInf).catch(() => undefined) }, [id])
  useEffect(() => {
    setDm(null)
    api.defMembers().then((r) => setDm(r.find((m) => m.bioguide === id) ?? null)).catch(() => undefined)
    api.defStates().then(setDStates).catch(() => undefined)
  }, [id])

  useEffect(() => {
    let alive = true
    Promise.all([api.scoreboard('all', 'All business'), api.profile(id), api.donorVotes(id), api.sectors(id), api.constituents(id)]).then(([b, p, v, s, c]) => {
      if (!alive) return
      setMe(b.members.find((m) => m.id === id) ?? null)
      setRanked(b.members.filter((m) => m.ranked && m.index != null))
      setProfile(p); setVotes(v); setSectors(s); setCons(c)
      const best = [...s].sort((a, b) => (b.votes >= 2 ? b.money : 0) - (a.votes >= 2 ? a.money : 0))[0]
      setSel(best ? `${best.sector}|${best.subsector}` : '')
    }).catch(() => undefined)
    return () => { alive = false }
  }, [id])

  const pctile = useMemo(() => (me?.index != null && ranked.length ? Math.round((100 * ranked.filter((m) => m.index! < me.index!).length) / ranked.length) : null), [me, ranked])
  const donors = useMemo(() => {
    if (!profile) return []
    const acc = new Map<string, number>()
    for (const r of profile.money_totals) {
      if (r.source !== 'pac_direct') continue
      const c = defs.category[r.sector]
      if (c !== 'industry' && c !== 'labor') continue
      acc.set(r.sector, (acc.get(r.sector) ?? 0) + r.amount)
    }
    return [...acc.entries()].filter(([s]) => s !== 'Business (sector not yet assigned)' && s !== 'General Business Associations').sort((a, b) => b[1] - a[1]).slice(0, 6)
  }, [profile, defs])

  if (!profile) return <div className="card hint">Loading…</div>
  const last = profile.terms[profile.terms.length - 1]
  const party = last.party_code === 100 ? 'D' : last.party_code === 200 ? 'R' : 'I'
  const isRanked = !!me?.ranked && me.index != null
  const selLine = sectors.find((s) => `${s.sector}|${s.subsector}` === sel)
  const selVotes = votes.filter((v) => `${v.sector}|${v.subsector}` === sel)
  const donorMax = donors[0]?.[1] ?? 1
  const story = buildStory({ name: profile.name, me, sectors, votes })
  const who = shortName(profile.name, last.chamber)
  const everyAll = inf?.summary.find((x) => x.label === 'All business') ?? null
  const headline = isRanked && me!.lift != null
    ? { lift: me!.lift, se: me!.se, source: 'industry side documented' }
    : everyAll && everyAll.lift != null ? { lift: everyAll.lift, se: everyAll.se, source: 'every vote since 2008' } : null

  return (
    <div className="page">
      <div className="card head">
        <img className="photo" alt="" src={`https://bioguide.congress.gov/bioguide/photo/${id[0]}/${id}.jpg`} onError={(e) => { (e.currentTarget as HTMLImageElement).style.visibility = 'hidden' }} />
        <div style={{ flex: 1 }}>
          <h2>{profile.name}</h2>
          <div className="sub">
            <span className={`party ${party}`}><i />{party === 'D' ? 'Democrat' : party === 'R' ? 'Republican' : 'Independent'}</span>
            {' · '}{last.chamber === 'Senate' ? `Senator, ${last.state}` : `Representative, ${last.state}${last.district ? `-${last.district}` : ''}`}{' · '}
            {ordinal(profile.terms[0].congress)}–{ordinal(last.congress)} Congress
          </div>
        </div>
        <button className="iconbtn" onClick={() => onExplore(id)}>Explore all their money and votes →</button>
      </div>

      <div className="card verdict">
        <div className="vleft">
          {headline ? (
            <>
              <div className="vtier" style={{ borderColor: headline.lift >= 0 ? 'var(--s2)' : 'var(--s3)' }}>{fmtLift(headline.lift)}</div>
              <div className="vlbl">{headline.lift >= 0 ? 'more often' : 'less often'} than same-party colleagues have voted with the industries funding them</div>
              <div className="vrange">{liftRange(headline.lift, headline.se)} · {headline.source}</div>
            </>
          ) : (
            <div className="vtier" style={{ borderColor: 'var(--muted)' }}>Not ranked yet</div>
          )}
        </div>
        <div className="vright">
          {headline ? (
            <>
              <p className="lead">
                Two ways of asking the same question for {who}. Each counts votes where an industry had given $10K or more in PAC money in the prior six years, and compares how often the vote went the industry’s way with how often
                same-party colleagues with the same ideology and district would be expected to. A small gap does not clear a member: their whole party may be funded by the same industries.
              </p>
              <div className="scroll-x">
                <table className="data">
                  <thead><tr><th style={{ textAlign: 'left' }}>Measure</th><th>Funded votes</th><th>Voted its way</th><th>Colleagues would</th><th>Gap (90% range)</th></tr></thead>
                  <tbody>
                    {isRanked && me && (
                      <tr>
                        <td style={{ textAlign: 'left' }}>Industry’s side documented<div className="hint">from its own statements, scorecards or the spending rule</div></td>
                        <td>{me.n_funded}</td><td>{me.n_funded_aligned}</td><td>{(me.peers_funded_aligned ?? 0).toFixed(1)}</td>
                        <td>{liftRange(me.lift, me.se)}{Math.abs(me.z ?? 0) < 1.5 ? <div className="hint">small enough that chance could explain it</div> : null}</td>
                      </tr>
                    )}
                    {everyAll && (
                      <tr>
                        <td style={{ textAlign: 'left' }}>Every vote since 2008<div className="hint">side inferred from where the money pulls</div></td>
                        <td>{everyAll.n_funded}</td><td>{everyAll.n_funded_aligned}</td><td>{everyAll.expected.toFixed(1)}</td>
                        <td>{liftRange(everyAll.lift, everyAll.se)}</td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            </>
          ) : (
            <p className="lead">
              {me?.votes_coded ? `Only ${me.votes_coded} vote(s) with a documented industry side and not enough sector money behind them to rank.` : 'No vote with a documented industry side involves this member.'} Rankings need at least about three such votes with real money behind them.
            </p>
          )}
          {story.length > 0 && <div className="story">{story.map((p, i) => <p key={i}>{p}</p>)}</div>}
        </div>
      </div>

      <IndustryTable sectors={sectors} inf={inf} />
      {inf && <EveryVoteCard inf={inf} />}
      {dm && ((dm.pac_all ?? 0) >= 25000 || dm.n >= 5) && <DefenseCard m={dm} states={dStates} />}

      {donors.length > 0 && (
        <div className="card">
          <h2>Who funds them</h2>
          <div className="sub">Direct PAC gifts by industry, 2005 to now (individual donors and outside spending are in the explorer).</div>
          <div className="bars">
            {donors.map(([sec, amt]) => (
              <div key={sec} className="hrow"><span className="nm">{sec}</span><span className="track"><i style={{ width: `${(100 * amt) / donorMax}%` }} /></span><span className="amt">{fmtMoney(amt)}</span></div>
            ))}
          </div>
        </div>
      )}

      {sectors.length > 0 && (
        <div className="card">
          <h2>Money, then votes</h2>
          <div className="sub">
            The line is how much the chosen sector’s PACs gave this member over the trailing six years. Each dot is a vote where that sector had a clear side:
            <b style={{ color: 'var(--ink)' }}> orange</b> = voted the donors’ way, <b style={{ color: 'var(--ink)' }}>green</b> = voted against them.
          </div>
          <div className="pills">
            {sectors.map((s) => {
              const k = `${s.sector}|${s.subsector}`
              return <button key={k} className="pill" aria-pressed={sel === k} onClick={() => setSel(k)}>{s.label} <span className="hint">{s.n_aligned}/{s.n_funded} · {fmtMoney(s.money)}</span></button>
            })}
          </div>
          {selLine && <BeforeAfter line={selLine} votes={selVotes} />}
        </div>
      )}

      {votes.length > 0 && <DonorVotesCard rows={votes} />}
      {cons.length > 0 && <ConstituentsCard rows={cons} />}
    </div>
  )
}

function BeforeAfter({ line, votes }: { line: SectorLine; votes: DonorVote[] }) {
  const [ref, width] = useWidth<HTMLDivElement>()
  const [hover, setHover] = useState<DonorVote | null>(null)
  const H = 250, M = { l: 56, r: 16, t: 14, b: 28 }
  const monthly = useMemo(() => {
    const map = new Map(line.series.map(([m, a]) => [m, a]))
    const out: { d: Date; v: number }[] = []
    for (let y = 2005; y <= 2026; y++) {
      for (let mo = 1; mo <= 12; mo++) {
        if (y === 2026 && mo > 10) break
        let sum = 0
        for (let k = 0; k < 72; k++) {
          const t = new Date(y, mo - 1 - k, 1)
          sum += map.get(`${t.getFullYear()}-${String(t.getMonth() + 1).padStart(2, '0')}`) ?? 0
        }
        out.push({ d: new Date(y, mo - 1, 1), v: Math.max(0, sum) })
      }
    }
    return out
  }, [line])
  const x = useMemo(() => d3.scaleTime().domain([new Date(2005, 0, 1), new Date(2026, 9, 1)]).range([M.l, width - M.r]), [width])
  const y = useMemo(() => d3.scaleLinear().domain([0, Math.max(10000, d3.max(monthly, (p) => p.v) ?? 0)]).nice().range([H - M.b, M.t]), [monthly])
  const path = d3.area<{ d: Date; v: number }>().x((p) => x(p.d)).y0(H - M.b).y1((p) => y(p.v)).curve(d3.curveStepAfter)(monthly) ?? ''
  const topLine = d3.line<{ d: Date; v: number }>().x((p) => x(p.d)).y((p) => y(p.v)).curve(d3.curveStepAfter)(monthly) ?? ''
  const at = (d: Date) => { let v = 0; for (const p of monthly) { if (p.d <= d) v = p.v; else break } return v }
  const pts = votes.map((v) => ({ v, px: x(new Date(v.d + 'T12:00:00')), py: y(at(new Date(v.d + 'T12:00:00'))) }))
  const lo = votes.filter((v) => v.pac_6y < 25000), hi = votes.filter((v) => v.pac_6y >= 25000)
  const cnt = (a: DonorVote[]) => (a.length ? `${a.filter((v) => v.aligned === 1).length} of ${a.length}` : 'no votes in this range')

  return (
    <div className="chart" ref={ref}>
      <svg width={width} height={H} role="img" aria-label={`${line.label} PAC money over time with each coded vote marked`}>
        {y.ticks(4).map((t) => (
          <g key={t}><line x1={M.l} x2={width - M.r} y1={y(t)} y2={y(t)} stroke="var(--grid)" /><text x={M.l - 8} y={y(t) + 4} textAnchor="end" fontSize={11} fill="var(--muted)">{fmtMoney(t)}</text></g>
        ))}
        {x.ticks(8).map((t) => <text key={+t} x={x(t)} y={H - 8} textAnchor="middle" fontSize={11} fill="var(--muted)">{t.getFullYear()}</text>)}
        <line x1={M.l} x2={width - M.r} y1={H - M.b} y2={H - M.b} stroke="var(--axis)" />
        <path d={path} fill="var(--s1)" opacity={0.12} />
        <path d={topLine} fill="none" stroke="var(--s1)" strokeWidth={2} strokeLinejoin="round" />
        {pts.map((p) => (
          <circle key={`${p.v.congress}-${p.v.chamber}-${p.v.rn}`} cx={p.px} cy={p.py} r={hover === p.v ? 7 : 5} fill={p.v.aligned ? 'var(--s2)' : 'var(--s3)'} stroke="var(--surface)" strokeWidth={2}
            onPointerEnter={() => setHover(p.v)} onPointerLeave={() => setHover(null)} />
        ))}
        <text x={M.l} y={10} fontSize={11} fill="var(--muted)">PAC gifts from {line.label}, trailing 6 years</text>
      </svg>
      {hover && (
        <div className="tooltip" style={{ left: Math.min(Math.max(x(new Date(hover.d + 'T12:00:00')) + 12, 0), width - 300), top: 20 }}>
          <div className="t-h">{hover.d} · {hover.chamber}</div>
          <div className="t-title">{hover.bill} · {(hover.desc || hover.q || '').slice(0, 70)}</div>
          <div className="t-r"><span className="n">Donors wanted</span><span className="v">{hover.helps_vote}</span></div>
          <div className="t-r"><span className="n">Member voted</span><span className="v">{hover.yea ? 'Yea' : 'Nay'} ({hover.aligned ? 'with donors' : 'against donors'})</span></div>
          <div className="t-r"><span className="n">Sector money (6 yrs)</span><span className="v">{fmtMoney(hover.pac_6y)}</span></div>
        </div>
      )}
      <div className="legend">
        <span><i className="dot" style={{ background: 'var(--s2)' }} />Voted the donors’ way</span><span><i className="dot" style={{ background: 'var(--s3)' }} />Voted against the donors</span>
      </div>
      <div className="note-box">
        When this sector had given less than $25K: voted the donors’ way on <strong>{cnt(lo)}</strong> votes. When it had given $25K or more: <strong>{cnt(hi)}</strong>.
        {Math.min(lo.length, hi.length) < 3 ? ' Too few votes in one group to read much into the difference.' : ''}
      </div>
    </div>
  )
}

function buildStory(a: { name: string; me: Scored | null; sectors: SectorLine[]; votes: DonorVote[] }): string[] {
  const out: string[] = []
  const ex = a.votes.filter((v) => v.district_match === 'direct' && v.aligned === 1 && v.with_district === 0).sort((x, y) => y.pac_6y - x.pac_6y).slice(0, 3)
  if (ex.length) out.push(`Votes with the industry against what a clear majority at home wanted include: ${ex.map((v) => `${(v.desc || v.q || v.bill || '').slice(0, 55)} (${v.d.slice(0, 4)}, ${fmtMoney(v.pac_6y)} from the industry)`).join('; ')}.`)
  const rev = a.votes.filter((v) => v.district_match === 'direct' && v.aligned === 0 && v.with_district === 1 && v.pac_6y >= 25000).sort((x, y) => y.pac_6y - x.pac_6y).slice(0, 2)
  if (rev.length) out.push(`Votes against a funding industry, with their district, despite its money include: ${rev.map((v) => `${(v.desc || v.q || v.bill || '').slice(0, 55)} (${v.d.slice(0, 4)}, ${fmtMoney(v.pac_6y)} from the industry)`).join('; ')}.`)
  return out
}

/** One row per industry: money, then how the member voted on the documented-side votes and on the every-vote set, each next to what politics predicts. */
function IndustryTable({ sectors, inf }: { sectors: SectorLine[]; inf: MemberInferred | null }) {
  const doc = new Map(sectors.map((s) => [s.label, s]))
  const evr = new Map((inf?.summary ?? []).filter((s) => s.label !== 'All business').map((s) => [s.label, s]))
  const labels = [...new Set([...doc.keys(), ...evr.keys()])]
    .map((l) => ({ l, d: doc.get(l), e: evr.get(l) }))
    .filter((r) => (r.d?.n_funded ?? 0) >= 3 || (r.e?.n_funded ?? 0) >= 5)
    .map((r) => ({ ...r, money: Math.max(r.d?.money ?? 0, r.e?.money ?? 0) }))
    .sort((x, y) => y.money - x.money)
    .slice(0, 10)
  if (labels.length === 0) return null
  const cell = (n: number | undefined, of: number | undefined, exp: number | undefined) => (of ? <>{n} of {of}<div className="hint">colleagues would: {(exp ?? 0).toFixed(0)}</div></> : '–')
  return (
    <div className="card">
      <h2>Industry by industry</h2>
      <div className="sub">PAC money is the most the industry gave this member in any six-year window. “Colleagues would” is how many of those votes same-party colleagues with the same ideology and district would be expected to cast the industry’s way.</div>
      <div className="scroll-x">
        <table className="data">
          <thead><tr><th style={{ textAlign: 'left' }}>Industry</th><th>PAC money, most in any 6 years</th><th>Documented side: voted its way</th><th>Every vote: voted with the money</th></tr></thead>
          <tbody>
            {labels.map((r) => (
              <tr key={r.l}>
                <td style={{ textAlign: 'left' }}>{industryName(r.l)}</td>
                <td>{fmtMoney(r.money)}</td>
                <td>{cell(r.d?.n_aligned, r.d?.n_funded, r.d?.peers_aligned)}</td>
                <td>{cell(r.e?.n_funded_aligned, r.e?.n_funded, r.e?.expected)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function voteTitle(v: InferredVote): string {
  return (v.descr || v.q || v.bill || 'Vote').slice(0, 110)
}

function EveryVoteCard({ inf }: { inf: MemberInferred }) {
  const list = (title: string, blurb: string, rows: InferredVote[]) => rows.length > 0 && (
    <div>
      <div className="fh">{title}</div>
      <div className="hint">{blurb}</div>
      <ul className="facts">
        {rows.map((v) => (
          <li key={`${v.congress}${v.chamber}${v.rollnumber}${v.label}`}>
            {voteTitle(v)} <span className="hint">({v.d?.slice(0, 4)}, {v.chamber}{v.bill ? `, ${v.bill}` : ''})</span>: {industryName(v.label)} had given {fmtMoney(v.pac_6y)}; ideology and district alone put the chance of voting that way at {Math.round(100 * v.p_exp)}%.
          </li>
        ))}
      </ul>
    </div>
  )
  if (inf.with_money.length === 0 && inf.against_money.length === 0) return null
  return (
    <div className="card">
      <h2>Votes that stand out</h2>
      <div className="sub">
        Among votes the industry lobbied or whose side is documented, and where its money lined up with the vote, these are the ones where the member’s vote was least or most expected from their ideology and district.
        Where the side is inferred from the money pattern it is not stated by the industry. Procedural votes are left out.
      </div>
      <div className="threecol" style={{ marginTop: 12 }}>
        {list('Voted with the money, against their profile', 'Industry gave $25K or more, and ideology and district made this vote unlikely.', inf.with_money)}
        {list('Voted against the money, despite it', 'Industry gave $25K or more, and ideology and district made voting with it likely.', inf.against_money)}
      </div>
    </div>
  )
}

function DefenseCard({ m, states }: { m: DefMember; states: DefState[] }) {
  const rank = m.state_pc != null ? states.filter((s) => s.pop > 0 && s.per_capita > m.state_pc!).length + 1 : null
  return (
    <div className="card">
      <h2>Defense: money, votes and contracts at home</h2>
      <ul className="facts">
        <li>Defense industry PAC gifts over their career in our data: <strong>{m.pac_all ? fmtMoney(m.pac_all) : '$0'}</strong>{m.ind_all ? `; itemized gifts from defense-company employees: ${fmtMoney(m.ind_all)}` : ''}.</li>
        {m.n > 0 && <li>Voted the industry’s side on <strong>{m.aligned} of {m.n}</strong> documented defense votes (NDAA and defense appropriations passage since 2008, plus Pentagon and weapons spending amendments and arms-sale resolutions, 2013 to 2024).</li>}
        {m.state_pc != null && <li>DoD contract dollars performed in {m.state}: <strong>${Math.round(m.state_pc).toLocaleString()}</strong> per resident per year{rank ? `, ${rank}${rank % 10 === 1 && rank !== 11 ? 'st' : rank % 10 === 2 && rank !== 12 ? 'nd' : rank % 10 === 3 && rank !== 13 ? 'rd' : 'th'} highest among states and DC` : ''}.</li>}
        {m.district_dod != null && <li>In their House district: <strong>{fmtMoney(m.district_dod)}</strong> a year in DoD prime contracts (approximate district boundaries).</li>}
      </ul>
      <div className="hint">Contracts at home are a local reason to back defense spending that is separate from donations. The defense page shows how votes, money and local contracts line up across members.</div>
    </div>
  )
}
