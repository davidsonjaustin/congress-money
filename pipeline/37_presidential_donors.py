"""Who paid for the presidential campaigns, by industry, 2008 to now.

The president acts through orders and appointments rather than roll calls, so there is no vote record to set donors against. What can be shown is who funded each
nominee's campaign and joint fundraising committees (itemized gifts from people and organisations, and gifts from PACs), and which industries those donors work in. The
super PACs that backed each nominee are already covered in the outside-money tables (30_superpac_donors.py).

Streams the same FEC contribution files as 04 and 30, keeps only the committees in COMMITTEES, and aggregates. Resumable; raw files are deleted after use.

Output (data/presidential.duckdb):
  pres_committee(cmte_id, candidate, role)
  pres_receipts(cycle, cmte_id, src, tp, entity_tp, name, other_id, employer, occupation, total, n)
  pres_funding(candidate, cycle, sector, amount)            receipts by who gave, after dropping transfers between a candidate's own committees
  pres_employers(candidate, cycle, employer, amount)         the 25 employers whose staff gave most
"""
import importlib.util
import re
import time
from pathlib import Path

import duckdb
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw" / "fec_indiv"
DB = ROOT / "data" / "presidential.duckdb"
CYCLES = list(range(2008, 2028, 2))
# candidate, role, committee ids
COMMITTEES = {
    "Obama": [("campaign", "C00431445"), ("joint fundraising", "C00451393"), ("joint fundraising", "C00494740")],
    "McCain": [("campaign", "C00430470"), ("campaign", "C00453928"), ("joint fundraising", "C00453738")],
    "Romney": [("campaign", "C00431171"), ("joint fundraising", "C00518282")],
    "Clinton": [("campaign", "C00431569"), ("campaign", "C00575795"), ("joint fundraising", "C00586537")],
    "Trump": [("campaign", "C00580100"), ("joint fundraising", "C00618389"), ("joint fundraising", "C00618371"), ("joint fundraising", "C00770941"), ("campaign", "C00828541"),
              ("joint fundraising", "C00867937"), ("joint fundraising", "C00873893")],
    "Biden / Harris": [("campaign", "C00703975"), ("campaign", "C00694455"), ("joint fundraising", "C00744946"), ("joint fundraising", "C00745976"),
                       ("joint fundraising", "C00746651"), ("joint fundraising", "C00762229")],
}
RECEIPT_TP = ("10", "11", "15", "15C", "15E", "15I", "15T", "15Z", "16C", "18K", "18U")      # 18G (transfers from the candidate's own committees) is left out


def load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


sp = load(Path(__file__).with_name("30_superpac_donors.py"), "sp30")
emp = load(Path(__file__).with_name("07_employer_sectors.py"), "emp07")


