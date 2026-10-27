"""Who lobbies for the big companies outside defense, and where did they work before? Senate LDA filings, 2008 to 2026.

The same method as 26_revolving_door.py (defense), run for the companies in definitions/companies.csv: search the LDA API by the company's name, keep the filings whose
client matches the company's lobbying pattern, and record each filing's lobbyists with the government job they report having held (the "covered position").
Resumable: companies already in the output are skipped.

Output (data/revolving.duckdb)
  rv_filing(slug, filing_uuid, filing_type, year, period, registrant, client, posted)
  rv_lobbyist(slug, filing_uuid, year, lobbyist_id, lobbyist, covered_position)
  rv_done(slug)
"""
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import duckdb
import pandas as pd
import requests

ROOT = Path(__file__).resolve().parent.parent
KEY = (ROOT / "data" / ".lda_key").read_text().strip()
H = {"Authorization": f"Token {KEY}"}
API = "https://lda.gov/api/v1/filings/"
YEARS = range(2008, 2027)
TOP = 70


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def fetch(name: str, year: int) -> list[dict]:
    out, page = [], 1
    while True:
        for attempt in range(6):
            try:
                r = requests.get(API, params={"filing_year": year, "client_name": name, "page_size": 25, "page": page}, headers=H, timeout=90)
                if r.status_code == 429:
                    time.sleep(5 * (attempt + 1))
                    continue
                r.raise_for_status()
                break
            except requests.RequestException:
                time.sleep(3 * (attempt + 1))
        else:
            raise RuntimeError(f"failed {name} {year} p{page}")
        d = r.json()
        out += d["results"]
        if not d.get("next"):
            return out
        page += 1


def main() -> None:
    co = pd.read_csv(ROOT / "pipeline" / "definitions" / "companies.csv", dtype=str).fillna("")
    # biggest lobbying spenders first, and only the top TOP: the long tail costs hours of API calls for little extra
    try:
        rank = duckdb.connect(str(ROOT / "data" / "companies.duckdb"), read_only=True).execute(
            "SELECT s.name FROM company s JOIN company_year y USING (slug) GROUP BY 1 ORDER BY sum(y.lobbying) DESC NULLS LAST").df()["name"].tolist()
        co["rank"] = co["company"].map({n: i for i, n in enumerate(rank)}).fillna(9999)
        co = co.sort_values("rank").head(TOP).reset_index(drop=True)
    except duckdb.Error:
        pass
    con = duckdb.connect(str(ROOT / "data" / "revolving.duckdb"))
    con.execute("CREATE TABLE IF NOT EXISTS rv_filing (slug VARCHAR, filing_uuid VARCHAR, filing_type VARCHAR, year INT, period VARCHAR, registrant VARCHAR, client VARCHAR, posted VARCHAR)")
    con.execute("CREATE TABLE IF NOT EXISTS rv_lobbyist (slug VARCHAR, filing_uuid VARCHAR, year INT, lobbyist_id BIGINT, lobbyist VARCHAR, covered_position VARCHAR)")
    con.execute("CREATE TABLE IF NOT EXISTS rv_done (slug VARCHAR)")
    done = {r[0] for r in con.execute("SELECT slug FROM rv_done").fetchall()}
    only = sys.argv[1:]
    for r in co.itertuples(index=False):
        s = slug(r.company)
        if s in done or (only and s not in only):
            continue
        rx = re.compile(r.regex)
        terms = [t for t in r.search.split("|") if t]
        jobs = [(t, y) for t in terms for y in YEARS]
        fil, lob, seen = [], [], set()
        with ThreadPoolExecutor(max_workers=8) as pool:
            for (term, year), res in zip(jobs, pool.map(lambda j: fetch(j[0], j[1]), jobs)):
                for f in res:
                    cname = (f["client"]["name"] or "").upper()
                    if not rx.search(cname) or f["filing_uuid"] in seen:
                        continue
                    seen.add(f["filing_uuid"])
                    fil.append((s, f["filing_uuid"], f["filing_type"], f["filing_year"], f["filing_period"], f["registrant"]["name"], f["client"]["name"], f["dt_posted"]))
                    for a in f["lobbying_activities"]:
                        for l in a.get("lobbyists") or []:
                            p = l["lobbyist"]
                            lob.append((s, f["filing_uuid"], f["filing_year"], p["id"], " ".join(x for x in (p["first_name"], p["last_name"]) if x), l.get("covered_position")))
        if fil:
            con.register("f_df", pd.DataFrame(fil, columns=["slug", "filing_uuid", "filing_type", "year", "period", "registrant", "client", "posted"]).drop_duplicates())
            con.execute("INSERT INTO rv_filing SELECT * FROM f_df")
        if lob:
            con.register("l_df", pd.DataFrame(lob, columns=["slug", "filing_uuid", "year", "lobbyist_id", "lobbyist", "covered_position"]).drop_duplicates())
            con.execute("INSERT INTO rv_lobbyist SELECT * FROM l_df")
        con.execute("INSERT INTO rv_done VALUES (?)", [s])
        print(f"{r.company}: {len(fil):,} filings, {len(lob):,} lobbyist rows", flush=True)


if __name__ == "__main__":
    main()
