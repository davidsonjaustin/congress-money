import type { Definitions } from '../types'

export default function AboutView({ defs }: { defs: Definitions }) {
  return (
    <div className="page">
      <div className="card prose">
        <h2>How to read this</h2>
        <p>This tool puts three things on one time axis: who funded a member, how that member voted, and what their district looks like. It shows associations. Nothing here proves that a donation changed a vote, and a vote that follows a donation is not evidence by itself. Members attract money from industries that already agree with them, so money and votes line up even if money does nothing.</p>

        <h3>What is shown</h3>
        <ul>
          <li><strong>PAC gifts</strong>: money a political action committee gave directly to the member (FEC Schedule B, type 24K). The PAC’s sector comes from its name, its connected organization and about 600 hand-checked labels.</li>
          <li><strong>Individual gifts</strong>: itemized donations of $200 or more to the member’s own committees. The sector is guessed from the donor’s stated employer and occupation. About 38% of dollars have no usable employer (retired, unemployed, blank) and another 26% don’t match a sector rule, so treat these as estimates.</li>
          <li><strong>Outside spending for / against</strong>: independent expenditures by groups that cannot coordinate with the campaign. Spending <em>against</em> a member helps their opponent, not them. These are never added to gifts.</li>
          <li><strong>Votes</strong>: every Yea/Nay roll call since the 109th Congress (2005), from Voteview.</li>
          <li><strong>Party-line vote</strong>: a roll call where most Democrats voted against most Republicans. <strong>Broke from party</strong>: voted against their own party’s majority on one.</li>
          <li><strong>Model chance</strong>: the probability that a statistical model of ideology (DW-NOMINATE) gave to the vote the member actually cast. “Surprising” means under 25%. The ideology scores are estimated from the same votes, so this is a generous yardstick: it flatters how well ideology predicts votes.</li>
          <li><strong>Own party’s share of the district’s presidential vote</strong>: from the American Ideology Project (Tausanovitch &amp; Warshaw). Where a district’s lines changed in mid-decade, the nearest map is used and the tile says so.</li>
          <li><strong>Committees</strong>: 2005–2022 from Stewart &amp; Woon with real start and end dates (shaded on the chart). The 118th and 119th Congress are snapshots with no dates.</li>
        </ul>

        <h3>How well the data checks out</h3>
        <ul>
          <li>PAC totals match the totals candidates reported to the FEC at 98.5–100.7% in every cycle.</li>
          <li>Itemized individual gifts are 63–76% of what candidates reported; the rest are unitemized small donations that are not public.</li>
          <li>In a random check of 24 PAC sector labels against outside reporting, 22 were right. The two errors were fixed and the rule that caused them was tightened.</li>
        </ul>

        <h3>Sector and topic matching</h3>
        <p>Which bills count as “about” a sector was written down and hashed before any model of money against votes was run, so the choice cannot bend toward a result. <em>Strict</em> means the bill’s own subject is the sector’s core business. <em>Broad</em> adds sectors a bill plausibly touches. A bill being about a sector does not say whether Yea helped or hurt it.</p>
        <p className="hint">{defs.lock.join(' · ')}</p>

        <h3>Landmark votes vs. the district</h3>
        <p>For 39 well-known votes, the member page compares how the member voted with what their district (House) or state (Senate) said on the same question in the Cooperative Election Study, an online survey of about 55,000 people per year. A district’s support is estimated from its own respondents (about 120 per district per year) and pulled toward what its presidential vote and ideology predict, in proportion to how noisy its sample is. A vote counts as against constituents only when we are at least 90% sure which way the district leaned. Caveats: questions describe a bill in a sentence, often in its favor, which can push support up; the survey pool is an online panel, weighted; the 2014 ACA-repeal answers were coded backwards in the source file and are corrected here; “related” matches are shown faded and left out of the headline count. Bill-to-question matches were fixed from the bill’s identity before any estimate was made.</p>
        <p className="hint">Almost every large gap is party-wide: for example, nearly all Republicans voted against background checks that most of their districts supported. That is evidence about parties and constituents, not about donors; donor tests come next.</p>

        <h3>Votes on the donors’ issues</h3>
        <p>For a pilot set of {new Set(defs.direction.map((r) => `${r.congress}-${r.chamber}-${r.rollnumber}`)).size} votes, each has a documented side that helps a donor sector, taken from a trade group’s own statement or reporting on it (listed below). For each member who voted, the member page shows whether they voted that way and how much that sector’s PACs had given in the six years before. “Reported” means the position comes from secondary coverage or from a group’s scorecard rather than the group’s own words. Industries inside a sector are split where they want different things (for example, banks vs. insurers, oil and gas vs. electric utilities, drug makers vs. doctors).</p>
        <p className="hint">What these coded votes show so far is summarized at the top of this page. Members from oil, coal and bank-heavy places also draw more of that money and have constituents who want those votes, so the numbers do not by themselves show money buying votes.</p>
        <div className="scroll-x">
          <table className="data">
            <thead><tr><th>Vote</th><th style={{ textAlign: 'left' }}>Sector</th><th>Helps if</th><th style={{ textAlign: 'left' }}>Evidence</th><th>Level</th></tr></thead>
            <tbody>
              {defs.direction.map((r, i) => (
                <tr key={i}>
                  <td>{r.bill} {r.chamber.slice(0, 3)} {r.date}</td>
                  <td style={{ textAlign: 'left' }}>{r.subsector ? r.subsector.replace('_', ' ') : r.sector}</td>
                  <td>{r.helps_vote}</td>
                  <td style={{ textAlign: 'left' }}><a href={r.source_url} target="_blank" rel="noopener noreferrer">{r.evidence}</a></td>
                  <td>{r.evidence_level}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <h3>Not built yet</h3>
        <ul>
          <li><strong>Lobbying</strong>: the Senate lobbying records are still downloading. They will show which bills each sector’s clients lobbied on and let interests be defined from lobbying, not from giving.</li>
          <li><strong>Which way the industry wanted each vote</strong>: needs published scorecards and key-vote lists.</li>
          <li><strong>District opinion on more bills</strong>: only 39 landmark votes are covered so far (see above); anything involving industry beyond finance, energy and health needs more survey questions.</li>
          <li><strong>Family and personal finances</strong>: official disclosures and stock-trade reports.</li>
          <li><strong>Tests</strong>: before-vs-after timing, placebo sectors, matched comparisons and sensitivity bounds. Until these exist, the charts are for exploring, not for conclusions.</li>
        </ul>
      </div>
    </div>
  )
}
