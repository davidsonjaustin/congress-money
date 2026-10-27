"""Company pages and outside-spending ("super PAC") money.

companies.duckdb (pipeline/33_companies.py) and superpac.duckdb (pipeline/30 and 31) are attached read-only on first use so the rest of the site runs without them.
"""
import csv
import re

from fastapi import APIRouter, HTTPException

from server.api import DEFS, attach_once, db, rows
from server.lobbying_api import ISSUES

router = APIRouter()
def ensure(alias: str, fname: str, hint: str) -> None:
    attach_once(alias, fname)


def people(con) -> str:
    """SQL fragment: bioguide, name, party, state, chamber of the latest term."""
    return """(SELECT t.bioguide_id AS bioguide, coalesce(any_value(x.full_name), any_value(t.bioname)) AS name,
                      CASE arg_max(t.party_code, t.congress) WHEN 100 THEN 'D' WHEN 200 THEN 'R' ELSE 'I' END AS party, arg_max(t.state, t.congress) AS state, arg_max(t.chamber, t.congress) AS chamber
               FROM c.member_terms t LEFT JOIN c.id_crosswalk x ON x.bioguide = t.bioguide_id WHERE t.bioguide_id IS NOT NULL GROUP BY t.bioguide_id)"""


@router.get("/api/companies")
def companies():
    ensure("co", "companies.duckdb", "run pipeline/33_companies.py")
    with db() as con:
        return rows(con, """
            SELECT c.slug, c.name, c.sector, c.in_defense, sum(y.lobbying) AS lobbying, sum(y.lobbying) FILTER (WHERE y.year = 2025) AS lobbying_2025,
                   sum(y.pac) AS pac, sum(y.indiv) AS indiv, sum(y.contracts) AS contracts
            FROM co.company c JOIN co.company_year y USING (slug) GROUP BY ALL ORDER BY sum(y.lobbying) DESC NULLS LAST""")


@router.get("/api/company/{slug}")
def company(slug: str):
    ensure("co", "companies.duckdb", "run pipeline/33_companies.py")
    with db() as con:
        meta = rows(con, "SELECT slug, name, sector, in_defense FROM co.company WHERE slug = ?", [slug])
        if not meta:
            raise HTTPException(404, "no such company")
        years = rows(con, "SELECT year, lobbying, pac, indiv, contracts FROM co.company_year WHERE slug = ? ORDER BY year", [slug])
        issues = rows(con, "SELECT issue_code AS code, filings FROM co.company_issue WHERE slug = ? ORDER BY filings DESC LIMIT 8", [slug])
        for r in issues:
            r["name"] = ISSUES.get(r["code"], r["code"])
        bills = rows(con, "SELECT bill, congress, title, filings, became_law FROM co.company_bill WHERE slug = ? ORDER BY filings DESC LIMIT 12", [slug])
        members = rows(con, f"""SELECT m.bioguide, p.name, p.party, p.state, p.chamber, m.pac, m.indiv FROM co.company_member m JOIN {people(con)} p ON p.bioguide = m.bioguide
                                WHERE m.slug = ? ORDER BY m.pac + m.indiv DESC LIMIT 12""", [slug])
        pacs = [r["committee"] for r in rows(con, "SELECT DISTINCT committee FROM co.company_pac WHERE slug = ? LIMIT 6", [slug])]
    reported = []
    if meta[0]["in_defense"]:
        with open(DEFS / "company_reported_share.csv", encoding="utf-8", newline="") as f:
            reported = [dict(r, share=float(r["share"]), year=int(r["year"]), share_with_fms=float(r["share_with_fms"]) if r.get("share_with_fms") else None) for r in csv.DictReader(f) if r["company"] == meta[0]["name"] or slug.startswith(re.sub(r"[^a-z0-9]+", "-", r["company"].lower())[:12])]
    return {"company": meta[0], "years": years, "issues": issues, "bills": bills, "members": members, "pacs": pacs, "reported": reported}


