"""Stream FEC itemized individual contributions (~0.6-4 GB per cycle) and keep only
weekly aggregates for contributions that reached a sitting/former member's committees.

Per cycle: download -> extract -> aggregate with DuckDB -> delete raw files. Resumable:
cycles already recorded in `indiv_done` are skipped.

Output (data/indiv.duckdb):
  indiv_agg(cycle, cand_id, cmte_dsgn, week, employer, occupation, total, n)
Itemized only (> $200 per cycle per donor); unitemized small-dollar money is not in FEC bulk data.
"""
import shutil
import sys
import time
import zipfile
from pathlib import Path

import duckdb
import requests

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw" / "fec_indiv"
MAIN_DB = ROOT / "data" / "congress.duckdb"
DB = ROOT / "data" / "indiv.duckdb"
CYCLES = list(range(2006, 2028, 2))

INDIV_COLS = ("CMTE_ID AMNDT_IND RPT_TP TRANSACTION_PGI IMAGE_NUM TRANSACTION_TP ENTITY_TP NAME CITY STATE "
              "ZIP_CODE EMPLOYER OCCUPATION TRANSACTION_DT TRANSACTION_AMT OTHER_ID TRAN_ID FILE_NUM "
              "MEMO_CD MEMO_TEXT SUB_ID").split()
CCL_COLS = "CAND_ID CAND_ELECTION_YR FEC_ELECTION_YR CMTE_ID CMTE_TP CMTE_DSGN LINKAGE_ID".split()


def log(msg: str) -> None:
    print(time.strftime("%H:%M:%S"), msg)
    sys.stdout.flush()


def download(url: str, dest: Path) -> bool:
    with requests.get(url, stream=True, timeout=120) as r:
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


def colspec(cols: list[str]) -> str:
    return ", ".join(f"'{c}': 'VARCHAR'" for c in cols)


def main() -> None:
    RAW.mkdir(parents=True, exist_ok=True)

    main_con = duckdb.connect(str(MAIN_DB), read_only=True)
    fec_ids = [r[0] for r in main_con.execute("SELECT DISTINCT fec_id FROM id_crosswalk WHERE fec_id IS NOT NULL").fetchall()]
    main_con.close()

    con = duckdb.connect(str(DB))
    con.execute("CREATE OR REPLACE TABLE member_fec (cand_id VARCHAR)")
    con.executemany("INSERT INTO member_fec VALUES (?)", [(i,) for i in fec_ids])
    con.execute("""CREATE TABLE IF NOT EXISTS indiv_agg (
        cycle INT, cand_id VARCHAR, cmte_dsgn VARCHAR, week DATE, employer VARCHAR, occupation VARCHAR,
        total DOUBLE, n INT)""")
    con.execute("CREATE TABLE IF NOT EXISTS indiv_done (cycle INT, rows_in BIGINT, rows_out BIGINT, secs DOUBLE)")
    done = {r[0] for r in con.execute("SELECT cycle FROM indiv_done").fetchall()}

    for cycle in CYCLES:
        if cycle in done:
            log(f"{cycle}: already done")
            continue
        yy = str(cycle)[2:]
        t0 = time.time()
        base = f"https://www.fec.gov/files/bulk-downloads/{cycle}"

        ccl_zip, ccl_txt = RAW / f"ccl{yy}.zip", RAW / f"ccl{yy}.txt"
        if not download(f"{base}/ccl{yy}.zip", ccl_zip):
            continue
        extract(ccl_zip, ccl_txt)
        con.execute("DROP TABLE IF EXISTS cand_cmte")
        con.execute(f"""
            CREATE TABLE cand_cmte AS
            SELECT DISTINCT CAND_ID AS cand_id, CMTE_ID AS cmte_id, CMTE_DSGN AS dsgn
            FROM read_csv('{ccl_txt.as_posix()}', delim='|', header=false, columns={{{colspec(CCL_COLS)}}},
                          quote='', escape='', null_padding=true, ignore_errors=true)
            WHERE CAND_ID IN (SELECT cand_id FROM member_fec) AND CMTE_DSGN IN ('P', 'A', 'D')""")

        z, txt = RAW / f"indiv{yy}.zip", RAW / f"indiv{yy}.txt"
        log(f"{cycle}: downloading indiv{yy}.zip ...")
        if not download(f"{base}/indiv{yy}.zip", z):
            continue
        log(f"{cycle}: downloaded {z.stat().st_size/1e9:.2f} GB, extracting")
        extract(z, txt)
        z.unlink()
        log(f"{cycle}: extracted {txt.stat().st_size/1e9:.2f} GB, aggregating")

        rows_in = 0
        con.execute(f"DELETE FROM indiv_agg WHERE cycle = {cycle}")
        con.execute(f"""
            INSERT INTO indiv_agg
            SELECT {cycle}, l.cand_id, l.dsgn, date_trunc('week', i.d)::DATE AS week,
                   upper(trim(i.EMPLOYER)), upper(trim(i.OCCUPATION)), sum(i.amt), count(*)::INT
            FROM (
                SELECT CMTE_ID, EMPLOYER, OCCUPATION,
                       TRY_STRPTIME(TRANSACTION_DT, '%m%d%Y')::DATE AS d,
                       TRY_CAST(TRANSACTION_AMT AS DOUBLE) AS amt
                FROM read_csv('{txt.as_posix()}', delim='|', header=false, columns={{{colspec(INDIV_COLS)}}},
                              quote='', escape='', null_padding=true, ignore_errors=true)
                WHERE coalesce(MEMO_CD, '') <> 'X'
                  AND TRANSACTION_TP IN ('15', '15E', '22Y')
                  AND coalesce(ENTITY_TP, 'IND') IN ('IND', '')
            ) i
            JOIN cand_cmte l ON l.cmte_id = i.CMTE_ID
            WHERE i.d IS NOT NULL AND i.amt IS NOT NULL AND year(i.d) BETWEEN {cycle - 1} AND {cycle}
            GROUP BY ALL""")
        rows_out = con.execute(f"SELECT count(*) FROM indiv_agg WHERE cycle = {cycle}").fetchone()[0]
        txt.unlink()
        ccl_zip.unlink(); ccl_txt.unlink()
        con.execute("INSERT INTO indiv_done VALUES (?,?,?,?)", [cycle, rows_in, rows_out, time.time() - t0])
        total = con.execute(f"SELECT round(sum(total)/1e6,1) FROM indiv_agg WHERE cycle = {cycle}").fetchone()[0]
        log(f"{cycle}: done -> {rows_out:,} aggregate rows, ${total}M itemized, {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