def main() -> None:
    RAW.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(DB))
    ids = [(c, role, cm) for c, lst in COMMITTEES.items() for role, cm in lst]
    pc = pd.DataFrame(ids, columns=["candidate", "role", "cmte_id"])
    con.execute("CREATE OR REPLACE TABLE pres_committee AS SELECT cmte_id, candidate, role FROM pc")
    con.execute("CREATE TABLE IF NOT EXISTS pres_receipts (cycle INT, cmte_id VARCHAR, src VARCHAR, tp VARCHAR, entity_tp VARCHAR, name VARCHAR, other_id VARCHAR, employer VARCHAR, occupation VARCHAR, total DOUBLE, n INT)")
    con.execute("CREATE TABLE IF NOT EXISTS pres_done (cycle INT, src VARCHAR)")
    done = {(r[0], r[1]) for r in con.execute("SELECT cycle, src FROM pres_done").fetchall()}
    for cycle in CYCLES:
        yy = str(cycle)[2:]
        for src, fname in (("oth", f"oth{yy}"), ("indiv", f"indiv{yy}")):
            if (cycle, src) in done:
                continue
            z, txt = RAW / f"{fname}.zip", RAW / f"{fname}.txt"
            t0 = time.time()
            print(f"{cycle} {src}: downloading", flush=True)
            if not sp.download(f"https://www.fec.gov/files/bulk-downloads/{cycle}/{fname}.zip", z):
                continue
            sp.extract(z, txt)
            z.unlink()
            con.execute(f"DELETE FROM pres_receipts WHERE cycle = {cycle} AND src = '{src}'")
            con.execute(f"""
                INSERT INTO pres_receipts
                SELECT {cycle}, CMTE_ID, '{src}', TRANSACTION_TP, coalesce(ENTITY_TP, ''),
                       CASE WHEN coalesce(ENTITY_TP, '') NOT IN ('IND', '') THEN upper(trim(NAME)) END, nullif(OTHER_ID, ''),
                       CASE WHEN coalesce(ENTITY_TP, '') IN ('IND', '') THEN upper(trim(EMPLOYER)) END, CASE WHEN coalesce(ENTITY_TP, '') IN ('IND', '') THEN upper(trim(OCCUPATION)) END,
                       sum(TRY_CAST(TRANSACTION_AMT AS DOUBLE)), count(*)::INT
                FROM read_csv('{txt.as_posix()}', delim='|', header=false, columns={{{sp.spec(sp.COLS)}}}, quote='', escape='', null_padding=true, ignore_errors=true)
                WHERE coalesce(MEMO_CD, '') <> 'X' AND CMTE_ID IN (SELECT cmte_id FROM pres_committee) AND TRY_CAST(TRANSACTION_AMT AS DOUBLE) IS NOT NULL
                GROUP BY CMTE_ID, TRANSACTION_TP, ENTITY_TP, CASE WHEN coalesce(ENTITY_TP, '') NOT IN ('IND', '') THEN upper(trim(NAME)) END, nullif(OTHER_ID, ''),
                         CASE WHEN coalesce(ENTITY_TP, '') IN ('IND', '') THEN upper(trim(EMPLOYER)) END, CASE WHEN coalesce(ENTITY_TP, '') IN ('IND', '') THEN upper(trim(OCCUPATION)) END""")
            txt.unlink()
            con.execute("INSERT INTO pres_done VALUES (?,?)", [cycle, src])
            n, tot = con.execute(f"SELECT count(*), round(sum(total) / 1e6, 1) FROM pres_receipts WHERE cycle = {cycle} AND src = '{src}'").fetchone()
            print(f"{cycle} {src}: {n:,} rows, ${tot}M, {time.time() - t0:.0f}s", flush=True)

    # sort receipts into industries (same rules as the outside-money tables)
    q31 = load(Path(__file__).with_name("31_ie_traced.py"), "q31")
    rc = con.execute(f"SELECT r.cycle, c.candidate, r.src, r.entity_tp, r.name, r.other_id, r.employer, r.occupation, sum(r.total) AS amount FROM pres_receipts r JOIN pres_committee c USING (cmte_id) WHERE r.tp IN {RECEIPT_TP} GROUP BY ALL").df()
    rc = rc.fillna({"employer": "", "occupation": "", "name": "", "other_id": "", "entity_tp": ""})
    ccon = duckdb.connect(str(ROOT / "data" / "congress.duckdb"), read_only=True)
    cs = ccon.execute("SELECT cmte_id, sector FROM committee_sector").df().set_index("cmte_id")["sector"].to_dict()
    cache: dict = {}

    def sector(r) -> str:
        if r.entity_tp in ("IND", ""):
            k = ("i", r.employer, r.occupation)
            if k not in cache:
                cache[k] = emp.classify(r.employer, r.occupation)[0]
            return cache[k]
        if r.entity_tp == "ORG":
            k = ("o", r.name)
            if k not in cache:
                cache[k] = q31.org_sector(r.name)
            return cache[k]
        s = cs.get(r.other_id)
        return s if s and s not in ("Candidate committee", "Leadership PAC", "Joint fundraising", "Party committee", "Caucus & Party-Aligned PACs") else q31.COMMITTEES

    rc["sector"] = [sector(r) for r in rc.itertuples(index=False)]
    pf = rc[rc["amount"] > 0].groupby(["candidate", "cycle", "sector"], as_index=False)["amount"].sum()
    con.execute("CREATE OR REPLACE TABLE pres_funding AS SELECT * FROM pf")
    pe = rc[(rc["amount"] > 0) & rc["employer"].ne("")].groupby(["candidate", "cycle", "employer"], as_index=False)["amount"].sum()
    pe = pe[~pe["employer"].str.match(emp.NO_INFO)].sort_values("amount", ascending=False).groupby(["candidate", "cycle"]).head(25)
    con.execute("CREATE OR REPLACE TABLE pres_employers AS SELECT * FROM pe")
    pd.set_option("display.width", 200)
    print(con.execute("SELECT candidate, cycle, round(sum(amount) / 1e6) AS raised_m, round(100 * sum(amount) FILTER (WHERE sector = 'Defense & Aerospace') / sum(amount), 2) AS defense_pct FROM pres_funding GROUP BY ALL ORDER BY cycle, candidate").df().to_string(index=False))


if __name__ == "__main__":
    main()