@router.get("/api/outside/overview")
def outside_overview():
    """The biggest outside spenders, who funds each, and how much of all outside spending can be traced to an industry."""
    ensure("sp", "superpac.duckdb", "run pipeline/30_superpac_donors.py and 31_ie_traced.py")
    with db() as con:
        spend = rows(con, """
            SELECT s.cmte_id, k.name, sum(s.amount) FILTER (WHERE s.kind = 'support') AS support, sum(s.amount) FILTER (WHERE s.kind = 'oppose') AS oppose, sum(s.amount) AS total
            FROM sp.ie_spend s JOIN sp.ie_committees k USING (cmte_id) GROUP BY 1, 2 ORDER BY total DESC LIMIT 30""")
        ids = [r["cmte_id"] for r in spend]
        mix = rows(con, f"""
            SELECT cmte_id, sector, sum(amount) AS amount FROM sp.committee_funding WHERE cmte_id IN ({','.join('?' * len(ids))}) GROUP BY 1, 2""", ids)
        donors = rows(con, f"""
            SELECT cmte_id, name, any_value(sector) AS sector, sum(amount) AS amount FROM sp.named_donors WHERE cmte_id IN ({','.join('?' * len(ids))}) GROUP BY 1, 2
            QUALIFY row_number() OVER (PARTITION BY cmte_id ORDER BY sum(amount) DESC) <= 5""", ids)
        cover = rows(con, "SELECT kind, grp, amount FROM sp.ie_coverage")
        cycles = rows(con, "SELECT cycle, kind, sum(amount) AS amount FROM sp.ie_spend GROUP BY 1, 2 ORDER BY 1")
    for s in spend:
        m = sorted([x for x in mix if x["cmte_id"] == s["cmte_id"]], key=lambda x: -x["amount"])
        tot = sum(x["amount"] for x in m) or 1
        s["funding_total"] = tot
        s["mix"] = [{"sector": x["sector"], "share": x["amount"] / tot} for x in m[:5]]
        s["donors"] = [{"name": d["name"], "sector": d["sector"], "amount": d["amount"]} for d in donors if d["cmte_id"] == s["cmte_id"]]
    return {"spenders": spend, "coverage": cover, "cycles": cycles}


@router.get("/api/member/{bg}/outside")
def member_outside(bg: str):
    """Outside spending for and against one member, and the industries and named donors behind it."""
    ensure("sp", "superpac.duckdb", "run pipeline/30_superpac_donors.py and 31_ie_traced.py")
    with db() as con:
        tot = rows(con, "SELECT kind, sum(amount) AS amount FROM sp.ie_spend WHERE bioguide = ? GROUP BY 1", [bg])
        by = rows(con, "SELECT kind, sector, sum(amount) AS amount FROM sp.ie_traced WHERE bioguide = ? GROUP BY 1, 2 ORDER BY 3 DESC", [bg])
        funders = rows(con, "SELECT kind, donor, sector, amount FROM sp.ie_funders WHERE bioguide = ? ORDER BY amount DESC", [bg])
        spenders = rows(con, """SELECT s.kind, k.name, sum(s.amount) AS amount FROM sp.ie_spend s JOIN sp.ie_committees k USING (cmte_id) WHERE s.bioguide = ? GROUP BY 1, 2 ORDER BY 3 DESC LIMIT 12""", [bg])
    return {"totals": tot, "by_sector": by, "funders": funders, "spenders": spenders}


@router.get("/api/pledges")
def pledges():
    """Pledge signers, the money the pledge was about year by year, the gifts since 2019, and how signers voted next to other members of their party."""
    attach_once("pl", "pledges.duckdb")
    with db() as con:
        meta = rows(con, "SELECT DISTINCT pledge FROM pl.pledge_member")
        members = rows(con, f"""
            SELECT m.pledge, m.bioguide, p.name, p.party, p.state, p.chamber FROM pl.pledge_member m JOIN {people(con)} p ON p.bioguide = m.bioguide ORDER BY p.name""")
        money = rows(con, "SELECT pledge, bioguide, year, pac_pledged_industry AS fossil, pac_all FROM pl.pledge_money WHERE year >= 2019 ORDER BY bioguide, year")
        gifts = rows(con, "SELECT pledge, bioguide, year, committee, amount FROM pl.pledge_gifts ORDER BY amount DESC")
        votes = rows(con, """
            SELECT CASE WHEN v.bioguide IN (SELECT bioguide FROM pl.pledge_member) THEN 'signers' WHEN v.party = 'D' THEN 'other Democrats' WHEN v.party = 'R' THEN 'Republicans' ELSE 'other' END AS grp,
                   count(*) AS members, sum(v.aligned) AS aligned, sum(v.n) AS n
            FROM pl.pledge_votes v GROUP BY 1""")
    sources = []
    with open(DEFS / "pledges.csv", encoding="utf-8", newline="") as f:
        seen = set()
        for r in csv.DictReader(f):
            if r["pledge"] not in seen:
                seen.add(r["pledge"])
                sources.append({"pledge": r["pledge"], "source_url": r["source_url"], "read_on": r["read_on"], "how_obtained": r["how_obtained"]})
    return {"pledges": meta, "members": members, "money": money, "gifts": gifts, "votes": votes, "sources": sources}


