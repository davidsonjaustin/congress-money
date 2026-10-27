"""Defense-industry endpoints: contracts (USAspending), company dependence, lobbying and revolving door, members' defense money and votes."""
import csv
from pathlib import Path

import pandas as pd
from fastapi import APIRouter, HTTPException

from server.api import DATA, _base_lock, _connection, db, rows

router = APIRouter()
ROOT_DIR = Path(__file__).resolve().parent.parent
TRACKED = "('defense prime', 'diversified prime', 'defense services')"
_u_ready = False
_fips: dict | None = None


def ensure_u() -> None:
    """Attach the contracts database on first use, so the rest of the site works without it."""
    global _u_ready
    if _u_ready:
        return
    con = _connection()
    with _base_lock:
        if not _u_ready:
            path = DATA / "usaspending.duckdb"
            if not path.exists():
                raise HTTPException(503, "contracts data not built (run pipeline/23_usaspending.py)")
            con.execute(f"ATTACH '{path.as_posix()}' AS u (READ_ONLY)")
            _u_ready = True


def fips() -> dict:
    global _fips
    if _fips is None:
        t = pd.read_csv(DATA / "raw" / "district" / "aip_states_ideology_v2022a.tab", sep="\t")[["abb", "fips"]].drop_duplicates()
        _fips = {a: f"{int(f):02d}" for a, f in zip(t["abb"], t["fips"])}
    return _fips


@router.get("/api/defense/overview")
def overview():
    """Contracts, company dependence, lobbying and campaign money for the defense industry, with company-reported shares and their sources."""
    ensure_u()
    with db() as con:
        fy = rows(con, "SELECT fy, scope, sum(amount) AS amount FROM u.usa_state WHERE length(state) = 2 GROUP BY 1, 2 ORDER BY 1, 2")
        comp = rows(con, "SELECT company, kind, year, contracts_dod, contracts_all, revenue, lobbying, pac, indiv FROM u.company_year ORDER BY company, year")
        tracked = rows(con, f"""SELECT year, sum(contracts_dod) AS dod, sum(contracts_all) AS allc, sum(lobbying) AS lobbying, sum(pac) AS pac, sum(indiv) AS indiv
                                FROM u.company_year WHERE kind IN {TRACKED} GROUP BY 1 ORDER BY 1""")
        money = rows(con, "SELECT year(week) AS y, source, sum(amount) AS amount FROM money_weekly WHERE sector = 'Defense & Aerospace' AND week >= DATE '2005-01-01' GROUP BY 1, 2 ORDER BY 1, 2")
    with open(ROOT_DIR / "pipeline" / "definitions" / "company_reported_share.csv", encoding="utf-8", newline="") as f:
        reported = [dict(r, share=float(r["share"]), year=int(r["year"])) for r in csv.DictReader(f)]
    return {"fy": fy, "companies": comp, "tracked": tracked, "member_money": money, "reported": reported}


@router.get("/api/defense/states")
def states():
    ensure_u()
    with db() as con:
        return rows(con, """SELECT state, avg(amount) AS dod, avg(population) AS pop, avg(amount) / nullif(avg(population), 0) AS per_capita
                            FROM u.usa_state WHERE scope = 'dod' AND fy BETWEEN 2023 AND 2025 AND length(state) = 2 GROUP BY 1 ORDER BY per_capita DESC""")


@router.get("/api/defense/members")
def members():
    """Every member with defense money or a documented defense vote, with DoD contract dollars performed in their state or district."""
    ensure_u()
    with db() as con:
        votes = {r["bioguide"]: r for r in rows(con, """SELECT bioguide, count(*) AS n, sum(aligned) AS aligned, avg(p_exp) AS p_exp FROM donor_alignment_scored
                                                       WHERE sector = 'Defense & Aerospace' GROUP BY 1""")}
        info = rows(con, "SELECT bioguide, name, party, state, chamber, last_c AS last_congress FROM member_info")
        pac = {r["bioguide"]: r for r in rows(con, """SELECT bioguide, sum(amount) AS pac_all, sum(amount) FILTER (WHERE week >= DATE '2020-10-26') AS pac_6y
                                                     FROM pac_sub_weekly WHERE sector = 'Defense & Aerospace' GROUP BY 1""")}
        ind = {r["bioguide"]: r for r in rows(con, """SELECT bioguide, sum(amount) AS ind_all FROM money_weekly WHERE sector = 'Defense & Aerospace' AND source = 'indiv' GROUP BY 1""")}
        st = {r["state"]: r for r in rows(con, """SELECT state, avg(amount) / nullif(avg(population), 0) AS per_capita FROM u.usa_state
                                                  WHERE scope = 'dod' AND fy BETWEEN 2023 AND 2025 AND length(state) = 2 GROUP BY 1""")}
        dist = {r["district"]: r for r in rows(con, """SELECT district, avg(amount) AS dod, avg(amount) / nullif(avg(population), 0) AS per_capita FROM u.usa_district
                                                       WHERE scope = 'dod' AND fy BETWEEN 2023 AND 2025 GROUP BY 1""")}
        cur = rows(con, "SELECT DISTINCT bioguide, state, district FROM member_vote WHERE congress = 119 AND chamber = 'House'")
    fp = fips()
    cur_d = {r["bioguide"]: f"{fp.get(r['state'], '??')}{int(r['district'] or 0):02d}" for r in cur}
    out = []
    for m in info:
        b = m["bioguide"]
        v = votes.get(b)
        if not v and b not in pac:
            continue
        d = dist.get(cur_d.get(b, ""))
        out.append({**m, "n": v["n"] if v else 0, "aligned": v["aligned"] if v else 0, "p_exp": v["p_exp"] if v else None,
                    "pac_all": (pac.get(b) or {}).get("pac_all"), "pac_6y": (pac.get(b) or {}).get("pac_6y"), "ind_all": (ind.get(b) or {}).get("ind_all"),
                    "state_pc": (st.get(m["state"]) or {}).get("per_capita"), "district_dod": d["dod"] if d else None, "district_pc": d["per_capita"] if d else None})
    return out


