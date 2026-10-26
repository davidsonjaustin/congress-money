"""Reconcile our aggregates against the candidates' own FEC summary reports (weball*.txt).

These come from the receiving side of the same transactions (candidate filings), so agreement
with our PAC-side (pas2) and individual-side (indiv) numbers is an independent integrity check.

  python 05_reconcile.py pac    -> our PAC 24K totals vs candidate-reported OTHER_POL_CMTE_CONTRIB
  python 05_reconcile.py indiv  -> our itemized individual totals vs TTL_INDIV_CONTRIB (we expect
                                   ours to be LOWER: bulk data has itemized gifts only)
"""
import sys
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parent.parent
FEC = ROOT / "data" / "raw" / "fec"
WEBALL_COLS = ("CAND_ID CAND_NAME CAND_ICI PTY_CD CAND_PTY TTL_RECEIPTS TRANS_FROM_AUTH TTL_DISB TRANS_TO_AUTH "
               "COH_BOP COH_COP CAND_CONTRIB CAND_LOANS OTHER_LOANS CAND_LOAN_REPAY OTHER_LOAN_REPAY DEBTS_OWED_BY "
               "TTL_INDIV_CONTRIB CAND_OFFICE_ST CAND_OFFICE_DISTRICT SPEC_ELECTION PRIM_ELECTION RUN_ELECTION "
               "GEN_ELECTION GEN_ELECTION_PCT OTHER_POL_CMTE_CONTRIB POL_PTY_CONTRIB CVG_END_DT INDIV_REFUNDS "
               "CMTE_REFUNDS").split()
CYCLES = [2014, 2018, 2022, 2024]


def load_weball(con: duckdb.DuckDBPyConnection) -> None:
    spec = ", ".join(f"'{c}': 'VARCHAR'" for c in WEBALL_COLS)
    con.execute("CREATE OR REPLACE TEMP TABLE weball (cycle INT, cand_id VARCHAR, other_pol DOUBLE, indiv DOUBLE)")
    for c in CYCLES:
        f = FEC / f"weball{str(c)[2:]}.txt"
        con.execute(f"""
            INSERT INTO weball
            SELECT {c}, CAND_ID, TRY_CAST(OTHER_POL_CMTE_CONTRIB AS DOUBLE), TRY_CAST(TTL_INDIV_CONTRIB AS DOUBLE)
            FROM read_csv('{f.as_posix()}', delim='|', header=false, columns={{{spec}}}, quote='', escape='',
                          null_padding=true, ignore_errors=true)""")


def report(con, ours_sql: str, label: str) -> None:
    con.execute(f"CREATE OR REPLACE TEMP TABLE cmp AS {ours_sql}")
    print(f"\n{label}")
    print(f"{'cycle':>6} {'members':>8} {'ours $M':>9} {'filed $M':>9} {'ratio':>6} {'corr':>6} {'within10%':>10}")
    for row in con.execute("""
        SELECT cycle, count(*), round(sum(ours)/1e6,1), round(sum(filed)/1e6,1),
               round(sum(ours)/sum(filed),3), round(corr(ours, filed),3),
               round(100.0*count(*) FILTER (WHERE abs(ours-filed) <= 0.10*greatest(filed,1))/count(*),1)
        FROM cmp WHERE filed > 10000 GROUP BY 1 ORDER BY 1""").fetchall():
        print(f"{row[0]:>6} {row[1]:>8} {row[2]:>9} {row[3]:>9} {row[4]:>6} {row[5]:>6} {row[6]:>9}%")


def main(mode: str) -> None:
    con = duckdb.connect(str(ROOT / "data" / "congress.duckdb"), read_only=True)
    load_weball(con)
    if mode == "pac":
        # A member who ran for a different office has two candidate IDs sharing one campaign committee,
        # and weball repeats the committee's totals under both: take max(filed), sum(ours) per member.
        report(con, """
            SELECT cycle, bioguide, max(filed) AS filed, sum(ours) AS ours FROM (
                SELECT w.cycle, x.bioguide, w.other_pol AS filed,
                       coalesce((SELECT sum(TRY_CAST(p.TRANSACTION_AMT AS DOUBLE)) FROM fec_pas2 p
                                 WHERE p.cycle = w.cycle AND p.CAND_ID = w.cand_id AND p.TRANSACTION_TP = '24K'), 0) AS ours
                FROM weball w JOIN (SELECT DISTINCT fec_id, bioguide FROM id_crosswalk) x ON x.fec_id = w.cand_id
            ) GROUP BY cycle, bioguide""",
            "PAC money: pas2 24K (paid by PACs) vs candidate-reported 'other political committee' receipts")
    else:
        con.execute(f"ATTACH '{(ROOT / 'data' / 'indiv.duckdb').as_posix()}' AS ind (READ_ONLY)")
        report(con, """
            SELECT cycle, bioguide, max(filed) AS filed, sum(ours) AS ours FROM (
                SELECT w.cycle, x.bioguide, w.indiv AS filed,
                       coalesce((SELECT sum(a.total) FROM ind.indiv_agg a
                                 WHERE a.cycle = w.cycle AND a.cand_id = w.cand_id AND a.cmte_dsgn IN ('P','A')), 0) AS ours
                FROM weball w JOIN (SELECT DISTINCT fec_id, bioguide FROM id_crosswalk) x ON x.fec_id = w.cand_id
            ) GROUP BY cycle, bioguide""",
            "Individual money: our itemized total vs candidate-reported total (incl. unitemized small gifts)")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "pac")