@router.get("/api/member/{bg}/earmarks")
def member_earmarks(bg: str):
    """Fiscal 2024 earmarks this member requested (pilot: the Committee's published final tables), and recipients whose name matches an employer of the member's donors."""
    attach_once("em", "earmarks.duckdb")
    with db() as con:
        tot = rows(con, "SELECT count(*) AS n, sum(amount) AS amount, sum(amount / n_requesters) AS share FROM em.earmark_member WHERE bioguide = ?", [bg])[0]
        top = rows(con, """SELECT project, recipient, amount, bill, n_requesters FROM em.earmark_member WHERE bioguide = ? ORDER BY amount DESC LIMIT 8""", [bg])
        match = rows(con, "SELECT recipient, employer, amount_to_member, earmark_amount FROM em.earmark_donor_match WHERE bioguide = ? ORDER BY earmark_amount DESC", [bg])
    return {"total": tot, "top": top, "donor_match": match}


# ---- who lobbies for the big companies, and where did they work before (all industries) ----
POS_OK = "NOT regexp_matches(upper(trim(l.covered_position)), '^(N/?A\\.?|NONE\\.?|NO|NOT APPLICABLE|NIL|-+|NOT A COVERED OFFICIAL|NO COVERED POSITION)$') AND upper(trim(l.covered_position)) NOT LIKE 'SEE %'"
CONG = ("(regexp_matches(upper(pos), 'CONGRESS|SENAT|REPRESENTATIVE|COMMITTEE|LEGISLAT|CHIEF OF STAFF|STAFF DIRECTOR|AIDE|MEMBER OF') "
        "OR (regexp_matches(upper(pos), 'HOUSE') AND NOT regexp_matches(upper(pos), 'WHITE HOUSE')))")
EXE = "DEFENSE|DOD|PENTAGON|ARMY|NAVY|AIR FORCE|MARINE|JOINT CHIEFS|MILITARY|NATIONAL SECURITY|WHITE HOUSE|SECRETARY OF|DEPARTMENT OF|DEPT|ADMINISTRATION|AGENCY|COMMISSION|BUREAU|CIA|FBI|OMB|TREASURY|AMBASSADOR|FDA|FCC|FTC|SEC |EPA|HHS|CMS"
RV_BASE = f"""WITH latest AS (SELECT *, row_number() OVER (PARTITION BY slug, registrant, client, year, period ORDER BY posted DESC) AS rn FROM rv.rv_filing),
              f AS (SELECT * FROM latest WHERE rn = 1),
              p AS (SELECT f.slug, l.lobbyist_id, any_value(l.lobbyist) AS lobbyist,
                           string_agg(DISTINCT nullif(trim(l.covered_position), ''), ' | ') FILTER (WHERE trim(coalesce(l.covered_position, '')) <> '' AND {POS_OK}) AS pos
                    FROM f JOIN rv.rv_lobbyist l USING (filing_uuid) GROUP BY 1, 2)"""


def rv_ready() -> bool:
    try:
        return attach_once("rv", "revolving.duckdb", required=False)
    except Exception:  # noqa: BLE001   (the file is locked while the fetch job is still writing it)
        return False


@router.get("/api/revolving/overview")
def revolving_overview():
    """For each company we read lobbyist records for: how many people lobby for it, how many report a past government job, and how many of those were in Congress."""
    if not rv_ready():
        raise HTTPException(503, "revolving-door data not available yet (pipeline/34_revolving_all.py)")
    attach_once("co", "companies.duckdb")
    with db() as con:
        per = rows(con, RV_BASE + f"""
            SELECT p.slug, c.name, c.sector, count(*) AS lobbyists, count(*) FILTER (WHERE pos IS NOT NULL) AS with_position,
                   count(*) FILTER (WHERE {CONG}) AS congress_roles, count(*) FILTER (WHERE regexp_matches(upper(pos), '{EXE}')) AS executive_roles
            FROM p JOIN co.company c USING (slug) GROUP BY ALL ORDER BY lobbyists DESC""")
        common = rows(con, RV_BASE + f"""
            SELECT trim(x) AS position, count(DISTINCT lobbyist_id) AS people FROM p, unnest(string_split(pos, ' | ')) AS t(x)
            WHERE pos IS NOT NULL AND regexp_matches(upper(x), 'CONGRESS|SENAT|HOUSE|REPRESENTATIVE|COMMITTEE|LEGISLAT|STAFF|SECRETARY|WHITE HOUSE') GROUP BY 1 ORDER BY 2 DESC LIMIT 12""")
    by_sector: dict[str, dict] = {}
    for r in per:
        s = by_sector.setdefault(r["sector"], {"sector": r["sector"], "companies": 0, "lobbyists": 0, "with_position": 0, "congress_roles": 0, "executive_roles": 0})
        s["companies"] += 1
        for k in ("lobbyists", "with_position", "congress_roles", "executive_roles"):
            s[k] += r[k]
    return {"per_company": per, "by_sector": sorted(by_sector.values(), key=lambda x: -x["lobbyists"]), "common_positions": common}


