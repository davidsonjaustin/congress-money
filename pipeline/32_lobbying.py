"""Lobbying, by industry: who spends, how much, on what, on which bills, next to PAC giving and federal contracts.

Senate LDA filings name the client (the company or group the lobbying is for), the registrant (the firm paid, or the client itself when it lobbies in-house), what
was paid (income to an outside firm, or expenses for in-house lobbying), the issue areas and the bills. We label each client by industry from its name (and its own
description as a fallback) with the same name rules used for PACs, keep the LATEST filing per registrant, client and period so amendments do not double count,
and total the spending by client, industry and year.

Spend is what filings report, in whole dollars, rounded by the filers (income and expenses under $5,000 are reported as zero or "less than $5,000"). Industry comes
from names, so a few clients are wrong; unlabelled clients (most small ones) are left out of industry totals and counted in `unlabelled`.

Outputs (data/lobbying.duckdb):
  client_industry(client_id, client_name, label, sector)             one row per labelled client
  client_year(client_id, client_name, label, sector, year, spend)    total reported spend per client and year
  industry_year(sector, label, year, clients, spend)                 by industry (label = sub-industry where one exists) and year
  issue_year(sector, year, issue_code, filings)                      filings naming each issue area
  bill_lobbied(sector, label, congress, bill, title, became_law, clients, filings, house_vote, senate_vote)   most-lobbied bills with what happened
  money_year(sector, year, lobbying, pac, indiv, contracts)          lobbying beside PAC gifts, employee gifts and federal contracts, by sector and year
  unlabelled(year, spend)                                            spend that could not be put in an industry
"""
import importlib.util
import re
from pathlib import Path

import duckdb
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
MIN_CLIENTS = 2
YEARS = range(2008, 2027)


def load(name: str):
    spec = importlib.util.spec_from_file_location(name.replace(".py", "_m"), Path(__file__).with_name(name))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


s03, s14 = load("03_sectors.py"), load("14_subsectors.py")
NOT_LABOR = re.compile(r"UNION (PACIFIC|BANK|CARBIDE|ELECTRIC|CAMP|OIL|PLANTERS)|WESTERN UNION|CREDIT UNION|EUROPEAN UNION|UNIONBANCAL|UNIVERSITY|TEACHERS INSURANCE")
SKIP = {"Candidate committee", "Leadership PAC", "Joint fundraising", "Party committee", "Caucus & Party-Aligned PACs", "Ideological / Single-Issue", "Ideological / Single-Issue / Unsorted",
        "Business (sector not yet assigned)", "Lawyers & Lobbyists"}


def classify(text) -> tuple[str, str] | None:
    """(sector, label) from a name, or None."""
    if not isinstance(text, str) or not text.strip():
        return None
    text = text.upper()
    for sector, rx in s03.RULES_RE:
        if sector == "Labor" and NOT_LABOR.search(text):
            continue
        if rx.search(text):
            if sector in SKIP:
                return None
            sub = ""
            if sector in s14.RULES:
                sub = s14.DEFAULT[sector]
                for lab, r in s14.RULES[sector]:
                    if r.search(text):
                        sub = lab
                        break
            return sector, (sub.replace("_", " ") if sub else sector.split(",")[0].replace(" & Consumer", ""))
    return None


