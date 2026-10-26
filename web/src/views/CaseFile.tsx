import { useEffect, useMemo, useState } from 'react'
import * as d3 from 'd3'
import { api } from '../api'
import type { Constituent, Definitions, DonorVote, InferredVote, MemberInferred, Profile, Scored, SectorLine } from '../types'
import { useWidth } from '../hooks'
import { fmtLift, fmtMoney, liftRange, ordinal } from '../util'
import { ConstituentsCard, DonorVotesCard } from './MemberView'

type Props = { id: string; defs: Definitions; onExplore: (id: string) => void }

function verdictWord(ix: number): string {
  return ix >= 65 ? 'far more donor-loyal than' : ix >= 55 ? 'more donor-loyal than' : ix > 45 ? 'about as donor-loyal as' : ix > 35 ? 'less donor-loyal than' : 'far less donor-loyal than'
}

export default function CaseFile({ id, defs, onExplore }: Props) {
  const [me, setMe] = useState<Scored | null>(null)
  const [labor, setLabor] = useState<Scored | null>(null)
  const [ranked, setRanked] = useState<Scored[]>([])
  const [profile, setProfile] = useState<Profile | null>(null)
  const [votes, setVotes] = useState<DonorVote[]>([])
  const [sectors, setSectors] = useState<SectorLine[]>([])
  const [cons, setCons] = useState<Constituent[]>([])
  const [sel, setSel] = useState('')
  const [inf, setInf] = useState<MemberInferred | null>(null)

  useEffect(() => { setInf(null); api.inferred(id).then(setInf).catch(() => undefined) }, [id])

  useEffect(() => {
    let alive = true
    Promise.all([api.scoreboard('all', 'All business'), api.profile(id), api.donorVotes(id), api.sectors(id), api.constituents(id), api.scoreboard('all', 'Labor')]).then(([b, p, v, s, c, lb]) => {
      if (!alive) return
      setMe(b.members.find((m) => m.id === id) ?? null)
      setLabor(lb.members.find((m) => m.id === id) ?? null)
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
          {isRanked ? (
            <>
              <div className="vtier" style={{ borderColor: 'var(--s2)' }}>{me!.n_funded_aligned} of {me!.n_funded}</div>
              <div className="vlbl">money-backed votes cast the industry’s way</div>
              <div className="vrange">{fmtMoney(me!.money_at_stake ?? 0)} from {me!.top_sectors || 'these industries'}</div>
            </>
          ) : (
            <div className="vtier" style={{ borderColor: 'var(--muted)' }}>Not ranked yet</div>
          )}
        </div>
        <div className="vright">
          {story.length > 0 && <div className="story">{story.map((p, i) => <p key={i}>{p}</p>)}</div>}
          {isRanked ? (
            <>
              <p className="lead">
                On votes where a business sector clearly won or lost and had given {profile.name.split(' ')[0]} $10K or more in the prior six years, they voted its way{' '}
                <strong>{me!.n_funded_aligned} of {me!.n_funded}</strong> times.
              </p>
              <ul className="facts">
                <li>Check, is it just their politics? Same-party colleagues with the same ideology and district would be expected to vote the industries’ way on about <strong>{(me!.peers_funded_aligned ?? 0).toFixed(1)}</strong> of those. The gap is <strong>{liftRange(me!.lift, me!.se)}</strong>{Math.abs(me!.z ?? 0) < 1.5 ? ' (small enough that chance could explain it)' : ''}. A small gap does not clear a member: their whole party may be funded by the same industries.</li>
                {labor?.ranked && labor.index != null ? <li>Labor unions: voted the unions’ way on <strong>{labor.n_funded_aligned} of {labor.n_funded}</strong> votes where union PACs had given $10K or more; same-party peers would be expected to on about <strong>{(labor.peers_funded_aligned ?? 0).toFixed(1)}</strong> (labor index <strong>{labor.index.toFixed(0)}</strong>).</li> : null}
                {me!.const_votes ? <li>On {me!.const_votes} landmark votes with a clear district majority, voted <strong>against</strong> that majority {me!.const_against} times{(me!.donors_over_district ?? 0) + (me!.district_over_donors ?? 0) > 0 ? `; sided with donors over the district ${me!.donors_over_district} time(s) and with the district over donors ${me!.district_over_donors}` : ''}.</li> : null}
              </ul>
            </>
          ) : (
            <p className="lead">
              {me?.votes_coded ? `Only ${me.votes_coded} coded vote(s) and not enough sector money behind them to rank.` : 'None of the votes coded so far involved this member.'} Rankings need at least about three votes where a funding sector had given real money. More coded votes will change this.
              {me?.const_votes ? ` On ${me.const_votes} landmark votes with a clear district majority, they went against it ${me.const_against} times.` : ''}
              {labor?.ranked && labor.index != null ? ` Labor unions: voted the unions’ way on ${labor.n_funded_aligned} of ${labor.n_funded} votes where union PACs had given $10K or more (labor index ${labor.index.toFixed(0)}).` : ''}
            </p>
          )}
        </div>
      </div>

      {inf && inf.summary.length > 0 && <EveryVoteCard inf={inf} name={profile.name} />}

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
  const first = a.name.split(' ')[0]
  const out: string[] = []
  const lines = a.sectors.filter((s) => s.n_funded >= 3).sort((x, y) => y.money - x.money)
  for (const s of lines.slice(0, 2)) {
    out.push(`The ${s.label} industry had given ${first} ${fmtMoney(s.money)} in PAC money; on ${s.n_funded} votes where it had given $10K or more and had a clear side, ${first} voted its way ${s.n_aligned} times.`)
  }
  const ex = a.votes.filter((v) => v.district_match === 'direct' && v.aligned === 1 && v.with_district === 0).sort((x, y) => y.pac_6y - x.pac_6y).slice(0, 3)
  if (ex.length) out.push(`Votes with the industry against what a clear majority at home wanted include: ${ex.map((v) => `${(v.desc || v.q || v.bill || '').slice(0, 55)} (${v.d.slice(0, 4)}, ${fmtMoney(v.pac_6y)} from the industry)`).join('; ')}.`)
  const rev = a.votes.filter((v) => v.district_match === 'direct' && v.aligned === 0 && v.with_district === 1 && v.pac_6y >= 25000).sort((x, y) => y.pac_6y - x.pac_6y).slice(0, 2)
  if (rev.length) out.push(`Votes against a funding industry, with their district, despite its money include: ${rev.map((v) => `${(v.desc || v.q || v.bill || '').slice(0, 55)} (${v.d.slice(0, 4)}, ${fmtMoney(v.pac_6y)} from the industry)`).join('; ')}.`)
  const px = a.votes.filter((v) => v.district_match === 'proxy' && v.district_view === 'supports')
  if (px.length >= 5) {
    const pAgainst = px.filter((v) => v.aligned === 1 && v.with_district === 0).length
    out.push(`On ${px.length} fossil votes, a clear majority in ${first}’s district backed letting the EPA regulate CO2 (a general stand-in, not a poll on each bill). ${first} sided with the industry against that view on ${pAgainst} of them.`)
  }
  const top = [...a.sectors].sort((x, y) => y.votes - x.votes)[0]
  if (top) {
    const sv = a.votes.filter((v) => v.sector === top.sector && v.subsector === top.subsector)
    const lo = sv.filter((v) => v.pac_6y < 25000), hi = sv.filter((v) => v.pac_6y >= 25000)
    if (lo.length >= 3 && hi.length >= 3) {
      const c = (x: DonorVote[]) => `${x.filter((v) => v.aligned === 1).length} of ${x.length}`
      out.push(`Before the ${top.label} industry had given $25K, ${first} voted its way ${c(lo)} times; once it had, ${c(hi)}.`)
    }
  }
  return out
}

function voteTitle(v: InferredVote): string {
  return (v.descr || v.q || v.bill || 'Vote').slice(0, 110)
}

function EveryVoteCard({ inf, name }: { inf: MemberInferred; name: string }) {
  const first = name.split(' ')[0]
  const all = inf.summary.find((s) => s.label === 'All business')
  const lines = inf.summary.filter((s) => s.label !== 'All business' && s.n_funded >= 5).slice(0, 8)
  const nice = (l: string) => (l === 'Labor' ? 'Labor unions' : l === 'oil gas' ? 'Oil and gas' : l.replace(/^./, (c) => c.toUpperCase()))
  const list = (title: string, blurb: string, rows: InferredVote[]) => rows.length > 0 && (
    <div>
      <div className="fh">{title}</div>
      <div className="hint">{blurb}</div>
      <ul className="facts">
        {rows.map((v) => (
          <li key={`${v.congress}${v.chamber}${v.rollnumber}${v.label}`}>
            {voteTitle(v)} <span className="hint">({v.d?.slice(0, 4)}, {v.chamber}{v.bill ? `, ${v.bill}` : ''})</span>: {nice(v.label)} industry had given {fmtMoney(v.pac_6y)}; ideology and district alone put the chance of voting that way at {Math.round(100 * v.p_exp)}%.
          </li>
        ))}
      </ul>
    </div>
  )
  return (
    <div className="card">
      <h2>Every vote since 2008</h2>
      <div className="sub">
        Votes where an industry’s money lined up strongly with how members voted, taking the side that money pulls toward. That side is inferred from the money pattern, not stated by the industry.
      </div>
      {all && (
        <p className="lead">
          On <strong>{all.n_funded}</strong> such votes where a business industry had given {first} $10K or more, they voted the way the money pulls <strong>{all.n_funded_aligned}</strong> times.
          Their ideology, party and district alone would predict about <strong>{all.expected.toFixed(0)}</strong>. Gap: <strong>{liftRange(all.lift, all.se)}</strong>.
        </p>
      )}
      {lines.length > 0 && (
        <div className="scroll-x">
          <table className="data">
            <thead><tr><th style={{ textAlign: 'left' }}>Industry</th><th>Money, 6-year peak</th><th>Voted with the money</th><th>Predicted by ideology and district</th></tr></thead>
            <tbody>
              {lines.map((s) => (
                <tr key={s.label}><td style={{ textAlign: 'left' }}>{nice(s.label)}</td><td>{fmtMoney(s.money)}</td><td>{s.n_funded_aligned} of {s.n_funded}</td><td>{s.expected.toFixed(0)}</td></tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <div className="threecol" style={{ marginTop: 12 }}>
        {list('Voted with the money against their profile', 'Industry gave $25K or more, and ideology and district made this vote unlikely.', inf.with_money)}
        {list('Voted against the money despite it', 'Industry gave $25K or more, and ideology and district made voting with it likely.', inf.against_money)}
      </div>
    </div>
  )
}
