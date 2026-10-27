import { useEffect, useMemo, useState } from 'react'
import { api } from '../api'
import type { PledgeData } from '../types'
import { fmtMoney } from '../util'

const pct = (a: number, b: number) => (b > 0 ? `${((100 * a) / b).toFixed(1)}%` : '–')

/** What members promised about money, next to the money their campaigns took in and how they voted. */
export default function PledgesView({ onOpen }: { onOpen: (id: string) => void }) {
  const [d, setD] = useState<PledgeData | null>(null)
  const [err, setErr] = useState('')
  useEffect(() => { api.pledges().then(setD).catch((e) => setErr(String(e))) }, [])
  const byYear = useMemo(() => {
    if (!d) return []
    const ys = [...new Set(d.gifts.map((g) => g.year))].sort()
    return ys.map((y) => {
      const g = d.gifts.filter((x) => x.year === y)
      return { year: y, members: new Set(g.map((x) => x.bioguide)).size, amount: g.reduce((a, x) => a + x.amount, 0), signers: new Set(d.money.filter((m) => m.year === y).map((m) => m.bioguide)).size }
    })
  }, [d])
  const recipients = useMemo(() => {
    if (!d) return []
    const by = new Map<string, { id: string; name: string; party: string; state: string; total: number; recent: number; committees: Map<string, number> }>()
    for (const g of d.gifts) {
      const m = d.members.find((x) => x.bioguide === g.bioguide)
      if (!m) continue
      const e = by.get(g.bioguide) ?? { id: g.bioguide, name: m.name, party: m.party, state: m.state, total: 0, recent: 0, committees: new Map() }
      e.total += g.amount
      if (g.year >= 2023) e.recent += g.amount
      e.committees.set(g.committee, (e.committees.get(g.committee) ?? 0) + g.amount)
      by.set(g.bioguide, e)
    }
    return [...by.values()].sort((a, b) => b.recent - a.recent || b.total - a.total)
  }, [d])
  const grp = (k: string) => d?.votes.find((v) => v.grp === k)
  const src = d?.sources[0]
  if (err) return <div className="card hint">Could not load pledge data ({err}). Run pipeline step 36, then restart the server.</div>
  if (!d) return <div className="card hint">Loading…</div>
  const total = recipients.reduce((a, r) => a + r.total, 0)
  return (
    <div className="page">
      <div className="card prose">
        <h2>Promises and money: did the money follow the pledge?</h2>
        <h3>The No Fossil Fuel Money pledge</h3>
        <p>
          Candidates who sign promise not to knowingly accept contributions of more than $200 from fossil-fuel PACs, lobbyists or executives. The organisation behind it lists <strong>{d.members.length}</strong> current members of Congress as signers
          (<a href={src?.source_url} target="_blank" rel="noreferrer">its list</a>, read {src?.read_on}).
        </p>
        <ul>
          <li>
            <strong>{recipients.length} of {d.members.length}</strong> signers received at least one PAC gift from an oil, gas, coal or refining committee since 2019, <strong>{fmtMoney(total)}</strong> in all.
            Most gifts were $5,000 or less and came from natural-gas utilities and trade groups, fuel marketers and similar committees rather than the big oil companies.
          </li>
          <li>
            On the documented fossil-fuel votes since 2008 (members with at least five), the signers voted the industry’s way <strong>{pct(grp('signers')?.aligned ?? 0, grp('signers')?.n ?? 0)}</strong> of the time ({grp('signers')?.members} members), other Democrats <strong>{pct(grp('other Democrats')?.aligned ?? 0, grp('other Democrats')?.n ?? 0)}</strong> ({grp('other Democrats')?.members}) and Republicans <strong>{pct(grp('Republicans')?.aligned ?? 0, grp('Republicans')?.n ?? 0)}</strong> ({grp('Republicans')?.members}).
          </li>
        </ul>
        <p className="hint">
          What this can and cannot say. The list has no signing dates, so a gift before someone signed is not a broken pledge. Only PAC gifts are tested: executives and lobbyists are in the pledge but cannot be separated from other donors here.
          Gas utilities and fuel marketers are counted as fossil-fuel committees; clean-energy, ethanol and biodiesel committees, and non-coal mining committees, are not. The names on the list were read from the organisation’s page by an automated reader, so check them against the page.
        </p>
        <div className="fh">PAC gifts from fossil-fuel committees to signers, by year</div>
        <div className="scroll-x">
          <table className="data">
            <thead><tr><th style={{ textAlign: 'left' }}>Year</th><th>Signers in office</th><th>Signers who got a gift</th><th>Total</th></tr></thead>
            <tbody>{byYear.map((y) => <tr key={y.year}><td style={{ textAlign: 'left' }}>{y.year}</td><td>{y.signers}</td><td>{y.members}</td><td>{fmtMoney(y.amount)}</td></tr>)}</tbody>
          </table>
        </div>
      </div>

      <div className="card">
        <h2>Signers who received fossil-fuel PAC gifts</h2>
        <div className="sub">Since 2019, newest first. Click a name for the full case file.</div>
        <div className="scroll-x">
          <table className="data">
            <thead><tr><th style={{ textAlign: 'left' }}>Member</th><th>Since 2023</th><th>Since 2019</th><th style={{ textAlign: 'left' }}>From</th></tr></thead>
            <tbody>
              {recipients.map((r) => (
                <tr key={r.id} className="clickrow" onClick={() => onOpen(r.id)}>
                  <td style={{ textAlign: 'left' }}><span className={`party ${r.party}`}><i />{r.party}</span> {r.name} <span className="hint">· {r.state}</span></td>
                  <td>{r.recent ? fmtMoney(r.recent) : '–'}</td><td>{fmtMoney(r.total)}</td>
                  <td style={{ textAlign: 'left', maxWidth: 420 }} className="hint">{[...r.committees.entries()].sort((a, b) => b[1] - a[1]).slice(0, 3).map(([c, a]) => `${c.replace(/ POLITICAL ACTION COMMITTEE| PAC|\(.*\)/gi, '').trim()} ${fmtMoney(a)}`).join('; ')}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <div className="card prose">
        <h2>Other promises</h2>
        <ul>
          <li>The defense-industry statements (“no new wars”, “no money from defense”) set against each member’s record are on the <a href="#/defense">Defense tab</a>.</li>
          <li>Corporate-PAC pledges: the organisation that tracks them publishes its list only as a web page that changes, so it is not loaded. Giving this project a dated copy of the list would let it be tested the same way.</li>
        </ul>
      </div>
    </div>
  )
}
