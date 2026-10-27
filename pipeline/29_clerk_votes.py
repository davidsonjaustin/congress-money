"""House Clerk roll-call XML, 2008 to now: what each House vote was about, so amendment votes can be shown by who offered them.

Voteview leaves the description blank on 3,700 of 3,900 House amendment votes since 2008, and its roll numbers are not the Clerk's (they differ by one or two within a
session, because Voteview skips some quorum calls). So we fetch every Clerk roll for each year and match to Voteview by date, bill and the Yea/Nay totals.

Outputs
  data/raw/clerk/clerk_rolls.csv   one row per Clerk roll (year, roll, date, legis_num, question, amendment_num, amendment_author, desc, yea, nay)
  analysis.duckdb.vote_label(congress, chamber, rollnumber, label)   a readable label for every House and Senate roll call since 2008
"""
import csv
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import duckdb
import pandas as pd
import requests

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "raw" / "clerk"
OUT.mkdir(parents=True, exist_ok=True)
CSV = OUT / "clerk_rolls.csv"
H = {"User-Agent": "CongressMoneyResearch personal-project research tool"}
FIELDS = ["year", "roll", "date", "legis_num", "question", "amendment_num", "amendment_author", "desc", "yea", "nay"]


def tag(x: str, t: str) -> str:
    m = re.search(rf"<{t}>(.*?)</{t}>", x, re.S)
    return re.sub(r"\s+", " ", m.group(1)).strip() if m else ""


def fetch(year: int, roll: int):
    for attempt in range(3):
        try:
            r = requests.get(f"https://clerk.house.gov/evs/{year}/roll{roll:03d}.xml", headers=H, timeout=40)
            if r.status_code == 404:
                return None
            if r.status_code == 200:
                x = r.text
                yea = re.search(r"<totals-by-vote>.*?<yea-total>(\d+)</yea-total>.*?<nay-total>(\d+)</nay-total>", x, re.S)
                return {"year": year, "roll": roll, "date": tag(x, "action-date"), "legis_num": tag(x, "legis-num"), "question": tag(x, "vote-question"),
                        "amendment_num": tag(x, "amendment-num"), "amendment_author": tag(x, "amendment-author"), "desc": tag(x, "vote-desc"),
                        "yea": int(yea.group(1)) if yea else "", "nay": int(yea.group(2)) if yea else ""}
        except requests.RequestException:
            time.sleep(2 * (attempt + 1))
    return "retry"


def do_year(year: int, done: set):
    out, misses, roll = [], 0, 1
    while misses < 4:
        if (year, roll) in done:
            roll += 1
            misses = 0
            continue
        r = fetch(year, roll)
        if r is None:
            misses += 1
        elif r == "retry":
            misses += 1
        elif not r["date"]:      # past the last roll of the year the Clerk answers 200 with an empty file
            misses += 1
        else:
            misses = 0
            out.append(r)
        roll += 1
    return out


def main():
    done = set()
    if CSV.exists() and CSV.stat().st_size > 0:
        d = pd.read_csv(CSV, dtype=str)
        done = set(zip(d.year.astype(int), d.roll.astype(int)))
    new = not CSV.exists() or CSV.stat().st_size == 0
    years = list(range(2008, 2027))
    with open(CSV, "a", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        if new:
            w.writeheader()
        with ThreadPoolExecutor(max_workers=6) as ex:
            futs = {ex.submit(do_year, y, done): y for y in years}
            for fu in as_completed(futs):
                rows_ = fu.result()
                w.writerows(rows_)
                f.flush()
                print(futs[fu], len(rows_), "new rolls", flush=True)


if __name__ == "__main__":
    main()
    sys.exit(0)
