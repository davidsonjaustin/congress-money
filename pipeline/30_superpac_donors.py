"""Who funds the committees that make independent expenditures (super PACs and other outside spenders), 2010 to now.

The scores use direct PAC gifts only. Outside spending is a large and growing channel (about $7.7B in the data, most of it unsorted), and its money comes from the
donors behind each spending committee. This step finds those committees and streams the FEC's contribution files to total what each one received, by who gave.

Inputs (FEC bulk files, downloaded one cycle at a time and deleted after use; resumable):
  pas2 files already in data/raw/fec        -> which committees made independent expenditures (24E support / 24A oppose)
  indiv{yy}.zip  contributions by persons   -> receipts of those committees from individuals and from organizations (ENTITY_TP ORG)
  oth{yy}.zip    committee-to-committee     -> receipts from PACs, party committees and other committees
Output (data/superpac.duckdb):
  ie_committees(cmte_id, name, total_ie)                   spenders with at least MIN_IE of independent expenditures
  ie_receipts(cycle, cmte_id, src, tp, entity_tp, name, other_id, employer, occupation, total, n)
        src = 'indiv' or 'oth'; name is kept for organizations only; individuals are grouped by employer and occupation
  ie_major(cycle, src, cmte_id, name, employer, occupation, total)     individuals who gave $100K or more to one committee in a cycle (public FEC data)
"""
import shutil
import sys
import time
import zipfile
from pathlib import Path

import duckdb
import requests

ROOT = Path(__file__).resolve().parent.parent
FEC = ROOT / "data" / "raw" / "fec"
RAW = ROOT / "data" / "raw" / "fec_indiv"
DB = ROOT / "data" / "superpac.duckdb"
CYCLES = list(range(2010, 2028, 2))
MIN_IE = 100_000
COLS = ("CMTE_ID AMNDT_IND RPT_TP TRANSACTION_PGI IMAGE_NUM TRANSACTION_TP ENTITY_TP NAME CITY STATE ZIP_CODE EMPLOYER OCCUPATION TRANSACTION_DT "
        "TRANSACTION_AMT OTHER_ID TRAN_ID FILE_NUM MEMO_CD MEMO_TEXT SUB_ID").split()
PAS_COLS = ("CMTE_ID AMNDT_IND RPT_TP TRANSACTION_PGI IMAGE_NUM TRANSACTION_TP ENTITY_TP NAME CITY STATE ZIP_CODE EMPLOYER OCCUPATION TRANSACTION_DT "
            "TRANSACTION_AMT OTHER_ID CAND_ID TRAN_ID FILE_NUM MEMO_CD MEMO_TEXT SUB_ID").split()
CM_COLS = "CMTE_ID CMTE_NM TRES_NM CMTE_ST1 CMTE_ST2 CMTE_CITY CMTE_ST CMTE_ZIP CMTE_DSGN CMTE_TP CMTE_PTY_AFFILIATION CMTE_FILING_FREQ ORG_TP CONNECTED_ORG_NM CAND_ID".split()


def log(msg: str) -> None:
    print(time.strftime("%H:%M:%S"), msg, flush=True)


def spec(cols):
    return ", ".join(f"'{c}': 'VARCHAR'" for c in cols)


def download(url: str, dest: Path) -> bool:
    with requests.get(url, stream=True, timeout=180) as r:
        if r.status_code != 200:
            log(f"  {url} -> HTTP {r.status_code}")
            return False
        with dest.open("wb") as f:
            for chunk in r.iter_content(chunk_size=8 << 20):
                f.write(chunk)
    return True


def extract(zpath: Path, dest: Path) -> None:
    with zipfile.ZipFile(zpath) as zf:
        member = max(zf.infolist(), key=lambda i: i.file_size)
        with zf.open(member) as src, dest.open("wb") as out:
            shutil.copyfileobj(src, out, length=16 << 20)


def find_spenders(con) -> None:
    files = sorted(FEC.glob("pas2*.txt"))
    parts = " UNION ALL ".join(
        f"""SELECT CMTE_ID, TRY_CAST(TRANSACTION_AMT AS DOUBLE) AS amt FROM read_csv('{f.as_posix()}', delim='|', header=false, columns={{{spec(PAS_COLS)}}},
                quote='', escape='', null_padding=true, ignore_errors=true) WHERE TRANSACTION_TP IN ('24E', '24A') AND coalesce(MEMO_CD, '') <> 'X'""" for f in files)
    cms = " UNION ALL ".join(
        f"""SELECT CMTE_ID, CMTE_NM FROM read_csv('{f.as_posix()}', delim='|', header=false, columns={{{spec(CM_COLS)}}}, quote='', escape='', null_padding=true, ignore_errors=true)"""
        for f in sorted(FEC.glob("cm[0-9]*.txt")))
    con.execute(f"""CREATE OR REPLACE TABLE ie_committees AS
        WITH s AS (SELECT CMTE_ID AS cmte_id, sum(amt) AS total_ie FROM ({parts}) GROUP BY 1),
             n AS (SELECT CMTE_ID AS cmte_id, arg_max(CMTE_NM, length(CMTE_NM)) AS name FROM ({cms}) GROUP BY 1)
        SELECT s.cmte_id, n.name, s.total_ie FROM s LEFT JOIN n USING (cmte_id) WHERE s.total_ie >= {MIN_IE} ORDER BY s.total_ie DESC""")
    n, tot = con.execute("SELECT count(*), sum(total_ie) FROM ie_committees").fetchone()
    log(f"{n} spending committees with at least ${MIN_IE:,} of independent expenditures, ${tot / 1e9:.2f}B in all")


