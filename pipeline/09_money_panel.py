"""Build the weekly money panel: one row per (member, week, source, sector).

  source = 'pac_direct'   direct PAC contribution to the member's committee (FEC 24K)
           'ie_support'   independent expenditure FOR the member (24E)       -- outside spending, not a gift
           'ie_oppose'    independent expenditure AGAINST the member (24A)   -- spent against them, benefits rivals
           'indiv'        itemized individual contributions to the member's principal/authorized committees
  sector = PAC: committee_sector.sector (spender); individuals: employer_sector.sector (donor's employer/occupation)
Output: data/analysis.duckdb.money_weekly.  Members are keyed by bioguide id (a member can have several FEC ids).
"""
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parent.parent
con = duckdb.connect(str(ROOT / "data" / "analysis.duckdb"))
con.execute(f"ATTACH '{(ROOT / 'data' / 'congress.duckdb').as_posix()}' AS c (READ_ONLY)")
con.execute(f"ATTACH '{(ROOT / 'data' / 'indiv.duckdb').as_posix()}' AS i (READ_ONLY)")

con.execute("""
CREATE OR REPLACE TABLE money_weekly AS
WITH xw AS (SELECT DISTINCT fec_id, bioguide FROM c.id_crosswalk WHERE fec_id IS NOT NULL),
pac AS (
    SELECT xw.bioguide,
           date_trunc('week', TRY_STRPTIME(p.TRANSACTION_DT, '%m%d%Y'))::DATE AS week,
           CASE p.TRANSACTION_TP WHEN '24K' THEN 'pac_direct' WHEN '24E' THEN 'ie_support' ELSE 'ie_oppose' END AS source,
           s.sector, sum(TRY_CAST(p.TRANSACTION_AMT AS DOUBLE)) AS amount, count(*)::INT AS n
    FROM c.fec_pas2 p
    JOIN xw ON xw.fec_id = p.CAND_ID
    JOIN c.committee_sector s ON s.cmte_id = p.CMTE_ID
    WHERE p.TRANSACTION_TP IN ('24K', '24E', '24A')
      AND TRY_STRPTIME(p.TRANSACTION_DT, '%m%d%Y') BETWEEN DATE '2004-01-01' AND DATE '2026-12-31'
    GROUP BY ALL
),
ind AS (
    SELECT xw.bioguide, a.week, 'indiv' AS source,
           coalesce(es.sector, 'Other / unclassified') AS sector, sum(a.total) AS amount, sum(a.n)::INT AS n
    FROM i.indiv_agg a
    JOIN xw ON xw.fec_id = a.cand_id
    LEFT JOIN i.employer_sector es ON es.employer = coalesce(a.employer, '') AND es.occupation = coalesce(a.occupation, '')
    WHERE a.cmte_dsgn IN ('P', 'A')
    GROUP BY ALL
)
SELECT * FROM pac UNION ALL SELECT * FROM ind
""")

print("money_weekly:", con.execute("SELECT count(*), count(DISTINCT bioguide), min(week), max(week) FROM money_weekly").fetchone())
print("\nBy source ($M, all years):")
for r in con.execute("SELECT source, round(sum(amount)/1e6,1), sum(n) FROM money_weekly GROUP BY 1 ORDER BY 2 DESC").fetchall():
    print(f"  {r[0]:12s} ${r[1]:>9,.1f}M  {r[2]:>11,} transactions")
print("\nTop sectors by direct PAC + individual money ($M):")
for r in con.execute("""SELECT sector, round(sum(amount) FILTER (WHERE source='pac_direct')/1e6,1), round(sum(amount) FILTER (WHERE source='indiv')/1e6,1)
                         FROM money_weekly GROUP BY 1 ORDER BY coalesce(sum(amount) FILTER (WHERE source='pac_direct'),0)+coalesce(sum(amount) FILTER (WHERE source='indiv'),0) DESC LIMIT 14""").fetchall():
    print(f"  {r[0]:52s} PAC {r[1] if r[1] is not None else 0:>8,.1f}   indiv {r[2] if r[2] is not None else 0:>8,.1f}")
