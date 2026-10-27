"""Stock trades reported by members of the House under the STOCK Act (Periodic Transaction Reports), 2014 to now.

The House Clerk publishes an index of every disclosure each year (financial-pdfs/<year>FD.zip) and the report itself as a PDF. We read the PDFs' text, pull out each
transaction (who owns the asset, the asset, buy or sell, the trade date, the amount range), match the filer to a member, and put the asset in an industry from its name.
Amounts are reported only as ranges ($1,001-$15,000 and so on); we keep the low and high ends and never treat the midpoint as a real figure.

Not covered: the Senate (its disclosure site asks every visitor to accept terms before it shows anything, which this project does not do on a person's behalf), paper filings
that are scanned images, and holdings that were not traded.

Output (data/trades.duckdb):
  house_ptr(doc_id, year, last, first, state_dst, filed)          one row per report found in the Clerk index
  house_trades(doc_id, owner, asset, ticker, asset_type, tx, tx_date, notified, lo, hi)
  ptr_done(doc_id, n)                                            reports already read (the job can be stopped and restarted)
"""
import io
import re
import sys
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import duckdb
import pandas as pd
import pypdf
import requests

ROOT = Path(__file__).resolve().parent.parent
H = {"User-Agent": "CongressMoneyResearch personal-project research tool"}
YEARS = range(2014, 2027)
META = re.compile(r"^\s*(F\s*S\s*:|S\s*O\s*:|D\s*:|C\s*:|L\s*:|\*|Filing ID|Digitally Signed|I\s*CERTIFY)", re.I)
TX = re.compile(r"(?:\b(?P<owner>SP|DC|JT)\s+)?(?P<asset>[^\[\]]{3,220}?)\s*\[(?P<atype>[A-Z]{2})\]\s*(?P<tx>S\s*\(partial\)|P|S|E)\s+(?P<d1>\d\d/\d\d/\d{4})\s+(?P<d2>\d\d/\d\d/\d{4})\s+\$(?P<lo>[\d,]+)\s*-\s*\$(?P<hi>[\d,]+)")
DATES = re.compile(r"\d\d/\d\d/\d{4}\s+\d\d/\d\d/\d{4}")
# reports filed in 2016 to 2018 use an older layout: no [ST] asset-type code, the ticker in parentheses closes the asset name
OLD = re.compile(r"(?P<asset>[^()]{3,200}?)\s*\((?P<ticker>[A-Z0-9.\-]{1,7})\)\s*(?P<tx>S\s*\(partial\)|P|S|E)\s+(?P<d1>\d\d/\d\d/\d{4})\s+(?P<d2>\d\d/\d\d/\d{4})\s+\$(?P<lo>[\d,]+)\s*-\s*\$(?P<hi>[\d,]+)", re.I)
OWNER = re.compile(r"\b(sp|dc|jt)\b", re.I)


def parse_pdf(content: bytes):
    text = []
    for page in pypdf.PdfReader(io.BytesIO(content)).pages:
        text.append((page.extract_text() or "").replace("\x00", ""))
    lines = [ln for ln in "\n".join(text).split("\n") if not META.match(ln)]
    flat = re.sub(r"\s+", " ", " ".join(lines))
    rows = []
    for m in TX.finditer(flat):
        asset = re.sub(r"\s+", " ", m.group("asset")).strip()
        tk = re.search(r"\(([A-Z0-9.\-]{1,7})\)\s*$", asset)
        rows.append({"owner": m.group("owner") or "", "asset": asset[: tk.start()].strip() if tk else asset, "ticker": tk.group(1) if tk else "", "asset_type": m.group("atype"),
                     "tx": "S" if m.group("tx").startswith("S") else m.group("tx"), "partial": "partial" in m.group("tx"), "tx_date": m.group("d1"), "notified": m.group("d2"),
                     "lo": float(m.group("lo").replace(",", "")), "hi": float(m.group("hi").replace(",", ""))})
    expected = len(DATES.findall(flat))
    if len(rows) < expected:
        old = parse_old(" ".join("\n".join(text).split("\n")))
        if len(old) > len(rows):          # keep whichever reading of the layout found more transactions
            rows = old
    return rows, expected


