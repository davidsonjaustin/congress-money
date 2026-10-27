"""Local read-only API over the analysis tables. Run from the project root:

    .venv\\Scripts\\python.exe -m uvicorn server.api:app --port 8000

Holds data/analysis.duckdb open read-only while running, so stop the server before re-running a pipeline step that
rewrites it. If web/dist exists (npm run build) it is served at / so one process runs the whole app.
"""
import csv
import datetime as dt
import math
import threading
from contextlib import contextmanager
from pathlib import Path

import duckdb
from fastapi import FastAPI, HTTPException
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.staticfiles import StaticFiles

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
DEFS = ROOT / "pipeline" / "definitions"
DELEGATES = "('DC','PR','GU','VI','AS','MP')"
TODAY = dt.date.today()

# How the front end groups the sector labels. Anything not listed falls under 'unknown'.
CATEGORY = {
    "Finance, Insurance & Real Estate": "industry", "Health": "industry", "Lawyers & Lobbyists": "industry",
    "Tech, Telecom & Media": "industry", "Energy & Natural Resources": "industry", "Agribusiness & Food": "industry",
    "Transportation": "industry", "Construction": "industry", "Defense & Aerospace": "industry",
    "Retail & Consumer": "industry", "Manufacturing & Industrial": "industry", "Travel, Lodging & Leisure": "industry",
    "General Business Associations": "industry", "Business (sector not yet assigned)": "industry",
    "Labor": "labor", "Education": "other", "Government / Public sector": "other",
    "Ideological / Single-Issue": "other", "Ideological / Single-Issue / Unsorted": "other",
    "Leadership PAC": "political", "Candidate committee": "political", "Party committee": "political",
    "Caucus & Party-Aligned PACs": "political", "Joint fundraising": "political",
}

app = FastAPI(title="Congress Money")
app.add_middleware(GZipMiddleware, minimum_size=1000)


_base = None
_base_lock = threading.Lock()


def _connection():
    """One shared read-only connection (the page fires several requests at once; per-request ATTACH collided)."""
    global _base
    with _base_lock:
        if _base is None:
            _base = duckdb.connect(str(DATA / "analysis.duckdb"), read_only=True)
            _base.execute(f"ATTACH '{(DATA / 'congress.duckdb').as_posix()}' AS c (READ_ONLY)")
    return _base


_attached: dict[str, bool] = {}


def attach_once(alias: str, fname: str, required: bool = True) -> bool:
    """Attach data/<fname> read-only as <alias> the first time it is needed. Returns False (or raises 503 if required) when the file has not been built."""
    if _attached.get(alias):
        return True
    con = _connection()
    with _base_lock:
        if not _attached.get(alias):
            path = DATA / fname
            if not path.exists():
                if required:
                    raise HTTPException(503, f"{fname} not built")
                return False
            con.execute(f"ATTACH '{path.as_posix()}' AS {alias} (READ_ONLY)")
            _attached[alias] = True
    return True


@contextmanager
def db():
    cur = _connection().cursor()      # a cursor per request is safe to use from worker threads
    try:
        yield cur
    finally:
        cur.close()


def _safe(v):
    if isinstance(v, float) and not math.isfinite(v):
        return None
    return v


def rows(con, sql: str, params=None) -> list[dict]:
    cur = con.execute(sql, params or [])
    cols = [d[0] for d in cur.description]
    return [{k: _safe(v) for k, v in zip(cols, r)} for r in cur.fetchall()]


def clean(v):
    return v.isoformat() if isinstance(v, (dt.date, dt.datetime)) else v


def congress_years(c: int) -> tuple[int, int]:
    return 2005 + 2 * (c - 109), 2006 + 2 * (c - 109)


