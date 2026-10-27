import { useEffect, useState } from 'react'
import { api } from '../api'
import type { CommitteeRow2, Definitions, PlaceboRow, Scored, TimingRow } from '../types'
import { useWidth } from '../hooks'
import AboutView from './AboutView'

export default function MethodView({ defs }: { defs: Definitions }) {
  const [timing, setTiming] = useState<TimingRow[]>([])
  const [placebo, setPlacebo] = useState<PlaceboRow[]>([])
  const [committee, setCommittee] = useState<CommitteeRow2[]>([])
  const [board, setBoard] = useState<Scored[]>([])
  useEffect(() => {
    api.method().then((r) => { setTiming(r.timing); setPlacebo(r.placebo); setCommittee(r.committee) }).catch(() => undefined)
    api.scoreboard().then((r) => setBoard(r.members)).catch(() => undefined)
  }, [])
  const ranked = board.filter((m) => m.ranked && m.loyalty != null)
  const mean = (p: string) => {
    const xs = ranked.filter((m) => m.party === p).map((m) => m.loyalty!)
    return xs.length ? (100 * xs.reduce((a, b) => a + b, 0)) / xs.length : null
  }
  const spec = 'Both, plus ideology, district lean and overall fundraising'
  return (
    <div className="page">
      <div className="card prose">
        <h2>What we found so far</h2>
        <p className="hint">Based on a pilot set of coded votes; every number here will move as more votes are added.</p>

        <h3>1. Party explains most of it</h3>
        <p>
          Among ranked members, the average share of funded votes cast the donors’ way is{' '}
          <strong>{mean('R') != null ? `${mean('R')!.toFixed(0)}%` : '–'} for Republicans</strong> and <strong>{mean('D') != null ? `${mean('D')!.toFixed(0)}%` : '–'} for Democrats</strong>.
          So “voted with donors” mostly means “voted with their party,” which is why the ranking compares each member with same-party colleagues on the same votes.
        </p>

        <h3>2. Money after the vote predicts as well as money before it</h3>
        <p>
          If donors were buying votes, money that arrived <em>before</em> a vote should predict the vote better than money that arrives <em>after</em>. We tested both at once,
          comparing same-party members on the same vote. The bars show how many percentage points more likely a member was to vote the donors’ way when a sector’s PACs had given
          $50K instead of nothing, in the two years before or the two years after the vote.
        </p>
        <TimingChart rows={timing.filter((r) => r.spec === spec)} />
        <TimingReading rows={timing.filter((r) => r.spec === spec)} />

        <h3>3. Money follows committee seats, not votes</h3>
        <p>
          When a member joins a committee that oversees an industry, that industry’s PAC money to them jumps, because donors follow the gavel. If money were buying votes, how the member
          votes should shift after joining as well. We compared member-years before and after joining with members who never joined (same member, same year).
        </p>
        <CommitteeBlock rows={committee} />

        <h3>4. Is it this industry’s money, or any money?</h3>
        <p>
          For each group of votes we put PAC money from every industry into one model at once. If money moved votes, the industry the vote concerns should stand out.
          Bars show points more likely to vote the industry’s way per $50K, own industry first.
        </p>
        <PlaceboBlock rows={placebo} />

        <h3>5. Does it hold up against local interests?</h3>
        <p>
          A member from a coal or oil state has a local reason to vote with those industries. The expected-vote model therefore includes how much of the member’s state economy
          (private employment, Census) rests on the industry, or how many residents are in a union. Adding it barely changed who ranks at the top.
        </p>

        <h3>6. How reliable are the coded votes?</h3>
        <ul>
          <li>We checked 30 random LCV-based oil and gas votes. The check exposed a real bug: 128 of 130 House votes had been tied to the wrong roll call because LCV’s House numbering differs. They are now matched on each vote’s printed tally, and all Senate matches were already right.</li>
          <li>Industry statements are only partly checked. For 8 of 30 sampled votes we searched for the industry’s own position: two were clearly confirmed (API’s letter backing H.R. 4899, and API’s opposition to the methane fee in the Build Back Better Act), one only partly (oil and gas associations applauded the House Interior bill with its methane riders, but not that specific amendment), and five turned up no statement either way. The other 22 have not been checked against the industry’s side yet, so we do not yet have an error rate for the coding. Votes coded from LCV’s scorecard carry the lower “scorecard” evidence tier, and the “Strictly sourced only” toggle drops them.</li>
          <li>Union positions come from the AFL-CIO, which speaks for most but not every union. Votes about voting rights, policing and similar causes were dropped because they are not union-donor interests.</li>
        </ul>

        <h3>7. The every-vote screen</h3>
        <ul>
          <li>The coded votes above cover only a small slice of the roll calls since 2008, because each needs a documented industry side. The “Every vote” page tests all of them (14,952 with enough members on both sides) without needing a side.</li>
          <li>For each vote and industry it asks whether members with more of that industry’s money in the two years before voted differently, holding ideology within party, party, district lean, district ideology and total fundraising fixed. Random money, shuffled within party, shows what chance looks like.</li>
          <li>It validates: where we already know the industry’s side, a strong link pointed to that side in 177 of 182 cases.</li>
          <li>It cannot show intent. Money that arrives after a vote predicts votes almost as well as money before it for most industries, so much of the link is donors backing members who already vote their way. Strong links also appear on votes with no obvious industry stake, so each is a lead, not a finding.</li>
        </ul>

        <h3>8. Defense, local controls and what is still missing</h3>
        <ul>
          <li>Defense votes (147 since 2008) are of two kinds. 54 are passage, conference-report and veto-override votes on the defense authorization and appropriations bills, where the industry side is Yea. 93 (2013 to 2024) come from Peace Action’s votes archive: amendments that cut or add Pentagon money or weapons programs and resolutions to block arms sales, where the industry side is the opposite of Peace Action’s position, a fiscal rule written before any model ran. 93 of 99 selected pages matched a roll call by tally, bill, vote type and a comparison of the Yea voter lists.</li>
          <li>Every test now holds fixed how much of the member’s state economy rests on the industry (Census employment, union membership, and for defense the DoD contract dollars per resident performed in the state). The every-vote results barely moved, so the links are not just jobs back home. State-level measures cannot separate districts within a state.</li>
          <li>Two independent checks on the industry side of the coded votes: a strong money link pointed to the documented side in 177 of 182 cases, and the industry lobbied the bill in 80% of oil and gas votes and 83% of labor votes. Only 48% of coal rows passed the lobbying check, so scorecard-tier coal rows are kept only where coal clients lobbied the bill.</li>
          <li>Contract totals are prime awards in obligated dollars. They leave out classified awards, subcontracts and direct sales to foreign governments, so “contracts ÷ revenue” is a floor. Company-reported government shares were read from search-result quotations of the filings and each carries a link to check.</li>
          <li>Not covered: campaign promises (no data source yet), the executive branch (appointments, contract awards), Pentagon officials who later join contractors, and spending that goes to members through earmarks.</li>
        </ul>

        <h3>How the tiers work</h3>
        <ul>
          <li>For each coded vote, find what chance a same-party colleague with the same ideology, district lean and local industry stake had of voting the industry’s way on that exact vote.</li>
          <li>Count each of the member’s votes in proportion to how much that industry had given them in the six years before (full weight at $50K).</li>
          <li>The gap is the average difference between what the member did and what peers would do, shrunk toward zero when the record is thin. “Far more loyal” needs a gap of 20+ points we are very sure of; “more loyal” 8+ points we are fairly sure of.</li>
          <li>A member is ranked only with about three votes’ worth of real funding. Everyone else is shown as “not ranked yet,” never as clean.</li>
        </ul>

        <h3>What a high or low score does not mean</h3>
        <ul>
          <li>It does not prove corruption. Members from oil, coal or farm states both attract that money and represent people who want those votes.</li>
          <li>A member who always votes with their party can’t stand out here even if donors love them. The “voted the donors’ way” counts show that side.</li>
          <li>Only PAC gifts count as sector money in the index. Individual donors and outside spending are in the explorer but not yet scored.</li>
          <li>The “donors’ side” of each vote comes from a cited trade-group position, listed below. Anything we could not source was left out.</li>
        </ul>
      </div>
      <AboutView defs={defs} />
    </div>
  )
}

