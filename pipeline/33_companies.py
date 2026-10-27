"""One page of facts per company: what it spends lobbying, what its PAC and employees give members of Congress, which members got it, and what the government pays it.

Companies come from definitions/companies.csv (about 130 of the largest lobbying spenders outside defense) and definitions/defense_companies.csv (the defense and
government-services firms already followed on the Defense tab). A company's rows are every source record whose name matches its regular expression:
  lobbying   Senate LDA clients (latest filing per registrant, client and period, so amendments do not double count)
  PAC gifts  FEC 24K gifts from committees whose name or connected organisation matches
  employees  itemized gifts to members from people who list a matching employer
  contracts  USAspending prime contracts to the ~235 largest recipients each fiscal year whose name matches
Name matching is not perfect (a subsidiary with a different name is missed; a short name can catch a stranger), so each page says what it matched.

Output (data/companies.duckdb):
  company(slug, name, sector, in_defense)
  company_year(slug, year, lobbying, pac, indiv, contracts)
  company_issue(slug, issue_code, filings)                top issue areas named in the company's filings, 2018 on
  company_bill(slug, congress, bill, title, filings, became_law)   bills named in most of its filings
  company_member(slug, bioguide, pac, indiv)              members who received the most from its PAC and employees
  client_company(client_id, slug)                         which lobbying clients are attributed to which company
  company_pac(slug, committee)                            the committees counted as its PAC
"""
import re
import warnings
from pathlib import Path

import duckdb
import pandas as pd

warnings.filterwarnings("ignore", message="This pattern is interpreted as a regular expression")
ROOT = Path(__file__).resolve().parent.parent
YEARS = range(2008, 2027)


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def load_companies() -> pd.DataFrame:
    a = pd.read_csv(ROOT / "pipeline" / "definitions" / "companies.csv", dtype=str).fillna("")
    rows = []
    for r in a.itertuples(index=False):
        rows.append({"name": r.company, "sector": {"Tech": "Tech, Telecom & Media", "Health": "Health", "Energy": "Energy & Natural Resources", "Finance": "Finance, Insurance & Real Estate",
                                                   "Transportation": "Transportation", "Agribusiness": "Agribusiness & Food", "Retail": "Retail & Consumer", "Manufacturing": "Manufacturing & Industrial",
                                                   "Construction": "Construction"}[r.sector],
                     "lda": r.regex, "pac": r.pac_regex or r.regex, "emp": r.employer_regex or r.regex, "rec": r.recipient_regex or r.regex, "in_defense": False})
    d = pd.read_csv(ROOT / "pipeline" / "definitions" / "defense_companies.csv", dtype=str).fillna("")
    for r in d.itertuples(index=False):
        rows.append({"name": r.company, "sector": "Defense & Aerospace", "lda": r.lda_regex or r.recipient_regex, "pac": r.pac_regex or r.lda_regex, "emp": r.employer_regex or r.lda_regex,
                     "rec": r.recipient_regex or r.lda_regex, "in_defense": True})
    df = pd.DataFrame(rows)
    for col in ("lda", "pac", "emp", "rec"):                      # SAIC and Leidos are listed separately; before 2014 "Science Applications" was one company, shown here under SAIC
        df.loc[df["name"].str.startswith("Leidos"), col] = df.loc[df["name"].str.startswith("Leidos"), col].str.replace("|SCIENCE APPLICATIONS", "", regex=False)
    df["slug"] = df["name"].map(slug)
    return df.drop_duplicates("slug").reset_index(drop=True)


def first_match(names: pd.Series, co: pd.DataFrame, col: str) -> pd.Series:
    """For each distinct name, the slug of the first company whose regex matches (companies are checked in list order)."""
    out = pd.Series(index=names.index, dtype="object")
    todo = pd.Series(True, index=names.index)
    up = names.str.upper()
    for r in co.itertuples(index=False):
        rx = getattr(r, col)
        if not rx:
            continue
        hit = todo & up.str.contains(rx, regex=True, na=False)
        out[hit] = r.slug
        todo &= ~hit
    return out


