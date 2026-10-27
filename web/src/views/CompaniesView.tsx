import { useEffect, useMemo, useState } from 'react'
import { api } from '../api'
import type { CompanyDetail, CompanyRevolving, CompanyRow } from '../types'
import Line from '../charts/Line'
import type { Series } from '../charts/Line'
import { fmtMoney } from '../util'

const mn = (v: number) => (v >= 1e9 ? `$${(v / 1e9).toFixed(2)}B` : v >= 1e6 ? `$${(v / 1e6).toFixed(v >= 1e8 ? 0 : 1)}M` : `$${Math.round(v / 1e3)}K`)

/** All the companies we follow: lobbying, campaign money from the company's PAC and employees, and government contracts. */
export default function CompaniesView({ slug, onOpenCompany, onOpenMember }: { slug?: string; onOpenCompany: (s: string) => void; onOpenMember: (id: string) => void }) {
  const [list, setList] = useState<CompanyRow[]>([])
  const [q, setQ] = useState('')
  const [sector, setSector] = useState('')
  useEffect(() => { api.companies().then(setList).catch(() => undefined) }, [])
  if (slug) return <Detail slug={slug} onBack={() => { location.hash = '#/companies' }} onOpenMember={onOpenMember} />
  const sectors = [...new Set(list.map((c) => c.sector))].sort()
  const rows = list.filter((c) => (!sector || c.sector === sector) && (!q.trim() || c.name.toLowerCase().includes(q.trim().toLowerCase())))
  return (
    <div className="page">
      <div className="card">
        <h2>Companies: what each spends on Washington, and what it takes from it</h2>
        <div className="sub">
          About {list.length} of the largest lobbying spenders, matched by name across Senate lobbying filings, PAC gifts, employees’ itemized gifts and federal contracts. Totals are 2008 on. Name matching can miss a subsidiary with a different name;
          each company page lists what it matched. Contracts cover the ~235 largest recipients each fiscal year.
        </div>
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', margin: '8px 0' }}>
          <input className="search" style={{ maxWidth: 280 }} placeholder="Find a company…" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Find a company" />
          <select value={sector} onChange={(e) => setSector(e.target.value)} aria-label="Industry"><option value="">All industries</option>{sectors.map((s) => <option key={s}>{s}</option>)}</select>
        </div>
        <div className="scroll-x">
          <table className="data">
            <thead><tr><th style={{ textAlign: 'left' }}>Company</th><th style={{ textAlign: 'left' }}>Industry</th><th>Lobbying, 2008 on</th><th>PAC gifts</th><th>Employee gifts</th><th>Federal contracts</th></tr></thead>
            <tbody>
              {rows.map((c) => (
                <tr key={c.slug} className="clickrow" onClick={() => onOpenCompany(c.slug)}>
                  <td style={{ textAlign: 'left' }}>{c.name}</td><td style={{ textAlign: 'left' }} className="hint">{c.sector.replace(', Insurance & Real Estate', '').replace(' & Natural Resources', '')}</td>
                  <td>{c.lobbying ? mn(c.lobbying) : '–'}</td><td>{c.pac ? mn(c.pac) : '–'}</td><td>{c.indiv ? mn(c.indiv) : '–'}</td><td>{c.contracts ? mn(c.contracts) : '–'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}

function Detail({ slug, onBack, onOpenMember }: { slug: string; onBack: () => void; onOpenMember: (id: string) => void }) {
  const [d, setD] = useState<CompanyDetail | null>(null)
  const [err, setErr] = useState('')
  const [rv, setRv] = useState<CompanyRevolving | null>(null)
  useEffect(() => { setRv(null); api.companyRevolving(slug).then(setRv).catch(() => undefined) }, [slug])
  useEffect(() => { setD(null); setErr(''); api.company(slug).then(setD).catch((e) => setErr(String(e))) }, [slug])
  const sum = (k: 'lobbying' | 'pac' | 'indiv' | 'contracts') => (d ? d.years.reduce((a, y) => a + (y[k] ?? 0), 0) : 0)
  const series: Series[] = useMemo(() => (d ? [
    { name: 'Lobbying', color: 'var(--s2)', pts: d.years.filter((y) => y.year <= 2025).map((y) => [y.year, (y.lobbying ?? 0) / 1e6] as [number, number]) },
    { name: 'PAC gifts to members', color: 'var(--s1)', pts: d.years.filter((y) => y.year <= 2025).map((y) => [y.year, (y.pac ?? 0) / 1e6] as [number, number]) },
    { name: 'Employee gifts to members', color: 'var(--s3)', pts: d.years.filter((y) => y.year <= 2025).map((y) => [y.year, (y.indiv ?? 0) / 1e6] as [number, number]) },
  ] : []), [d])
  const contractSeries: Series[] = useMemo(() => (d && sum('contracts') > 0 ? [{ name: 'Federal prime contracts', color: 'var(--s4, #6b7bb3)', pts: d.years.filter((y) => y.year <= 2025).map((y) => [y.year, (y.contracts ?? 0) / 1e9] as [number, number]) }] : []), [d])
  if (err) return <div className="card hint">No such company. <a onClick={onBack} style={{ cursor: 'pointer' }}>Back to the list</a></div>
  if (!d) return <div className="card hint">Loading…</div>
  const lob = sum('lobbying'), pac = sum('pac'), emp = sum('indiv'), con = sum('contracts')
  const rep = d.reported[d.reported.length - 1]
  return (
    <div className="page">
      <div className="card prose">
        <div className="hint"><a onClick={onBack} style={{ cursor: 'pointer' }}>← All companies</a></div>
        <h2>{d.company.name}</h2>
        <div className="sub">{d.company.sector}</div>
        <p>
          Since 2008 the company has reported <strong>{mn(lob)}</strong> in lobbying; its PAC gave members of Congress <strong>{mn(pac)}</strong> and people who list it as their employer gave <strong>{mn(emp)}</strong>.
          {con > 0 ? <> The federal government awarded it <strong>{mn(con)}</strong> in prime contracts (among the largest recipients each year).</> : null}
          {pac + emp > 0 ? <> That is about <strong>${(lob / (pac + emp)).toFixed(1)}</strong> of lobbying for every $1 given to members.</> : null}
        </p>
        <Line series={series} fmt={(v) => `$${v.toFixed(0)}M`} height={210} />
        {contractSeries.length > 0 && <><div className="fh" style={{ marginTop: 8 }}>Federal prime contracts, $B a year</div><Line series={contractSeries} fmt={(v) => `$${v.toFixed(0)}B`} height={150} /></>}
        <p className="hint">
          Lobbying is Senate disclosures (fees to outside firms or in-house costs). PAC gifts are FEC type 24K. Employee gifts are itemized gifts of $200 or more to members’ campaign committees from people listing the company as their employer.
          {d.pacs.length > 0 ? <> PAC counted: {d.pacs.join('; ')}.</> : <> No company PAC was found by name.</>} 2026 is left out because filings are still coming in.
        </p>
      </div>

      <div className="card">
        <div className="threecol">
          <div>
            <div className="fh">What it lobbies on (filings naming each issue, 2018 on)</div>
            <ul className="facts">{d.issues.map((i) => <li key={i.code}>{i.name} <span className="hint">· {i.filings} filings</span></li>)}</ul>
          </div>
          <div>
            <div className="fh">Members who received the most from its PAC and employees</div>
            <ul className="facts">
              {d.members.map((m) => (
                <li key={m.bioguide}><span className={`party ${m.party}`}><i />{m.party}</span> <a onClick={() => onOpenMember(m.bioguide)} style={{ cursor: 'pointer' }}>{m.name}</a> <span className="hint">· {m.state}{m.chamber === 'Senate' ? ' Sen.' : ''}</span>: <strong>{fmtMoney(m.pac + m.indiv)}</strong> <span className="hint">({fmtMoney(m.pac)} PAC, {fmtMoney(m.indiv)} employees)</span></li>
              ))}
            </ul>
          </div>
        </div>
        {rv?.available && (rv.lobbyists ?? 0) > 0 && (
          <div style={{ marginTop: 10 }}>
            <div className="fh">Who lobbies for it, and where they worked before</div>
            <p style={{ margin: '4px 0' }}>
              <strong>{rv.lobbyists}</strong> different people appear as lobbyists in its filings since 2008. <strong>{Math.round((100 * (rv.with_position ?? 0)) / (rv.lobbyists ?? 1))}%</strong> report a past government job, <strong>{Math.round((100 * (rv.congress_roles ?? 0)) / (rv.lobbyists ?? 1))}%</strong> in Congress and <strong>{Math.round((100 * (rv.executive_roles ?? 0)) / (rv.lobbyists ?? 1))}%</strong> in the executive branch.
            </p>
            <ul className="facts">{(rv.examples ?? []).slice(0, 5).map((e, i) => <li key={i}>{e.lobbyist}: <span className="hint">{e.pos.length > 140 ? `${e.pos.slice(0, 138)}…` : e.pos}</span></li>)}</ul>
          </div>
        )}
        <div className="fh" style={{ marginTop: 10 }}>Bills named in the most of its lobbying filings</div>
        <div className="scroll-x">
          <table className="data">
            <thead><tr><th style={{ textAlign: 'left' }}>Bill</th><th>Filings naming it</th><th>Became law</th></tr></thead>
            <tbody>{d.bills.map((b) => <tr key={`${b.congress}-${b.bill}`}><td style={{ textAlign: 'left', maxWidth: 520 }}>{b.title ?? b.bill}<div className="hint">{b.bill} · {b.congress}th Congress</div></td><td>{b.filings}</td><td>{b.became_law == null ? '–' : b.became_law ? 'Yes' : 'No'}</td></tr>)}</tbody>
          </table>
        </div>
        {d.company.in_defense && (
          <div className="hint" style={{ marginTop: 8 }}>
            This is a defense or government-services contractor. Its votes, local contracts and lobbyists are on the <a href="#/defense">Defense tab</a>.
            {rep ? <> Share of revenue from the US government, from its own annual report: <strong>{Math.round(100 * rep.share)}%</strong> ({rep.year}) <a href={rep.source_url} target="_blank" rel="noreferrer">10-K</a>.</> : null}
          </div>
        )}
      </div>
    </div>
  )
}
