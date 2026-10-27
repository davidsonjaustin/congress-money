"""How much of each defense company's revenue is federal contracts, and what it spends to influence the people who fund them.

One row per company and year (2008 to 2025):
  contracts_dod / contracts_all  prime contract dollars obligated to the company's recipients (USAspending; FY Oct-Sep, labelled by FY end year)
  revenue                         total company revenue from SEC annual filings (company fiscal year, labelled by the year it ends)
  lobbying                        lobbying spend named for the company as a client (Senate LDA; outside firms' income or the company's own expenses, latest filing per period)
  pac                             PAC gifts to federal candidates from the company's PAC (FEC 24K)
  indiv                           itemized gifts to members' campaign committees from people who list the company as employer (FEC)

Caveats printed with the table on the site: contracts are PRIME awards, so a company that mostly works as a subcontractor shows less than it really takes;
obligations are not the same as revenue recognised that year; foreign military sales run through DoD contracts and ARE in the DoD totals, direct sales to
foreign governments are not; revenue is total company revenue, so diversified firms (Boeing, GE, Honeywell, RTX before 2020) show a lower share than their defense business.
Output: data/usaspending.duckdb.company_year
"""
import re
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
import requests

ROOT = Path(__file__).resolve().parent.parent
H = {"User-Agent": "CongressMoneyResearch personal-project research tool", "Accept-Encoding": "gzip, deflate"}
REV_TAGS = ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax", "SalesRevenueNet", "SalesRevenueGoodsNet", "RevenueFromContractWithCustomerIncludingAssessedTax"]
YEARS = range(2008, 2026)