def main() -> None:
    RAW.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(DB))
    if not con.execute("SELECT count(*) FROM information_schema.tables WHERE table_name = 'ie_committees'").fetchone()[0]:
        find_spenders(con)
    con.execute("""CREATE TABLE IF NOT EXISTS ie_receipts (cycle INT, cmte_id VARCHAR, src VARCHAR, tp VARCHAR, entity_tp VARCHAR, name VARCHAR, other_id VARCHAR,
                   employer VARCHAR, occupation VARCHAR, total DOUBLE, n INT)""")
    con.execute("CREATE TABLE IF NOT EXISTS ie_major (cycle INT, src VARCHAR, cmte_id VARCHAR, name VARCHAR, employer VARCHAR, occupation VARCHAR, total DOUBLE)")
    con.execute("CREATE TABLE IF NOT EXISTS ie_receipts_done (cycle INT, src VARCHAR, secs DOUBLE)")
    done = {(r[0], r[1]) for r in con.execute("SELECT cycle, src FROM ie_receipts_done").fetchall()}
    only = sys.argv[1:]  # optional: cycles to run, e.g. 2024
    for cycle in CYCLES:
        if only and str(cycle) not in only:
            continue
        yy = str(cycle)[2:]
        for src, fname in (("oth", f"oth{yy}"), ("indiv", f"indiv{yy}")):
            if (cycle, src) in done:
                log(f"{cycle} {src}: already done")
                continue
            t0 = time.time()
            z, txt = RAW / f"{fname}.zip", RAW / f"{fname}.txt"
            log(f"{cycle} {src}: downloading {fname}.zip")
            if not download(f"https://www.fec.gov/files/bulk-downloads/{cycle}/{fname}.zip", z):
                continue
            extract(z, txt)
            z.unlink()
            log(f"{cycle} {src}: extracted {txt.stat().st_size / 1e9:.2f} GB, aggregating")
            con.execute(f"DELETE FROM ie_receipts WHERE cycle = {cycle} AND src = '{src}'")
            con.execute(f"DELETE FROM ie_major WHERE cycle = {cycle} AND src = '{src}'")
            con.execute(f"""
                CREATE OR REPLACE TEMP TABLE x AS
                SELECT CMTE_ID, TRANSACTION_TP, coalesce(ENTITY_TP, '') AS ENTITY_TP, upper(trim(NAME)) AS NAME, nullif(OTHER_ID, '') AS OTHER_ID,
                       upper(trim(EMPLOYER)) AS EMPLOYER, upper(trim(OCCUPATION)) AS OCCUPATION, TRY_CAST(TRANSACTION_AMT AS DOUBLE) AS amt
                FROM read_csv('{txt.as_posix()}', delim='|', header=false, columns={{{spec(COLS)}}}, quote='', escape='', null_padding=true, ignore_errors=true)
                WHERE coalesce(MEMO_CD, '') <> 'X' AND CMTE_ID IN (SELECT cmte_id FROM ie_committees)""")
            con.execute(f"""
                INSERT INTO ie_major
                SELECT {cycle}, '{src}', CMTE_ID, NAME, EMPLOYER, OCCUPATION, sum(amt) FROM x WHERE ENTITY_TP IN ('IND', '') AND amt IS NOT NULL
                GROUP BY CMTE_ID, NAME, EMPLOYER, OCCUPATION HAVING sum(amt) >= 100000""")
            con.execute(f"""
                INSERT INTO ie_receipts
                SELECT {cycle}, CMTE_ID, '{src}', TRANSACTION_TP, ENTITY_TP, CASE WHEN ENTITY_TP NOT IN ('IND', '') THEN NAME END, OTHER_ID,
                       CASE WHEN ENTITY_TP IN ('IND', '') THEN EMPLOYER END, CASE WHEN ENTITY_TP IN ('IND', '') THEN OCCUPATION END, sum(amt), count(*)::INT
                FROM x WHERE amt IS NOT NULL
                GROUP BY CMTE_ID, TRANSACTION_TP, ENTITY_TP, CASE WHEN ENTITY_TP NOT IN ('IND', '') THEN NAME END, OTHER_ID,
                         CASE WHEN ENTITY_TP IN ('IND', '') THEN EMPLOYER END, CASE WHEN ENTITY_TP IN ('IND', '') THEN OCCUPATION END""")
            con.execute("DROP TABLE x")
            txt.unlink()
            n, tot = con.execute(f"SELECT count(*), round(sum(total) / 1e6, 1) FROM ie_receipts WHERE cycle = {cycle} AND src = '{src}'").fetchone()
            con.execute("INSERT INTO ie_receipts_done VALUES (?,?,?)", [cycle, src, time.time() - t0])
            log(f"{cycle} {src}: {n:,} rows, ${tot}M in receipts, {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