def main() -> None:
    out = duckdb.connect(str(ROOT / "data" / "lobbying.duckdb"))
    out.execute(f"ATTACH '{(ROOT / 'data' / 'lda.duckdb').as_posix()}' AS l (READ_ONLY)")
    out.execute(f"ATTACH '{(ROOT / 'data' / 'analysis.duckdb').as_posix()}' AS a (READ_ONLY)")
    out.execute(f"ATTACH '{(ROOT / 'data' / 'congress.duckdb').as_posix()}' AS c (READ_ONLY)")
    out.execute(f"ATTACH '{(ROOT / 'data' / 'bills.duckdb').as_posix()}' AS b (READ_ONLY)")
    out.execute(f"ATTACH '{(ROOT / 'data' / 'usaspending.duckdb').as_posix()}' AS u (READ_ONLY)")

    cl = out.execute("SELECT client_id, any_value(client_name) AS client_name, any_value(client_desc) AS client_desc FROM l.lda_filings WHERE client_id IS NOT NULL GROUP BY 1").df()
    ov = pd.read_csv(ROOT / "pipeline" / "definitions" / "lobbying_client_overrides.csv").set_index("client_id")[["sector", "label"]]
    res = [(ov.loc[cid, "sector"], ov.loc[cid, "label"]) if cid in ov.index else (classify(n or "") or classify(d or ""))
           for cid, n, d in zip(cl["client_id"], cl["client_name"], cl["client_desc"])]
    cl["sector"] = [r[0] if r else None for r in res]
    cl["label"] = [r[1] if r else None for r in res]
    ci = cl.dropna(subset=["label"])[["client_id", "client_name", "label", "sector"]]
    out.execute("CREATE OR REPLACE TABLE client_industry AS SELECT * FROM ci")
    print(f"clients {len(cl):,}; labelled to an industry {len(ci):,}")

    out.execute(f"""
        CREATE OR REPLACE TABLE client_year AS
        WITH r AS (SELECT *, row_number() OVER (PARTITION BY registrant_id, client_id, filing_year, period ORDER BY posted DESC) AS rn FROM l.lda_filings WHERE filing_year BETWEEN 2008 AND 2026)
        SELECT r.client_id, any_value(r.client_name) AS client_name, i.label, i.sector, r.filing_year AS year, sum(coalesce(r.income, r.expenses, 0)) AS spend
        FROM r JOIN client_industry i ON i.client_id = r.client_id WHERE r.rn = 1 GROUP BY r.client_id, i.label, i.sector, r.filing_year""")
    out.execute("""
        CREATE OR REPLACE TABLE industry_year AS
        SELECT sector, label, year, count(DISTINCT client_id) FILTER (WHERE spend > 0) AS clients, sum(spend) AS spend FROM client_year GROUP BY 1, 2, 3""")
    out.execute("""
        CREATE OR REPLACE TABLE unlabelled AS
        WITH r AS (SELECT *, row_number() OVER (PARTITION BY registrant_id, client_id, filing_year, period ORDER BY posted DESC) AS rn FROM l.lda_filings WHERE filing_year BETWEEN 2008 AND 2026)
        SELECT filing_year AS year, sum(coalesce(income, expenses, 0)) AS spend FROM r WHERE rn = 1 AND client_id NOT IN (SELECT client_id FROM client_industry) GROUP BY 1""")
    out.execute("""
        CREATE OR REPLACE TABLE issue_year AS
        WITH r AS (SELECT *, row_number() OVER (PARTITION BY registrant_id, client_id, filing_year, period ORDER BY posted DESC) AS rn FROM l.lda_filings WHERE filing_year BETWEEN 2008 AND 2026)
        SELECT i.sector, r.filing_year AS year, x.issue_code, count(DISTINCT r.filing_uuid) AS filings
        FROM r JOIN client_industry i ON i.client_id = r.client_id JOIN l.lda_activities x ON x.filing_uuid = r.filing_uuid WHERE r.rn = 1 AND x.issue_code IS NOT NULL GROUP BY 1, 2, 3""")

    # bills the industry lobbied, with what happened to them
    out.execute(f"""
        CREATE OR REPLACE TABLE bill_lobbied AS
        WITH lb AS (
            SELECT i.sector, i.label, bl.congress, lower(bl.bill_type) AS bill_type, bl.bill_number, count(DISTINCT f.client_id) AS clients, count(DISTINCT f.filing_uuid) AS filings
            FROM l.lda_bills bl JOIN l.lda_filings f USING (filing_uuid) JOIN client_industry i ON i.client_id = f.client_id
            WHERE bl.congress >= 110 GROUP BY 1, 2, 3, 4, 5 HAVING count(DISTINCT f.client_id) >= {MIN_CLIENTS}),
        pv AS (
            SELECT congress, lower(bill_type) AS bill_type, TRY_CAST(bill_num AS INTEGER) AS bill_number, chamber,
                   arg_max(vote_result || ' ' || yea_count || '-' || nay_count, vote_date) FILTER (WHERE vote_question ILIKE '%passage%' OR vote_question ILIKE '%agreeing to the conference%') AS res
            FROM a.rollcall_topic GROUP BY 1, 2, 3, 4)
        SELECT lb.sector, lb.label, lb.congress, upper(lb.bill_type) || lb.bill_number AS bill, bb.title, bb.became_law, lb.clients, lb.filings,
               (SELECT res FROM pv WHERE pv.congress = lb.congress AND pv.bill_type = lb.bill_type AND pv.bill_number = lb.bill_number AND pv.chamber = 'House') AS house_vote,
               (SELECT res FROM pv WHERE pv.congress = lb.congress AND pv.bill_type = lb.bill_type AND pv.bill_number = lb.bill_number AND pv.chamber = 'Senate') AS senate_vote
        FROM lb LEFT JOIN b.bills bb ON bb.congress = lb.congress AND lower(bb.bill_type) = lb.bill_type AND bb.bill_number = lb.bill_number""")

    # lobbying next to PAC gifts, employee gifts and federal contracts, by sector and year
    rec = out.execute("SELECT fy, recipient, amount FROM u.usa_recipient WHERE scope = 'all'").df()
    rc = [classify(r) for r in rec["recipient"]]
    rec["sector"] = [r[0] if r else None for r in rc]
    cs = rec.dropna(subset=["sector"]).groupby(["sector", "fy"], as_index=False)["amount"].sum().rename(columns={"fy": "year", "amount": "contracts"})
    out.execute("CREATE OR REPLACE TABLE contracts_sector AS SELECT * FROM cs")
    out.execute("""
        CREATE OR REPLACE TABLE money_year AS
        WITH lob AS (SELECT sector, year, sum(spend) AS lobbying FROM client_year GROUP BY 1, 2),
             pac AS (SELECT sector, year(week) AS year, sum(amount) FILTER (WHERE source = 'pac_direct') AS pac, sum(amount) FILTER (WHERE source = 'indiv') AS indiv
                     FROM a.money_weekly WHERE week <= current_date GROUP BY 1, 2),
             k AS (SELECT sector, year FROM lob UNION SELECT sector, year FROM pac UNION SELECT sector, year FROM contracts_sector)
        SELECT k.sector, k.year, lob.lobbying, pac.pac, pac.indiv, cs.contracts
        FROM k LEFT JOIN lob USING (sector, year) LEFT JOIN pac USING (sector, year) LEFT JOIN contracts_sector cs USING (sector, year)
        WHERE k.year BETWEEN 2008 AND 2026 AND k.sector IN (SELECT DISTINCT sector FROM client_industry)""")

    pd.set_option("display.width", 200)
    print(out.execute("SELECT sector, round(sum(spend) FILTER (WHERE year = 2024) / 1e6) AS m2024, round(sum(spend) / 1e9, 1) AS b_all FROM client_year GROUP BY 1 ORDER BY 3 DESC").df().to_string(index=False))
    print(out.execute("SELECT year, round(sum(spend) / 1e6) AS unlabelled_m FROM unlabelled GROUP BY 1 ORDER BY 1 DESC LIMIT 3").df().to_string(index=False))
    print(out.execute("SELECT year, round(sum(spend) / 1e6) AS labelled_m FROM client_year GROUP BY 1 ORDER BY 1 DESC LIMIT 3").df().to_string(index=False))
    print(out.execute("SELECT count(*) AS lobbied_bills FROM bill_lobbied").fetchone())


if __name__ == "__main__":
    main()
