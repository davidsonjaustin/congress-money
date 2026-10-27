import { useEffect, useMemo, useState } from 'react'
import { api } from '../api'
import type { LobOverview, LobSector, RevolvingOverview } from '../types'
import Line from '../charts/Line'
import type { Series } from '../charts/Line'

const bn = (v: number) => `$${(v / 1e9).toFixed(v >= 1e10 ? 1 : 2)}B`
const mn = (v: number) => (v >= 1e9 ? bn(v) : `$${(v / 1e6).toFixed(v >= 1e8 ? 0 : 1)}M`)
const NOT_AN_INDUSTRY = new Set(['Ideological / Single-Issue', 'Government / Public sector', 'Education', 'Lawyers & Lobbyists'])
const COLORS = ['var(--s1)', 'var(--s2)', 'var(--s3)', 'var(--s4, #6b7bb3)', 'var(--s5)', 'var(--s6)', 'var(--s7)', 'var(--s8)']
const LATEST = 2025       // the latest complete year of filings

/** Lobbying for every industry: how much, next to what the same industries give campaigns and take in federal contracts, and which bills they worked. */
export default function LobbyingView({ onCompany }: { onCompany?: (slug: string) => void }) {
  const [ov, setOv] = useState<LobOverview | null>(null)
  const [sel, setSel] = useState('Health')
  const [det, setDet] = useState<LobSector | null>(null)
  const [err, setErr] = useState('')
  const [rv, setRv] = useState<RevolvingOverview | null>(null)
  useEffect(() => { api.revolving().then(setRv).catch(() => undefined) }, [])
  useEffect(() => { api.lobOverview().then(setOv).catch((e) => setErr(String(e))) }, [])
  useEffect(() => { setDet(null); api.lobSector(sel).then(setDet).catch(() => undefined) }, [sel])

  const rows = useMemo(() => {
    if (!ov) return []
    const m = new Map(ov.money.filter((r) => r.year === LATEST).map((r) => [r.sector, r]))
    return ov.years.filter((r) => r.year === LATEST && !NOT_AN_INDUSTRY.has(r.sector))
      .map((r) => ({ sector: r.sector, lobbying: r.spend, clients: r.clients, pac: m.get(r.sector)?.pac ?? 0, indiv: m.get(r.sector)?.indiv ?? 0, contracts: m.get(r.sector)?.contracts ?? 0 }))
      .sort((a, b) => b.lobbying - a.lobbying)
  }, [ov])
  const top8 = rows.slice(0, 8).map((r) => r.sector)
  const series: Series[] = useMemo(() => (ov ? top8.map((s, i) => ({
    name: s.replace(', Insurance & Real Estate', '').replace(' & Natural Resources', ''), color: COLORS[i],
    pts: ov.years.filter((r) => r.sector === s && r.year >= 2008 && r.year <= LATEST).map((r) => [r.year, r.spend / 1e6] as [number, number]),
  })) : []), [ov, top8.join('|')])
  const cover = ov?.coverage.find((c) => c.year === LATEST)
  const total = cover ? cover.labelled + cover.unlabelled : 0
  const clientSeries: Series[] = useMemo(() => {
    if (!det) return []
    const names = [...new Set(det.series.map((r) => r.name))]
    return names.map((n, i) => ({ name: n.length > 30 ? `${n.slice(0, 29)}…` : n, color: COLORS[i % 8], pts: det.series.filter((r) => r.name === n && r.year >= 2008 && r.year <= LATEST).map((r) => [r.year, r.spend / 1e6] as [number, number]) }))
  }, [det])

  if (err) return <div className="card hint">Could not load lobbying data ({err}). Run pipeline step 32, then restart the server.</div>
  return (
    <div className="page">
      <div className="card prose">
        <h2>Lobbying: who spends, on what, and how it compares to what they give and take</h2>
        {ov && cover ? (
          <p>
            Federal lobbying disclosures report <strong>{bn(total)}</strong> of spending in {LATEST}. We can put <strong>{Math.round((100 * cover.labelled) / total)}%</strong> of it in an industry from the client’s name (a hand-checked list covers the
            largest ~1,000 clients whose names the rules missed). The rest is spread over tens of thousands of smaller clients.
            {rows[0] ? <> The biggest is <strong>{rows[0].sector}</strong> at <strong>{bn(rows[0].lobbying)}</strong>.</> : null}
          </p>
        ) : <p className="hint">Loading…</p>}
        <p className="hint">
          Spending is what Senate filings report: fees paid to outside firms, or an organisation’s own in-house costs, with the latest filing kept for each period. It is rounded by the filers, and a filing does not say how much went to which bill.
          Lobbying is legal and disclosed; the question here is how large it is next to campaign money and contracts, and what it was aimed at.
        </p>
        <Line series={series} fmt={(v) => `$${v.toFixed(0)}M`} height={230} />
      </div>

      <div className="card">
        <h2>Each industry in {LATEST}: lobbying, campaign money and federal contracts</h2>
        <div className="sub">
          Lobbying is Senate disclosures. PAC gifts and employee gifts go to members of Congress (FEC). Contracts are prime awards to the ~235 largest recipients each year, grouped by industry from the recipient’s name, so they are a floor for industries whose
          work is mostly small awards. Click an industry to see its clients, issues and bills.
        </div>
        <div className="scroll-x">
          <table className="data">
            <thead><tr><th style={{ textAlign: 'left' }}>Industry</th><th>Lobbying</th><th>PAC gifts to members</th><th>Employee gifts to members</th><th>Federal contracts (top recipients)</th><th>Lobbying per $1 of PAC gifts</th></tr></thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.sector} className="clickrow" aria-selected={sel === r.sector} style={sel === r.sector ? { background: 'var(--ghost)' } : undefined} onClick={() => setSel(r.sector)}>
                  <td style={{ textAlign: 'left' }}>{r.sector}</td><td>{mn(r.lobbying)}</td><td>{r.pac ? mn(r.pac) : '–'}</td><td>{r.indiv ? mn(r.indiv) : '–'}</td>
                  <td>{r.contracts ? bn(r.contracts) : '–'}</td><td>{r.pac > 0 ? `$${(r.lobbying / r.pac).toFixed(1)}` : '–'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="hint" style={{ marginTop: 8 }}>
          Ideological and single-issue groups, universities and governments also lobby but are not shown as industries. {LATEST + 1} filings are still coming in, so the latest complete year is {LATEST}.
        </div>
      </div>


      {rv && (
        <div className="card">
          <h2>The revolving door, across industries</h2>
          <div className="sub">
            For the {rv.per_company.length} biggest lobbying companies outside defense, we read every lobbyist named in their Senate filings since 2008 and the government job each one reports having held (the “covered position” a lobbyist must disclose).
            “Congress” counts congressional staff and members; “executive” counts agencies, departments and the White House. Free-text job titles are sorted by keyword, so treat the shares as close estimates.
          </div>
          <div className="scroll-x">
            <table className="data">
              <thead><tr><th style={{ textAlign: 'left' }}>Industry</th><th>Companies read</th><th>Lobbyists</th><th>Report a past government job</th><th>Worked in Congress</th><th>Worked in the executive branch</th></tr></thead>
              <tbody>
                {rv.by_sector.map((s) => (
                  <tr key={s.sector}><td style={{ textAlign: 'left' }}>{s.sector}</td><td>{s.companies}</td><td>{s.lobbyists.toLocaleString()}</td>
                    <td>{Math.round((100 * s.with_position) / s.lobbyists)}%</td><td>{Math.round((100 * s.congress_roles) / s.lobbyists)}%</td><td>{Math.round((100 * s.executive_roles) / s.lobbyists)}%</td></tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="hint" style={{ marginTop: 6 }}>Defense contractors, read the same way, are on the <a href="#/defense">Defense tab</a>. A lobbyist who lobbies for several companies is counted once for each.</div>
        </div>
      )}

      <div className="card">
        <h2>{sel}</h2>
        {!det ? <div className="hint">Loading…</div> : (
          <>
            <div className="threecol">
              <div>
                <div className="fh">Biggest clients, 2008 to now</div>
                <ul className="facts">
                  {(ov?.top_clients[sel] ?? []).slice(0, 10).map((c) => (
                    <li key={c.client_id}>{onCompany && c.slug ? <a onClick={() => onCompany(c.slug!)} style={{ cursor: 'pointer' }}>{c.name}</a> : c.name}: <strong>{mn(c.spend)}</strong> <span className="hint">· {c.recent ? `${mn(c.recent)} since 2023` : 'none since 2023'}</span></li>
                  ))}
                </ul>
              </div>
              <div>
                <div className="fh">What they lobby on (filings naming each issue, 2018 on)</div>
                <ul className="facts">
                  {det.issues.map((i) => <li key={i.code}>{i.name} <span className="hint">· {i.filings.toLocaleString()} filings</span></li>)}
                </ul>
              </div>
            </div>
            <div className="fh" style={{ marginTop: 10 }}>The five biggest clients’ spending, $M a year</div>
            <Line series={clientSeries} fmt={(v) => `$${v.toFixed(0)}M`} />
            <div className="fh" style={{ marginTop: 10 }}>Bills this industry’s clients lobbied most, and what happened</div>
            <div className="sub">Ranked by how many different clients named the bill in their filings. “Vote” is the last passage vote in each chamber we have; many bills never reached a vote.</div>
            <div className="scroll-x">
              <table className="data">
                <thead><tr><th style={{ textAlign: 'left' }}>Bill</th><th>Clients</th><th>House</th><th>Senate</th><th>Became law</th></tr></thead>
                <tbody>
                  {det.bills.map((b) => (
                    <tr key={`${b.congress}-${b.bill}`}>
                      <td style={{ textAlign: 'left', maxWidth: 480 }}>{b.title ?? b.bill}<div className="hint">{b.bill} · {b.congress}th Congress</div></td>
                      <td>{b.clients}</td><td>{b.house_vote ?? '–'}</td><td>{b.senate_vote ?? '–'}</td><td>{b.became_law == null ? '–' : b.became_law ? 'Yes' : 'No'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}
      </div>
    </div>
  )
}
