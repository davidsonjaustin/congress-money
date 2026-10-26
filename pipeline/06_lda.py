"""Ingest Senate LDA (lobbying disclosure) quarterly reports into data/lda.duckdb.

Usage:  python 06_lda.py 2023 2024 [--types Q1 Q2 Q3 Q4 1A 2A 3A 4A] [--per-min 100] [--workers 5]
Auth:   LDA_API_KEY env var or data/.lda_key (free key from lda.gov; anonymous is ~15 req/min).
Resumable: progress is stored per (year, type) as the last flushed page.

Tables:
  lda_filings(filing_uuid, filing_type, filing_year, period, posted, income, expenses,
              registrant_id, registrant_name, client_id, client_name, client_desc)
  lda_activities(filing_uuid, issue_code, description)          -- free-text "specific issues"
  lda_bills(filing_uuid, congress, bill_type, bill_number)      -- bills named in the text
Filing types: Q1-Q4 = quarterly reports, 1A-4A = their amendments (activity-bearing). An amended
filing supersedes the original, so analysis must keep the latest per registrant+client+period.
"""
import argparse
import os
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import duckdb
import pandas as pd
import requests

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "lda.duckdb"
API = "https://lda.gov/api/v1/filings/"
DEFAULT_TYPES = ["Q1", "Q2", "Q3", "Q4", "1A", "2A", "3A", "4A"]
PAGE_SIZE = 25
CHUNK = 24  # pages fetched in parallel, then flushed to the database together

# (regex, canonical bill_type). Lookbehind keeps "U.S. 1234"/"AS 12" from matching bare "S".
BILL_PATTERNS = [
    (re.compile(r"(?<![A-Za-z])H\.?\s?J\.?\s?Res\.?\s?(\d{1,4})", re.I), "hjres"),
    (re.compile(r"(?<![A-Za-z])S\.?\s?J\.?\s?Res\.?\s?(\d{1,4})", re.I), "sjres"),
    (re.compile(r"(?<![A-Za-z])H\.?\s?Con\.?\s?Res\.?\s?(\d{1,4})", re.I), "hconres"),
    (re.compile(r"(?<![A-Za-z])S\.?\s?Con\.?\s?Res\.?\s?(\d{1,4})", re.I), "sconres"),
    (re.compile(r"(?<![A-Za-z])H\.?\s?R\.?\s?(\d{1,5})(?!\d)"), "hr"),
    (re.compile(r"(?<![A-Za-z.])S\.\s?(\d{1,4})(?!\d)"), "s"),
]


def congress_for(year: int) -> int:
    return (year - 1789) // 2 + 1


def extract_bills(text: str, year: int) -> set[tuple[int, str, int]]:
    out = set()
    for rx, kind in BILL_PATTERNS:
        for m in rx.finditer(text or ""):
            out.add((congress_for(year), kind, int(m.group(1))))
    return out


class Limiter:
    """Shared across threads: spaces requests at per_min and honours server Retry-After pauses."""

    def __init__(self, per_min: float) -> None:
        self.interval, self.lock, self.next, self.pause_until = 60.0 / per_min, threading.Lock(), 0.0, 0.0

    def wait(self) -> None:
        with self.lock:
            now = time.time()
            t = max(self.next, self.pause_until, now)
            self.next = t + self.interval
        time.sleep(max(0.0, t - now))

    def pause(self, secs: float) -> None:
        with self.lock:
            self.pause_until = max(self.pause_until, time.time() + secs)


_local = threading.local()


def get(limiter: Limiter, headers: dict, params: dict) -> dict:
    if not hasattr(_local, "s"):
        _local.s = requests.Session()
        _local.s.headers.update(headers)
    while True:
        limiter.wait()
        try:
            r = _local.s.get(API, params=params, timeout=120)
        except requests.RequestException:
            time.sleep(10)
            continue
        if r.status_code == 429:
            wait = int(r.headers.get("Retry-After", "30")) + 1
            print(f"  throttled, pausing all workers {wait}s")
            sys.stdout.flush()
            limiter.pause(wait)
            continue
        if r.status_code >= 500:
            time.sleep(15)
            continue
        r.raise_for_status()
        return r.json()


