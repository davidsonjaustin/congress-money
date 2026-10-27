"""Earmarks ("Community Project Funding" in the House, "Congressionally Directed Spending" in the Senate) in the final fiscal 2024 appropriations bills.

The House Appropriations Committee publishes, for each of the final fiscal 2024 bills, a table of every earmark: the account, the project, the recipient, the amount,
and the House and Senate members who requested it. This reads those tables and matches the requesters to members of the 118th Congress.

Pilot scope: fiscal 2024 only, and only the tables the Committee published as PDFs (the Defense bill's earmarks are not in this set). Fiscal 2022, 2023, 2025 and 2026 tables
are published on differently organised pages and are not loaded yet. Amounts are the total provided; a project with several requesters is counted in full for each of them.

Output (data/earmarks.duckdb):
  earmark(fy, bill, account, project, recipient, location, amount, house_req, senate_req)             one row per project
  earmark_member(fy, bioguide, chamber, bill, project, recipient, amount, n_requesters)                 one row per project and requester we could match
  earmark_unmatched(fy, requester, chamber, n)                                                          requesters we could not match to one member
  earmark_donor_match(bioguide, recipient, employer, amount_to_member, earmark_amount)                  recipients whose name equals an employer of the member's itemized donors
"""
import io
import re
import unicodedata
from pathlib import Path

import duckdb
import pandas as pd
import pdfplumber
import requests

ROOT = Path(__file__).resolve().parent.parent
H = {"User-Agent": "CongressMoneyResearch personal-project research tool"}
B = "https://appropriations.house.gov/sites/evo-subsites/republicans-appropriations.house.gov/files/evo-media-document/"
FILES = {
    "Agriculture": "fy24-agriculture-rural-development-food-and-drug-administration-and-related-agencies-cpf-table-final.pdf",
    "Commerce, Justice, Science": "fy24-commerce-justice-science-and-related-agencies-cpf-table-final.pdf",
    "Energy and Water": "fy24-energy-and-water-development-and-related-agencies-cpf-table-final.pdf",
    "Financial Services": "fy24-financial-services-and-general-government-cpf-table-final.pdf",
    "Homeland Security": "fy24-homeland-security-cpf-table-final.pdf",
    "Interior": "fy24-interior-environment-and-related-agencies-cpf-table-final.pdf",
    "Labor-HHS-Education": "fy24-labor-health-and-human-services-education-cpf-table-final.pdf",
    "Military Construction-VA": "fy24-military-construction-veterans-affairs-and-related-agencies-cpf-table-final.pdf",
    "Transportation-HUD": "fy24-transportation-housing-and-urban-development-and-related-agencies-cpf-table-final.pdf",
}
AMT = re.compile(r"^\$?\s*[\d,]{3,}$")


def clean(c) -> str:
    return re.sub(r"\s+", " ", (c or "").replace("\n", " ").replace("\x00", "")).strip()


def parse(bill: str, content: bytes) -> list[dict]:
    out = []
    with pdfplumber.open(io.BytesIO(content)) as pdf:
        for page in pdf.pages:
            for t in page.extract_tables():
                if not t or len(t) < 2:
                    continue
                head = [clean(c).lower() for c in t[0]]
                if not any("amount" in h for h in head):
                    continue
                # the earmark is the amount ABOVE the budget request ("Additional Amount") where that column exists, otherwise the single Amount column
                ai = next((i for i, h in enumerate(head) if "additional" in h), None)
                if ai is None:
                    ai = max(i for i, h in enumerate(head) if "amount" in h)
                hi = next((i for i, h in enumerate(head) if "requestor" in h), None)
                for row in t[1:]:
                    cells = [clean(c) for c in row] + [""] * 8
                    if not AMT.match(cells[ai].replace(" ", "")) or not any(cells):
                        continue
                    if hi is None:
                        continue
                    house, senate = cells[hi], cells[hi + 1]
                    d = {h: cells[i] for i, h in enumerate(head) if h}
                    proj = d.get("project") or d.get("project name; recipient") or d.get("project recipient and name") or ""
                    rec = d.get("recipient", "")
                    if not rec and ";" in proj:
                        proj, rec = [x.strip() for x in proj.split(";", 1)]
                    loc = d.get("location") or d.get("state") or ""
                    out.append({"bill": bill, "account": d.get("account", ""), "project": proj, "recipient": rec, "location": loc,
                                "amount": float(cells[ai].replace("$", "").replace(",", "").strip()), "house_req": house, "senate_req": senate})
    return out


def plain(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c)).lower()


