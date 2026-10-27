"""Local stake: how much of each state's economy rests on the industries our coded votes touch.

Source: Census County Business Patterns, state files cbp05st.zip ... cbp22st.zip (employment by NAICS industry; public, no key).
Union density comes from the Cooperative Election Study (respondents' own union membership, weighted, by state and year).

Output (analysis.duckdb)
  state_industry(state, year, grp, emp, total_emp, share)          share = industry employment / all private employment in the state-year
  state_union(state, year, share)                                   share of CES respondents in a union household
  local_stake(state, year, subsector, share, z)                    z = share standardised across states within the year
'local_stake' is what the score controls for: a member whose state leans on coal or banks has a local reason to vote with those industries,
whether or not donors push. Suppressed cells (employment withheld, only a size class published) are filled with the class midpoint.
"""
import io
import zipfile
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
import pyarrow.feather as pf
import requests

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw" / "cbp"
YEARS = range(2005, 2023)
# NAICS prefixes -> the subsector they describe. 211 oil and gas extraction, 213 mining support (drilling services), 324 petroleum and coal
# products (refining), 2121 coal mining, 2211 electric power, 5221 depository credit (banks), 3254 pharmaceuticals.
GROUPS = {"oil_gas": ["211", "213"], "refining": ["324"], "coal_mining": ["2121"], "electric_utilities": ["2211"], "banks": ["5221"], "pharma": ["3254"],
          # the other industries the every-vote screen tests (keys are the score labels, so sector-level labels keep their names)
          "Defense & Aerospace": ["3364", "336992", "3366", "332993", "332994", "332995"],     # aerospace, armored vehicles, ships, ordnance
          "Agribusiness & Food": ["311", "312", "115"], "Tech": ["5112", "5182", "334", "517", "5415"], "Transportation": ["481", "482", "484", "485", "488"],
          "Construction": ["23"], "Retail": ["44", "45"], "insurance": ["524"], "physicians_clinicians": ["6211", "6212", "6213", "6214"]}
FLAG_MID = {"A": 10, "B": 60, "C": 175, "E": 375, "F": 750, "G": 1750, "H": 3750, "I": 7500, "J": 17500, "K": 37500, "L": 75000, "M": 100000}


def fetch(year: int) -> pd.DataFrame:
    yy = f"{year % 100:02d}"
    zpath = RAW / f"cbp{yy}st.zip"
    if not zpath.exists():
        r = requests.get(f"https://www2.census.gov/programs-surveys/cbp/datasets/{year}/cbp{yy}st.zip", timeout=300)
        r.raise_for_status()
        zpath.write_bytes(r.content)
    with zipfile.ZipFile(zpath) as z:
        name = [n for n in z.namelist() if n.lower().endswith(".txt")][0]
        want = {"fipstate", "naics", "lfo", "empflag", "emp"}
        df = pd.read_csv(z.open(name), usecols=lambda c: c.strip().lower() in want, dtype=str, encoding="latin-1")
    df.columns = [c.strip().lower() for c in df.columns]
    df["naics"] = df["naics"].str.replace(r"[/-]", "", regex=True)
    if "lfo" in df:
        df = df[df["lfo"].isin(["-", None]) | df["lfo"].isna()]
    emp = pd.to_numeric(df["emp"], errors="coerce").fillna(0)
    if "empflag" in df:
        mid = df["empflag"].map(FLAG_MID)
        emp = np.where((emp == 0) & mid.notna(), mid, emp)
    df["emp"] = emp
    df["year"] = year
    return df[["fipstate", "naics", "year", "emp"]]


