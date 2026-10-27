import { useEffect, useMemo, useState } from 'react'
import { api } from '../api'
import type { AllVotesSummary, TopVotes } from '../types'

const pct = (v: number | null | undefined, d = 1) => (v == null ? '–' : `${(100 * v).toFixed(d)}%`)
const NOT_INDUSTRY = ['Candidate committee', 'Leadership PAC', 'Ideological / Single-Issue / Unsorted', 'Business (sector not yet assigned)']
const DOSE: Record<string, string> = { '1': 'Under $1K', '2': '$1K to $10K', '3': '$10K to $50K', '4': '$50K to $200K', '5': '$200K or more' }
const NAMES: Record<string, string> = { Labor: 'Labor unions', 'oil gas': 'Oil and gas', 'coal mining': 'Coal mining', 'electric utilities': 'Electric utilities', 'physicians clinicians': 'Physicians and clinicians' }
const nice = (l: string) => NAMES[l] ?? l.replace(/^./, (c) => c.toUpperCase())

export default function AllVotesView() {
  const [sum, setSum] = useState<AllVotesSummary | null>(null)
  const [label, setLabel] = useState('oil gas')
  const [top, setTop] = useState<TopVotes | null>(null)
  const [limit, setLimit] = useState(25)

  useEffect(() => { api.allVotesSummary().then(setSum).catch(() => undefined) }, [])
  useEffect(() => { setTop(null); api.allVotesTop(label, 3.13, limit).then(setTop).catch(() => undefined) }, [label, limit])

  const industries = useMemo(() => (sum ? sum.industries.filter((r) => !NOT_INDUSTRY.includes(r.label)).sort((a, b) => (b.link_before ?? 0) - (a.link_before ?? 0)) : []), [sum])
  const lead = industries.filter((r) => (r.link_before ?? 0) - (r.link_after ?? 0) >= 0.01)
  const tie = industries.filter((r) => (r.link_before ?? 0) - (r.link_after ?? 0) < 0.01)
  const maxShare = Math.max(0.12, ...industries.map((r) => Math.max(r.link_before ?? 0, r.link_after ?? 0)))
  const agree = sum ? sum.validation.reduce((a, v) => a + v.agree, 0) : 0
  const agreeN = sum ? sum.validation.reduce((a, v) => a + v.n, 0) : 0

  return (
    <div className="page">
      <div className="card prose">
        <h2>Every vote since 2008</h2>
        {sum ? (
          <p>
            We tested <strong>{sum.tested.toLocaleString()}</strong> of the <strong>{sum.all_votes.toLocaleString()}</strong> House and Senate roll call votes since 2008 (the rest were near-unanimous or too small to test).
            No one has to tell us which side an industry wanted. For each vote and each industry, we ask whether members who had received more of that industry’s PAC money in the two years before
            the vote voted differently from members who had received less, after accounting for their ideology within their party, their district’s lean and ideology, and how much PAC money they raised overall.
          </p>
        ) : <p className="hint">Loading…</p>}
        <p className="hint">
          Patterns, not proof. A link means the money and the votes line up, not that the money caused the vote. To find out whether it did, we run the same test on money that arrived <em>after</em> the vote.
          Money that comes later can’t have moved the vote, so it shows how much of the link is donors rewarding or choosing members who already vote their way.
        </p>
      </div>

      <div className="card prose">
        <h2>How often does each industry’s money line up with the vote?</h2>
        <div className="sub">
          Share of votes where the industry’s PAC money predicts the vote beyond chance. “Before” is money from the two years before the vote; “after” is money from the two years after, tested together on the same votes.
          “Chance” is what random money does. Ranked by before-vote money.
        </div>
        <div className="legend3">
          <span><i style={{ background: 'var(--s2)' }} /> money before the vote</span>
          <span><i style={{ background: 'var(--s4, #6b7bb3)' }} /> money after the vote</span>
          <span><i style={{ background: 'var(--muted)' }} /> random money (chance)</span>
        </div>
        <div className="bars">
          {industries.map((r) => (
            <div key={r.label} className="trio">
              <span className="nm">{nice(r.label)}</span>
              <span className="tracks">
                <span className="track"><i style={{ width: `${(100 * (r.link_before ?? 0)) / maxShare}%`, background: 'var(--s2)' }} /><b>{pct(r.link_before)}</b></span>
                <span className="track"><i style={{ width: `${(100 * (r.link_after ?? 0)) / maxShare}%`, background: 'var(--s4, #6b7bb3)' }} /><b>{pct(r.link_after)}</b></span>
                <span className="track"><i style={{ width: `${(100 * (r.link_before_null ?? 0)) / maxShare}%`, background: 'var(--muted)' }} /><b>{pct(r.link_before_null)}</b></span>
              </span>
            </div>
          ))}
        </div>
        <ul>
          <li>Every industry’s money lines up with votes more often than chance, so the link is real.</li>
          <li>
            Money from <em>before</em> the vote beats money from after it, by a point or more, for: {lead.map((r) => nice(r.label)).join(', ') || 'no industry'}. That is the pattern influence would leave, though it is also what
            donors choosing members they expect to vote their way would leave.
          </li>
          <li>
            For {tie.map((r) => nice(r.label)).join(', ') || 'no industry'} the money that came <em>later</em> predicts the votes about as well or better. That fits donors favoring members who already vote their way,
            and it does not rule out influence, because giving is steady year to year and the two windows overlap.
          </li>
          <li>Direction check: on votes where we had already documented which side the industry wanted, a strong money link pointed to that side in <strong>{agree} of {agreeN}</strong> cases. So where the screen finds a link, it points the way the industry’s interests do.</li>
        </ul>
      </div>

      <div className="card prose">
        <h2>When the money lines up with a vote, how much is the money, and how much is politics?</h2>
        <div className="sub">
          On the votes where an industry’s money lined up strongly, members who had received $10K or more from that industry in the prior six years voted the way the money pulls this often.
          “Predicted” is how often they would have anyway given their ideology within their party, party, district lean and district ideology, estimated without using that industry’s money.
        </div>
        <div className="scroll-x">
          <table className="data">
            <thead><tr><th style={{ textAlign: 'left' }}>Industry</th><th>Strong-link votes</th><th>Voted with the money</th><th>Predicted by politics</th><th>Gap</th></tr></thead>
            <tbody>
              {(sum?.funded ?? []).filter((r) => !NOT_INDUSTRY.includes(r.label)).map((r) => (
                <tr key={r.label}>
                  <td style={{ textAlign: 'left' }}>{nice(r.label)}</td><td>{r.votes.toLocaleString()}</td><td>{pct(r.aligned, 0)}</td><td>{pct(r.expected, 0)}</td>
                  <td>{r.aligned - r.expected >= 0 ? '+' : '−'}{Math.abs(100 * (r.aligned - r.expected)).toFixed(1)} pts</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <h3>The more an industry gave, the more members voted its way</h3>
        <div className="sub">Same votes, grouped by how much the industry had given that member in the prior six years (business industries; unions are left out of this table).</div>
        <div className="bars">
          {(sum?.dose ?? []).map((r) => {
            const gap = 100 * (r.aligned - r.expected)
            const w = Math.min(100, (Math.abs(gap) / 9) * 100)
            return (
              <div key={r.k} className="hrow" style={{ gridTemplateColumns: '130px 1fr 150px' }}>
                <span className="nm">{DOSE[r.k]}</span>
                <span className="track"><i style={{ width: `${Math.max(2, w)}%`, background: gap >= 0 ? 'var(--s2)' : 'var(--muted)' }} /></span>
                <span className="amt">{gap >= 0 ? '+' : '−'}{Math.abs(gap).toFixed(1)} pts · {pct(r.aligned, 0)} vs {pct(r.expected, 0)}</span>
              </div>
            )
          })}
        </div>
        <div className="hint">Each row: share of votes cast the way the money pulls, against what their ideology, party and district predict, and the difference. Members who got little from an industry voted its way less than their politics predicts; those who got the most voted its way more. This lines up with money moving votes, and it equally fits donors giving most to members who already vote their way, which the before-and-after test above cannot rule out for most industries.</div>
        <div className="hint">These votes were picked because the money lined up with them, so every gap is pushed upward by how they were chosen. Compare industries with each other, not against zero.</div>
      </div>

      <div className="card">
        <h2>Votes where an industry’s money lines up most strongly</h2>
        <div className="sub">
          Strongest links stronger than 99.9% of what random money produces. “Money pulls toward” shows which way members with more of the industry’s money voted. Votes we have already coded with an
          industry side show it in the last column.
        </div>
        <div className="pills" style={{ marginBottom: 8 }}>
          {['', ...industries.map((r) => r.label)].map((l) => (
            <button key={l || 'all'} className="pill" aria-pressed={label === l} onClick={() => { setLabel(l); setLimit(25) }}>{l ? nice(l) : 'All industries'}</button>
          ))}
        </div>
        <div className="scroll-x">
          <table className="data">
            <thead><tr>
              <th style={{ textAlign: 'left' }}>Date</th><th style={{ textAlign: 'left' }}>Vote</th><th style={{ textAlign: 'left' }}>Industry</th>
              <th>Result</th><th style={{ textAlign: 'left' }}>Money pulls toward</th><th>Strength</th><th>After-vote money</th><th style={{ textAlign: 'left' }}>Known industry side</th>
            </tr></thead>
            <tbody>
              {(top?.rows ?? []).map((r) => (
                <tr key={`${r.congress}-${r.chamber}-${r.rollnumber}-${r.label}`}>
                  <td style={{ textAlign: 'left', whiteSpace: 'nowrap' }}>{r.d}<div className="hint">{r.chamber}</div></td>
                  <td style={{ textAlign: 'left', maxWidth: 420 }}>
                    <div>{(r.title || r.descr || r.q || '').slice(0, 150)}</div>
                    <div className="hint">{r.bill ? `${r.bill} · ` : ''}{r.q ?? ''}</div>
                  </td>
                  <td style={{ textAlign: 'left' }}>{nice(r.label)}</td>
                  <td>{r.result ?? ''}<div className="hint">{r.yeas}–{r.nays}</div></td>
                  <td style={{ textAlign: 'left' }}>{r.b_only >= 0 ? 'Yea' : 'Nay'}</td>
                  <td>{Math.abs(r.t_only).toFixed(1)}</td>
                  <td>{r.t_after == null ? '–' : Math.abs(r.t_after).toFixed(1)}</td>
                  <td style={{ textAlign: 'left' }}>{r.coded_side ? `${r.coded_side}${(r.b_only >= 0) === (r.coded_side === 'Yea') ? ' ✓' : ' ✗'}` : '–'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {!top && <div className="hint">Loading…</div>}
        {top && <div className="hint" style={{ marginTop: 6 }}>Some strong links sit on votes with no obvious industry stake (a resolution on Syria, a congressional adjournment). That means part of any link comes from things the model cannot see, such as how leadership and committee members vote. Treat each row as a lead to check, not a finding. </div>}
        {top && <div className="hint" style={{ marginTop: 6 }}>{top.rows.length} of {top.total.toLocaleString()} strong links shown. Strength is how many standard errors the link is from zero (about 3.1 is the line random money almost never crosses).</div>}
        {top && top.rows.length < top.total && <button className="iconbtn" style={{ marginTop: 8 }} onClick={() => setLimit(limit + 50)}>Show 50 more</button>}
      </div>
    </div>
  )
}
