import { useMemo, useState } from 'react'
import type { Definitions } from '../types'

const PAGE = 100

/** Every vote with a documented industry side, with the source for that side. Search, filter and download. */
export default function CodebookView({ defs }: { defs: Definitions }) {
  const [q, setQ] = useState('')
  const [sector, setSector] = useState('')
  const [level, setLevel] = useState('')
  const [shown, setShown] = useState(PAGE)
  const label = (r: Definitions['direction'][number]) => (r.subsector ? r.subsector.replace('_', ' ') : r.sector)
  const sectors = useMemo(() => [...new Set(defs.direction.map(label))].sort(), [defs])
  const levels = useMemo(() => [...new Set(defs.direction.map((r) => r.evidence_level))].sort(), [defs])
  const rows = useMemo(() => {
    const t = q.trim().toLowerCase()
    return defs.direction
      .filter((r) => (!sector || label(r) === sector) && (!level || r.evidence_level === level) && (!t || `${r.bill} ${r.evidence} ${label(r)}`.toLowerCase().includes(t)))
      .sort((a, b) => b.date.localeCompare(a.date))
  }, [defs, q, sector, level])
  const votes = useMemo(() => new Set(rows.map((r) => `${r.congress}-${r.chamber}-${r.rollnumber}`)).size, [rows])

  const download = () => {
    const esc = (v: string) => `"${String(v ?? '').replace(/"/g, '""')}"`
    const head = ['date', 'chamber', 'bill', 'industry', 'helps_if', 'evidence_level', 'evidence', 'source_url']
    const body = rows.map((r) => [r.date, r.chamber, r.bill, label(r), r.helps_vote, r.evidence_level, r.evidence, r.source_url].map(esc).join(','))
    const url = URL.createObjectURL(new Blob([[head.join(','), ...body].join('\n')], { type: 'text/csv' }))
    const a = document.createElement('a')
    a.href = url
    a.download = 'vote_codebook.csv'
    a.click()
    URL.revokeObjectURL(url)
  }

  return (
    <div className="page">
      <div className="card">
        <h2>Vote codebook: which side each industry wanted, and where we got it</h2>
        <div className="sub">
          Every vote where the industry’s side is documented rather than inferred. “Helps if” is the vote that helps the industry. Levels: <strong>documented</strong> (the industry’s or its trade group’s own statement),
          <strong> reported</strong> (secondary coverage), <strong>scorecard</strong> (a published key-vote list), <strong>fiscal</strong> (the vote adds or cuts money for the industry, by rule). {votes} votes in {rows.length} industry-vote rows match your filters.
        </div>
        <div className="filterbar" style={{ display: 'flex', gap: 8, flexWrap: 'wrap', margin: '8px 0' }}>
          <input className="search" placeholder="Search bill, source or industry…" value={q} onChange={(e) => { setQ(e.target.value); setShown(PAGE) }} aria-label="Search the codebook" />
          <select value={sector} onChange={(e) => { setSector(e.target.value); setShown(PAGE) }} aria-label="Industry"><option value="">All industries</option>{sectors.map((s) => <option key={s}>{s}</option>)}</select>
          <select value={level} onChange={(e) => { setLevel(e.target.value); setShown(PAGE) }} aria-label="Evidence level"><option value="">All evidence levels</option>{levels.map((s) => <option key={s}>{s}</option>)}</select>
          <button className="iconbtn" onClick={download}>Download CSV</button>
        </div>
        <div className="scroll-x">
          <table className="data">
            <thead><tr><th style={{ textAlign: 'left' }}>Vote</th><th style={{ textAlign: 'left' }}>Industry</th><th>Helps if</th><th style={{ textAlign: 'left' }}>Evidence</th><th>Level</th></tr></thead>
            <tbody>
              {rows.slice(0, shown).map((r, i) => (
                <tr key={i}>
                  <td style={{ textAlign: 'left' }}>{r.bill} {r.chamber.slice(0, 3)} {r.date}</td>
                  <td style={{ textAlign: 'left' }}>{label(r)}</td>
                  <td>{r.helps_vote}</td>
                  <td style={{ textAlign: 'left' }}><a href={r.source_url} target="_blank" rel="noopener noreferrer">{r.evidence}</a></td>
                  <td>{r.evidence_level}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {shown < rows.length && <button className="iconbtn" style={{ marginTop: 8 }} onClick={() => setShown((n) => n + PAGE)}>Show {Math.min(PAGE, rows.length - shown)} more of {rows.length - shown}</button>}
      </div>
    </div>
  )
}