function TimingChart({ rows }: { rows: TimingRow[] }) {
  const [ref, width] = useWidth<HTMLDivElement>()
  if (!rows.length) return <div className="hint">Loading…</div>
  const groups = ['Banks', 'Oil and gas', 'Labor (unions)']
  const H = 80 * groups.length + 78, M = { l: 130, r: 130, t: 34, b: 44 }
  const lo = Math.min(-5, ...rows.map((r) => r.effect_pts - 1.64 * r.se_pts)), hi = Math.max(10, ...rows.map((r) => r.effect_pts + 1.64 * r.se_pts))
  const x = (v: number) => M.l + ((v - lo) / (hi - lo)) * (width - M.l - M.r)
  let yy = M.t
  return (
    <div className="chart" ref={ref}>
      <svg width={width} height={H} role="img" aria-label="Effect of sector money before versus after a vote on voting the donors' way">
        {[0, 5, 10, 15, 20].filter((t) => t >= lo && t <= hi).map((t) => (
          <g key={t}><line x1={x(t)} x2={x(t)} y1={M.t - 6} y2={H - M.b + 2} stroke={t === 0 ? 'var(--axis)' : 'var(--grid)'} /><text x={x(t)} y={H - 22} textAnchor="middle" fontSize={11} fill="var(--muted)">{t}</text></g>
        ))}
        <text x={(M.l + width - M.r) / 2} y={H - 4} textAnchor="middle" fontSize={11} fill="var(--ink-2)">percentage points more likely to vote the donors’ way, $0 → $50K of sector PAC money</text>
        <circle cx={M.l + 6} cy={12} r={5} fill="var(--s2)" /><text x={M.l + 16} y={16} fontSize={11} fill="var(--ink-2)">money in the 2 years before the vote</text>
        <circle cx={M.l + 250} cy={12} r={5} fill="var(--s1)" /><text x={M.l + 260} y={16} fontSize={11} fill="var(--ink-2)">money in the 2 years after the vote</text>
        {groups.map((g) => {
          const before = rows.find((r) => r.group === g && r.term.includes('before'))
          const after = rows.find((r) => r.group === g && r.term.includes('after'))
          const y0 = yy
          yy += 80
          return (
            <g key={g}>
              <text x={M.l - 10} y={y0 + 30} textAnchor="end" fontSize={12} fill="var(--ink)">{g}</text>
              {[['money before the vote', before, 'var(--s2)', 18], ['money after the vote', after, 'var(--s1)', 48]].map(([lab, r, col, dy]) => {
                const row = r as TimingRow | undefined
                if (!row) return null
                const yb = y0 + (dy as number)
                return (
                  <g key={lab as string}>
                    <line x1={x(row.effect_pts - 1.64 * row.se_pts)} x2={x(row.effect_pts + 1.64 * row.se_pts)} y1={yb} y2={yb} stroke={col as string} strokeWidth={2} />
                    <circle cx={x(row.effect_pts)} cy={yb} r={5} fill={col as string} stroke="var(--surface)" strokeWidth={2} />
                    <text x={x(row.effect_pts + 1.64 * row.se_pts) + 8} y={yb + 4} fontSize={11} fill="var(--ink-2)">{row.effect_pts >= 0 ? '+' : ''}{row.effect_pts.toFixed(0)}</text>
                  </g>
                )
              })}
            </g>
          )
        })}
      </svg>
    </div>
  )
}