@router.get("/api/defense/revolving")
def revolving():
    ensure_u()
    cong_expr = ("(regexp_matches(upper(pos), 'CONGRESS|SENAT|REPRESENTATIVE|COMMITTEE|LEGISLAT|CHIEF OF STAFF|STAFF DIRECTOR|AIDE|MEMBER OF') "
                 "OR (regexp_matches(upper(pos), 'HOUSE') AND NOT regexp_matches(upper(pos), 'WHITE HOUSE')))")       # 'White House' is not Congress
    exe = "DEFENSE|DOD|PENTAGON|ARMY|NAVY|AIR FORCE|MARINE|JOINT CHIEFS|MILITARY|DARPA|NATIONAL SECURITY|WHITE HOUSE|SECRETARY OF|DEPARTMENT OF|DEPT|ADMINISTRATION|AGENCY|COMMISSION|BUREAU|CIA|FBI|OMB|TREASURY|AMBASSADOR"
    base = r"""WITH latest AS (SELECT *, row_number() OVER (PARTITION BY company, registrant, client, year, period ORDER BY posted DESC) AS rn FROM u.lda_def_filing),
                   f AS (SELECT * FROM latest WHERE rn = 1),
                   l AS (SELECT f.company, f.year, l.lobbyist_id, any_value(l.lobbyist) AS lobbyist, string_agg(DISTINCT nullif(trim(l.covered_position), ''), ' | ') FILTER (WHERE trim(coalesce(l.covered_position, '')) <> '' AND NOT regexp_matches(upper(trim(l.covered_position)), '^(N/?A\.?|NONE\.?|NO|NOT APPLICABLE|NIL|-+|NOT A COVERED OFFICIAL|NO COVERED POSITION)$') AND upper(trim(l.covered_position)) NOT LIKE 'SEE %') AS pos
                         FROM f JOIN u.lda_def_lobbyist l USING (filing_uuid) GROUP BY 1, 2, 3)"""
    with db() as con:
        per = rows(con, base + f"""
            SELECT company, count(DISTINCT lobbyist_id) AS lobbyists, count(DISTINCT lobbyist_id) FILTER (WHERE pos IS NOT NULL) AS with_position,
                   count(DISTINCT lobbyist_id) FILTER (WHERE {cong_expr}) AS congress_roles,
                   count(DISTINCT lobbyist_id) FILTER (WHERE regexp_matches(upper(pos), '{exe}')) AS executive_roles
            FROM l GROUP BY 1 ORDER BY lobbyists DESC""")
        spend = rows(con, base + """
            SELECT company, count(DISTINCT registrant) AS firms, count(*) AS filings, sum(amount) AS spend FROM f GROUP BY 1 ORDER BY spend DESC""")
        yr = rows(con, base + f"""
            SELECT year, count(DISTINCT lobbyist_id) AS lobbyists, count(DISTINCT lobbyist_id) FILTER (WHERE pos IS NOT NULL) AS with_position,
                   count(DISTINCT lobbyist_id) FILTER (WHERE {cong_expr}) AS congress_roles
            FROM l GROUP BY 1 ORDER BY 1""")
        common = rows(con, base + """
            SELECT trim(p) AS position, count(DISTINCT lobbyist_id) AS people FROM l, unnest(string_split(pos, ' | ')) AS t(p)
                                       WHERE pos IS NOT NULL AND regexp_matches(upper(p), 'CONGRESS|SENAT|HOUSE|REPRESENTATIVE|COMMITTEE|LEGISLAT|STAFF|SECRETARY|DEFENSE|ARMY|NAVY|AIR FORCE|WHITE HOUSE') GROUP BY 1 ORDER BY 2 DESC LIMIT 15""")
        ents = rows(con, """WITH latest AS (SELECT *, row_number() OVER (PARTITION BY company, registrant, client, year, period ORDER BY posted DESC) AS rn FROM u.lda_def_filing),
                                 f AS (SELECT * FROM latest WHERE rn = 1)
                            SELECT e.entity, count(DISTINCT e.filing_uuid) AS filings FROM f JOIN u.lda_def_entity e USING (filing_uuid) GROUP BY 1 ORDER BY 2 DESC LIMIT 12""")
    with open(ROOT_DIR / "pipeline" / "definitions" / "door_facts.csv", encoding="utf-8", newline="") as f:
        door = list(csv.DictReader(f))
    return {"per_company": per, "spend": spend, "by_year": yr, "common_positions": common, "entities": ents, "door_facts": door}