@app.get("/api/members")
def members():
    with db() as con:
        out = rows(con, f"""
            WITH t AS (
              SELECT bioguide_id, arg_max(bioname, congress) bioname, arg_max(party_code, congress) party_code,
                     arg_max(state, congress) state, arg_max(chamber, congress) chamber, arg_max(district, congress) district,
                     min(congress) first_congress, max(congress) last_congress, list(DISTINCT chamber) chambers
              FROM c.member_terms WHERE state NOT IN {DELEGATES} AND bioguide_id IS NOT NULL GROUP BY 1),
            x AS (SELECT bioguide, any_value(full_name) full_name FROM c.id_crosswalk GROUP BY 1),
            m AS (SELECT bioguide, sum(amount) FILTER (WHERE source IN ('pac_direct','indiv')) money FROM money_weekly GROUP BY 1)
            SELECT t.bioguide_id AS id, coalesce(x.full_name, t.bioname) AS name,
                   CASE t.party_code WHEN 100 THEN 'D' WHEN 200 THEN 'R' ELSE 'I' END AS party, t.state, t.chamber,
                   t.first_congress, t.last_congress, t.chambers, t.district, coalesce(m.money, 0) AS money
            FROM t LEFT JOIN x ON x.bioguide = t.bioguide_id LEFT JOIN m ON m.bioguide = t.bioguide_id
            ORDER BY t.last_congress DESC, name""")
    return out


@app.get("/api/definitions")
def definitions():
    """The locked sector <-> topic / committee mappings (pipeline/definitions)."""
    def read(name):
        with open(DEFS / name, encoding="utf-8", newline="") as f:
            return list(csv.DictReader(f))
    lock = (DEFS / "LOCK.txt").read_text(encoding="utf-8").splitlines()[:2]
    return {"policy_sector": read("policy_sector.csv"), "committee_sector": read("committee_sector.csv"),
            "direction": [r for f in sorted(DEFS.glob("vote_direction*.csv")) for r in read(f.name)], "category": CATEGORY, "lock": lock}


@app.get("/api/member/{bg}")
def member(bg: str):
    with db() as con:
        terms = rows(con, """
            SELECT t.congress, t.chamber, t.state, t.district, t.party_code, t.nominate_dim1,
                   d.demshare_pres, d.mrp_ideology, d.lines_match
            FROM c.member_terms t
            LEFT JOIN district_lean d ON d.congress = t.congress AND d.chamber = t.chamber AND d.state = t.state
                 AND d.district = CASE WHEN t.chamber = 'Senate' THEN 0 ELSE t.district::INT END
            WHERE t.bioguide_id = ? ORDER BY t.congress""", [bg])
        if not terms:
            raise HTTPException(404, "unknown member")
        for t in terms:
            t["start"], t["end"] = congress_years(t["congress"])
        name = rows(con, "SELECT any_value(full_name) n FROM c.id_crosswalk WHERE bioguide = ?", [bg])[0]["n"]
        stats = rows(con, """
            SELECT congress, chamber, count(*) AS votes,
                   count(*) FILTER (WHERE unity) AS unity_votes,
                   100.0 * avg(defect) FILTER (WHERE unity) AS defect_pct,
                   100.0 * avg((p_cast < .25)::INT) FILTER (WHERE p_cast IS NOT NULL) AS surprising_pct
            FROM member_vote WHERE bioguide = ? GROUP BY 1, 2 ORDER BY 1""", [bg])
        comm = rows(con, """
            SELECT congress, chamber, committee_name, start_date, end_date, majority, rank, source
            FROM committee_assignment WHERE bioguide = ? ORDER BY congress, committee_name""", [bg])
        for c in comm:
            c["start_date"], c["end_date"] = clean(c["start_date"]), clean(c["end_date"])
        money = rows(con, f"""
            SELECT source, sector, sum(amount) AS amount FROM money_weekly
            WHERE bioguide = ? AND week BETWEEN DATE '2004-01-01' AND DATE '{TODAY}' GROUP BY 1, 2""", [bg])
    return {"id": bg, "name": name or terms[-1].get("bioname"), "terms": terms, "stats": stats, "committees": comm, "money_totals": money}


