"""Which industries lobbied on which votes, from Senate lobbying disclosures (LDA).

A lobbying filing names the bills the client lobbied on. We label each client by industry from its name (and its own description as a fallback) with
the same name rules used for PACs (03_sectors, 14_subsectors), then say an industry LOBBIED a bill when at least MIN_CLIENTS distinct clients of that
industry named the bill in filings during the bill's Congress. A roll call counts as lobbied by an industry when the bill it voted on was.

Why: the every-vote screen (20/21) finds votes where an industry's money lines up with how members voted. Some of those links sit on votes the
industry never cared about. Requiring that the industry lobbied the bill keeps the ones where it plausibly had a stake.

Caveats, shown on the site: client industry comes from names (a few are wrong); filings name bill numbers only when the lobbyist wrote them down;
votes with no bill (nominations, many procedural motions) and years not yet downloaded have no lobbying data, so they are not 'lobbied' by this test.

Output (analysis.duckdb): lda_client_industry(client_id, client_name, label), lobbied_bills(congress, bill_type, bill_number, label, clients, filings),
lobbied_votes(congress, chamber, rollnumber, label, clients, filings)
"""
import importlib.util
import re
from pathlib import Path

import duckdb
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
MIN_CLIENTS = 2


def load(name: str):
    spec = importlib.util.spec_from_file_location(name.replace(".py", "_m"), Path(__file__).with_name(name))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


s03, s14 = load("03_sectors.py"), load("14_subsectors.py")
NOT_LABOR = re.compile(r"UNION (PACIFIC|BANK|CARBIDE|ELECTRIC|CAMP|OIL|PLANTERS)|WESTERN UNION|CREDIT UNION|EUROPEAN UNION|UNIONBANCAL|UNIVERSITY|TEACHERS INSURANCE")
KEEP = {"Labor", "Defense & Aerospace", "Health", "Finance, Insurance & Real Estate", "Energy & Natural Resources", "Tech, Telecom & Media", "Transportation",
        "Agribusiness & Food", "Construction", "Retail & Consumer"}


def label_of(sector: str, sub: str) -> str:
    return sub.replace("_", " ") if sub else sector.split(",")[0].replace(" & Consumer", "")


def classify(text) -> str | None:
    if not isinstance(text, str):
        return None
    text = text.upper()
    for sector, rx in s03.RULES_RE:
        if sector == "Labor" and NOT_LABOR.search(text):
            continue
        if rx.search(text):
            if sector not in KEEP:
                return None
            sub = ""
            if sector in s14.RULES:
                sub = s14.DEFAULT[sector]
                for lab, r in s14.RULES[sector]:
                    if r.search(text):
                        sub = lab
                        break
            return label_of(sector, sub)
    return None


def main() -> None:
    con = duckdb.connect(str(ROOT / "data" / "analysis.duckdb"))
    con.execute(f"ATTACH '{(ROOT / 'data' / 'lda.duckdb').as_posix()}' AS lda (READ_ONLY)")
    cl = con.execute("""SELECT client_id, any_value(client_name) AS client_name, any_value(client_desc) AS client_desc FROM lda.lda_filings
                        WHERE client_id IS NOT NULL GROUP BY 1""").df()
    labs = []
    ov = pd.read_csv(ROOT / "pipeline" / "definitions" / "lobbying_client_overrides.csv")
    ov = ov[ov["sector"].isin(KEEP)].set_index("client_id")["label"]      # hand labels for the largest clients whose names the rules missed (same ten scored sectors)
    for cid, n, d in zip(cl["client_id"], cl["client_name"], cl["client_desc"]):
        labs.append(ov[cid] if cid in ov.index else (classify(n or "") or classify(d or "")))
    cl["label"] = labs
    ci = cl.dropna(subset=["label"])[["client_id", "client_name", "label"]]
    con.execute("CREATE OR REPLACE TABLE lda_client_industry AS SELECT * FROM ci")
    print(f"clients: {len(cl):,} | labelled to a scored industry: {len(ci):,}")
    print(ci["label"].value_counts().to_string())
    con.execute("""
        CREATE OR REPLACE TABLE lobbied_bills AS
        SELECT b.congress, b.bill_type, b.bill_number, i.label, count(DISTINCT f.client_id) AS clients, count(DISTINCT f.filing_uuid) AS filings
        FROM lda.lda_bills b JOIN lda.lda_filings f USING (filing_uuid) JOIN lda_client_industry i ON i.client_id = f.client_id
        GROUP BY 1, 2, 3, 4""")
    con.execute(f"""
        CREATE OR REPLACE TABLE lobbied_votes AS
        SELECT t.congress, t.chamber, t.rollnumber, l.label, l.clients, l.filings
        FROM rollcall_topic t JOIN lobbied_bills l ON l.congress = t.congress AND l.bill_type = lower(t.bill_type) AND l.bill_number = TRY_CAST(t.bill_num AS INTEGER)
        WHERE l.clients >= {MIN_CLIENTS}""")
    print(con.execute("SELECT count(*) AS bills FROM lobbied_bills").fetchone(), con.execute("""
        SELECT count(DISTINCT (congress, chamber, rollnumber)) AS votes, count(*) AS vote_industry_pairs FROM lobbied_votes""").fetchone())
    cover = con.execute("""
        SELECT (t.congress - 109) AS c_idx, t.congress, count(DISTINCT (t.chamber, t.rollnumber)) AS bill_votes,
               count(DISTINCT CASE WHEN v.rollnumber IS NOT NULL THEN (t.chamber, t.rollnumber) END) AS lobbied
        FROM rollcall_topic t LEFT JOIN lobbied_votes v ON v.congress = t.congress AND v.chamber = t.chamber AND v.rollnumber = t.rollnumber
        WHERE t.vote_date >= DATE '2008-01-01' GROUP BY 1, 2 ORDER BY 2""").df()
    print(cover.to_string(index=False))
    s = con.execute("""
        SELECT i.label, count(*) AS pairs FROM lobbied_votes i GROUP BY 1 ORDER BY 2 DESC""").df()
    print(s.to_string(index=False))


if __name__ == "__main__":
    main()
