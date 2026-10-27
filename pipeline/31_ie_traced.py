"""Who is behind the outside spending for and against each member.

Outside spenders (super PACs, party committees, some nonprofits) report what they spend for or against a candidate; the money behind them comes from donors the
spenders also report. 30_superpac_donors.py streamed those receipts. Here we sort each spender's receipts by who gave (industry from the donor's employer or name,
political committees, nonprofits that do not disclose their own donors), then split every dollar a spender put into a member's race the way that spender's money
was funded in that cycle.

This is an attribution, not a trace of individual dollars: a committee funded 40% by finance and 20% by oil is treated as spending 40% finance and 20% oil money in
every race it enters. Money from nonprofits and from other committees is shown as such; we do not look through them.

Output (data/superpac.duckdb):
  ie_spend(bioguide, cmte_id, cycle, kind, amount)                  what each outside spender put for/against each member
  committee_funding(cmte_id, cycle, sector, amount)                 each spender's receipts by who gave
  ie_traced(bioguide, cycle, kind, sector, amount)                  spending in a member's race attributed to the industries behind it
  ie_funders(bioguide, kind, donor, sector, amount)                 the named donors (organisations, and individuals who gave $100K or more) behind it, top 25 per member and kind
  ie_coverage(kind, sector_group, amount)                           how much of all spending could be put in an industry
"""
import importlib.util
import re
from pathlib import Path

import duckdb
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
FEC = ROOT / "data" / "raw" / "fec"
RECEIPT_TP = ("10", "11", "15", "15C", "15E", "15I", "15T", "15Z", "16C", "18G", "18H", "18J", "18K", "18U")
PAS_COLS = ("CMTE_ID AMNDT_IND RPT_TP TRANSACTION_PGI IMAGE_NUM TRANSACTION_TP ENTITY_TP NAME CITY STATE ZIP_CODE EMPLOYER OCCUPATION TRANSACTION_DT "
            "TRANSACTION_AMT OTHER_ID CAND_ID TRAN_ID FILE_NUM MEMO_CD MEMO_TEXT SUB_ID").split()
NOT_ID = "Not identifiable (retired / unemployed / no employer)"
COMMITTEES = "Other political committees"
NONPROFIT = "Nonprofits that do not disclose their donors"
NONPROFIT_RX = re.compile(r"\b(FUND|FOUNDATION|ACTION|PROJECT|NETWORK|ALLIANCE|COALITION|PARTNERSHIP|CENTER|INSTITUTE|COUNCIL|TRUST|SOCIETY|FEDERATION|LEAGUE|"
                          r"AMERICANS FOR|CITIZENS FOR|FOR AMERICA|FOR AMERICAN|FREEDOM|LIBERTY|LEADERSHIP|PRIORITIES|FUTURE|VOICE|ADVOCACY|CAMPAIGN)\b")


def load(name: str):
    spec = importlib.util.spec_from_file_location(name.replace(".py", "_m"), Path(__file__).with_name(name))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


emp, s03 = load("07_employer_sectors.py"), load("03_sectors.py")


ORG_OV = {r["name"].upper(): r["sector"] for r in pd.read_csv(ROOT / "pipeline" / "definitions" / "org_overrides.csv").to_dict("records")}


def org_sector(name: str) -> str:
    n = (name or "").upper()
    if n in ORG_OV:
        return ORG_OV[n]
    for sector, rx in emp.EMP_RULES:
        if rx.search(n):
            return sector
    if emp.OVERRIDES.get(n):
        return emp.OVERRIDES[n]
    return NONPROFIT if NONPROFIT_RX.search(n) else "Other / unclassified"