@app.get("/api/member/{bg}/money")
def member_money(bg: str):
    """Monthly money by source and sector. Future-dated rows (FEC typos) are dropped."""
    with db() as con:
        return rows(con, f"""
            SELECT strftime(date_trunc('month', week), '%Y-%m') AS m, source, sector,
                   round(sum(amount), 2) AS amt, sum(n)::INT AS n
            FROM money_weekly WHERE bioguide = ? AND week BETWEEN DATE '2004-01-01' AND DATE '{TODAY}'
            GROUP BY 1, 2, 3 ORDER BY 1""", [bg])


@app.get("/api/member/{bg}/votes")
def member_votes(bg: str):
    with db() as con:
        return rows(con, """
            SELECT strftime(r.vote_date, '%Y-%m-%d') AS d, v.congress, v.chamber, v.rollnumber AS rn,
                   CASE v.yea WHEN 1 THEN 'Y' ELSE 'N' END AS vote, round(v.p_cast, 3) AS p, v.unity, v.defect,
                   v.party_maj_yea AS pm, r.vote_question AS q, coalesce(left(r.vote_desc, 140), left(vl.label, 140)) AS desc,
                   t.policy_area AS pa, left(t.title, 140) AS title, t.bill_number AS bill, r.vote_result AS result
            FROM member_vote v
            JOIN c.rollcalls r ON r.congress = v.congress AND r.chamber = v.chamber AND r.rollnumber = v.rollnumber
            LEFT JOIN rollcall_topic t ON t.congress = v.congress AND t.chamber = v.chamber AND t.rollnumber = v.rollnumber
            LEFT JOIN vote_label vl ON vl.congress = v.congress AND vl.chamber = v.chamber AND vl.rollnumber = v.rollnumber
            WHERE v.bioguide = ? ORDER BY r.vote_date, v.rollnumber""", [bg])


@app.get("/api/member/{bg}/constituents")
def member_constituents(bg: str):
    """Landmark votes with district (House) or state (Senate) opinion on the issue behind each vote."""
    with db() as con:
        return rows(con, """
            SELECT r.date AS d, v.congress, v.chamber, v.rollnumber AS rn, v.state, v.district::INT AS district, v.bill, r.note, v.item,
                   v."match" AS match, v.yea AS yea, v.voted_for_item, round(v.est, 3) AS est, round(v.sd, 3) AS sd,
                   round(v.p_support, 3) AS p_support, v.district_view, v.with_district, v.n_resp
            FROM vote_vs_district v
            JOIN rollcall_issue r ON r.congress = v.congress AND r.chamber = v.chamber AND r.rollnumber = v.rollnumber
            WHERE v.bioguide = ? ORDER BY r.date, v.rollnumber""", [bg])


