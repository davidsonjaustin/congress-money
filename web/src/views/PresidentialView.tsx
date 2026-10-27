import { useEffect, useMemo, useState } from 'react'
import { api } from '../api'
import type { PresidentialData } from '../types'
import { fmtMoney } from '../util'

const NOMINEES: Record<number, string[]> = { 2008: ['Obama', 'McCain'], 2012: ['Obama', 'Romney'], 2016: ['Clinton', 'Trump'], 2020: ['Biden / Harris', 'Trump'], 2024: ['Biden / Harris', 'Trump'], 2026: ['Trump'] }
const GROUP_NOTE = new Set(['Other political committees', 'Nonprofits that do not disclose their donors', 'Not identifiable (retired / unemployed / no employer)', 'Other / unclassified'])

/** Who paid for the presidential campaigns, by the industry the donors work in. */
export default function PresidentialView() {
  const [d, setD] = useState<PresidentialData | null>(null)
  const [cycle, setCycle] = useState(2024)
  const [err, setErr] = useState('')
  useEffect(() => { api.presidential().then(setD).catch((e) => setErr(String(e))) }, [])
  const cands = NOMINEES[cycle] ?? []
  const view = useMemo(() => {
    if (!d) return null
    const by = (c: string) => d.funding.filter((f) => f.candidate === c && f.cycle === cycle)
    const tot = (c: string) => by(c).reduce((a, f) => a + f.amount, 0)
    const sectors = [...new Set(cands.flatMap((c) => by(c).map((f) => f.sector)))]
    const rows = sectors.map((s) => ({ sector: s, vals: cands.map((c) => (by(c).find((f) => f.sector === s)?.amount ?? 0) / (tot(c) || 1)), amts: cands.map((c) => by(c).find((f) => f.sector === s)?.amount ?? 0) }))
      .sort((a, b) => Math.max(...b.vals) - Math.max(...a.vals))
    const def = cands.map((c) => by(c).find((f) => f.sector === 'Defense & Aerospace')?.amount ?? 0)
    return { rows, totals: cands.map(tot), def }
  }, [d, cycle, cands.join('|')])
  if (err) return <div className="card hint">Could not load presidential data ({err}). Run pipeline step 37, then restart the server.</div>
  if (!d || !view) return <div className="card hint">Loading…</div>
  const cycles = [...new Set(d.funding.map((f) => f.cycle))].sort()
  return (
    <div className="page">
      <div className="card prose">
        <h2>The White House: who paid for the campaigns</h2>
        <p>
          A president acts through orders, appointments and vetoes rather than roll calls, so there is no vote record to set donors against. What can be shown is who paid for each campaign and its joint fundraising committees, and what industries those donors work in.
          The super PACs behind each nominee are on the <a href="#/outside">Outside money</a> page. What the administration did next to what it said is on the <a href="#/defense">Defense tab</a> (executive record).
        </p>
        <p className="hint">
          Counts itemized gifts of more than $200 from people and organisations, and gifts from PACs and other committees, to the campaign and joint fundraising committees listed in the pipeline (transfers between a candidate’s own committees are left out). Small-dollar gifts below the itemizing line are not public,
          so campaigns that rely on them (most of all through ActBlue and WinRed) look smaller here than they were. A donor’s industry comes from the employer they list.
        </p>
        <div className="seg" style={{ margin: '8px 0' }}>{cycles.map((c) => <button key={c} aria-pressed={cycle === c} onClick={() => setCycle(c)}>{c}</button>)}</div>
        <div className="scroll-x">
          <table className="data">
            <thead><tr><th style={{ textAlign: 'left' }}>Where the itemized money came from, {cycle}</th>{cands.map((c, i) => <th key={c}>{c}<div className="hint">{fmtMoney(view.totals[i])}</div></th>)}</tr></thead>
            <tbody>
              {view.rows.slice(0, 16).map((r) => (
                <tr key={r.sector} className={GROUP_NOTE.has(r.sector) ? 'hint' : undefined}>
                  <td style={{ textAlign: 'left' }}>{r.sector.replace('Nonprofits that do not disclose their donors', 'Nonprofits (their donors are hidden)')}</td>
                  {r.vals.map((v, i) => <td key={i}>{(100 * v).toFixed(1)}%<div className="hint">{fmtMoney(r.amts[i])}</div></td>)}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p style={{ marginTop: 8 }}>
          Employees and PACs of defense and aerospace companies gave {cands.map((c, i) => `${c} ${fmtMoney(view.def[i])} (${view.totals[i] ? (100 * view.def[i] / view.totals[i]).toFixed(2) : '0'}% of itemized money)`).join(', ')} in {cycle}.
          For scale, defense-industry PACs gave members of Congress about $183 million between 2005 and 2026 (Defense tab).
        </p>
        <div className="fh" style={{ marginTop: 10 }}>Employers whose staff gave the most, {cycle}</div>
        <div className="threecol">
          {cands.map((c) => (
            <div key={c}>
              <div className="hint">{c}</div>
              <ul className="facts">{d.employers.filter((e) => e.candidate === c && e.cycle === cycle).slice(0, 8).map((e) => <li key={e.employer}>{e.employer.length > 40 ? `${e.employer.slice(0, 38)}…` : e.employer} <span className="hint">· {fmtMoney(e.amount)}</span></li>)}</ul>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
