import { useEffect, useState } from 'react'
import { api } from '../api'
import type { TradesOverview } from '../types'
import Line from '../charts/Line'
import { fmtMoney } from '../util'

const range = (lo: number, hi: number) => `${fmtMoney(lo)} – ${fmtMoney(hi)}`

/** Stock trades House members reported under the STOCK Act. */
export default function TradesView({ onOpen }: { onOpen: (id: string) => void }) {
  const [d, setD] = useState<TradesOverview | null>(null)
  const [err, setErr] = useState('')
  useEffect(() => { api.trades().then(setD).catch((e) => setErr(String(e))) }, [])
  if (err) return <div className="card hint">Could not load trade data ({err}). Run pipeline steps 35 and 39, then restart the server.</div>
  if (!d) return <div className="card hint">Loading…</div>
  const tot = d.sectors.reduce((a, s) => a + s.trades, 0)
  const rate = (from: number, to: number) => { const r = d.coverage.parse_by_year.filter((y) => y.year >= from && y.year <= to); const e = r.reduce((a, y) => a + y.expected, 0); return e ? Math.round((100 * r.reduce((a, y) => a + y.parsed, 0)) / e) : 0 }
  return (
    <div className="page">
      <div className="card prose">
        <h2>Stock trades by members of the House</h2>
        <p>
          The STOCK Act makes members report trades by themselves, their spouses and dependent children within 45 days. We read <strong>{d.coverage.reports.toLocaleString()}</strong> reports filed since 2014 and found <strong>{tot.toLocaleString()}</strong> trades.
          Values are reported only as ranges (for example $15,001 to $50,000), so every total below is a low and a high figure, never one number.
        </p>
        <p className="hint">
          House only: the Senate’s disclosure site makes every visitor accept its terms before showing anything, which this project does not do on a person’s behalf. We read about {rate(2021, 2026)}% of the transaction lines in reports filed since 2021 and about {rate(2014, 2020)}% before that (older layouts, scans and corrupt files are the rest), so totals are a floor. {d.coverage.unmatched} filer names could not be matched to one member and are left out.
          A trade is not wrongdoing, and an index fund or a spouse’s broker may place trades the member did not choose. The question here is how often members trade in the industries whose bills they vote on and whose PACs fund them.
        </p>
        <Line series={[{ name: 'Trades reported per year', color: 'var(--s2)', pts: d.years.filter((y) => y.year >= 2014 && y.year <= 2025).map((y) => [y.year, y.trades] as [number, number]) }]} fmt={(v) => v.toFixed(0)} height={170} />
      </div>

      <div className="card">
        <h2>By industry</h2>
        <div className="scroll-x">
          <table className="data">
            <thead><tr><th style={{ textAlign: 'left' }}>Industry of the stock</th><th>Trades</th><th>Members</th><th>Amount, low to high</th></tr></thead>
            <tbody>{d.sectors.map((s) => <tr key={s.sector}><td style={{ textAlign: 'left' }}>{s.sector}</td><td>{s.trades.toLocaleString()}</td><td>{s.members}</td><td>{range(s.lo, s.hi)}</td></tr>)}</tbody>
          </table>
        </div>
        <div className="hint" style={{ marginTop: 6 }}>Industry comes from the company’s SEC industry code (funds, ETFs and bonds are grouped separately). “Unclassified” is a company we could not place.</div>
      </div>

      <div className="card">
        <div className="threecol">
          <div>
            <h2>Most trades since 2019</h2>
            <ul className="facts">{d.top.slice(0, 15).map((m) => <li key={m.bioguide}><span className={`party ${m.party}`}><i />{m.party}</span> <a onClick={() => onOpen(m.bioguide)} style={{ cursor: 'pointer' }}>{m.name}</a> <span className="hint">· {m.state}</span>: {m.trades.toLocaleString()} trades <span className="hint">({range(m.lo, m.hi)})</span></li>)}</ul>
          </div>
          <div>
            <h2>Most trades in defense contractors</h2>
            <ul className="facts">{d.defense.map((m) => <li key={m.bioguide}><span className={`party ${m.party}`}><i />{m.party}</span> <a onClick={() => onOpen(m.bioguide)} style={{ cursor: 'pointer' }}>{m.name}</a> <span className="hint">· {m.state}</span>: {m.trades} trades <span className="hint">({m.buys} buys, {m.sells} sells; {range(m.lo, m.hi)}){m.tickers ? ` · ${m.tickers.split(' ').slice(0, 6).join(', ')}` : ''}</span></li>)}</ul>
          </div>
        </div>
      </div>
    </div>
  )
}