@app.get("/api/scoreboard")
def scoreboard(variant: str = "all", sector: str = "All business"):
    """Every member's donor-loyalty and against-constituents numbers for one evidence variant and sector, for the ranking page."""
    if variant not in ("all", "core", "inferred", "lobbied"):
        raise HTTPException(400, "variant")
    with db() as con:
        members = rows(con, """SELECT i.bioguide AS id, i.name, i.party, i.state, i.chamber, i.last_c AS last_congress, i.first_c AS first_congress,
                                      s.votes_coded, s.weight, s.n_funded, s.n_funded_aligned, s.peers_funded_aligned, s.loyalty, s.peers, s.lift, s.se, s.z,
                                      s."index", s.money_at_stake, s.top_sectors, coalesce(s.ranked, false) AS ranked,
                                      i.const_votes, i.const_against, i.const_rate, i.const_lift, i.donors_over_district, i.district_over_donors, i.donor_district_votes, i.proxy_donors_over, i.proxy_district_over, i.proxy_votes, i.fossil_const_votes, i.fossil_const_against
                               FROM member_info i LEFT JOIN scores s ON s.bioguide = i.bioguide AND s.variant = ? AND s.sector_label = ?
                               WHERE s.bioguide IS NOT NULL OR i.const_votes IS NOT NULL""", [variant, sector])
        sectors = rows(con, "SELECT sector_label AS label, votes, members_ranked FROM coverage_stats WHERE variant = ? ORDER BY votes DESC", [variant])
        cov = rows(con, """SELECT (SELECT count(*) FROM c.rollcalls) AS roll_calls,
                                  (SELECT count(*) FROM rollcall_topic WHERE policy_area IS NOT NULL) AS bill_votes,
                                  (SELECT count(DISTINCT (congress, chamber, rollnumber)) FROM vote_vs_district) AS landmark_votes,
                                  (SELECT count(*) FROM c.rollcalls WHERE vote_date >= DATE '2008-01-01' AND yea_count + nay_count >= 50) AS votes_since_2008,
                                  (SELECT count(DISTINCT (congress, chamber, rollnumber)) FROM vote_direction WHERE date >= DATE '2008-01-01') AS coded_since_2008""")[0]
        mine = next((x for x in sectors if x["label"] == sector), {"votes": 0, "members_ranked": 0})
        cov.update({"coded_votes": mine["votes"], "ranked_members": mine["members_ranked"]})
        cov["coded_by_label"] = {r["label"]: r["n"] for r in rows(con, f"""SELECT {LABEL_SQL} AS label, count(DISTINCT (d.congress, d.chamber, d.rollnumber)) AS n
                                                                              FROM vote_direction d WHERE d.date >= DATE '2008-01-01' GROUP BY 1 ORDER BY n DESC""")}
        cov["landmark_by_match"] = {r["match"]: r["n"] for r in rows(con, "SELECT match, count(DISTINCT (congress, chamber, rollnumber)) AS n FROM vote_vs_district GROUP BY 1")}
        cov["lobbied_through"] = rows(con, "SELECT strftime(max(r.vote_date), '%Y-%m-%d') AS d FROM lobbied_votes l JOIN c.rollcalls r USING (congress, chamber, rollnumber)")[0]["d"]
    return {"members": members, "coverage": cov, "sectors": sectors}


_fresh = {}


@app.get("/api/freshness")
def freshness():
    """How recent each source is. Slow ones (lobbying, contracts) are read once and kept."""
    with db() as con:
        votes = rows(con, "SELECT strftime(max(vote_date), '%Y-%m-%d') AS d, count(*) AS n FROM c.rollcalls")[0]
        money = rows(con, "SELECT source, strftime(max(week) FILTER (WHERE amount <> 0 AND week <= current_date), '%Y-%m-%d') AS d FROM money_weekly GROUP BY 1")
    if "lda" not in _fresh:
        try:
            with duckdb.connect(str(DATA / "lda.duckdb"), read_only=True) as l:
                _fresh["lda"] = l.execute("SELECT strftime(max(posted), '%Y-%m-%d') FROM lda_filings").fetchone()[0]
        except Exception:  # noqa: BLE001
            _fresh["lda"] = None
    if "usa" not in _fresh:
        try:
            with duckdb.connect(str(DATA / "usaspending.duckdb"), read_only=True) as u:
                _fresh["usa"] = int(u.execute("SELECT max(fy) FROM usa_state").fetchone()[0])
        except Exception:  # noqa: BLE001
            _fresh["usa"] = None
    src = {m["source"]: m["d"] for m in money}
    return {"sources": [
        {"source": "Roll-call votes (Voteview, House Clerk)", "through": votes["d"], "note": f"{votes['n']:,} roll calls since 2005"},
        {"source": "PAC gifts to members (FEC)", "through": src.get("pac_direct"), "note": "dates are transaction dates; late reports can still add earlier gifts"},
        {"source": "Itemized individual gifts (FEC)", "through": src.get("indiv"), "note": "gifts over $200 per cycle only; small-dollar money is not public"},
        {"source": "Outside spending (FEC)", "through": src.get("ie_support"), "note": "independent expenditures for and against members"},
        {"source": "Lobbying disclosures (Senate LDA)", "through": _fresh["lda"], "note": "filings posted through this date"},
        {"source": "Federal contracts (USAspending)", "through": f"fiscal {_fresh['usa']}" if _fresh["usa"] else None, "note": "prime awards; latest complete fiscal year"},
    ]}


