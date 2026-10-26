"""Baseline: how much of how members vote is already explained by party, ideology and district -- before any money.

Builds in data/analysis.duckdb
  member_vote(congress, chamber, rollnumber, icpsr, bioguide, party, state, district, nominate_dim1, yea, p_cast, p_yea,
              unity, party_maj_yea, defect, own_share, mrp_ideology, lines_match, rc)
  rollcall_party(congress, chamber, rollnumber, n_d, n_r, d_yea_share, r_yea_share, d_maj_yea, r_maj_yea, unity)

Definitions
  p_cast   Voteview's NOMINATE-model probability of the vote the member actually cast (needs the vote to have been
           scaled: lopsided votes and some early-Congress votes are not, so p_cast is NULL for ~19%).
  p_yea    model probability of Yea (p_cast if they voted Yea, else 1 - p_cast).
  unity    CQ-style party-unity roll call: a majority of Democrats votes against a majority of Republicans
           (each party needs >= MIN_PARTY voters).
  defect   member voted against their own party's majority on that roll call (D/R only; independents excluded).
  own_share  the member's own party's presidential two-party share in their district (House) or state (Senate).
Nothing here uses money. This is the yardstick any money effect has to beat.
"""
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
MIN_PARTY = 10

con = duckdb.connect(str(ROOT / "data" / "analysis.duckdb"))
con.execute(f"ATTACH '{(ROOT / 'data' / 'congress.duckdb').as_posix()}' AS c (READ_ONLY)")


def build() -> None:
    con.execute("""
    CREATE OR REPLACE TABLE mv0 AS
    SELECT v.congress, v.chamber, v.rollnumber, v.icpsr, m.bioguide_id AS bioguide,
           CASE m.party_code WHEN 100 THEN 'D' WHEN 200 THEN 'R' ELSE 'I' END AS party,
           m.state, m.district::INT AS district, m.nominate_dim1,
           (v.vote = 'Yea')::INT AS yea,
           TRY_CAST(v.prob AS DOUBLE) / 100.0 AS p_cast,   -- Voteview stores a percent, as text
           (v.congress * 2 + (v.chamber = 'Senate')::INT) * 100000 + v.rollnumber AS rc
    FROM c.votes v JOIN c.member_terms m USING (congress, chamber, icpsr)
    WHERE v.vote IN ('Yea', 'Nay')
      AND m.state NOT IN ('DC', 'PR', 'GU', 'VI', 'AS', 'MP')   -- delegates: no district lean, not full votes""")
    con.execute(f"""
    CREATE OR REPLACE TABLE rollcall_party AS
    SELECT congress, chamber, rollnumber,
           count(*) FILTER (WHERE party = 'D') AS n_d, count(*) FILTER (WHERE party = 'R') AS n_r,
           avg(yea) FILTER (WHERE party = 'D') AS d_yea_share, avg(yea) FILTER (WHERE party = 'R') AS r_yea_share
    FROM mv0 GROUP BY 1, 2, 3""")
    con.execute(f"""
    ALTER TABLE rollcall_party ADD COLUMN d_maj_yea INT; ALTER TABLE rollcall_party ADD COLUMN r_maj_yea INT; ALTER TABLE rollcall_party ADD COLUMN unity BOOLEAN;
    UPDATE rollcall_party SET
        d_maj_yea = CASE WHEN d_yea_share > 0.5 THEN 1 WHEN d_yea_share < 0.5 THEN 0 END,
        r_maj_yea = CASE WHEN r_yea_share > 0.5 THEN 1 WHEN r_yea_share < 0.5 THEN 0 END;
    UPDATE rollcall_party SET unity = (n_d >= {MIN_PARTY} AND n_r >= {MIN_PARTY} AND d_maj_yea IS NOT NULL
                                       AND r_maj_yea IS NOT NULL AND d_maj_yea <> r_maj_yea)""")
    con.execute("""
    CREATE OR REPLACE TABLE member_vote AS
    SELECT mv.congress, mv.chamber, mv.rollnumber, mv.icpsr, mv.bioguide, mv.party, mv.state, mv.district, mv.nominate_dim1,
           mv.yea, mv.p_cast,
           CASE WHEN mv.p_cast IS NULL THEN NULL WHEN mv.yea = 1 THEN mv.p_cast ELSE 1 - mv.p_cast END AS p_yea,
           coalesce(rp.unity, false) AS unity,
           CASE mv.party WHEN 'D' THEN rp.d_maj_yea WHEN 'R' THEN rp.r_maj_yea END AS party_maj_yea,
           CASE WHEN mv.party IN ('D', 'R') AND (CASE mv.party WHEN 'D' THEN rp.d_maj_yea ELSE rp.r_maj_yea END) IS NOT NULL
                THEN (mv.yea <> (CASE mv.party WHEN 'D' THEN rp.d_maj_yea ELSE rp.r_maj_yea END))::INT END AS defect,
           CASE mv.party WHEN 'D' THEN d.demshare_pres WHEN 'R' THEN 1 - d.demshare_pres END AS own_share,
           d.mrp_ideology, d.lines_match, mv.rc
    FROM mv0 mv
    JOIN rollcall_party rp USING (congress, chamber, rollnumber)
    LEFT JOIN district_lean d ON d.congress = mv.congress AND d.chamber = mv.chamber AND d.state = mv.state
                             AND d.district = CASE WHEN mv.chamber = 'Senate' THEN 0 ELSE mv.district END""")
    con.execute("DROP TABLE mv0")


