import { useEffect, useMemo, useState } from 'react'
import * as d3 from 'd3'
import { api } from '../api'
import type { Constituent, Definitions, DonorVote, MoneyRow, Profile, Vote } from '../types'
import { CATEGORY_LABEL, ITEM_LABEL, SECTOR_SLOT, SOURCES, fmtMoney, fmtPct, ordinal } from '../util'
import { useWidth } from '../hooks'
import MoneyChart, { MARGIN } from '../charts/MoneyChart'
import type { Band, Bucket, Series } from '../charts/MoneyChart'
import VoteStrip from '../charts/VoteStrip'

type Gran = 'month' | 'quarter' | 'year'
type VoteFilter = 'unity_against' | 'all' | 'surprising' | 'relevant_strict' | 'relevant_broad'
const PRESETS: [string, string][] = [['all', 'All years'], ['2015', 'Since 2015'], ['2020', 'Since 2020'], ['2y', 'Last 2 years']]
const NO_FOCUS_SECTORS = new Set(['Business (sector not yet assigned)', 'General Business Associations'])
const isoDay = d3.timeFormat('%Y-%m-%d')

export default function MemberView({ id, defs }: { id: string; defs: Definitions }) {
  const [profile, setProfile] = useState<Profile | null>(null)
  const [money, setMoney] = useState<MoneyRow[] | null>(null)
  const [votes, setVotes] = useState<Vote[] | null>(null)
  const [cons, setCons] = useState<Constituent[]>([])
  const [donor, setDonor] = useState<DonorVote[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [source, setSource] = useState('pac_direct')
  const [gran, setGran] = useState<Gran>('quarter')
  const [focus, setFocusRaw] = useState('')
  const [inc, setInc] = useState<Record<string, boolean>>({ industry: true, labor: true, other: false, political: false, unknown: false })
  const [vf, setVf] = useState<VoteFilter>('unity_against')
  const [preset, setPreset] = useState('all')
  const [table, setTable] = useState(false)
  const [showRest, setShowRest] = useState(false)
  const [ref, width] = useWidth<HTMLDivElement>()

  useEffect(() => {
    let alive = true
    setLoading(true); setError('')
    Promise.all([api.profile(id), api.money(id), api.votes(id), api.constituents(id), api.donorVotes(id)])
      .then(([p, m, v, c, dv]) => { if (alive) { setProfile(p); setMoney(m); setVotes(v); setCons(c); setDonor(dv); setLoading(false) } })
      .catch((e) => { if (alive) { setError(String(e)); setLoading(false) } })
    return () => { alive = false }
  }, [id])

  const setFocus = (s: string) => {
    setFocusRaw(s)
    setVf((cur) => (s ? (cur.startsWith('relevant') ? cur : 'relevant_strict') : cur.startsWith('relevant') ? 'unity_against' : cur))
  }

  const sectors = useMemo(() => {
    const all = Object.entries(defs.category).filter(([s, c]) => ['industry', 'labor', 'other'].includes(c) && !NO_FOCUS_SECTORS.has(s)).map(([s]) => s)
    return all.sort((a, b) => (SECTOR_SLOT[a] || 99) - (SECTOR_SLOT[b] || 99) || a.localeCompare(b))
  }, [defs])

  const domain: [Date, Date] = useMemo(() => {
    const now = new Date()
    const end = new Date(now.getFullYear(), now.getMonth() + 1, 1)
    const start = preset === 'all' ? new Date(2005, 0, 1) : preset === '2015' ? new Date(2015, 0, 1) : preset === '2020' ? new Date(2020, 0, 1) : new Date(now.getFullYear() - 2, now.getMonth(), 1)
    return [start, end]
  }, [preset])
  const x = useMemo(() => d3.scaleTime().domain(domain).range([MARGIN.l, width - MARGIN.r]), [domain, width])

  const { series, buckets } = useMemo(() => {
    const empty = { series: [] as Series[], buckets: [] as Bucket[] }
    if (!money) return empty
    const cat = (s: string) => defs.category[s] ?? 'unknown'
    const rows = money.filter((r) => r.source === source && (focus ? (r.sector === focus || (showRest && inc[cat(r.sector)])) : inc[cat(r.sector)]))
    const keyOf = (sector: string): string => {
      if (focus) return sector === focus ? focus : '__rest'
      if (SECTOR_SLOT[sector]) return sector
      const c = cat(sector)
      return c === 'political' ? '__political' : c === 'unknown' ? '__unknown' : '__other'
    }
    const start = (m: string): Date => {
      const [Y, M] = m.split('-').map(Number)
      return gran === 'year' ? new Date(Y, 0, 1) : gran === 'quarter' ? new Date(Y, Math.floor((M - 1) / 3) * 3, 1) : new Date(Y, M - 1, 1)
    }
    const next = (d: Date) => (gran === 'year' ? new Date(d.getFullYear() + 1, 0, 1) : gran === 'quarter' ? new Date(d.getFullYear(), d.getMonth() + 3, 1) : new Date(d.getFullYear(), d.getMonth() + 1, 1))
    const label = (d: Date) => (gran === 'year' ? `${d.getFullYear()}` : gran === 'quarter' ? `${d.getFullYear()} Q${d.getMonth() / 3 + 1}` : d3.timeFormat('%b %Y')(d))
    const map = new Map<number, Bucket>()
    const totals: Record<string, number> = {}
    for (const r of rows) {
      const s = start(r.m)
      const b = map.get(+s) ?? { start: s, end: next(s), label: label(s), vals: {} }
      const k = keyOf(r.sector)
      b.vals[k] = (b.vals[k] || 0) + r.amt
      totals[k] = (totals[k] || 0) + r.amt
      map.set(+s, b)
    }
    const all = [...map.values()].sort((a, b) => +a.start - +b.start).filter((b) => b.end > domain[0] && b.start < domain[1])
    let ser: Series[]
    if (focus) {
      ser = [{ key: focus, label: focus, color: 'var(--s1)' }]
      if (showRest) ser.push({ key: '__rest', label: 'All other sectors shown', color: 'var(--other)' })
    } else {
      ser = Object.entries(SECTOR_SLOT).sort((a, b) => a[1] - b[1]).filter(([s]) => (totals[s] || 0) > 0).map(([s, slot]) => ({ key: s, label: s, color: `var(--s${slot})` }))
      if (totals.__other) ser.push({ key: '__other', label: 'Other sectors', color: 'var(--other)' })
      if (totals.__political) ser.push({ key: '__political', label: CATEGORY_LABEL.political, color: 'var(--pol)' })
      if (totals.__unknown) ser.push({ key: '__unknown', label: CATEGORY_LABEL.unknown, color: 'var(--unk)' })
    }
    return { series: ser, buckets: all }
  }, [money, defs, source, focus, inc, gran, domain, showRest])

  const relevantAreas = useMemo(() => {
    const s = new Set<string>()
    if (!focus) return s
    defs.policy_sector.filter((r) => r.sector === focus && (r.tier === 'strict' || vf === 'relevant_broad')).forEach((r) => s.add(r.policy_area))
    return s
  }, [defs, focus, vf])
  const strictAreas = useMemo(() => new Set(defs.policy_sector.filter((r) => r.sector === focus && r.tier === 'strict').map((r) => r.policy_area)), [defs, focus])

  const shownVotes = useMemo(() => {
    if (!votes) return []
    const d0 = isoDay(domain[0]), d1 = isoDay(domain[1])
    let v = votes.filter((r) => r.d >= d0 && r.d <= d1)
    if (vf === 'unity_against') v = v.filter((r) => r.unity && r.defect === 1)
    else if (vf === 'surprising') v = v.filter((r) => r.p != null && r.p < 0.25)
    else if (vf.startsWith('relevant')) v = v.filter((r) => r.pa != null && relevantAreas.has(r.pa))
    return v
  }, [votes, domain, vf, relevantAreas])

  const congresses = useMemo(() => {
    const out: { c: number; start: Date; end: Date }[] = []
    for (let c = 109; c <= 119; c++) out.push({ c, start: new Date(2005 + 2 * (c - 109), 0, 3), end: new Date(2007 + 2 * (c - 109), 0, 3) })
    return out
  }, [])

  const bands: Band[] = useMemo(() => {
    if (!profile || !focus) return []
    const out: Band[] = []
    for (const c of profile.committees) {
      if (c.source !== 'stewart_woon' || !c.start_date || !c.end_date) continue
      const hit = defs.committee_sector.some((r) => r.chamber === c.chamber && r.sector === focus && (r.tier === 'strict' || vf === 'relevant_broad') && new RegExp(r.committee_pattern).test(c.committee_name.toLowerCase()))
      if (hit) out.push({ start: new Date(c.start_date), end: new Date(c.end_date), label: c.committee_name })
    }
    return out
  }, [profile, focus, defs, vf])

  const perCongress = useMemo(() => {
    if (!profile || !votes || !money) return []
    return profile.terms.map((t) => {
      const st = profile.stats.find((s) => s.congress === t.congress && s.chamber === t.chamber)
      const y0 = `${t.start}-01`, y1 = `${t.end}-12`
      const sec = (src: string) => money.filter((r) => r.sector === focus && r.source === src && r.m >= y0 && r.m <= y1).reduce((a, r) => a + r.amt, 0)
      const rel = focus ? votes.filter((v) => v.congress === t.congress && v.chamber === t.chamber && v.pa != null && strictAreas.has(v.pa)) : []
      const relUnity = rel.filter((v) => v.unity)
      return {
        t, st, pac: sec('pac_direct'), ind: sec('indiv'), relN: rel.length,
        relYea: rel.length ? (100 * rel.filter((v) => v.vote === 'Y').length) / rel.length : null,
        relDefect: relUnity.length ? (100 * relUnity.filter((v) => v.defect === 1).length) / relUnity.length : null, relUnityN: relUnity.length,
        relP: rel.filter((v) => v.p != null).length ? d3.mean(rel.filter((v) => v.p != null), (v) => v.p as number)! * 100 : null,
      }
    })
  }, [profile, votes, money, focus, strictAreas])

  if (error) return <div className="card">Could not load this member: {error}. Is the API server running on port 8000?</div>
  if (!profile || !money || !votes) return <div className="card hint">Loading…</div>

  const tot = (src: string) => profile.money_totals.filter((r) => r.source === src).reduce((a, r) => a + r.amount, 0)
  const unityN = profile.stats.reduce((a, s) => a + s.unity_votes, 0)
  const careerDefect = unityN ? profile.stats.reduce((a, s) => a + s.unity_votes * (s.defect_pct ?? 0), 0) / unityN : null
  const votesN = profile.stats.reduce((a, s) => a + s.votes, 0)
  const surprising = votesN ? profile.stats.reduce((a, s) => a + s.votes * (s.surprising_pct ?? 0), 0) / votesN : null
  const last = profile.terms[profile.terms.length - 1]
  const ownShare = last.demshare_pres == null ? null : last.party_code === 100 ? last.demshare_pres : last.party_code === 200 ? 1 - last.demshare_pres : null
  const party = last.party_code === 100 ? 'D' : last.party_code === 200 ? 'R' : 'I'
  const latestCommittees = [...new Set(profile.committees.filter((c) => c.congress === last.congress).map((c) => c.committee_name))]
  const srcInfo = SOURCES.find((s) => s.key === source)!
  const lock = defs.lock[0]?.replace('locked ', '')
  const noMapping = !!focus && strictAreas.size === 0

  return (
    <div className="page" ref={ref}>
      <div className={`card head ${loading ? 'reloading' : ''}`}>
        <img className="photo" alt="" src={`https://bioguide.congress.gov/bioguide/photo/${id[0]}/${id}.jpg`} onError={(e) => { (e.currentTarget as HTMLImageElement).style.visibility = 'hidden' }} />
        <div>
          <h2>{profile.name}</h2>
          <div className="sub">
            <span className={`party ${party}`}><i />{party === 'D' ? 'Democrat' : party === 'R' ? 'Republican' : 'Independent'}</span>
            {' · '}{last.chamber === 'Senate' ? `Senator, ${last.state}` : `Representative, ${last.state}${last.district ? `-${last.district}` : ''}`}
            {' · '}{profile.terms.length} Congress{profile.terms.length > 1 ? 'es' : ''} since 2005 ({ordinal(profile.terms[0].congress)}–{ordinal(last.congress)})
          </div>
          {latestCommittees.length > 0 && <div className="sub hint">{ordinal(last.congress)} Congress committees: {latestCommittees.slice(0, 6).join(' · ')}{latestCommittees.length > 6 ? ` · +${latestCommittees.length - 6} more` : ''}</div>}
        </div>
      </div>

      <div className={`tiles ${loading ? 'reloading' : ''}`}>
        <Tile label="PAC gifts received" value={fmtMoney(tot('pac_direct'))} note="direct, all sectors, 2005–now" />
        <Tile label="Individual gifts (itemized)" value={fmtMoney(tot('indiv'))} note="$200+ donors; small gifts not itemized" />
        <Tile label="Outside spending for" value={fmtMoney(tot('ie_support'))} note="not a gift to the member" />
        <Tile label="Outside spending against" value={fmtMoney(tot('ie_oppose'))} note="spent to defeat the member" />
        <DonorTile rows={donor} />
        <Tile label={last.chamber === 'Senate' ? 'Own party’s share of state’s presidential vote' : 'Own party’s share of district’s presidential vote'} value={ownShare == null ? '–' : fmtPct(ownShare * 100, 0)} note={last.lines_match === 'approx' ? 'district lines approximate' : `${ordinal(last.congress)} Congress map`} />
      </div>

      <div className="card">
        <div className="controls">
          <div className="ctl">Money source
            <select value={source} onChange={(e) => setSource(e.target.value)}>
              {SOURCES.map((s) => <option key={s.key} value={s.key}>{s.label}</option>)}
            </select>
          </div>
          <div className="ctl">Focus on one sector
            <select value={focus} onChange={(e) => setFocus(e.target.value)}>
              <option value="">All sectors</option>
              {sectors.map((s) => <option key={s} value={s}>{s}</option>)}
            </select>
          </div>
          <div className="ctl">Votes shown
            <select value={vf} onChange={(e) => setVf(e.target.value as VoteFilter)}>
              <option value="unity_against">Broke from own party (party-line votes)</option>
              <option value="surprising">Surprising given ideology (&lt; 25%)</option>
              <option value="all">Every recorded vote</option>
              <option value="relevant_strict" disabled={!focus}>On topics tied to the focus sector (strict)</option>
              <option value="relevant_broad" disabled={!focus}>On topics tied to the focus sector (strict + broad)</option>
            </select>
          </div>
          <div className="ctl">Bars per
            <div className="seg">
              {(['month', 'quarter', 'year'] as Gran[]).map((g) => <button key={g} aria-pressed={gran === g} onClick={() => setGran(g)}>{g[0].toUpperCase() + g.slice(1)}</button>)}
            </div>
          </div>
          <div className="ctl">Period
            <div className="seg">
              {PRESETS.map(([k, l]) => <button key={k} aria-pressed={preset === k} onClick={() => setPreset(k)}>{l}</button>)}
            </div>
          </div>
        </div>
        <div className="chips" style={{ marginTop: 10 }}>
          <span className="hint">Include:</span>
          {(['industry', 'labor', 'other', 'political', 'unknown'] as const).map((c) => (
            <label key={c}><input type="checkbox" checked={inc[c]} onChange={(e) => setInc({ ...inc, [c]: e.target.checked })} disabled={!!focus && !showRest} />{CATEGORY_LABEL[c]}</label>
          ))}
          {focus && <label style={{ marginLeft: 12 }}><input type="checkbox" checked={showRest} onChange={(e) => setShowRest(e.target.checked)} />Also show all other sectors, for scale</label>}
        </div>
      </div>

      <div className={`card ${loading ? 'reloading' : ''}`}>
        <h2>{focus ? `${focus}: ` : ''}{srcInfo.label}</h2>
        <div className="sub">{srcInfo.help} {source === 'indiv' && 'Donors with no usable employer (retired, unemployed, blank) are in “Unclassified”, off by default.'}</div>
        <div className="legend">
          {series.map((s) => <span key={s.key}><i style={{ background: s.color }} />{s.label}</span>)}
          {bandsLegend(bands)}
        </div>
        {series.length === 0 ? <div className="hint" style={{ padding: '24px 0' }}>No money of this kind in the selected period and categories.</div> : (
          <MoneyChart buckets={buckets} series={series} x={x} width={width - 34} bands={bands} yLabel={`$ per ${gran}`} ariaLabel={`${srcInfo.label} by ${gran}${focus ? `, ${focus} highlighted` : ''}`} />
        )}
        <div style={{ marginTop: 6 }}>
          <button className="iconbtn" onClick={() => setTable((t) => !t)}>{table ? 'Hide table' : 'View as table'}</button>
        </div>
        {table && <MoneyTable buckets={buckets} series={series} />}
      </div>

      <div className={`card ${loading ? 'reloading' : ''}`}>
        <h2>Votes{focus && vf.startsWith('relevant') ? ` on topics tied to ${focus}` : ''}</h2>
        <div className="sub">{shownVotes.length.toLocaleString()} votes shown. Position on the same time axis as the money above.</div>
        <div className="legend">
          <span><i className="dot" style={{ background: 'var(--s2)' }} />Voted against own party’s majority</span>
          <span><i className="dot" style={{ background: 'var(--muted)', opacity: 0.6 }} />Voted with own party’s majority</span>
          <span><i className="ring" style={{ borderColor: 'var(--muted)' }} />Not a party-line vote</span>
          <span><i className="ring" />Ringed: model gave this vote under 25%</span>
        </div>
        {noMapping && <div className="note-box" style={{ marginBottom: 6 }}>No bill topics are tied to this sector yet, so the topic filter shows nothing. For sectors without a topic list, the lobbied-votes view on the front page uses lobbying filings instead.</div>}
        <VoteStrip votes={shownVotes} x={x} width={width - 34} congresses={congresses} />
        {vf.startsWith('relevant') && <div className="note-box" style={{ marginTop: 8 }}>Votes are tied to the sector by bill topic only. This does not show whether Yea helped or hurt the sector, and nothing on this page shows that money caused a vote.</div>}
      </div>

      {donor.length > 0 && <DonorVotesCard rows={donor} />}

      {cons.length > 0 && <ConstituentsCard rows={cons} />}

      <div className="card">
        <h2>By Congress</h2>
        <div className="sub">{focus ? `Money from ${focus} next to how this member voted on topics tied to it (strict list).` : 'How this member voted in each Congress. Pick a sector above to add money and topic-specific votes.'}</div>
        <div className="scroll-x">
          <table className="data">
            <thead><tr>
              <th>Congress</th><th>Votes</th><th>Party-line votes</th><th>Broke from party</th><th>Surprising</th>
              {focus && <><th>{focus} PAC $</th><th>{focus} indiv. $</th><th>Topic votes</th><th>Yea on topic</th><th>Broke on topic</th></>}
            </tr></thead>
            <tbody>
              {perCongress.map(({ t, st, pac, ind, relN, relYea, relDefect, relUnityN }) => (
                <tr key={`${t.congress}-${t.chamber}`}>
                  <td>{ordinal(t.congress)} ({t.start}–{String(t.end).slice(2)})</td>
                  <td>{st?.votes.toLocaleString() ?? '–'}</td><td>{st?.unity_votes.toLocaleString() ?? '–'}</td>
                  <td>{fmtPct(st?.defect_pct)}</td><td>{fmtPct(st?.surprising_pct)}</td>
                  {focus && <><td>{fmtMoney(pac)}</td><td>{fmtMoney(ind)}</td><td>{relN}</td><td>{fmtPct(relYea, 0)}</td><td>{relDefect == null ? '–' : `${relDefect.toFixed(0)}% of ${relUnityN}`}</td></>}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="hint" style={{ marginTop: 8 }}>Definitions locked {lock}. Topic matching, “strict” and “broad”, is described under About.</div>
      </div>
    </div>
  )
}

function bandsLegend(bands: Band[]) {
  if (!bands.length) return null
  return <span><i style={{ background: 'var(--band)', border: '1px solid var(--axis)' }} />Shaded: on a committee covering this sector</span>
}

function Tile({ label, value, note }: { label: string; value: string; note: string }) {
  return <div className="tile"><div className="lbl">{label}</div><div className="val">{value}</div><div className="note">{note}</div></div>
}

function MoneyTable({ buckets, series }: { buckets: Bucket[]; series: Series[] }) {
  return (
    <div className="scroll-x" style={{ maxHeight: 320, overflowY: 'auto', marginTop: 8 }}>
      <table className="data">
        <thead><tr><th>Period</th>{series.map((s) => <th key={s.key}>{s.label}</th>)}<th>Total</th></tr></thead>
        <tbody>
          {buckets.map((b) => (
            <tr key={+b.start}><td>{b.label}</td>{series.map((s) => <td key={s.key}>{fmtMoney(b.vals[s.key] || 0)}</td>)}<td>{fmtMoney(series.reduce((a, s) => a + (b.vals[s.key] || 0), 0))}</td></tr>
          ))}
        </tbody>
      </table>
      <div className="hint">Refunds net against gifts within a period; the chart draws negative net amounts as zero.</div>
    </div>
  )
}

export function ConstituentsCard({ rows }: { rows: Constituent[] }) {
  const [all, setAll] = useState(false)
  const direct = rows.filter((r) => r.match === 'direct')
  const proxy = rows.filter((r) => r.match === 'proxy')
  const clear = (x: Constituent[]) => x.filter((r) => r.with_district != null)
  const count = (x: Constituent[]) => ({ n: clear(x).length, against: clear(x).filter((r) => r.with_district === 0).length })
  const d = count(direct), p = count(proxy)
  const verdict = (r: Constituent) =>
    r.with_district == null ? (r.district_view === 'unknown' ? 'No estimate' : 'District split / unclear') : r.with_district === 1 ? 'With district' : 'Against district'
  const basis = (r: Constituent) => (r.match === 'direct' ? 'Survey asked about this issue' : r.match === 'proxy' ? 'Climate-opinion stand-in' : 'Related question')
  const shown = all ? rows : rows.slice(0, 12)
  return (
    <div className="card">
      <h2>Votes vs. what the district wanted</h2>
      <div className="sub">
        {d.n > 0 ? <>On <strong>{direct.length}</strong> landmark votes where the survey asked about the issue itself, the district’s majority was clear on <strong>{d.n}</strong> and the member went <strong>against</strong> it on <strong>{d.against}</strong>. </> : direct.length > 0 ? 'On the landmark votes where the survey asked about the issue itself, no district majority was clear enough to call. ' : 'No landmark vote with a direct survey question covers this member. '}
        {proxy.length > 0 ? <>On <strong>{proxy.length}</strong> fossil-fuel votes judged by one stand-in question (letting the EPA regulate CO2), the district’s view was clear on <strong>{p.n}</strong> and the member went against it on <strong>{p.against}</strong>; that is a looser measure. </> : null}
        A vote counts as “against” only if we are at least 90% sure which way the district leaned.
      </div>
      <div className="scroll-x">
        <table className="data">
          <thead><tr><th>Date</th><th style={{ textAlign: 'left' }}>Vote</th><th style={{ textAlign: 'left' }}>Voters were asked</th><th style={{ textAlign: 'left' }}>Basis</th><th>Member</th><th>{'District / state support'}</th><th>Result</th></tr></thead>
          <tbody>
            {shown.map((r) => (
              <tr key={`${r.congress}-${r.chamber}-${r.rn}`} style={r.match === 'related' ? { opacity: 0.65 } : undefined}>
                <td>{r.d}</td>
                <td style={{ textAlign: 'left' }}>{r.bill} · {r.note.length > 70 ? `${r.note.slice(0, 68)}…` : r.note}</td>
                <td style={{ textAlign: 'left' }}>{ITEM_LABEL[r.item] ?? r.item}</td>
                <td style={{ textAlign: 'left' }} className="hint">{basis(r)}</td>
                <td>{r.voted_for_item === 1 ? 'For' : 'Against'}</td>
                <td>{r.est == null ? '–' : `${Math.round(r.est * 100)}% ± ${Math.round((r.sd ?? 0) * 164)}`}</td>
                <td className={r.with_district === 0 ? 'warn' : undefined} style={r.with_district === 0 ? { fontWeight: 600 } : undefined}>{verdict(r)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {rows.length > 12 && <button className="iconbtn" style={{ marginTop: 8 }} onClick={() => setAll((v) => !v)}>{all ? 'Show fewer' : `Show all ${rows.length}`}</button>}
      <div className="hint" style={{ marginTop: 8 }}>
        “For/Against” is the member’s position on the question voters were asked, which can be the opposite of Yea/Nay (for example, voting Yea to block the EPA is “Against” letting it regulate CO2). Support is a survey estimate pooled with the district’s presidential vote and ideology; ± is a 90% range. Most of these gaps are party-wide patterns and say nothing yet about donors.
      </div>
    </div>
  )
}

const MONEY_FLOOR = 10_000

function DonorTile({ rows }: { rows: DonorVote[] }) {
  const funded = rows.filter((r) => r.pac_6y >= MONEY_FLOOR)
  const n = funded.length
  const a = funded.filter((r) => r.aligned === 1).length
  return (
    <div className="tile">
      <div className="lbl">Voted the donors’ way</div>
      <div className="val">{n >= 3 ? `${a} of ${n}` : '–'}</div>
      <div className="note">{n >= 3 ? `votes on sectors that gave $10K+ in the prior 6 years (documented-side votes)` : rows.length ? 'too few coded votes with sector money' : 'no coded votes for this member yet'}</div>
    </div>
  )
}

export function DonorVotesCard({ rows }: { rows: DonorVote[] }) {
  const [all, setAll] = useState(false)
  const funded = rows.filter((r) => r.pac_6y >= MONEY_FLOOR)
  const unfunded = rows.filter((r) => r.pac_6y < MONEY_FLOOR)
  const sh = (x: DonorVote[]) => (x.length ? `${x.filter((r) => r.aligned === 1).length} of ${x.length}` : '–')
  return (
    <div className="card">
      <h2>Votes on the donors’ issues</h2>
      <div className="sub">
        Voted the donors’ way on {sh(funded)} votes where that sector had given $10K or more in the six years before{unfunded.length ? `, and on ${sh(unfunded)} where it had given less` : ''}.
        Each vote’s “helps” side comes from a cited source (see the <a href="#/codebook">vote codebook</a>). A vote that matters to two industries, such as oil and coal, appears once for each.
      </div>
      <div className="scroll-x">
        <table className="data">
          <thead><tr>
            <th>Date</th><th style={{ textAlign: 'left' }}>Vote</th><th style={{ textAlign: 'left' }}>Sector</th><th>Helps if</th><th>Member voted</th>
            <th>Result</th><th>Sector PAC $ (6 yrs before)</th><th>District</th>
          </tr></thead>
          <tbody>
            {(all ? rows : rows.slice(0, 25)).map((r) => (
              <tr key={`${r.congress}-${r.chamber}-${r.rn}-${r.sector}-${r.subsector}`} title={r.evidence}>
                <td>{r.d}</td>
                <td style={{ textAlign: 'left' }}>{r.bill} · {(r.desc || r.q || '').slice(0, 64)}</td>
                <td style={{ textAlign: 'left' }}>{r.subsector ? r.subsector.replace('_', ' ') : r.sector}</td>
                <td>{r.helps_vote}</td>
                <td>{r.yea === 1 ? 'Yea' : 'Nay'}</td>
                <td style={r.aligned === 1 ? { fontWeight: 600 } : undefined}>{r.aligned === 1 ? 'With donors' : 'Against donors'}</td>
                <td>{fmtMoney(r.pac_6y)}</td>
                <td>{r.with_district == null ? '–' : r.with_district === 1 ? 'With district' : 'Against district'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {rows.length > 25 && <button className="iconbtn" style={{ marginTop: 8 }} onClick={() => setAll((v) => !v)}>{all ? 'Show fewer' : `Show all ${rows.length}`}</button>}
      <div className="hint" style={{ marginTop: 8 }}>
        Hover a row for the evidence behind the donors’ side; every source is in the vote codebook. Sector money is direct PAC gifts. A member who votes with donors and also with their party may simply be doing what their party does; that is why the tests compare members of the same party on the same vote.
      </div>
    </div>
  )
}