def main() -> None:
    rows = []
    for bill, f in FILES.items():
        r = requests.get(B + f, headers=H, timeout=120)
        if r.status_code != 200:
            print(bill, "HTTP", r.status_code)
            continue
        got = parse(bill, r.content)
        print(f"{bill}: {len(got)} projects, ${sum(x['amount'] for x in got) / 1e6:,.0f}M", flush=True)
        rows += got
    em = pd.DataFrame(rows)
    em.insert(0, "fy", 2024)
    con = duckdb.connect(str(ROOT / "data" / "earmarks.duckdb"))
    con.execute("CREATE OR REPLACE TABLE earmark AS SELECT * FROM em")
    con.execute(f"ATTACH '{(ROOT / 'data' / 'congress.duckdb').as_posix()}' AS c (READ_ONLY)")
    terms = con.execute("SELECT bioguide_id AS bioguide, bioname, state, chamber, district FROM c.member_terms WHERE congress = 118 AND bioguide_id IS NOT NULL").df()
    terms["last"] = terms["bioname"].str.split(",").str[0].map(plain)
    terms["first"] = terms["bioname"].str.split(",").str[1].fillna("").str.strip().str.split().str[0].map(plain)
    out, unmatched = [], {}
    for r in em.itertuples(index=False):
        for chamber, field in (("House", r.house_req), ("Senate", r.senate_req)):
            if not field:
                continue
            reqs = [x.strip() for x in re.split(r",\s*(?![A-Z]{2}\))", re.sub(r"\(([A-Z]{2})\)", r"(\1)", field)) if x.strip()]
            # "Lee (CA), Smith" -> keep "(CA)" attached to its name
            reqs = re.findall(r"[^,()]+(?:\([A-Z]{2}\))?", field)
            reqs = [x.strip() for x in reqs if x.strip()]
            for name in reqs:
                m = re.match(r"(.+?)\s*\(([A-Z]{2})\)$", name)
                last, st = (m.group(1), m.group(2)) if m else (name, None)
                cand = terms[(terms["chamber"] == chamber) & (terms["last"] == plain(last).strip())]
                if st:
                    cand = cand[cand["state"] == st]
                if len(cand) != 1:
                    unmatched[(name, chamber)] = unmatched.get((name, chamber), 0) + 1
                    continue
                out.append((2024, cand.iloc[0]["bioguide"], chamber, r.bill, r.project, r.recipient, r.amount, len(reqs)))
    m = pd.DataFrame(out, columns=["fy", "bioguide", "chamber", "bill", "project", "recipient", "amount", "n_requesters"])
    con.execute("CREATE OR REPLACE TABLE earmark_member AS SELECT * FROM m")
    um = pd.DataFrame([(2024, k[0], k[1], v) for k, v in unmatched.items()], columns=["fy", "requester", "chamber", "n"])
    con.execute("CREATE OR REPLACE TABLE earmark_unmatched AS SELECT * FROM um")
    tot_proj = len(em)
    # recipients whose name is the same as an employer of the member's itemized donors (company-like recipients only)
    con.execute(f"ATTACH '{(ROOT / 'data' / 'indiv.duckdb').as_posix()}' AS i (READ_ONLY)")
    norm = lambda col: f"trim(regexp_replace(regexp_replace(upper({col}), '[^A-Z0-9 ]', ' ', 'g'), '\\b(THE|INC|LLC|LP|LTD|CORP|CORPORATION|COMPANY|CO)\\b', ' ', 'g'))"
    con.execute(f"""
        CREATE OR REPLACE TABLE earmark_donor_match AS
        WITH r AS (SELECT bioguide, recipient, sum(amount) AS earmark, {norm('recipient')} AS k FROM earmark_member
                   WHERE regexp_matches(upper(recipient), '\\b(INC|LLC|LP|LTD|CORP|CORPORATION|COMPANY)\\b') GROUP BY 1, 2),
        x AS (SELECT DISTINCT fec_id, bioguide FROM c.id_crosswalk WHERE fec_id IS NOT NULL AND bioguide IS NOT NULL),
        d AS (SELECT x.bioguide, a.employer, {norm('a.employer')} AS k, sum(a.total) AS given FROM i.indiv_agg a JOIN x ON x.fec_id = a.cand_id
              WHERE a.employer IS NOT NULL AND a.week >= DATE '2019-01-01' GROUP BY 1, 2, 3 HAVING sum(a.total) >= 1000)
        SELECT r.bioguide, r.recipient, d.employer, d.given AS amount_to_member, r.earmark AS earmark_amount FROM r JOIN d ON d.bioguide = r.bioguide AND d.k = r.k AND length(r.k) >= 4""")
    print(con.execute("SELECT count(*) AS donor_employer_matches, count(DISTINCT bioguide) AS members FROM earmark_donor_match").fetchone())
    print(f"{len(m)} project-requester links matched to a member; {len(um)} requester names not matched to one member ({int(um['n'].sum()) if len(um) else 0} links)")
    print(con.execute("SELECT chamber, count(DISTINCT bioguide) AS members, round(sum(amount) / 1e6) AS m FROM earmark_member GROUP BY 1").df().to_string(index=False))
    print(con.execute("SELECT em.bioguide, round(sum(amount) / 1e6, 1) AS m FROM earmark_member em GROUP BY 1 ORDER BY 2 DESC LIMIT 5").df().to_string(index=False))
    if tot_proj:
        print(em.nlargest(5, "amount")[["bill", "recipient", "amount"]].to_string(index=False))


if __name__ == "__main__":
    main()