@app.get("/api/moneycoverage")
def money_coverage():
    """For each kind of money, how much could be put in an industry, how much is political committees, how much has no usable employer, how much is unrecognised."""
    with db() as con:
        return rows(con, """
            SELECT source, CASE WHEN sector = 'Not identifiable (retired / unemployed / no employer)' THEN 'no_employer'
                                WHEN sector IN ('Other / unclassified', 'Unclassified', 'Business (sector not yet assigned)', 'Ideological / Single-Issue / Unsorted') THEN 'unsorted'
                                WHEN sector IN ('Candidate committee', 'Leadership PAC', 'Party committee', 'Joint fundraising', 'Caucus & Party-Aligned PACs', 'Conduit (excluded)') THEN 'committees'
                                ELSE 'sorted' END AS grp, sum(amount) AS amount
            FROM money_weekly WHERE week <= current_date GROUP BY 1, 2 ORDER BY 1, 2""")


@app.get("/api/method")
def method():
    with db() as con:
        timing = rows(con, 'SELECT "group", spec, term, effect_pts, se_pts, n FROM timing_test')
        placebo = rows(con, "SELECT vote_group, money_from, is_own, effect_pts, se_pts, n FROM placebo_test")
        committee = rows(con, "SELECT industry, outcome, effect, se, joiners, n FROM committee_did")
    return {"timing": timing, "placebo": placebo, "committee": committee}


LABEL_SQL = "CASE WHEN d.subsector <> '' THEN replace(d.subsector, '_', ' ') ELSE replace(split_part(d.sector, ',', 1), ' & Consumer', '') END"


@app.get("/api/allvotes/summary")
def allvotes_summary():
    """Per industry, across every tested roll call since 2008: how often its money predicts the vote, against shuffled money."""
    with db() as con:
        thr = rows(con, """SELECT quantile_cont(abs(t_only), 0.999) AS only, quantile_cont(abs(t_before), 0.999) AS joint_b, quantile_cont(abs(t_after), 0.999) AS joint_a FROM all_vote_null""")[0]
        per = rows(con, f"""
            SELECT r.label, count(r.t_only) AS votes,
                   avg((abs(r.t_only) >= {thr['only']})::INT) AS strong_only,
                   avg((abs(r.t_only) >= 2)::INT) AS link_only, avg((abs(n.t_only) >= 2)::INT) AS link_only_null,
                   avg(CASE WHEN r.has_after THEN (abs(r.t_before) >= 2)::INT END) AS link_before, avg(CASE WHEN r.has_after THEN (abs(n.t_before) >= 2)::INT END) AS link_before_null,
                   avg(CASE WHEN r.has_after THEN (abs(r.t_after) >= 2)::INT END) AS link_after
            FROM all_vote_money r JOIN all_vote_null n USING (congress, chamber, rollnumber, label)
            GROUP BY 1 ORDER BY strong_only DESC""")
        tested = rows(con, "SELECT count(DISTINCT (congress, chamber, rollnumber)) AS tested FROM all_vote_money")[0]["tested"]
        total = rows(con, "SELECT count(*) AS n FROM c.rollcalls WHERE vote_date >= DATE '2008-01-01' AND yea_count + nay_count >= 50")[0]["n"]
        val = rows(con, f"""
            SELECT d.evidence_level AS tier, count(*) AS n, sum(((m.b_only > 0) = (d.helps_vote = 'Yea'))::INT) AS agree
            FROM all_vote_money m JOIN vote_direction d ON d.congress = m.congress AND d.chamber = m.chamber AND d.rollnumber = m.rollnumber AND {LABEL_SQL} = m.label
            WHERE abs(m.t_only) >= 2 GROUP BY 1""")
        funded = rows(con, """SELECT label, count(DISTINCT (congress, chamber, rollnumber)) AS votes, count(*) AS member_votes, avg(aligned) AS aligned, avg(p_exp) AS expected
                              FROM inferred_alignment WHERE pac_6y >= 10000 GROUP BY 1 ORDER BY (avg(aligned) - avg(p_exp)) DESC""")
        dose = rows(con, """SELECT CASE WHEN pac_6y < 1000 THEN '1' WHEN pac_6y < 10000 THEN '2' WHEN pac_6y < 50000 THEN '3' WHEN pac_6y < 200000 THEN '4' ELSE '5' END AS k,
                                   count(*) AS member_votes, avg(aligned) AS aligned, avg(p_exp) AS expected
                            FROM inferred_alignment WHERE label <> 'Labor' GROUP BY 1 ORDER BY 1""")
    return {"thresholds": thr, "industries": per, "tested": tested, "all_votes": total, "validation": val, "funded": funded, "dose": dose}