def accuracy() -> None:
    print("\n=== A. How well do party and ideology predict a member's vote? (D/R members, votes Voteview scaled) ===")
    print("party-line = % voting with their own party's majority; NOMINATE = % where the model gave the cast vote p>=.5")
    print(f"{'':12s}{'member-votes':>13s}{'party-line':>11s}{'NOMINATE':>10s}{'|':>2s}{'unity votes':>12s}{'party-line':>11s}{'NOMINATE':>10s}")
    q = """
    SELECT chamber, congress, count(*) n, 100*avg(1-defect) party, 100*avg((p_cast >= .5)::INT) nom,
           count(*) FILTER (WHERE unity) nu, 100*avg(1-defect) FILTER (WHERE unity) pu, 100*avg((p_cast >= .5)::INT) FILTER (WHERE unity) nu_nom
    FROM member_vote WHERE party IN ('D','R') AND p_cast IS NOT NULL AND defect IS NOT NULL
    GROUP BY ROLLUP (chamber, congress) ORDER BY chamber NULLS LAST, congress NULLS LAST"""
    for ch, cg, n, pa, no, nu, pu, nun in con.execute(q).fetchall():
        label = f"{ch or 'ALL'} {cg or ''}".strip()
        print(f"{label:12s}{n:>13,}{pa:>10.1f}%{no:>9.1f}%{'|':>2s}{nu:>12,}{pu:>10.1f}%{nun:>9.1f}%")
    r = con.execute("""SELECT count(*) FILTER (WHERE p_cast IS NULL)*100.0/count(*) FROM member_vote WHERE party IN ('D','R')""").fetchone()[0]
    print(f"(votes Voteview did not scale, so no NOMINATE probability: {r:.1f}% of D/R member-votes)")


def surprise() -> None:
    print("\n=== B. How much is left for anything else to explain? Share of D/R member-votes the model found surprising ===")
    print(f"{'':10s}{'p<.10':>8s}{'p<.25':>8s}{'p<.50':>8s}   (probability the model gave to the vote actually cast)")
    for ch, a, b, c_ in con.execute("""
        SELECT chamber, 100*avg((p_cast<.10)::INT), 100*avg((p_cast<.25)::INT), 100*avg((p_cast<.5)::INT)
        FROM member_vote WHERE party IN ('D','R') AND p_cast IS NOT NULL GROUP BY 1 ORDER BY 1""").fetchall():
        print(f"{ch:10s}{a:>7.1f}%{b:>7.1f}%{c_:>7.1f}%")


def lean() -> None:
    print("\n=== C. Does district lean matter? Defection on party-unity votes by own party's presidential share ===")
    print("(own_share = % of the district's two-party presidential vote that went to the member's own party)")
    q = """
    SELECT chamber, CASE WHEN own_share < .40 THEN '1: <40%' WHEN own_share < .45 THEN '2: 40-45%' WHEN own_share < .50 THEN '3: 45-50%'
                         WHEN own_share < .55 THEN '4: 50-55%' WHEN own_share < .65 THEN '5: 55-65%' ELSE '6: 65%+' END AS bin,
           count(*) n, count(DISTINCT bioguide) members, 100*avg(defect) rate
    FROM member_vote WHERE unity AND defect IS NOT NULL AND own_share IS NOT NULL
    GROUP BY 1, 2 ORDER BY 1, 2"""
    cur = None
    for ch, b, n, m, rate in con.execute(q).fetchall():
        if ch != cur:
            print(f"  {ch}:")
            cur = ch
        print(f"    {b:12s} {n:>10,} votes  {m:>4} members   defect {rate:>5.1f}%")


