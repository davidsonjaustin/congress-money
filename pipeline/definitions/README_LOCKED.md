# Locked definitions (written BEFORE any money-vs-vote model was run)

Status when locked: the only analysis run so far is the no-money baseline (party, ideology, district lean).
No test of donor money against votes, and no look at sector-level vote patterns, had been run.

Files
- policy_sector.csv    which bill policy areas count as "relevant to" which donor sector. tier = strict | broad.
- committee_sector.csv which committees' jurisdictions count as relevant to which sector. tier = strict | broad.

Rules
1. PRIMARY analysis uses `strict` rows only. `broad` (strict + broad rows) is a robustness check, reported next to it.
2. A third tier, `lda`, will be added from Senate lobbying filings (bills each sector's clients lobbied on) in a
   separate file locked the same way before any model is fit. Interests are NOT inferred from who gives to whom.
3. These files may not be edited after seeing results. If a mapping is later found wrong, add a new version file,
   report both, and say why. Never silently replace.
4. Relevance is not direction. A bill being "about" Finance does not say whether Yea helps or hurts Finance.
   Direction (the industry-preferred vote) will come from published scorecards / key-vote lists, fixed per roll call
   before modelling. Roll calls with no sourced direction are excluded from the direction-based tests.
5. Policy areas deliberately left unmapped (no sector): Congress, Commemorations, Emergency Management, Crime and Law
   Enforcement, Economics and Public Finance (appropriations/budget -- too heterogeneous), Social Welfare, Families,
   Civil Rights, Native Americans, Sports, Arts, Social Sciences, Private Legislation, International Affairs,
   Government Operations.
