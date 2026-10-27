# Congress Money Tracker

A local tool that asks one question: **do members of Congress vote the way the industries funding them want, and does that track the money?**
It ranks members by how much more they side with their donor industries than same-party peers do, shows how often they vote against what their
own districts said, and tests whether money arrives before or after the votes.

> **Patterns, not proof.** A high score means a member votes with the industries funding them more than their party peers do. It does not prove
> anyone was bought. See "Findings & method" in the app for what the numbers can and cannot say.

## Run it
1. Python 3.14 venv with `duckdb pandas numpy pyarrow requests fastapi uvicorn pypdf xlrd pyyaml` and Node 20+.
2. Build the data (see *Pipeline*); raw data and DuckDB files live in `data/` and are **not** in git.
3. `cd web && npm install && npm run build`, then double-click `run.bat` (or `python -m uvicorn server.api:app --port 8000`) and open http://127.0.0.1:8000.
   The server holds `data/analysis.duckdb` open read-only, so stop it before re-running a step that rewrites that file.

## Pipeline (`pipeline/`, run in order)
| step | what it does |
|---|---|
| 01 votes | Voteview roll calls + votes + member crosswalk (109th Congress on) |
| 02 fec | FEC PAC-to-candidate files (24K gifts, 24E/24A outside spending) |
| 03 sectors | PAC sector classifier (+ `sector_overrides.csv`, `sector_codes.csv`) |
| 04 indiv | itemized individual donations, aggregated weekly |
| 05 reconcile | checks our totals against FEC candidate summaries |
| 06 lda | Senate lobbying filings (lda.gov API; needs `data/.lda_key`) |
| 07 employer sectors | donor employer/occupation -> sector |
| 08 bills | bill metadata (GovInfo BILLSTATUS) |
| 09 money panel | member x week x source x sector money |
| 10 district | district presidential share + ideology (American Ideology Project) |
| 11 baseline | party / ideology / district baseline for votes |
| 12 committees | committee assignments (Stewart-Woon + snapshots) |
| 13 district opinion | CES survey opinion by district on 39 landmark votes |
| 14 subsectors | splits Energy / Health / Finance into industries that want opposite things |
| 15 alignment | per member x coded vote: voted the donors' way? sector PAC money before/after |
| 16 scores | donor-loyalty index, against-constituents rate, timing tests |
| 17 import positions | turns AFL-CIO / LCV scorecard positions into direction rows |
| 18 local industry | state industry employment (Census CBP) and union density (CES) as local-stake controls |
| 19 robustness | placebo-industry and committee-join difference-in-differences tests |
| 20 all votes money | tests every roll call since 2008 against every industry's PAC money, direction-free, with before/after and shuffled-money checks |
| 21 inferred alignment | member-level rows on votes where an industry's money lines up strongly with the vote (direction and expectation cross-fitted across member folds) |
| 22 lobbied votes | which industries lobbied each bill (Senate LDA filings 2008 to 2026) |
| 23 usaspending | federal prime contracts by recipient, state and district, FY2008 to FY2025 (public API) -> data/usaspending.duckdb |
| 24 company dependence | per defense company and year: contracts, SEC revenue, lobbying, PAC and employee gifts |
| 25 defense votes | defense vote directions: Peace Action scorecard (inverted on a fiscal rule) plus every NDAA / defense appropriations passage vote since 2008 |
| 26 revolving door | defense companies' lobbyists and the government positions they report (LDA API) |
| 27 war powers | every vote on a resolution directing removal of US forces from hostilities since 2008 |

## Locked definitions (`pipeline/definitions/`)
Which bills touch which sector, and **which way each vote helps each industry**, are written down and hashed (`LOCK*.txt`) *before* any model
sees the money. Do not edit a locked file; add a new version and report both. Evidence tiers: `documented` (the industry's own statement),
`reported` (credible reporting of it), `scorecard` (derived from an advocacy group's scorecard: LCV for fossil fuels, AFL-CIO for labor).

## Data sources
Voteview, FEC bulk files, Senate LDA, GovInfo BILLSTATUS, unitedstates/congress-legislators, Stewart & Woon committee data, American Ideology Project,
Cooperative Election Study (cumulative + policy preferences + 2010 roll-call battery), LCV and AFL-CIO scorecard pages. Source URLs for each coded
vote are in the `source_url` column of the `vote_direction*.csv` files.

## Defense and contracts
The Defense tab answers a different question from the scoreboard: how dependent the industry is on federal contracts, what it spends on Washington, where the contract
dollars land, how members vote next to local contracts and money, who lobbies for the companies, and what members said next to what they did. Contract totals are PRIME
awards in obligated dollars (they omit classified awards, subcontracts and direct foreign sales); company-reported government shares are in
`pipeline/definitions/company_reported_share.csv` with source links, and were read from search-result quotations of the filings, so check each source.
Statements for the said-versus-did table are in `promises.csv`, executive-branch statements and actions in `executive_record.csv`, Pentagon-to-contractor facts in `door_facts.csv`.

## Known limits
Only ~300 of ~18,000 roll calls since 2008 have a documented industry side (mostly oil, gas, coal and labor); the every-vote screen (step 20) covers the rest
without needing a side but cannot show intent. District opinion is a direct survey measure for only a handful of coded votes; the fossil votes use one
climate-opinion item as a proxy and are reported separately. PAC gifts only in the scores (individual donors and outside spending are in the explorer).
Money arriving after a vote predicts votes almost as well as money before it for most industries, so the data shows money and votes lining up, not that
money moved them. No campaign-promise data yet.