def lpm_fe(df: pd.DataFrame, y: str, xs: list[str], fe: str, cluster: str):
    d = df[[y] + xs + [fe, cluster]].dropna()
    g = d.groupby(fe)
    yv = (d[y] - g[y].transform("mean")).to_numpy()
    X = (d[xs] - g[xs].transform("mean")).to_numpy()
    xtx = X.T @ X
    beta = np.linalg.solve(xtx, X.T @ yv)
    e = yv - X @ beta
    s = pd.DataFrame(X * e[:, None]).groupby(d[cluster].to_numpy()).sum().to_numpy()
    inv = np.linalg.inv(xtx)
    v = inv @ (s.T @ s) @ inv * (len(s) / (len(s) - 1))
    return beta, np.sqrt(np.diag(v)), 1 - (e @ e) / (yv @ yv), len(d), len(s)


def regress() -> None:
    print("\n=== D. What predicts defecting from the party majority on unity votes? (linear model, roll-call fixed effects, SEs clustered by member) ===")
    df = con.execute("""
        SELECT chamber, congress, party, bioguide, rc, defect, own_share, nominate_dim1 FROM member_vote
        WHERE unity AND defect IS NOT NULL AND own_share IS NOT NULL AND nominate_dim1 IS NOT NULL
          AND lines_match = 'exact'""").df()  # exact: drop districts whose lines changed under a borrowed map
    # moderation: how far the member sits toward the other party from their own party's mean, standardised within party-Congress-chamber
    grp = df.groupby(["chamber", "congress", "party"])["nominate_dim1"]
    z = (df["nominate_dim1"] - grp.transform("mean")) / grp.transform("std")
    df["moderation"] = np.where(df["party"] == "D", z, -z)       # + = more moderate than the party's average member
    df["own_share10"] = (df["own_share"] - 0.5) * 10             # per 10 points of own-party presidential share, centred at 50%
    df["defect"] = df["defect"].astype(float)
    specs = [("ideology only", ["moderation"]), ("district lean only", ["own_share10"]), ("both", ["moderation", "own_share10"])]
    for ch in ("House", "Senate"):
        sub = df[df["chamber"] == ch]
        print(f"\n  {ch}  ({len(sub):,} member-votes on unity roll calls, {sub['bioguide'].nunique()} members)")
        print(f"    {'model':20s}{'moderation (1 SD)':>22s}{'own-party share (+10pts)':>28s}{'within R2':>11s}")
        for name, xs in specs:
            b, se, r2, n, g = lpm_fe(sub, "defect", xs, "rc", "bioguide")
            cell = {x: f"{b[i]*100:+.2f} pts (se {se[i]*100:.2f})" for i, x in enumerate(xs)}
            print(f"    {name:20s}{cell.get('moderation', '-'):>22s}{cell.get('own_share10', '-'):>28s}{r2:>11.3f}")
    print("\n  Reading: a coefficient is the change in the chance of voting against one's own party on a unity vote.")
    print("  'within R2' is the share of who-defects-on-a-given-vote variation explained; the rest is what money (or anything else) must explain.")


def faces() -> None:
    print("\n=== E. Face-validity check: most frequent defectors on unity votes (>=150 such votes) ===")
    for name, party, n, rate in con.execute("""
        SELECT m.bioname, v.party, count(*) n, 100*avg(defect) FROM member_vote v
        JOIN (SELECT DISTINCT bioguide_id, last_value(bioname) OVER (PARTITION BY bioguide_id ORDER BY congress) AS bioname FROM c.member_terms) m
          ON m.bioguide_id = v.bioguide
        WHERE unity AND defect IS NOT NULL GROUP BY m.bioname, v.party HAVING count(*) >= 150 ORDER BY 4 DESC LIMIT 12""").fetchall():
        print(f"    {name:32s} {party}  {rate:>5.1f}%  of {n:,} unity votes")


if __name__ == "__main__":
    build()
    print("member_vote:", con.execute("SELECT count(*), count(p_cast), count(own_share), count(defect) FROM member_vote").fetchone(),
          "(rows, with p_cast, with district lean, with defect flag)")
    print("unity roll calls:", con.execute("SELECT chamber, count(*) FILTER (WHERE unity), count(*) FROM rollcall_party GROUP BY 1 ORDER BY 1").fetchall())
    accuracy()
    surprise()
    lean()
    regress()
    faces()
