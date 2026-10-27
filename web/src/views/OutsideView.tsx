import { useEffect, useMemo, useState } from 'react'
import { api } from '../api'
import type { OutsideOverview } from '../types'
import { fmtMoney } from '../util'

const bn = (v: number) => `$${(v / 1e9).toFixed(2)}B`
const pc = (v: number) => `${Math.round(100 * v)}%`
const HIDDEN = new Set(['Other political committees', 'Nonprofits that do not disclose their donors', 'Not identifiable (retired / unemployed / no employer)', 'Other / unclassified'])

/** Outside spending: who spends for and against members of Congress, and who funds the spenders. */
export default function OutsideView() {
  const [ov, setOv] = useState<OutsideOverview | null>(null)
  const [err, setErr] = useState('')
  useEffect(() => { api.outside().then(setOv).catch((e) => setErr(String(e))) }, [])
  const total = useMemo(() => (ov ? ov.cycles.reduce((a, c) => a + c.amount, 0) : 0), [ov])
  const groups = useMemo(() => {
    if (!ov) return []
    const by = new Map<string, number>()
    for (const c of ov.coverage) by.set(c.grp, (by.get(c.grp) ?? 0) + c.amount)
    const sum = [...by.values()].reduce((a, b) => a + b, 0) || 1
    return [...by.entries()].map(([grp, amount]) => ({ grp, amount, share: amount / sum })).sort((a, b) => b.amount - a.amount)
  }, [ov])
  if (err) return <div className="card hint">Could not load outside-spending data ({err}). Run pipeline steps 30 and 31, then restart the server.</div>
  return (
    <div className="page">
      <div className="card prose">
        <h2>Outside money: who spends for and against members, and who pays for it</h2>
        {ov ? (
          <>
            <p>
              Since 2010, super PACs, party committees and other outside groups have reported <strong>{bn(total)}</strong> of independent spending for or against members of Congress (house and Senate races in this data). They cannot give a candidate money or coordinate with the campaign,
              but they decide a lot of who wins. Their donors have no limit on what they give. This page follows the money one step back: who funds each spender.
            </p>
            <h3>How much of it can be traced to an industry</h3>
            <div className="bars">
              {groups.map((g) => (
                <div key={g.grp} className="hrow" style={{ gridTemplateColumns: 'minmax(110px, 260px) minmax(40px, 1fr) minmax(80px, 120px)' }}>
                  <span className="nm">{g.grp}</span><span className="track"><i style={{ width: `${100 * g.share}%`, background: g.grp.startsWith('Sorted') ? 'var(--s2)' : 'var(--muted)' }} /></span><span className="amt">{pc(g.share)} · {bn(g.amount)}</span>
                </div>
              ))}
            </div>
            <p className="hint">
              Each spender’s spending is split the way its receipts were split that cycle, so this is an attribution, not a trace of individual dollars. An individual’s industry comes from the employer they list, which is not always where their wealth comes from.
              Gifts through nonprofits and other committees are shown as such; we do not look through them. That is exactly what “dark money” means: the first donor is visible, the original source is not.
            </p>
          </>
        ) : <p className="hint">Loading…</p>}
      </div>

      <div className="card">
        <h2>The 30 biggest outside spenders</h2>
        <div className="sub">Spending is on members of Congress only. “Funded mostly by” is each spender’s receipts by who gave, over all cycles. Named donors are organisations and people who gave $100,000 or more.</div>
        <div className="scroll-x">
          <table className="data">
            <thead><tr><th style={{ textAlign: 'left' }}>Spender</th><th>For</th><th>Against</th><th style={{ textAlign: 'left' }}>Funded mostly by</th><th style={{ textAlign: 'left' }}>Largest named donors</th></tr></thead>
            <tbody>
              {(ov?.spenders ?? []).map((s) => (
                <tr key={s.cmte_id}>
                  <td style={{ textAlign: 'left' }}>{s.name}<div className="hint">{fmtMoney(s.funding_total)} raised</div></td>
                  <td>{s.support ? fmtMoney(s.support) : '–'}</td><td>{s.oppose ? fmtMoney(s.oppose) : '–'}</td>
                  <td style={{ textAlign: 'left', maxWidth: 260 }}>{s.mix.slice(0, 4).map((m) => <div key={m.sector} className={HIDDEN.has(m.sector) ? 'hint' : undefined}>{pc(m.share)} {m.sector.replace('Nonprofits that do not disclose their donors', 'nonprofits (donors hidden)').replace(', Insurance & Real Estate', '').replace(' & Natural Resources', '')}</div>)}</td>
                  <td style={{ textAlign: 'left', maxWidth: 320 }}>{s.donors.slice(0, 4).map((d) => <div key={d.name}>{d.name.length > 46 ? `${d.name.slice(0, 44)}…` : d.name} <span className="hint">· {fmtMoney(d.amount)}</span></div>)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}
