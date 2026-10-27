"""Federal prime contract dollars from USAspending.gov (public API, no key), fiscal years 2008 to 2025.

Contracts only (award types A-D: definitive contracts, delivery orders, purchase orders, BPA calls), in obligated dollars by action date, two scopes:
  dod = awarding agency Department of Defense;  all = every agency.
Cuts: by recipient (top ~300 names per year), by state of performance, by congressional district of performance.

Output: data/usaspending.duckdb  (separate file so the web server can keep running)
  usa_recipient(fy, scope, recipient, amount)
  usa_state(fy, scope, state, amount, population)
  usa_district(fy, scope, district, amount, population)      district = state FIPS + 2-digit district, e.g. 5101 = VA-01
Cautions: these are PRIME awards; money that reaches companies as subcontracts is not counted. District codes follow the districts USAspending reports
today, so district totals before the 2013 and 2023 redistricting are approximate; state totals are not affected.
"""
import json
import time
from pathlib import Path

import duckdb
import pandas as pd
import requests

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw" / "usaspending"
API = "https://api.usaspending.gov/api/v2"
FYS = range(2008, 2026)
SCOPES = {"dod": [{"type": "awarding", "tier": "toptier", "name": "Department of Defense"}], "all": None}


def filters(fy: int, scope: str) -> dict:
    f = {"award_type_codes": ["A", "B", "C", "D"], "time_period": [{"start_date": f"{fy - 1}-10-01", "end_date": f"{fy}-09-30"}]}
    if SCOPES[scope]:
        f["agencies"] = SCOPES[scope]
    return f


def post(path: str, body: dict, cache: Path) -> dict:
    if cache.exists():
        return json.loads(cache.read_text(encoding="utf-8"))
    for attempt in range(6):
        try:
            r = requests.post(API + path, json=body, timeout=120)
            if r.status_code == 200:
                cache.parent.mkdir(parents=True, exist_ok=True)
                cache.write_text(r.text, encoding="utf-8")
                return r.json()
            print("  status", r.status_code, path, r.text[:120])
        except requests.RequestException as e:
            print("  retry", e)
        time.sleep(3 * (attempt + 1))
    raise RuntimeError(f"failed {path}")


def main() -> None:
    rec, st, di = [], [], []
    for fy in FYS:
        for scope in SCOPES:
            f = filters(fy, scope)
            for page in (1, 2, 3):
                d = post("/search/spending_by_category/recipient/", {"filters": f, "limit": 100, "page": page}, RAW / f"rec_{scope}_{fy}_{page}.json")
                rec += [(fy, scope, x["name"], float(x["amount"])) for x in d["results"] if x["name"]]
                if not d.get("page_metadata", {}).get("hasNext"):
                    break
            for layer, out in (("state", st), ("district", di)):
                d = post("/search/spending_by_geography/", {"filters": f, "scope": "place_of_performance", "geo_layer": layer, "subawards": False}, RAW / f"{layer}_{scope}_{fy}.json")
                out += [(fy, scope, x["shape_code"], float(x["aggregated_amount"] or 0), x.get("population")) for x in d["results"] if x.get("shape_code")]
        print(f"FY{fy} done", flush=True)
    con = duckdb.connect(str(ROOT / "data" / "usaspending.duckdb"))
    r_df = pd.DataFrame(rec, columns=["fy", "scope", "recipient", "amount"])
    s_df = pd.DataFrame(st, columns=["fy", "scope", "state", "amount", "population"])
    d_df = pd.DataFrame(di, columns=["fy", "scope", "district", "amount", "population"])
    con.execute("CREATE OR REPLACE TABLE usa_recipient AS SELECT * FROM r_df")
    con.execute("CREATE OR REPLACE TABLE usa_state AS SELECT * FROM s_df")
    con.execute("CREATE OR REPLACE TABLE usa_district AS SELECT * FROM d_df")
    print(con.execute("SELECT fy, scope, round(sum(amount) / 1e9, 1) AS bn FROM usa_state WHERE state NOT IN ('PR', 'VI', 'GU', 'AS', 'MP') GROUP BY 1, 2 ORDER BY 1, 2").df().pivot(index="fy", columns="scope", values="bn").to_string())


if __name__ == "__main__":
    main()
