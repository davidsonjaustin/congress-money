"""Who lobbies for the defense companies, and where did they work before? Senate LDA filings, 2008 to 2026.

For each company in definitions/defense_companies.csv we search the LDA API by client name, keep filings whose client matches the company's lobbying regex, and
record each filing's lobbyists with the government position they report having held ("covered position"), the issue areas and the parts of government lobbied.

Output (data/usaspending.duckdb)
  lda_def_filing(company, filing_uuid, filing_type, year, period, registrant, client, posted, amount)
  lda_def_lobbyist(company, filing_uuid, year, lobbyist_id, lobbyist, covered_position)
  lda_def_entity(company, filing_uuid, year, entity)          government bodies named as lobbied
  lda_def_issue(company, filing_uuid, year, issue_code)
Amendments supersede originals: analysis keeps the latest filing per registrant, client, year and period.
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
SEARCH = {"Lockheed Martin": ["lockheed martin"], "RTX (Raytheon / United Technologies)": ["raytheon", "united technologies", "rtx corp"], "Boeing": ["boeing"],
          "General Dynamics": ["general dynamics"], "Northrop Grumman": ["northrop grumman"], "L3Harris (Harris / L3)": ["l3harris", "l-3 communications", "l3 technologies", "harris corp"],
          "Huntington Ingalls": ["huntington ingalls"], "Leidos (and SAIC before 2014)": ["leidos", "science applications international"], "Booz Allen Hamilton": ["booz allen"],
          "CACI": ["caci"], "KBR": ["kbr"], "Fluor": ["fluor"], "Honeywell": ["honeywell"], "General Electric": ["general electric"], "Textron": ["textron"], "Oshkosh": ["oshkosh"],
          "Palantir": ["palantir"], "BAE Systems Inc (UK parent)": ["bae systems"]}
YEARS = range(2008, 2027)


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
    co = pd.read_csv(ROOT / "pipeline" / "definitions" / "defense_companies.csv", dtype=str).fillna("")
    rx = {c: re.compile(l) for c, l in zip(co["company"], co["lda_regex"])}
    jobs = [(c, n, y) for c, names in SEARCH.items() for n in names for y in YEARS]
    fil, lob, ent, iss = [], [], [], []
    seen = set()
    with ThreadPoolExecutor(max_workers=8) as pool:
        for k, ((company, name, year), res) in enumerate(zip(jobs, pool.map(lambda j: fetch(j[1], j[2]), jobs))):
            for f in res:
                cname = (f["client"]["name"] or "").upper()
                if not rx[company].search(cname) or (company, f["filing_uuid"]) in seen:
                    continue
                seen.add((company, f["filing_uuid"]))
                amt = f.get("income") or f.get("expenses")
                fil.append((company, f["filing_uuid"], f["filing_type"], f["filing_year"], f["filing_period"], f["registrant"]["name"], f["client"]["name"], f["dt_posted"], float(amt) if amt else None))
                for a in f["lobbying_activities"]:
                    iss.append((company, f["filing_uuid"], f["filing_year"], a["general_issue_code"]))
                    for g in a.get("government_entities") or []:
                        ent.append((company, f["filing_uuid"], f["filing_year"], g["name"]))
                    for l in a.get("lobbyists") or []:
                        p = l["lobbyist"]
                        lob.append((company, f["filing_uuid"], f["filing_year"], p["id"], " ".join(x for x in (p["first_name"], p["last_name"]) if x), l.get("covered_position")))
            if k % 25 == 0:
                print(f"{k}/{len(jobs)} {company} {year}: {len(fil):,} filings", flush=True)
    con = duckdb.connect(str(ROOT / "data" / "usaspending.duckdb"))
    for name, rows, cols in (("lda_def_filing", fil, ["company", "filing_uuid", "filing_type", "year", "period", "registrant", "client", "posted", "amount"]),
                             ("lda_def_lobbyist", lob, ["company", "filing_uuid", "year", "lobbyist_id", "lobbyist", "covered_position"]),
                             ("lda_def_entity", ent, ["company", "filing_uuid", "year", "entity"]), ("lda_def_issue", iss, ["company", "filing_uuid", "year", "issue_code"])):
        df = pd.DataFrame(rows, columns=cols).drop_duplicates()
        con.register("tmp_df", df)
        con.execute(f"CREATE OR REPLACE TABLE {name} AS SELECT * FROM tmp_df")
        con.unregister("tmp_df")
        print(name, len(df))


if __name__ == "__main__":
    main()