def parse_old(raw: str):
    flat = re.sub(r"\s+", " ", raw)
    rows = []
    for m in OLD.finditer(flat):
        asset = m.group("asset").split(":")[-1]
        owners = list(OWNER.finditer(asset))
        owner = owners[-1].group(1).upper() if owners else ""
        if owners:
            asset = asset[owners[-1].end():]
        asset = re.sub(r"\s+", " ", asset).strip(" ,-")
        tx = m.group("tx").upper()
        rows.append({"owner": owner, "asset": asset, "ticker": m.group("ticker").upper(), "asset_type": "ST", "tx": "S" if tx.startswith("S") else tx, "partial": "PARTIAL" in tx,
                     "tx_date": m.group("d1"), "notified": m.group("d2"), "lo": float(m.group("lo").replace(",", "")), "hi": float(m.group("hi").replace(",", ""))})
    return rows


def fetch_one(args):
    doc_id, year = args
    for attempt in range(3):
        try:
            r = requests.get(f"https://disclosures-clerk.house.gov/public_disc/ptr-pdfs/{year}/{doc_id}.pdf", headers=H, timeout=60)
            if r.status_code == 404:
                return doc_id, None, 0
            if r.status_code == 200:
                rows, expected = parse_pdf(r.content)
                return doc_id, rows, expected
        except (requests.RequestException, pypdf.errors.PyPdfError, ValueError):
            time.sleep(2 * (attempt + 1))
    return doc_id, None, 0


def main() -> None:
    con = duckdb.connect(str(ROOT / "data" / "trades.duckdb"))
    con.execute("CREATE TABLE IF NOT EXISTS house_ptr (doc_id VARCHAR, year INT, last VARCHAR, first VARCHAR, state_dst VARCHAR, filed VARCHAR)")
    con.execute("""CREATE TABLE IF NOT EXISTS house_trades (doc_id VARCHAR, owner VARCHAR, asset VARCHAR, ticker VARCHAR, asset_type VARCHAR, tx VARCHAR, partial BOOLEAN,
                   tx_date VARCHAR, notified VARCHAR, lo DOUBLE, hi DOUBLE)""")
    con.execute("CREATE TABLE IF NOT EXISTS ptr_done (doc_id VARCHAR, n INT, expected INT)")
    have = {r[0] for r in con.execute("SELECT DISTINCT year FROM house_ptr").fetchall()}
    for y in YEARS:
        if y in have and y < max(YEARS):
            continue
        z = zipfile.ZipFile(io.BytesIO(requests.get(f"https://disclosures-clerk.house.gov/public_disc/financial-pdfs/{y}FD.zip", headers=H, timeout=120).content))
        x = z.read(f"{y}FD.xml").decode("utf-8-sig", "ignore")
        recs = []
        for m in re.findall(r"<Member>.*?</Member>", x, re.S):
            if "<FilingType>P</FilingType>" not in m:
                continue
            g = lambda t: (re.search(rf"<{t}>(.*?)</{t}>", m, re.S) or [None, ""])[1].strip()
            recs.append((g("DocID"), int(g("Year") or y), g("Last"), g("First"), g("StateDst"), g("FilingDate")))
        con.execute(f"DELETE FROM house_ptr WHERE year = {y}")
        df = pd.DataFrame(recs, columns=["doc_id", "year", "last", "first", "state_dst", "filed"])
        con.execute("INSERT INTO house_ptr SELECT * FROM df")
        print(y, len(recs), "reports in the index", flush=True)
    if "--redo" in sys.argv:
        con.execute("DELETE FROM house_trades WHERE doc_id IN (SELECT doc_id FROM ptr_done WHERE expected > n)")
        con.execute("DELETE FROM ptr_done WHERE expected > n")
        sys.argv.remove("--redo")
    todo = con.execute("SELECT doc_id, year FROM house_ptr WHERE doc_id NOT IN (SELECT doc_id FROM ptr_done) ORDER BY year DESC").fetchall()
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else len(todo)
    todo = todo[:limit]
    print(len(todo), "reports to read", flush=True)
    ok = bad = 0
    with ThreadPoolExecutor(max_workers=6) as pool:
        for k, (doc_id, rows, expected) in enumerate(pool.map(fetch_one, todo)):
            if rows is None:
                continue
            if rows:
                df = pd.DataFrame(rows)
                df.insert(0, "doc_id", doc_id)
                con.execute("INSERT INTO house_trades SELECT * FROM df")
            con.execute("INSERT INTO ptr_done VALUES (?,?,?)", [doc_id, len(rows), expected])
            ok += len(rows)
            bad += max(0, expected - len(rows))
            if k % 200 == 0:
                print(f"{k}/{len(todo)} reports, {ok:,} trades parsed, {bad:,} date pairs not parsed", flush=True)
    print(f"done: {ok:,} trades; {bad:,} transaction lines found by date but not parsed")


if __name__ == "__main__":
    main()