PROCEDURAL_SQL = """(t.bill_number SIMILAR TO '(HRES|PN)[0-9]+' OR t.vote_question ILIKE '%Journal%' OR t.vote_question ILIKE '%Adjourn%' OR t.vote_question ILIKE '%Previous Question%'
                     OR t.vote_question ILIKE '%Table%' OR t.vote_question ILIKE '%Reconsider%' OR t.vote_question ILIKE '%Quorum%' OR t.vote_question ILIKE '%Nomination%')"""
def lobbied_sql(a: str) -> str:
    return f"EXISTS (SELECT 1 FROM lobbied_votes l WHERE l.congress = {a}.congress AND l.chamber = {a}.chamber AND l.rollnumber = {a}.rollnumber AND l.label = {a}.label)"


def coded_sql(a: str) -> str:
    return f"EXISTS (SELECT 1 FROM vote_direction d WHERE d.congress = {a}.congress AND d.chamber = {a}.chamber AND d.rollnumber = {a}.rollnumber AND " + LABEL_SQL + f" = {a}.label)"


LOBBIED_SQL, CODED_SQL = lobbied_sql("m"), coded_sql("m")


@app.get("/api/allvotes/top")
def allvotes_top(label: str = "", min_t: float = 3.15, limit: int = 60, offset: int = 0, scope: str = "linked"):
    """Roll calls where an industry's pre-vote PAC money predicts the vote most strongly, with what the vote was.
    scope 'linked' (default) keeps votes that are not procedural and that either the industry lobbied or have a documented industry side; 'all' keeps every strong link."""
    if scope not in ("linked", "all"):
        raise HTTPException(400, "scope")
    where = "(? = '' OR m.label = ?) AND abs(m.t_only) >= ?"
    if scope == "linked":
        where += f" AND NOT coalesce({PROCEDURAL_SQL}, false) AND ({LOBBIED_SQL} OR {CODED_SQL})"
    with db() as con:
        r = rows(con, f"""
            SELECT m.congress, m.chamber, m.rollnumber, strftime(m.vdate, '%Y-%m-%d') AS d, m.label, m.n,
                   round(m.b_only, 2) AS b_only, round(m.t_only, 2) AS t_only, round(m.t_before, 2) AS t_before, round(m.t_after, 2) AS t_after,
                   t.vote_question AS q, t.vote_desc AS descr, t.title, t.bill_number AS bill, t.policy_area, t.vote_result AS result, t.yea_count AS yeas, t.nay_count AS nays, vl.label AS text,
                   (SELECT any_value(d.helps_vote) FROM vote_direction d WHERE d.congress = m.congress AND d.chamber = m.chamber AND d.rollnumber = m.rollnumber AND {LABEL_SQL} = m.label) AS coded_side,
                   {LOBBIED_SQL} AS lobbied, coalesce({PROCEDURAL_SQL}, false) AS procedural
            FROM all_vote_money m LEFT JOIN rollcall_topic t USING (congress, chamber, rollnumber)
                 LEFT JOIN vote_label vl ON vl.congress = m.congress AND vl.chamber = m.chamber AND vl.rollnumber = m.rollnumber
            WHERE {where}
            ORDER BY abs(m.t_only) DESC LIMIT ? OFFSET ?""", [label, label, min_t, limit, offset])
        counts = rows(con, f"""
            SELECT count(*) AS total_all,
                   count(*) FILTER (WHERE NOT coalesce({PROCEDURAL_SQL}, false) AND ({LOBBIED_SQL} OR {CODED_SQL})) AS total_linked
            FROM all_vote_money m LEFT JOIN rollcall_topic t USING (congress, chamber, rollnumber)
            WHERE (? = '' OR m.label = ?) AND abs(m.t_only) >= ?""", [label, label, min_t])[0]
    return {"rows": r, "total": counts["total_linked"] if scope == "linked" else counts["total_all"], "total_all": counts["total_all"], "total_linked": counts["total_linked"]}


