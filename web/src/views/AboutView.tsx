import { useEffect, useState } from 'react'
import { api } from '../api'
import type { Coverage, Definitions, FreshRow } from '../types'

export default function AboutView({ defs }: { defs: Definitions }) {
  const [cov, setCov] = useState<Coverage | null>(null)
  const [fresh, setFresh] = useState<FreshRow[]>([])
  useEffect(() => { api.scoreboard('all', 'All business').then((r) => setCov(r.coverage)).catch(() => undefined); api.freshness().then((r) => setFresh(r.sources)).catch(() => undefined) }, [])
  const lm = cov?.landmark_by_match ?? {}
  const documented = new Set(defs.direction.map((r) => `${r.congress}-${r.chamber}-${r.rollnumber}`)).size
  return (
    <div className="page">
      <div className="card prose">
        <h2>Sources, definitions and how recent the data is</h2>
        <p>This tool puts three things on one time axis: who funded a member, how that member voted, and what their district looks like. It shows associations. Nothing here proves that a donation changed a vote, and a vote that follows a donation is not evidence by itself. Members attract money from industries that already agree with them, so money and votes line up even if money does nothing.</p>

        <h3>How recent each source is</h3>
        <div className="scroll-x">
          <table className="data">
            <thead><tr><th style={{ textAlign: 'left' }}>Source</th><th>Data through</th><th style={{ textAlign: 'left' }}>Note</th></tr></thead>
            <tbody>{fresh.map((f) => <tr key={f.source}><td style={{ textAlign: 'left' }}>{f.source}</td><td>{f.through ?? '–'}</td><td style={{ textAlign: 'left' }} className="hint">{f.note}</td></tr>)}</tbody>
          </table>
        </div>

        <h3>Plain-language terms</h3>
        <ul>
          <li><strong>Funded vote</strong>: a vote where the industry had given the member $10,000 or more in PAC money in the six years before.</li>
          <li><strong>Gap</strong> (shown as “points”, with a 90% range): how much more often a member voted the industry’s way than same-party colleagues with the same ideology and district would be expected to. “+10 points” means 10 more votes in 100.</li>
          <li><strong>Same-party colleagues</strong> (“peers”): members of the member’s own party with similar ideology and a similar district, voting on the same roll calls. The expectation comes from how they voted, estimated without using that industry’s money.</li>
          <li><strong>Documented side</strong>: the industry’s position on the vote is stated by the industry or a scorecard, or follows from the spending rule. <strong>Inferred side</strong>: the side is the one the money pulls toward, found from the pattern of votes and money across all members.</li>
          <li><strong>Strong link</strong>: a vote where an industry’s money predicts the vote more strongly than 99.9% of what randomly shuffled money does.</li>
          <li><strong>Strength</strong>: how many standard errors the link is from zero; about 3.1 is the line random money almost never crosses.</li>
          <li><strong>Lobbied vote</strong>: a vote on a bill that at least two clients of that industry named in their Senate lobbying filings.</li>
        </ul>

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
        <p>
          {cov ? <>For <strong>{lm.direct ?? 0}</strong> well-known votes with a matching survey question (plus <strong>{lm.related ?? 0}</strong> related ones shown faded), </> : 'For well-known votes with a matching survey question, '}
          the member page compares how the member voted with what their district (House) or state (Senate) said on the same question in the Cooperative Election Study, an online survey of about 55,000 people per year. A district’s support is estimated from its own respondents (about 120 per district per year) and pulled toward what its presidential vote and ideology predict, in proportion to how noisy its sample is. A vote counts as against constituents only when we are at least 90% sure which way the district leaned. Caveats: questions describe a bill in a sentence, often in its favor, which can push support up; the survey pool is an online panel, weighted; the 2014 ACA-repeal answers were coded backwards in the source file and are corrected here; “related” matches are shown faded and left out of the headline count. Bill-to-question matches were fixed from the bill’s identity before any estimate was made.
          {cov && lm.proxy ? <> A separate set of <strong>{lm.proxy}</strong> fossil-fuel votes is judged by one climate-opinion question (letting the EPA regulate CO2) used as a stand-in for every bill; it is a looser measure and is always labelled as a proxy.</> : null}
        </p>
        <p className="hint">Almost every large gap is party-wide: for example, nearly all Republicans voted against background checks that most of their districts supported. That is evidence about parties and constituents, not about donors; the donor tests are on the Findings page.</p>

        <h3>Votes with a documented industry side</h3>
        <p>
          For <strong>{documented}</strong> votes, each has a documented side that helps a donor sector, taken from a trade group’s own statement, a scorecard, or (for defense spending bills) the fiscal effect of the vote. Every row, with its source and evidence level, is in the <a href="#/codebook">vote codebook</a>.
          “Reported” means the position comes from secondary coverage or from a group’s scorecard rather than the group’s own words. Industries inside a sector are split where they want different things (for example, banks vs. insurers, oil and gas vs. electric utilities, drug makers vs. doctors).
        </p>
        <p className="hint">Members from oil, coal and bank-heavy places also draw more of that money and have constituents who want those votes, so the numbers do not by themselves show money buying votes.</p>

        <h3>Corrections</h3>
        <p>A wrong number is fixed by changing the data or the written rule that produces it, never by editing the page. Each result names the pipeline step behind it on the Findings page, and the rules were fixed in writing before the money-versus-vote models ran.</p>

        <h3>Not covered yet</h3>
        <ul>
          <li><strong>Individual donors and outside spending in the scores</strong>: only direct PAC gifts are scored. Most individual dollars and super-PAC dollars cannot yet be assigned to an industry (the shares are above).</li>
          <li><strong>Lobbying and government funding outside defense</strong>: lobbying is used to pick the votes an industry cared about, but spending, targets and contracts are only broken out for defense.</li>
          <li><strong>The executive branch</strong>: donors to presidential campaigns, their super PACs and inaugural committees are not yet linked to executive actions.</li>
          <li><strong>Members’ own finances</strong>: stock-trade and asset disclosures, and earmarks.</li>
          <li><strong>District opinion on most bills</strong>: only the landmark votes above are covered.</li>
        </ul>
      </div>
    </div>
  )
}