def main() -> None:
    RAW.mkdir(parents=True, exist_ok=True)
    aip = pd.read_csv(ROOT / "data" / "raw" / "district" / "aip_states_ideology_v2022a.tab", sep="\t")[["abb", "fips"]].drop_duplicates()
    fips = {f"{int(f):02d}": a for a, f in zip(aip["abb"], aip["fips"])}
    rows = []
    for y in YEARS:
        d = fetch(y)
        total = d[d["naics"] == ""].groupby("fipstate")["emp"].sum()
        for grp, prefixes in GROUPS.items():
            sel = d[d["naics"].isin(prefixes)].groupby("fipstate")["emp"].sum()
            for st in total.index:
                rows.append((fips.get(st), y, grp, float(sel.get(st, 0)), float(total[st])))
        print(f"  {y} done", end="\r")
    si = pd.DataFrame(rows, columns=["state", "year", "grp", "emp", "total_emp"]).dropna(subset=["state"])
    si["share"] = si["emp"] / si["total_emp"]

    cu = pf.read_table(ROOT / "data" / "raw" / "district" / "ces_cumulative.feather", columns=["year", "st", "union", "weight"]).to_pandas()
    cu = cu[cu["union"].notna()]                       # 1 = current union member, 2 = former, 3 = never
    cu["u"] = (cu["union"] == 1).astype(float)
    su = cu.assign(wu=cu["u"] * cu["weight"]).groupby(["st", "year"]).agg(wu=("wu", "sum"), w=("weight", "sum")).reset_index()
    su["share"] = su["wu"] / su["w"]
    su = su.rename(columns={"st": "state"})[["state", "year", "share"]]

    ls = si.rename(columns={"grp": "subsector"})[["state", "year", "subsector", "share"]]
    lab = su.assign(subsector="Labor")[["state", "year", "subsector", "share"]]
    ls = pd.concat([ls, lab], ignore_index=True)
    ls["z"] = ls.groupby(["year", "subsector"])["share"].transform(lambda s: (s - s.mean()) / s.std(ddof=0) if s.std(ddof=0) > 0 else 0.0)

    # one row for every year 2005-2026 using the nearest year we have (Census stops at 2022; the survey skips a couple of years)
    full = []
    for (st, sub), g in ls.groupby(["state", "subsector"]):
        g = g.drop_duplicates("year").set_index("year").sort_index()
        idx = list(range(2005, 2027))
        r = g.reindex(idx, method="nearest")
        r["state"], r["subsector"], r["year"] = st, sub, idx
        full.append(r.reset_index(drop=True))
    ls = pd.concat(full, ignore_index=True)[["state", "year", "subsector", "share", "z"]]
    # Defense: what matters for a member's vote is also DoD contract dollars performed in the state, so add a second defense stake from USAspending
    # (3-year average of DoD prime contract dollars per resident, logged and z-scored across states), keyed 'Defense contracts'
    try:
        us = duckdb.connect(str(ROOT / "data" / "usaspending.duckdb"), read_only=True)
        dc = us.execute("SELECT fy AS year, state, amount / nullif(population, 0) AS pc FROM usa_state WHERE scope = 'dod' AND length(state) = 2 AND population > 0").df()
        us.close()
        dc = dc.sort_values(["state", "year"])
        dc["share"] = dc.groupby("state")["pc"].transform(lambda x: x.rolling(3, min_periods=1).mean())
        dc["z"] = dc.groupby("year")["share"].transform(lambda x: (np.log1p(x) - np.log1p(x).mean()) / np.log1p(x).std(ddof=0))
        dfull = []
        for st, g in dc.groupby("state"):
            g = g.drop_duplicates("year").set_index("year").sort_index().reindex(range(2005, 2027), method="nearest")
            g["state"], g["subsector"], g["year"] = st, "Defense contracts", range(2005, 2027)
            dfull.append(g.reset_index(drop=True))
        ls = pd.concat([ls] + [d[["state", "year", "subsector", "share", "z"]] for d in dfull], ignore_index=True)
    except Exception as e:                      # the contracts file is built by 23_usaspending.py; without it the CBP-only stake is used
        print("defense contract stake skipped:", e)
    con = duckdb.connect(str(ROOT / "data" / "analysis.duckdb"))
    con.execute("CREATE OR REPLACE TABLE state_industry AS SELECT * FROM si")
    con.execute("CREATE OR REPLACE TABLE state_union AS SELECT * FROM su")
    con.execute("CREATE OR REPLACE TABLE local_stake AS SELECT * FROM ls")
    print("\nstate_industry rows:", len(si), "| union rows:", len(su))
    print("Top states by 2019 share of private employment:")
    for grp in list(GROUPS) + ["Labor"]:
        t = ls[(ls["year"] == 2019) & (ls["subsector"] == grp)].sort_values("share", ascending=False).head(5)
        print(f"  {grp:18s}", ", ".join(f"{s} {100*v:.1f}%" for s, v in zip(t["state"], t["share"])))


if __name__ == "__main__":
    main()
