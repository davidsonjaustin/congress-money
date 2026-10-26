"""Download FEC bulk files (candidate master, committee master, PAC->candidate itemized
contributions) for each 2-year cycle and load them into DuckDB.

Individual contributions (indiv*.zip, ~4 GB/cycle) are handled separately in 03_indiv.py.
"""
import io
import sys
import zipfile
from pathlib import Path

import duckdb
import requests

ROOT = Path(__file__).resolve().parent.parent
FEC_DIR = ROOT / "data" / "raw" / "fec"
DB = ROOT / "data" / "congress.duckdb"
CYCLES = list(range(2006, 2028, 2))  # 2006 .. 2026 (cycle year = end year)

COLS = {
    "cn": "CAND_ID CAND_NAME CAND_PTY CAND_ELECTION_YR CAND_OFFICE_ST CAND_OFFICE CAND_OFFICE_DISTRICT CAND_ICI CAND_STATUS CAND_PCC CAND_ST1 CAND_ST2 CAND_CITY CAND_ST CAND_ZIP".split(),
    "cm": "CMTE_ID CMTE_NM TRES_NM CMTE_ST1 CMTE_ST2 CMTE_CITY CMTE_ST CMTE_ZIP CMTE_DSGN CMTE_TP CMTE_PTY CMTE_FILING_FREQ ORG_TP CONNECTED_ORG_NM CAND_ID".split(),
    "pas2": "CMTE_ID AMNDT_IND RPT_TP TRANSACTION_PGI IMAGE_NUM TRANSACTION_TP ENTITY_TP NAME CITY STATE ZIP_CODE EMPLOYER OCCUPATION TRANSACTION_DT TRANSACTION_AMT OTHER_ID CAND_ID TRAN_ID FILE_NUM MEMO_CD MEMO_TEXT SUB_ID".split(),
}


def fetch(kind: str, cycle: int) -> Path | None:
    yy = str(cycle)[2:]
    dest = FEC_DIR / f"{kind}{yy}.zip"
    if dest.exists() and dest.stat().st_size > 0:
        return dest
    url = f"https://www.fec.gov/files/bulk-downloads/{cycle}/{kind}{yy}.zip"
    r = requests.get(url, timeout=300)
    if r.status_code != 200:
        print(f"  skip {url} -> HTTP {r.status_code}")
        return None
    dest.write_bytes(r.content)
    return dest


def main() -> None:
    FEC_DIR.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(DB))
    for kind, cols in COLS.items():
        con.execute(f"DROP TABLE IF EXISTS fec_{kind}")
        created = False
        for cycle in CYCLES:
            z = fetch(kind, cycle)
            if not z:
                continue
            with zipfile.ZipFile(z) as zf:
                member = zf.namelist()[0]
                out = FEC_DIR / f"{kind}{str(cycle)[2:]}.txt"
                if not out.exists():
                    out.write_bytes(zf.read(member))
            colspec = ", ".join(f"'{c}': 'VARCHAR'" for c in cols)
            src = (f"SELECT {cycle} AS cycle, * FROM read_csv('{out.as_posix()}', delim='|', header=false, "
                   f"columns={{{colspec}}}, quote='', escape='', null_padding=true, ignore_errors=true)")
            if not created:
                con.execute(f"CREATE TABLE fec_{kind} AS {src}")
                created = True
            else:
                con.execute(f"INSERT INTO fec_{kind} {src}")
            print(f"{kind} {cycle}: {con.execute(f'SELECT count(*) FROM fec_{kind} WHERE cycle={cycle}').fetchone()[0]} rows")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