function TimingReading({ rows }: { rows: TimingRow[] }) {
  const lines = [['Banks', 'Banks'], ['Oil and gas', 'Oil and gas'], ['Labor (unions)', 'Unions']].map(([g, nm]) => {
    const b = rows.find((r) => r.group === g && r.term.includes('before')), a = rows.find((r) => r.group === g && r.term.includes('after'))
    if (!a || !b) return null
    const diff = b.effect_pts - a.effect_pts
    const se = Math.hypot(a.se_pts, b.se_pts)
    const verdict = Math.abs(diff) < 1.64 * se ? 'about the same' : diff > 0 ? 'bigger before the vote' : 'bigger after the vote'
    return { nm, b: b.effect_pts, a: a.effect_pts, verdict }
  }).filter((x): x is { nm: string; b: number; a: number; verdict: string } => !!x)
  return (
    <>
      <ul>
        {lines.map((l) => <li key={l.nm}><strong>{l.nm}:</strong> {l.b.toFixed(0)} points from money before, {l.a.toFixed(0)} from money after, so the effect is <strong>{l.verdict}</strong>.</li>)}
      </ul>
      <p>
        Reading: for banks and oil and gas, money after a vote predicts how someone voted at least as well as money before it, which fits donors backing members who already vote
        their way (or rewarding them afterwards) better than donors changing votes. Unions are the exception: money before a vote predicts it clearly better than money after,
        the pattern you would expect if the money comes first. Neither result clears or convicts anyone: long-running relationships can produce a “before” effect without any
        one gift mattering, and rewarding a vote after the fact is still money following votes.
      </p>
    </>
  )
}