def main() -> None:
    co = load_companies()
    con = duckdb.connect(str(ROOT / "data" / "companies.duckdb"))
    con.execute(f"ATTACH '{(ROOT / 'data' / 'congress.duckdb').as_posix()}' AS c (READ_ONLY)")
    con.execute(f"ATTACH '{(ROOT / 'data' / 'indiv.duckdb').as_posix()}' AS i (READ_ONLY)")
    con.execute(f"ATTACH '{(ROOT / 'data' / 'lda.duckdb').as_posix()}' AS l (READ_ONLY)")
    con.execute(f"ATTACH '{(ROOT / 'data' / 'bills.duckdb').as_posix()}' AS b (READ_ONLY)")
    con.execute(f"ATTACH '{(ROOT / 'data' / 'usaspending.duckdb').as_posix()}' AS u (READ_ONLY)")
    con.execute("CREATE OR REPLACE TABLE company AS SELECT slug, name, sector, in_defense FROM co")

    # lobbying
    cl = con.execute("""
        WITH r AS (SELECT *, row_number() OVER (PARTITION BY registrant_id, client_id, filing_year, period ORDER BY posted DESC) AS rn FROM l.lda_filings WHERE filing_year BETWEEN 2008 AND 2026)
        SELECT client_id, any_value(client_name) AS client_name, filing_year AS year, sum(coalesce(income, expenses, 0)) AS amt FROM r WHERE rn = 1 GROUP BY 1, 3""").df()
    names = cl.drop_duplicates("client_id").set_index("client_id")["client_name"].fillna("")
    sl = first_match(names, co, "lda")
    cc = pd.DataFrame({"client_id": names.index, "slug": sl.values}).dropna()
    con.execute("CREATE OR REPLACE TABLE client_company AS SELECT * FROM cc")
    lob = cl.merge(cc, on="client_id").groupby(["slug", "year"], as_index=False)["amt"].sum().rename(columns={"amt": "lobbying"})

    # PAC gifts and which members got them
    pac = con.execute("""
        SELECT p.CMTE_ID AS cmte_id, coalesce(s.name, '') || ' ' || coalesce(s.connected_org, '') AS txt, any_value(coalesce(s.name, '')) AS name
        FROM (SELECT DISTINCT CMTE_ID FROM c.fec_pas2 WHERE TRANSACTION_TP = '24K') p JOIN c.committee_sector s ON s.cmte_id = p.CMTE_ID GROUP BY 1, 2""").df()
    pac["slug"] = first_match(pac["txt"], co, "pac").values
    pm = pac.dropna(subset=["slug"])[["cmte_id", "slug", "name"]]
    con.execute("CREATE OR REPLACE TABLE pac_map AS SELECT * FROM pm")
    con.execute("CREATE OR REPLACE TABLE company_pac AS SELECT slug, name AS committee FROM pm")
    con.execute("""
        CREATE OR REPLACE TABLE pac_gifts AS
        SELECT m.slug, year(strptime(p.TRANSACTION_DT, '%m%d%Y')) AS year, x.bioguide, sum(TRY_CAST(p.TRANSACTION_AMT AS DOUBLE)) AS amt
        FROM c.fec_pas2 p JOIN pac_map m ON m.cmte_id = p.CMTE_ID
        LEFT JOIN (SELECT DISTINCT fec_id, bioguide FROM c.id_crosswalk WHERE fec_id IS NOT NULL AND bioguide IS NOT NULL) x ON x.fec_id = p.CAND_ID
        WHERE p.TRANSACTION_TP = '24K' AND length(p.TRANSACTION_DT) = 8 GROUP BY 1, 2, 3""")

    # employees
    emps = con.execute("SELECT DISTINCT employer FROM i.indiv_agg WHERE employer IS NOT NULL AND employer <> ''").df()["employer"]
    es = first_match(emps, co, "emp")
    em = pd.DataFrame({"employer": emps.values, "slug": es.values}).dropna()
    con.execute("CREATE OR REPLACE TABLE emp_map AS SELECT * FROM em")
    con.execute("""
        CREATE OR REPLACE TABLE emp_gifts AS
        SELECT m.slug, year(a.week) AS year, x.bioguide, sum(a.total) AS amt
        FROM i.indiv_agg a JOIN emp_map m ON m.employer = a.employer
        LEFT JOIN (SELECT DISTINCT fec_id, bioguide FROM c.id_crosswalk WHERE fec_id IS NOT NULL AND bioguide IS NOT NULL) x ON x.fec_id = a.cand_id
        GROUP BY 1, 2, 3""")

    # contracts
    rec = con.execute("SELECT fy, recipient, amount FROM u.usa_recipient WHERE scope = 'all'").df()
    rec["slug"] = first_match(rec["recipient"].fillna(""), co, "rec").values
    ct = rec.dropna(subset=["slug"]).groupby(["slug", "fy"], as_index=False)["amount"].sum().rename(columns={"fy": "year", "amount": "contracts"})

    py = con.execute("SELECT slug, year, sum(amt) AS pac FROM pac_gifts GROUP BY 1, 2").df()
    iy = con.execute("SELECT slug, year, sum(amt) AS indiv FROM emp_gifts GROUP BY 1, 2").df()
    cy = co[["slug"]].merge(pd.DataFrame({"year": list(YEARS)}), how="cross")
    for t in (lob, py, iy, ct):
        cy = cy.merge(t, on=["slug", "year"], how="left")
    con.execute("CREATE OR REPLACE TABLE company_year AS SELECT * FROM cy")
    con.execute("""
        CREATE OR REPLACE TABLE company_member AS
        SELECT slug, bioguide, sum(pac) AS pac, sum(indiv) AS indiv FROM (
            SELECT slug, bioguide, amt AS pac, 0.0 AS indiv FROM pac_gifts WHERE bioguide IS NOT NULL
            UNION ALL SELECT slug, bioguide, 0.0, amt FROM emp_gifts WHERE bioguide IS NOT NULL) GROUP BY 1, 2
        QUALIFY row_number() OVER (PARTITION BY slug ORDER BY sum(pac) + sum(indiv) DESC) <= 15""")

    # issues and bills
    con.execute("""
        CREATE OR REPLACE TABLE company_issue AS
        WITH r AS (SELECT f.filing_uuid, f.client_id, f.filing_year, row_number() OVER (PARTITION BY f.registrant_id, f.client_id, f.filing_year, f.period ORDER BY f.posted DESC) AS rn FROM l.lda_filings f WHERE f.filing_year >= 2018)
        SELECT m.slug, a.issue_code, count(DISTINCT r.filing_uuid) AS filings FROM r JOIN client_company m ON m.client_id = r.client_id JOIN l.lda_activities a ON a.filing_uuid = r.filing_uuid
        WHERE r.rn = 1 AND a.issue_code IS NOT NULL GROUP BY 1, 2""")
    con.execute("""
        CREATE OR REPLACE TABLE company_bill AS
        WITH r AS (SELECT f.filing_uuid, f.client_id, row_number() OVER (PARTITION BY f.registrant_id, f.client_id, f.filing_year, f.period ORDER BY f.posted DESC) AS rn FROM l.lda_filings f WHERE f.filing_year >= 2008),
        x0 AS (SELECT m.slug, bl.congress, lower(bl.bill_type) AS bill_type, bl.bill_number, count(DISTINCT r.filing_uuid) AS filings
               FROM r JOIN client_company m ON m.client_id = r.client_id JOIN l.lda_bills bl ON bl.filing_uuid = r.filing_uuid WHERE r.rn = 1 AND bl.congress >= 110
               GROUP BY m.slug, bl.congress, lower(bl.bill_type), bl.bill_number),
        x AS (SELECT * FROM x0 QUALIFY row_number() OVER (PARTITION BY slug ORDER BY filings DESC) <= 12)
        SELECT x.slug, x.congress, upper(x.bill_type) || x.bill_number AS bill, bb.title, x.filings, bb.became_law
        FROM x LEFT JOIN b.bills bb ON bb.congress = x.congress AND lower(bb.bill_type) = x.bill_type AND bb.bill_number = x.bill_number""")

    pd.set_option("display.width", 200)
    print(con.execute("""
        SELECT c.name, round(sum(y.lobbying) / 1e6) AS lobby_m, round(sum(y.pac) / 1e6, 1) AS pac_m, round(sum(y.indiv) / 1e6, 1) AS emp_m, round(sum(y.contracts) / 1e9, 1) AS contracts_b
        FROM company c JOIN company_year y USING (slug) GROUP BY 1 ORDER BY sum(y.lobbying) DESC NULLS LAST LIMIT 25""").df().to_string(index=False))
    print(con.execute("SELECT count(*) AS companies_with_lobbying FROM (SELECT slug FROM company_year GROUP BY 1 HAVING sum(lobbying) > 0)").fetchone(),
          con.execute("SELECT count(*) AS companies_with_pac FROM (SELECT slug FROM company_year GROUP BY 1 HAVING sum(pac) > 0)").fetchone())


if __name__ == "__main__":
    main()