def flatten(results: list[dict]):
    filings, acts, bills = [], [], []
    for f in results:
        reg, cli = f.get("registrant") or {}, f.get("client") or {}
        filings.append((f["filing_uuid"], f["filing_type"], f["filing_year"], f.get("filing_period"),
                        (f.get("dt_posted") or "")[:19] or None,
                        float(f["income"]) if f.get("income") else None,
                        float(f["expenses"]) if f.get("expenses") else None,
                        reg.get("id"), reg.get("name"), cli.get("id"), cli.get("name"), cli.get("general_description")))
        seen = set()
        for a in f.get("lobbying_activities") or []:
            acts.append((f["filing_uuid"], a.get("general_issue_code"), a.get("description")))
            seen |= extract_bills(a.get("description") or "", f["filing_year"])
        bills += [(f["filing_uuid"], c, k, n) for c, k, n in seen]
    return filings, acts, bills


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("years", nargs="+", type=int)
    ap.add_argument("--types", nargs="+", default=DEFAULT_TYPES)
    ap.add_argument("--per-min", type=float, default=100)
    ap.add_argument("--workers", type=int, default=5)
    args = ap.parse_args()

    key = os.environ.get("LDA_API_KEY")
    key_file = ROOT / "data" / ".lda_key"
    if not key and key_file.exists():
        key = key_file.read_text().strip()
    headers = {"Authorization": f"Token {key}"} if key else {}
    if not key:
        print("No LDA key found: anonymous access is ~15 requests/min, this will be slow.")
    limiter = Limiter(args.per_min if key else 14)

    con = duckdb.connect(str(DB))
    con.execute("""CREATE TABLE IF NOT EXISTS lda_filings (filing_uuid VARCHAR PRIMARY KEY, filing_type VARCHAR,
        filing_year INT, period VARCHAR, posted TIMESTAMP, income DOUBLE, expenses DOUBLE, registrant_id BIGINT,
        registrant_name VARCHAR, client_id BIGINT, client_name VARCHAR, client_desc VARCHAR)""")
    con.execute("CREATE TABLE IF NOT EXISTS lda_activities (filing_uuid VARCHAR, issue_code VARCHAR, description VARCHAR)")
    con.execute("CREATE TABLE IF NOT EXISTS lda_bills (filing_uuid VARCHAR, congress INT, bill_type VARCHAR, bill_number INT)")
    con.execute("CREATE TABLE IF NOT EXISTS lda_progress (filing_year INT, filing_type VARCHAR, last_page INT, total_pages INT)")

    cols = {
        "lda_filings": ["filing_uuid", "filing_type", "filing_year", "period", "posted", "income", "expenses",
                        "registrant_id", "registrant_name", "client_id", "client_name", "client_desc"],
        "lda_activities": ["filing_uuid", "issue_code", "description"],
        "lda_bills": ["filing_uuid", "congress", "bill_type", "bill_number"],
    }

    def fetch(year: int, ftype: str, page: int) -> dict:
        return get(limiter, headers, {"filing_year": year, "filing_type": ftype, "page": page, "page_size": PAGE_SIZE})

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        for year in args.years:
            for ftype in args.types:
                row = con.execute("SELECT last_page, total_pages FROM lda_progress WHERE filing_year=? AND filing_type=?",
                                  [year, ftype]).fetchone()
                page = (row[0] + 1) if row else 1
                total = row[1] if row else None
                if total is None:
                    total = max(1, -(-fetch(year, ftype, 1)["count"] // PAGE_SIZE))
                while page <= total:
                    pages = list(range(page, min(page + CHUNK, total + 1)))
                    datas = list(pool.map(lambda p: fetch(year, ftype, p), pages))
                    total = max(1, -(-datas[0]["count"] // PAGE_SIZE))
                    results = [f for d in datas for f in d["results"]]
                    filings, acts, bills = flatten(results)
                    if results:
                        uuids = [f["filing_uuid"] for f in results]
                        marks = ",".join("?" * len(uuids))
                        for t in cols:
                            con.execute(f"DELETE FROM {t} WHERE filing_uuid IN ({marks})", uuids)
                    for t, rows in (("lda_filings", filings), ("lda_activities", acts), ("lda_bills", bills)):
                        if rows:
                            df = pd.DataFrame(rows, columns=cols[t])
                            con.register("batch_df", df)
                            con.execute(f"INSERT INTO {t} SELECT * FROM batch_df")
                            con.unregister("batch_df")
                    con.execute("DELETE FROM lda_progress WHERE filing_year=? AND filing_type=?", [year, ftype])
                    con.execute("INSERT INTO lda_progress VALUES (?,?,?,?)", [year, ftype, pages[-1], total])
                    print(time.strftime("%H:%M:%S"), f"{year} {ftype}: page {pages[-1]}/{total}")
                    sys.stdout.flush()
                    page = pages[-1] + 1


if __name__ == "__main__":
    main()