@app.get("/api/member/{bg}/inferred")
def member_inferred(bg: str):
    """Every-vote view for one member: per industry, how they voted on votes where its money lined up strongly with the vote, plus the most surprising ones."""
    with db() as con:
        summ = rows(con, """SELECT sector_label AS label, votes_coded, weight, n_funded, n_funded_aligned, peers_funded_aligned AS expected, lift, se, z, money_at_stake AS money
                            FROM scores WHERE variant = 'inferred' AND bioguide = ? ORDER BY (sector_label = 'All business') DESC, money_at_stake DESC""", [bg])
        base = ("""SELECT strftime(t.vote_date, '%Y-%m-%d') AS d, a.congress, a.chamber, a.rollnumber, a.label, a.aligned, round(a.p_exp, 2) AS p_exp, a.pac_6y, a.pull_yea,
                         round(a.t_only, 1) AS t_only, t.bill_number AS bill, t.vote_question AS q, coalesce(vl.label, t.title, t.vote_desc) AS descr, t.vote_result AS result
                  FROM inferred_alignment a LEFT JOIN rollcall_topic t USING (congress, chamber, rollnumber)
                       LEFT JOIN vote_label vl ON vl.congress = a.congress AND vl.chamber = a.chamber AND vl.rollnumber = a.rollnumber
                  WHERE a.bioguide = ? AND a.pac_6y >= 25000 AND NOT coalesce(""" + PROCEDURAL_SQL + ", false) AND (" + lobbied_sql("a") + " OR " + coded_sql("a") + ")")
        with_money = rows(con, base + " AND a.aligned = 1 ORDER BY a.p_exp ASC, a.pac_6y DESC LIMIT 8", [bg])
        against_money = rows(con, base + " AND a.aligned = 0 ORDER BY a.p_exp DESC, a.pac_6y DESC LIMIT 8", [bg])
    return {"summary": summ, "with_money": with_money, "against_money": against_money}


@app.get("/api/member/{bg}/sectors")
def member_sectors(bg: str):
    """Per coded donor sector: votes, money, and a monthly PAC-gift series (for the before/after chart)."""
    with db() as con:
        lines = rows(con, """SELECT sector, subsector, label, votes, round(weight, 2) AS weight, round(money) AS money, n_funded, n_aligned,
                                    round(peers_aligned, 2) AS peers_aligned, round(lift, 3) AS lift, round(se, 3) AS se, round(z, 2) AS z
                             FROM member_sector_scores WHERE bioguide = ? ORDER BY money DESC""", [bg])
        for ln in lines:
            ln["series"] = [[r["m"], r["amt"]] for r in rows(con, """
                SELECT strftime(date_trunc('month', week), '%Y-%m') AS m, round(sum(amount)) AS amt FROM pac_sub_weekly
                WHERE bioguide = ? AND sector = ? AND (? = '' OR subsector = ?) AND week BETWEEN DATE '2000-01-01' AND DATE '2026-12-31'
                GROUP BY 1 ORDER BY 1""", [bg, ln["sector"], ln["subsector"], ln["subsector"]])]
    return lines