function CommitteeBlock({ rows }: { rows: CommitteeRow2[] }) {
  if (!rows.length) return <div className="hint">Loading...</div>
  const inds = ['oil and gas', 'banks', 'labor']
  return (
    <div className="scroll-x">
      <table className="data">
        <thead><tr><th style={{ textAlign: 'left' }}>Industry</th><th>Members who joined</th><th>Their PAC money from it after joining</th><th>Their votes the industry's way after joining</th></tr></thead>
        <tbody>
          {inds.map((i) => {
            const m = rows.find((r) => r.industry === i && r.outcome.startsWith('sector money'))
            const v = rows.find((r) => r.industry === i && r.outcome.startsWith('votes'))
            if (!m || !v) return null
            const pct = (Math.exp(m.effect) - 1) * 100
            return (
              <tr key={i}>
                <td style={{ textAlign: 'left' }}>{i === 'labor' ? 'Unions' : i === 'banks' ? 'Banks' : 'Oil and gas'}</td>
                <td>{m.joiners}</td>
                <td>{pct >= 0 ? '+' : ''}{pct.toFixed(0)}%</td>
                <td>{v.effect >= 0 ? '+' : ''}{v.effect.toFixed(1)} points (range {(v.effect - 1.64 * v.se).toFixed(1)} to {(v.effect + 1.64 * v.se).toFixed(1)})</td>
              </tr>
            )
          })}
        </tbody>
      </table>
      <div className="hint">Votes: points more likely to vote the industry's way than same-party peers. Banks have few coded votes, so that range is wide.</div>
    </div>
  )
}

function PlaceboBlock({ rows }: { rows: PlaceboRow[] }) {
  if (!rows.length) return <div className="hint">Loading...</div>
  const groups: [string, string][] = [['labor votes', 'Votes unions care about'], ['oil and gas votes', 'Oil and gas votes'], ['bank votes', 'Bank votes']]
  return (
    <div className="threecol">
      {groups.map(([g, title]) => {
        const sub = rows.filter((r) => r.vote_group === g)
        const own = sub.find((r) => r.is_own)
        const others = sub.filter((r) => !r.is_own).sort((a, b) => b.effect_pts - a.effect_pts).slice(0, 4)
        const show = [own, ...others].filter((r): r is PlaceboRow => !!r)
        const max = Math.max(1, ...show.map((r) => Math.abs(r.effect_pts)))
        return (
          <div key={g}>
            <div className="fh">{title}</div>
            {show.map((r) => (
              <div key={r.money_from} className="hrow" style={{ gridTemplateColumns: '120px 1fr 54px' }}>
                <span className="nm" style={{ fontWeight: r.is_own ? 600 : 400 }}>{r.is_own ? '* ' : ''}{r.money_from}</span>
                <span className="track"><i style={{ width: `${Math.max(2, (100 * Math.abs(r.effect_pts)) / max)}%`, background: r.is_own ? 'var(--s2)' : 'var(--other)' }} /></span>
                <span className="amt">{r.effect_pts >= 0 ? '+' : ''}{r.effect_pts.toFixed(0)}</span>
              </div>
            ))}
            <div className="hint">* = the industry the votes concern</div>
          </div>
        )
      })}
    </div>
  )
}
