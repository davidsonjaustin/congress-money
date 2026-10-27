import { useEffect, useState } from 'react'
import { api } from '../api'
import type { Coverage, Definitions, FreshRow, MoneyCoverage } from '../types'

export default function AboutView({ defs }: { defs: Definitions }) {
  const [cov, setCov] = useState<Coverage | null>(null)
  const [fresh, setFresh] = useState<FreshRow[]>([])
  const [mc, setMc] = useState<MoneyCoverage[]>([])
  useEffect(() => { api.scoreboard('all', 'All business').then((r) => setCov(r.coverage)).catch(() => undefined); api.freshness().then((r) => setFresh(r.sources)).catch(() => undefined); api.moneyCoverage().then(setMc).catch(() => undefined) }, [])
  const share = (src: string, grp: string) => { const t = mc.filter((m) => m.source === src).reduce((a, m) => a + m.amount, 0); const g = mc.find((m) => m.source === src && m.grp === grp)?.amount ?? 0; return t > 0 ? `${Math.round((100 * g) / t)}%` : '–' }
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
          <li><strong>Individual gifts</strong>: itemized donations of $200 or more to the member’s own committees. The sector is taken from the donor’s stated employer and occupation, with a hand-checked list for the largest employers. Of these dollars, <strong>{share('indiv', 'sorted')}</strong> are put in an industry, <strong>{share('indiv', 'no_employer')}</strong> list no usable employer (retired, unemployed, blank) and <strong>{share('indiv', 'unsorted')}</strong> name an employer we do not recognise. Treat industry totals from individual gifts as a floor.</li>
          <li><strong>Outside spending for / against</strong>: independent expenditures by groups that cannot coordinate with the campaign. Spending <em>against</em> a member helps their opponent, not them. These are never added to gifts. The spender’s own name rarely says who is behind it, so the <a href="#/outside">Outside money</a> page and each case file follow the money one step back to the spender’s donors.</li>
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
          <li><strong>Individual donors and outside spending in the vote scores</strong>: the scores use direct PAC gifts only. Individual gifts and outside spending are shown, by industry where the donor’s employer or the spender’s funders allow, on the member, company and outside-money pages, not yet in the money-versus-vote tests.</li>
          <li><strong>Contracts and grants outside defense</strong>: contracts are shown for the ~235 largest recipients each year, grouped by name. Grants, loans, subsidies and Medicare or Medicaid payments to industries are not included.</li>
          <li><strong>Lobbyists’ government backgrounds</strong>: read for defense contractors and for the 70 biggest lobbying companies outside defense, not for every client.</li>
          <li><strong>The executive branch</strong>: who paid for presidential campaigns is shown (White House tab); donors are not yet linked to executive orders, appointments or contracts, and inaugural committees and dark-money groups are not included.</li>
          <li><strong>Members’ own finances</strong>: House stock trades are shown; Senate trades are not (the Senate’s site requires accepting its terms first), and asset and income disclosures are not.</li>
          <li><strong>Earmarks</strong>: fiscal 2024 only, from the House Appropriations Committee’s published tables, without defense earmarks.</li>
          <li><strong>Pledges</strong>: the No Fossil Fuel Money pledge only. Corporate-PAC pledge lists are not published in a form that can be loaded.</li>
          <li><strong>District opinion on most bills</strong>: only the landmark votes above are covered.</li>
        </ul>
      </div>
    </div>
  )
}