@router.get("/api/defense/war")
def war():
    """Votes on resolutions directing the removal of US forces from hostilities (a Yea constrains unauthorized military action), and who voted how in the current Congress."""
    import numpy as np
    with db() as con:
        votes = rows(con, """SELECT congress, chamber, rollnumber, strftime(vote_date, '%Y-%m-%d') AS d, bill_number AS bill, vote_question AS q, substr(vote_desc, 1, 170) AS descr,
                                    yea_count AS yeas, nay_count AS nays, vote_result AS result FROM war_vote ORDER BY vote_date DESC""")
        by_party = rows(con, """SELECT w.chamber, v.party, count(DISTINCT v.bioguide) AS members, avg(v.yea) AS share FROM member_vote v JOIN war_vote w USING (congress, chamber, rollnumber)
                                WHERE w.congress = 119 AND v.party IN ('D', 'R') GROUP BY 1, 2 ORDER BY 1, 2""")
        mem = rows(con, """SELECT w.bioguide AS id, i.name, i.party, i.state, i.chamber, w.n119 AS n, w.constrain119 AS constrain, coalesce(p.pac6, 0) AS pac_6y
                           FROM war_member w JOIN member_info i ON i.bioguide = w.bioguide
                           LEFT JOIN (SELECT bioguide, sum(amount) AS pac6 FROM pac_sub_weekly WHERE sector = 'Defense & Aerospace' AND week >= DATE '2020-10-26' GROUP BY 1) p ON p.bioguide = w.bioguide
                           WHERE w.n119 >= 5 AND i.party IN ('D', 'R')""")
    assoc = []
    for party in ("R", "D"):
        for ch in ("House", "Senate"):
            s = [m for m in mem if m["party"] == party and m["chamber"] == ch]
            if len(s) < 20:
                continue
            x = np.log1p(np.clip(np.array([m["pac_6y"] for m in s], dtype=float), 0, None) / 1000.0)
            y = np.array([m["constrain"] / m["n"] for m in s])
            if x.std() > 0 and y.std() > 0:
                assoc.append({"party": party, "chamber": ch, "members": len(s), "corr": float(np.corrcoef(x, y)[0, 1])})
    return {"votes": votes, "by_party": by_party, "members": mem, "association": assoc}


@router.get("/api/defense/promises")
def promises():
    """Public statements (each with its source) next to the member's record on the matching votes, plus the sourced record for the executive branch."""
    with open(ROOT_DIR / "pipeline" / "definitions" / "promises.csv", encoding="utf-8", newline="") as f:
        items = list(csv.DictReader(f))
    with open(ROOT_DIR / "pipeline" / "definitions" / "executive_record.csv", encoding="utf-8", newline="") as f:
        executive = list(csv.DictReader(f))
    ids = sorted({i["bioguide"] for i in items})
    mk = ",".join("?" * len(ids))
    with db() as con:
        war_m = {r["bioguide"]: r for r in rows(con, f"SELECT bioguide, n, constrain, n119, constrain119 FROM war_member WHERE bioguide IN ({mk})", ids)}
        dv = {r["bioguide"]: r for r in rows(con, f"""SELECT bioguide, count(*) AS n, sum(aligned) AS aligned FROM donor_alignment_scored
                                                    WHERE sector = 'Defense & Aerospace' AND bioguide IN ({mk}) GROUP BY 1""", ids)}
        pac = {r["bioguide"]: r for r in rows(con, f"""SELECT bioguide, sum(amount) AS pac_all FROM pac_sub_weekly WHERE sector = 'Defense & Aerospace' AND bioguide IN ({mk}) GROUP BY 1""", ids)}
        last = {r["bioguide"]: r for r in rows(con, f"SELECT bioguide, name, party, state, last_c AS last_congress FROM member_info WHERE bioguide IN ({mk})", ids)}
    for it in items:
        b = it["bioguide"]
        it["record"] = {"war": war_m.get(b), "defense": dv.get(b), "pac_all": (pac.get(b) or {}).get("pac_all"), "member": last.get(b)}
    return {"items": items, "executive": executive}
