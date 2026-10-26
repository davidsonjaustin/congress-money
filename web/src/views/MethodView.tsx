import { useEffect, useState } from 'react'
import { api } from '../api'
import type { Definitions, Scored, TimingRow } from '../types'
import { useWidth } from '../hooks'
import AboutView from './AboutView'

export default function MethodView({ defs }: { defs: Definitions }) {
  const [timing, setTiming] = useState<TimingRow[]>([])
  const [board, setBoard] = useState<Scored[]>([])
  useEffect(() => {
    api.method().then((r) => setTiming(r.timing)).catch(() => undefined)
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

        <h3>How the index works</h3>
        <ul>
          <li>For each coded vote, find what chance a same-party colleague with the same ideology and district lean had of voting the donors’ way on that exact vote.</li>
          <li>Count each of the member’s votes in proportion to how much that sector had given them in the six years before (full weight at $50K).</li>
          <li>The index is 50 plus the average gap between what the member did and what peers would do, shrunk toward 50 when the record is thin. 50 means “votes like same-party peers.”</li>
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