def revenue(cik: str) -> dict[int, float]:
    r = requests.get(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{int(cik):010d}.json", headers=H, timeout=120)
    r.raise_for_status()
    gaap = r.json()["facts"].get("us-gaap", {})
    best: dict[tuple[int, str], tuple[str, float]] = {}
    for tag in REV_TAGS:
        for u in gaap.get(tag, {}).get("units", {}).get("USD", []):
            if u.get("form") != "10-K" or "start" not in u:
                continue
            if not 340 <= (pd.Timestamp(u["end"]) - pd.Timestamp(u["start"])).days <= 380:
                continue
            key = ((pd.Timestamp(u["end"]) - pd.Timedelta(days=14)).year, tag)      # 52/53-week years that end in the first days of January belong to the year before
            if key not in best or u["filed"] > best[key][0]:
                best[key] = (u["filed"], float(u["val"]))
    out: dict[int, float] = {}
    for y in {k[0] for k in best}:
        for tag in REV_TAGS:                       # first tag in priority order that has the year
            if (y, tag) in best:
                out[y] = best[(y, tag)][1]
                break
    return out


def match(text: str, rx: str) -> bool:
    return bool(re.search(rx, text.upper())) if rx else False


def main() -> None:
    co = pd.read_csv(ROOT / "pipeline" / "definitions" / "defense_companies.csv", dtype=str).fillna("")
    con = duckdb.connect(str(ROOT / "data" / "usaspending.duckdb"))
    con.execute(f"ATTACH '{(ROOT / 'data' / 'congress.duckdb').as_posix()}' AS c (READ_ONLY)")
    con.execute(f"ATTACH '{(ROOT / 'data' / 'indiv.duckdb').as_posix()}' AS i (READ_ONLY)")
    con.execute(f"ATTACH '{(ROOT / 'data' / 'lda.duckdb').as_posix()}' AS l (READ_ONLY)")
    # the lobbyist tables from 26_revolving_door.py were filtered with an earlier L3 pattern; keep only L3Harris clients that match the current one
    try:
        con.execute("""DELETE FROM lda_def_filing WHERE company LIKE 'L3Harris%' AND NOT regexp_matches(upper(client), '\bL3\b|L-3|HARRIS CORP|EXELIS|L3HARRIS')""")
        for t in ("lda_def_lobbyist", "lda_def_entity", "lda_def_issue"):
            con.execute(f"DELETE FROM {t} WHERE company LIKE 'L3Harris%' AND filing_uuid NOT IN (SELECT filing_uuid FROM lda_def_filing WHERE company LIKE 'L3Harris%')")
    except duckdb.Error as e:
        print("lobbyist cleanup skipped:", e)
    names = co["company"].tolist()
    rows = {(n, y): {"company": n, "kind": k, "year": y} for n, k in zip(co["company"], co["kind"]) for y in YEARS}

    # contracts
    rec = con.execute("SELECT fy, scope, recipient, amount FROM usa_recipient").df()
    for fy, scope, rname, amt in rec.itertuples(index=False):
        u = rname.upper()
        hit = None
        for _, r in co.iterrows():
            if match(u, r["recipient_regex"]):
                hit = r["company"]
                break
        if "SIKORSKY" in u:
            hit = "Lockheed Martin" if fy >= 2016 else "RTX (Raytheon / United Technologies)"
        if hit == "Science Applications International (SAIC)" and fy <= 2013:
            hit = "Leidos (and SAIC before 2014)"
        if hit:
            d = rows[(hit, fy)]
            d[f"contracts_{scope}"] = d.get(f"contracts_{scope}", 0.0) + amt
    # revenue
    for _, r in co.iterrows():
        if not r["cik"]:
            continue
        rev = revenue(r["cik"])
        if r["cik_before_2020"]:
            old = revenue(r["cik_before_2020"])
            for y in YEARS:
                if y < 2020 and y in rev and y in old:
                    rev[y] += old[y]
        for y in YEARS:
            if y in rev:
                rows[(r["company"], y)]["revenue"] = rev[y]
        print(r["company"], "revenue years:", sorted(y for y in rev if y in YEARS)[:1], "...", sorted(y for y in rev if y in YEARS)[-1:], flush=True)
    # lobbying
    lob = con.execute("""
        WITH r AS (SELECT *, row_number() OVER (PARTITION BY registrant_id, client_id, filing_year, period ORDER BY posted DESC) AS rn FROM l.lda_filings)
        SELECT filing_year AS y, client_name, sum(coalesce(income, expenses, 0)) AS amt FROM r WHERE rn = 1 GROUP BY 1, 2""").df()
    for y, cn, amt in lob.itertuples(index=False):
        if y not in YEARS:
            continue
        for _, r in co.iterrows():
            if match(cn, r["lda_regex"]):
                if r["company"].startswith("Leidos") and y >= 2014 and "SCIENCE APPLICATIONS" in cn.upper():
                    r = co[co["company"].str.startswith("Science Applications")].iloc[0]      # new SAIC from 2014
                d = rows[(r["company"], y)]
                d["lobbying"] = d.get("lobbying", 0.0) + amt
                break
    # PAC gifts
    pac = con.execute("""
        SELECT year(strptime(p.TRANSACTION_DT, '%m%d%Y')) AS y, coalesce(s.name, '') || ' ' || coalesce(s.connected_org, '') AS txt, sum(TRY_CAST(p.TRANSACTION_AMT AS DOUBLE)) AS amt
        FROM c.fec_pas2 p JOIN c.committee_sector s ON s.cmte_id = p.CMTE_ID WHERE p.TRANSACTION_TP = '24K' AND length(p.TRANSACTION_DT) = 8 GROUP BY 1, 2""").df()
    for y, txt, amt in pac.itertuples(index=False):
        if y not in YEARS or amt is None:
            continue
        for _, r in co.iterrows():
            if match(txt, r["pac_regex"]):
                if r["company"].startswith("Leidos") and int(y) >= 2014 and "SCIENCE APPLICATIONS" in txt.upper():
                    r = co[co["company"].str.startswith("Science Applications")].iloc[0]
                d = rows[(r["company"], int(y))]
                d["pac"] = d.get("pac", 0.0) + amt
                break
    # individual donors by employer
    big = "|".join(f"(?:{x})" for x in co["employer_regex"] if x)
    ind = con.execute("SELECT year(week) AS y, employer, sum(total) AS amt FROM i.indiv_agg WHERE employer IS NOT NULL GROUP BY 1, 2").df()
    ind = ind[ind["employer"].str.upper().str.contains(big, regex=True, na=False)]
    for y, emp, amt in ind.itertuples(index=False):
        if y not in YEARS:
            continue
        for _, r in co.iterrows():
            if match(emp, r["employer_regex"]):
                d = rows[(r["company"], int(y))]
                d["indiv"] = d.get("indiv", 0.0) + amt
                break
    cy = pd.DataFrame(rows.values())
    for c_ in ("contracts_dod", "contracts_all", "revenue", "lobbying", "pac", "indiv"):
        if c_ not in cy:
            cy[c_] = np.nan
    cy = cy[["company", "kind", "year", "contracts_dod", "contracts_all", "revenue", "lobbying", "pac", "indiv"]]
    con.execute("CREATE OR REPLACE TABLE company_year AS SELECT * FROM cy")
    cov = con.execute("""SELECT r.fy, round(sum(r.amount) / 1e9) AS in_top300, (SELECT round(sum(amount) / 1e9) FROM usa_state s WHERE s.fy = r.fy AND s.scope = 'all') AS total
                         FROM usa_recipient r WHERE r.scope = 'all' GROUP BY 1 ORDER BY 1""").df()
    print("\ncoverage of recipient list vs total federal contracts ($B):\n", cov.T.to_string(header=False))
    pd.set_option("display.width", 240)
    t = cy[cy["year"].isin([2019, 2021, 2023, 2025])].copy()
    t["gov_share"] = t["contracts_all"] / t["revenue"]
    for c_ in ("contracts_all", "revenue", "lobbying", "pac", "indiv"):
        t[c_] = (t[c_] / 1e6).round(1)
    print(t[["company", "year", "contracts_all", "revenue", "gov_share", "lobbying", "pac", "indiv"]].round(2).to_string(index=False))


if __name__ == "__main__":
    main()