@router.get("/api/company/{slug}/revolving")
def company_revolving(slug: str):
    if not rv_ready():
        return {"available": False}
    with db() as con:
        r = rows(con, RV_BASE + f"""
            SELECT count(*) AS lobbyists, count(*) FILTER (WHERE pos IS NOT NULL) AS with_position, count(*) FILTER (WHERE {CONG}) AS congress_roles,
                   count(*) FILTER (WHERE regexp_matches(upper(pos), '{EXE}')) AS executive_roles FROM p WHERE slug = ?""", [slug])
        names = rows(con, RV_BASE + f"""
            SELECT lobbyist, pos FROM p WHERE slug = ? AND pos IS NOT NULL AND {CONG} ORDER BY length(pos) DESC LIMIT 10""", [slug])
    return {"available": True, **(r[0] if r else {}), "examples": names}


# ---- presidential campaign money ----
@router.get("/api/presidential")
def presidential():
    attach_once("pr", "presidential.duckdb")
    with db() as con:
        funding = rows(con, "SELECT candidate, cycle, sector, amount FROM pr.pres_funding ORDER BY cycle, candidate, amount DESC")
        employers = rows(con, "SELECT candidate, cycle, employer, amount FROM pr.pres_employers ORDER BY cycle, candidate, amount DESC")
    return {"funding": funding, "employers": employers}


# ---- stock trades (House) ----
@router.get("/api/trades/overview")
def trades_overview():
    attach_once("tr", "trades.duckdb")
    with db() as con:
        sectors = rows(con, "SELECT sector, count(*) AS trades, count(DISTINCT bioguide) AS members, sum(lo) AS lo, sum(hi) AS hi FROM tr.trade_clean WHERE tx_date >= DATE '2014-01-01' GROUP BY 1 ORDER BY 2 DESC")
        years = rows(con, "SELECT year(tx_date) AS year, count(*) AS trades, sum(lo) AS lo, sum(hi) AS hi FROM tr.trade_clean WHERE tx_date >= DATE '2014-01-01' GROUP BY 1 ORDER BY 1")
        top = rows(con, f"""
            SELECT t.bioguide, p.name, p.party, p.state, sum(t.n) AS trades, sum(t.lo) AS lo, sum(t.hi) AS hi
            FROM tr.trade_member t JOIN {people(con)} p ON p.bioguide = t.bioguide WHERE t.year >= 2019 GROUP BY ALL ORDER BY trades DESC LIMIT 25""")
        defense = rows(con, f"""
            SELECT s.bioguide, p.name, p.party, p.state, s.n AS trades, s.buys, s.sells, s.lo, s.hi, s.tickers
            FROM tr.trade_sector_member s JOIN {people(con)} p ON p.bioguide = s.bioguide WHERE s.sector = 'Defense & Aerospace' ORDER BY s.n DESC LIMIT 15""")
        cover = rows(con, "SELECT (SELECT count(*) FROM tr.house_ptr) AS reports, (SELECT count(*) FROM tr.ptr_done WHERE n > 0) AS reports_with_trades, (SELECT count(*) FROM tr.trade_clean) AS trades, (SELECT count(*) FROM tr.trade_unmatched) AS unmatched")[0]
    return {"sectors": sectors, "years": years, "top": top, "defense": defense, "coverage": cover}


@router.get("/api/member/{bg}/trades")
def member_trades(bg: str):
    attach_once("tr", "trades.duckdb")
    with db() as con:
        by = rows(con, "SELECT sector, n, buys, sells, lo, hi, tickers FROM tr.trade_sector_member WHERE bioguide = ? ORDER BY hi DESC", [bg])
        yr = rows(con, "SELECT year, n, lo, hi FROM tr.trade_member WHERE bioguide = ? ORDER BY year", [bg])
        recent = rows(con, """SELECT strftime(tx_date, '%Y-%m-%d') AS d, tx, owner, asset, ticker, sector, lo, hi FROM tr.trade_clean WHERE bioguide = ? AND tx_date IS NOT NULL ORDER BY tx_date DESC LIMIT 12""", [bg])
    return {"by_sector": by, "by_year": yr, "recent": recent}