def main() -> None:
    con = duckdb.connect(str(ROOT / "data" / "superpac.duckdb"))
    con.execute(f"ATTACH '{(ROOT / 'data' / 'congress.duckdb').as_posix()}' AS c (READ_ONLY)")
    spec = ", ".join(f"'{c}': 'VARCHAR'" for c in PAS_COLS)

    # 1. what each spender put into each member's race
    parts = " UNION ALL ".join(
        f"""SELECT {int(f.stem[4:]) + 2000} AS cycle, CMTE_ID, CAND_ID, TRANSACTION_TP, TRY_CAST(TRANSACTION_AMT AS DOUBLE) AS amt FROM read_csv('{f.as_posix()}', delim='|', header=false,
             columns={{{spec}}}, quote='', escape='', null_padding=true, ignore_errors=true) WHERE TRANSACTION_TP IN ('24E', '24A') AND coalesce(MEMO_CD, '') <> 'X'""" for f in sorted(FEC.glob("pas2*.txt")))
    con.execute(f"""
        CREATE OR REPLACE TABLE ie_spend AS
        SELECT x.bioguide, p.CMTE_ID AS cmte_id, p.cycle, CASE p.TRANSACTION_TP WHEN '24E' THEN 'support' ELSE 'oppose' END AS kind, sum(p.amt) AS amount
        FROM ({parts}) p JOIN (SELECT DISTINCT fec_id, bioguide FROM c.id_crosswalk WHERE fec_id IS NOT NULL AND bioguide IS NOT NULL) x ON x.fec_id = p.CAND_ID
        WHERE p.amt IS NOT NULL GROUP BY 1, 2, 3, 4""")
    print(con.execute("SELECT kind, count(DISTINCT cmte_id) AS spenders, round(sum(amount) / 1e9, 2) AS billions FROM ie_spend GROUP BY 1").df().to_string(index=False))

    # 2. classify each receipt: individuals by employer, organisations by name, committees by the committee's own sector
    rc = con.execute(f"""
        SELECT cycle, cmte_id, src, entity_tp, name, other_id, employer, occupation, sum(total) AS amount FROM ie_receipts
        WHERE tp IN {RECEIPT_TP} GROUP BY ALL""").df().fillna({"employer": "", "occupation": "", "name": "", "other_id": "", "entity_tp": ""})
    cs = con.execute("SELECT cmte_id, sector FROM c.committee_sector").df().set_index("cmte_id")["sector"].to_dict()
    cache: dict = {}

    def sec(r) -> str:
        e = r.entity_tp
        if e in ("IND", ""):
            k = ("i", r.employer, r.occupation)
            if k not in cache:
                cache[k] = emp.classify(r.employer or "", r.occupation or "")[0]
            return cache[k]
        if e == "ORG":
            k = ("o", r.name)
            if k not in cache:
                cache[k] = org_sector(r.name)
            return cache[k]
        s = cs.get(r.other_id)
        return COMMITTEES if s in (None, "Candidate committee", "Leadership PAC", "Joint fundraising", "Party committee", "Caucus & Party-Aligned PACs", "Ideological / Single-Issue", "Ideological / Single-Issue / Unsorted") else s

    rc["sector"] = [sec(r) for r in rc.itertuples(index=False)]
    cf = rc[rc["amount"] > 0].groupby(["cmte_id", "cycle", "sector"], as_index=False)["amount"].sum()
    con.execute("CREATE OR REPLACE TABLE committee_funding AS SELECT * FROM cf")

    # 3. split each spender's spending the way it was funded that cycle
    con.execute("""
        CREATE OR REPLACE TABLE ie_traced AS
        WITH tot AS (SELECT cmte_id, cycle, sum(amount) AS t FROM committee_funding GROUP BY 1, 2)
        SELECT s.bioguide, s.cycle, s.kind, f.sector, sum(s.amount * f.amount / t.t) AS amount
        FROM ie_spend s JOIN committee_funding f ON f.cmte_id = s.cmte_id AND f.cycle = s.cycle JOIN tot t ON t.cmte_id = s.cmte_id AND t.cycle = s.cycle
        GROUP BY 1, 2, 3, 4""")
    con.execute("""
        CREATE OR REPLACE TABLE ie_coverage AS
        SELECT kind, CASE WHEN sector = 'Not identifiable (retired / unemployed / no employer)' THEN 'Individuals with no usable employer' WHEN sector = 'Other / unclassified' THEN 'Not sorted'
                          WHEN sector = 'Other political committees' THEN 'Other political committees' WHEN sector = 'Nonprofits that do not disclose their donors' THEN 'Nonprofits (donors hidden)'
                          ELSE 'Sorted into an industry or group' END AS grp, sum(amount) AS amount FROM ie_traced GROUP BY 1, 2""")
    unmatched = con.execute("SELECT kind, round(sum(amount) / 1e6) AS m FROM ie_spend WHERE (cmte_id, cycle) NOT IN (SELECT cmte_id, cycle FROM committee_funding) GROUP BY 1").df()
    print("spending by spenders whose receipts we do not have (no attribution):\n", unmatched.to_string(index=False))

    # 4. named donors behind each member's race
    named = rc[(rc["amount"] > 0) & (rc["entity_tp"] == "ORG") & rc["name"].notna()][["cycle", "cmte_id", "name", "sector", "amount"]]
    major = con.execute("SELECT cycle, cmte_id, name, employer, total AS amount FROM ie_major WHERE total > 0").df().fillna({"employer": "", "name": ""})
    major["sector"] = [emp.classify(e or "", "")[0] for e in major["employer"]]
    major["name"] = major["name"] + major["employer"].fillna("").map(lambda e: f" ({e.title()})" if e and e not in ("SELF-EMPLOYED", "SELF EMPLOYED", "NONE", "RETIRED", "N/A") else "")
    nd = pd.concat([named, major[["cycle", "cmte_id", "name", "sector", "amount"]]], ignore_index=True)
    con.execute("CREATE OR REPLACE TABLE named_donors AS SELECT * FROM nd")
    con.execute("""
        CREATE OR REPLACE TABLE ie_funders AS
        WITH tot AS (SELECT cmte_id, cycle, sum(amount) AS t FROM committee_funding GROUP BY 1, 2),
        x AS (SELECT s.bioguide, s.kind, d.name AS donor, d.sector, sum(s.amount * d.amount / t.t) AS amount
              FROM ie_spend s JOIN named_donors d ON d.cmte_id = s.cmte_id AND d.cycle = s.cycle JOIN tot t ON t.cmte_id = s.cmte_id AND t.cycle = s.cycle GROUP BY ALL)
        SELECT * FROM x QUALIFY row_number() OVER (PARTITION BY bioguide, kind ORDER BY amount DESC) <= 25""")
    print(con.execute("SELECT kind, grp, round(sum(amount) / 1e9, 2) AS b FROM ie_coverage GROUP BY 1, 2 ORDER BY 1, 3 DESC").df().to_string(index=False))
    print(con.execute("""SELECT sector, round(sum(amount) / 1e6) AS m FROM ie_traced WHERE kind = 'support' GROUP BY 1 ORDER BY 2 DESC LIMIT 14""").df().to_string(index=False))


if __name__ == "__main__":
    main()