@app.get("/api/member/{bg}/donor_votes")
def member_donor_votes(bg: str):
    """Direction-coded votes: which way helps the donor sector, how the member voted, sector money before the vote, district view."""
    with db() as con:
        return rows(con, """
            SELECT strftime(a.vdate, '%Y-%m-%d') AS d, a.congress, a.chamber, a.rollnumber AS rn, a.bill, a.sector, a.subsector, a.helps_vote,
                   a.evidence_level, a.yea, a.aligned, round(a.pac_6y) AS pac_6y, round(a.pac_2y) AS pac_2y, round(a.share_6y, 3) AS share_6y,
                   r.vote_question AS q, coalesce(left(r.vote_desc, 110), left(vl.label, 110)) AS desc, dir.evidence, dir.source_url,
                   v.district_view, v.with_district, round(v.est, 3) AS est, v.item, v."match" AS district_match
            FROM donor_alignment a
            JOIN c.rollcalls r ON r.congress = a.congress AND r.chamber = a.chamber AND r.rollnumber = a.rollnumber
            JOIN vote_direction dir ON dir.congress = a.congress AND dir.chamber = a.chamber AND dir.rollnumber = a.rollnumber
                 AND dir.sector = a.sector AND dir.subsector = a.subsector
            LEFT JOIN vote_vs_district v ON v.congress = a.congress AND v.chamber = a.chamber AND v.rollnumber = a.rollnumber AND v.bioguide = a.bioguide
            LEFT JOIN vote_label vl ON vl.congress = a.congress AND vl.chamber = a.chamber AND vl.rollnumber = a.rollnumber
            WHERE a.bioguide = ? ORDER BY a.vdate, a.sector""", [bg])


@app.get("/api/leaderboard")
def leaderboard(sector: str, source: str = "pac_direct", chamber: str = "", congress_from: int = 109, congress_to: int = 119, limit: int = 25):
    y0, _ = congress_years(congress_from)
    _, y1 = congress_years(congress_to)
    with db() as con:
        return rows(con, f"""
            WITH t AS (SELECT bioguide_id, arg_max(bioname, congress) bn, arg_max(party_code, congress) pc, arg_max(state, congress) st,
                              arg_max(chamber, congress) ch FROM c.member_terms GROUP BY 1),
                 x AS (SELECT bioguide, any_value(full_name) fn FROM c.id_crosswalk GROUP BY 1)
            SELECT w.bioguide AS id, coalesce(x.fn, t.bn) AS name,
                   CASE t.pc WHEN 100 THEN 'D' WHEN 200 THEN 'R' ELSE 'I' END AS party, t.st AS state, t.ch AS chamber,
                   round(sum(w.amount)) AS amount
            FROM money_weekly w JOIN t ON t.bioguide_id = w.bioguide LEFT JOIN x ON x.bioguide = w.bioguide
            WHERE w.sector = ? AND w.source = ? AND w.week BETWEEN DATE '{y0}-01-01' AND LEAST(DATE '{y1}-12-31', DATE '{TODAY}')
              AND (? = '' OR t.ch = ?)
            GROUP BY ALL ORDER BY amount DESC LIMIT ?""", [sector, source, chamber, chamber, limit])


# defense-industry endpoints live in their own module (imported here so the helpers above exist, and before the static mount so the mount does not shadow them)
from server import companies_api, defense_api, lobbying_api  # noqa: E402

app.include_router(defense_api.router)
app.include_router(lobbying_api.router)
app.include_router(companies_api.router)

dist = ROOT / "web" / "dist"
if dist.exists():
    app.mount("/", StaticFiles(directory=dist, html=True), name="web")
