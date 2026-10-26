"""Rank members: how much do they vote with the sectors that fund them, beyond what their party peers would do?

Reads analysis.duckdb.donor_alignment (one row per member x coded vote x sector) and vote_vs_district.
Writes scores (per member, evidence variant and sector), member_info, coverage_stats, timing_test.

Donor-loyalty index (the ranking)
  For each coded vote the member cast, we ask what chance a same-party member with the same ideology and district lean had of
  voting the donors' way on that very vote (p_expected; leave-one-out so the member does not help predict themselves).
  Votes count in proportion to how much that sector had given them in the prior 6 years: weight = min(1, $ / $50K).
      lift  = sum(weight x (voted_donors_way - p_expected)) / (sum(weight) + 2)      (the +2 shrinks thin records toward 0)
      index = 50 + 100 x lift, clipped to 0-100.   50 = votes like their peers; above = more donor-loyal than peers; below = less.
  Ranked only if sum(weight) >= MIN_WEIGHT (about three votes with full funding).
Variants: 'all' uses every coded vote; 'core' only votes whose donor side is documented or reported from the industry's own statements
  (scorecard-derived positions from advocacy groups are excluded).
Against-constituents rate: share of landmark votes (CES survey) with a confident district majority where the member voted the other way.
Timing test: does sector money received BEFORE a vote predict voting the donors' way as strongly as money received AFTER?
"""
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
MIN_WEIGHT = 2.5
FULL_FUNDING = 50_000.0
SHRINK = 2.0
CORE_LEVELS = {"documented", "reported"}
con = duckdb.connect(str(ROOT / "data" / "analysis.duckdb"))
con.execute(f"ATTACH '{(ROOT / 'data' / 'congress.duckdb').as_posix()}' AS c (READ_ONLY)")


def expected_alignment(df: pd.DataFrame) -> pd.Series:
    """Leave-one-out chance a same-party peer votes the donors' way on the same vote, adjusted for ideology and district lean.

    The ideology/district slopes are estimated separately for each sector group: being conservative raises the chance of voting
    with banks and oil but lowers it for labor, so one shared slope would be wrong for both.
    """
    d = df[["rc", "sector", "subsector", "party", "aligned", "nominate_dim1", "own_share", "local_z"]].copy()
    d["fe"] = d["rc"].astype(str) + "|" + d["sector"] + "|" + d["subsector"] + "|" + d["party"]
    g = d.groupby("fe")
    n = g["aligned"].transform("size")
    loo = (g["aligned"].transform("sum") - d["aligned"]) / (n - 1).clip(lower=1)
    X = d[["nominate_dim1", "own_share", "local_z"]]
    ok = X.notna().all(axis=1)
    Xd = X - g[["nominate_dim1", "own_share", "local_z"]].transform("mean")
    yd = d["aligned"] - g["aligned"].transform("mean")
    adj = pd.Series(0.0, index=d.index)
    for _, idx in d.groupby(["sector", "subsector"]).groups.items():
        m = ok.loc[idx]
        use = pd.Index(idx)[m.to_numpy()]
        if len(use) < 200:
            continue
        beta = np.linalg.lstsq(Xd.loc[use].to_numpy(), yd.loc[use].to_numpy(), rcond=None)[0]
        adj.loc[use] = Xd.loc[use].to_numpy() @ beta
    return (loo + adj).clip(0.02, 0.98).where(n > 1, 0.5)


def sector_label(sector: str, sub: str) -> str:
    return sub.replace("_", " ") if sub else sector.split(",")[0].replace(" & Consumer", "")


def score_rows(g: pd.DataFrame) -> pd.Series:
    sw = g["w"].sum()
    lift = (g["w"] * g["resid"]).sum() / (sw + SHRINK)
    se = np.sqrt((g["w"] ** 2 * g["p_exp"] * (1 - g["p_exp"])).sum()) / (sw + SHRINK)
    funded = g[g["pac_6y"] >= 10_000]
    top = g.groupby("label")["pac_6y"].max().sort_values(ascending=False)
    return pd.Series({
        "votes_coded": len(g), "weight": sw, "n_funded": len(funded), "n_funded_aligned": int(funded["aligned"].sum()),
        "peers_funded_aligned": float(funded["p_exp"].sum()),
        "loyalty": float((g["w"] * g["aligned"]).sum() / sw) if sw > 0 else np.nan,
        "peers": float((g["w"] * g["p_exp"]).sum() / sw) if sw > 0 else np.nan,
        "lift": lift, "se": se, "z": lift / se if se > 0 else np.nan, "index": float(np.clip(50 + 100 * lift, 0, 100)),
        "money_at_stake": float(top.sum()), "top_sectors": ", ".join(f"{k} ${v/1000:.0f}K" for k, v in top.head(3).items() if v >= 10_000),
    })


def build_scores() -> pd.DataFrame:
    raw = con.execute("SELECT * FROM donor_alignment").df()
    raw["label"] = [sector_label(a, b) for a, b in zip(raw["sector"], raw["subsector"])]
    frames, cov = [], []
    has_inferred = con.execute("SELECT count(*) FROM information_schema.tables WHERE table_name = 'inferred_alignment'").fetchone()[0] > 0
    has_lobbied = has_inferred and con.execute("SELECT count(*) FROM information_schema.tables WHERE table_name = 'lobbied_votes'").fetchone()[0] > 0
    for variant in ("all", "core") + (("inferred",) if has_inferred else ()) + (("lobbied",) if has_lobbied else ()):
        if variant in ("inferred", "lobbied"):
            # rows from 21_inferred_alignment.py: the industry's side is inferred from the money pattern and p_exp is already a cross-fitted
            # ideology/district model, so the same-party-peer expectation is not used here. 'lobbied' keeps the votes whose bill that industry lobbied (22)
            q = ("SELECT * FROM inferred_alignment" if variant == "inferred" else
                 """SELECT a.* FROM inferred_alignment a WHERE EXISTS (SELECT 1 FROM lobbied_votes l WHERE l.congress = a.congress AND l.chamber = a.chamber
                                                                       AND l.rollnumber = a.rollnumber AND l.label = a.label)""")
            df = con.execute(q).df().reset_index(drop=True)
        else:
            df = (raw if variant == "all" else raw[raw["evidence_level"].isin(CORE_LEVELS)]).copy().reset_index(drop=True)
            df["p_exp"] = expected_alignment(df)
        df["w"] = (df["pac_6y"].clip(lower=0) / FULL_FUNDING).clip(upper=1.0)
        df["resid"] = df["aligned"] - df["p_exp"]
        # 'All business' leaves out Labor so its hundreds of union-scorecard votes do not swamp the handful of business-sector votes
        groups = [("All business", df[df["sector"] != "Labor"])] + [(lab, g) for lab, g in df.groupby("label")]
        for lab, g in groups:
            s = g.groupby("bioguide").apply(score_rows, include_groups=False).reset_index()
            s["variant"], s["sector_label"] = variant, lab
            frames.append(s)
            cov.append({"variant": variant, "sector_label": lab, "votes": g["rc"].nunique(), "members_ranked": int((s["weight"] >= MIN_WEIGHT).sum())})
        if variant == "all":
            con.execute("CREATE OR REPLACE TABLE donor_alignment_scored AS SELECT * FROM df")
    scores_df = pd.concat(frames, ignore_index=True)
    scores_df["ranked"] = scores_df["weight"] >= MIN_WEIGHT
    # NB: the DataFrame must not share its name with the table, or DuckDB reads the old table instead of the DataFrame
    con.execute("CREATE OR REPLACE TABLE scores AS SELECT * FROM scores_df")
    cov_df = pd.DataFrame(cov)
    con.execute("CREATE OR REPLACE TABLE coverage_stats AS SELECT * FROM cov_df")
    return scores_df


def build_info() -> pd.DataFrame:
    vv = con.execute("""SELECT congress, chamber, rollnumber, bioguide, party, with_district FROM vote_vs_district
                        WHERE match = 'direct' AND with_district IS NOT NULL AND party IN ('D','R')""").df()
    vv["against"] = 1.0 - vv["with_district"]
    vv["peer_against"] = vv.groupby(["congress", "chamber", "rollnumber", "party"])["against"].transform("mean")
    cs = vv.groupby("bioguide").agg(const_votes=("against", "size"), const_against=("against", "sum"), const_peer=("peer_against", "sum")).reset_index()
    cs["const_rate"] = cs["const_against"] / cs["const_votes"]
    cs["const_lift"] = (cs["const_against"] - cs["const_peer"]) / cs["const_votes"]
    # donors vs district over every coded vote that has a clear district view. 'direct' = a survey item about that very issue;
    # 'proxy' = the fossil votes, with district opinion stood in by support for letting the EPA regulate CO2. Kept apart: the proxy is one opinion item
    # applied to ~150 different fossil votes, so it must never be pooled with the direct matches.
    dd = con.execute("""
        SELECT a.bioguide,
               sum((v.match = 'direct' AND a.aligned = 1 AND v.with_district = 0)::INT) AS donors_over_district,
               sum((v.match = 'direct' AND a.aligned = 0 AND v.with_district = 1)::INT) AS district_over_donors,
               sum((v.match = 'direct')::INT) AS donor_district_votes,
               sum((v.match = 'proxy' AND a.aligned = 1 AND v.with_district = 0)::INT) AS proxy_donors_over,
               sum((v.match = 'proxy' AND a.aligned = 0 AND v.with_district = 1)::INT) AS proxy_district_over,
               sum((v.match = 'proxy')::INT) AS proxy_votes
        FROM (SELECT DISTINCT bioguide, congress, chamber, rollnumber, aligned FROM donor_alignment WHERE sector <> 'Labor') a
        JOIN vote_vs_district v ON v.congress = a.congress AND v.chamber = a.chamber AND v.rollnumber = a.rollnumber
             AND v.bioguide = a.bioguide AND v.with_district IS NOT NULL AND v.match IN ('direct', 'proxy')
        GROUP BY 1""").df()
    fo = con.execute("""SELECT bioguide, count(*) AS fossil_const_votes, sum((1 - with_district)::INT) AS fossil_const_against
                        FROM vote_vs_district WHERE match = 'proxy' AND with_district IS NOT NULL GROUP BY 1""").df()
    names = con.execute("""
        WITH t AS (SELECT bioguide_id, arg_max(bioname, congress) bn, arg_max(party_code, congress) pc, arg_max(state, congress) st,
                          arg_max(chamber, congress) ch, max(congress) last_c, min(congress) first_c FROM c.member_terms
                   WHERE state NOT IN ('DC','PR','GU','VI','AS','MP') GROUP BY 1),
             x AS (SELECT bioguide, any_value(full_name) fn FROM c.id_crosswalk GROUP BY 1)
        SELECT t.bioguide_id AS bioguide, coalesce(x.fn, t.bn) AS name, CASE t.pc WHEN 100 THEN 'D' WHEN 200 THEN 'R' ELSE 'I' END AS party,
               t.st AS state, t.ch AS chamber, t.last_c, t.first_c FROM t LEFT JOIN x ON x.bioguide = t.bioguide_id""").df()
    info = names.merge(cs, on="bioguide", how="left").merge(dd, on="bioguide", how="left").merge(fo, on="bioguide", how="left")
    con.execute("CREATE OR REPLACE TABLE member_info AS SELECT * FROM info")
    return info


def build_sector_lines() -> None:
    """Per member x coded sector, for the case file (all evidence)."""
    s = con.execute("""SELECT bioguide, sector_label AS label FROM scores WHERE variant = 'all' AND sector_label <> 'All'""").df()
    df = con.execute("SELECT * FROM donor_alignment_scored").df()
    df["label"] = [sector_label(a, b) for a, b in zip(df["sector"], df["subsector"])]

    def agg_s(g: pd.DataFrame) -> pd.Series:
        sw = g["w"].sum()
        funded = g[g["pac_6y"] >= 10_000]
        lift = (g["w"] * g["resid"]).sum() / (sw + SHRINK)
        se = np.sqrt((g["w"] ** 2 * g["p_exp"] * (1 - g["p_exp"])).sum()) / (sw + SHRINK)
        return pd.Series({"votes": len(g), "weight": sw, "money": float(g["pac_6y"].max()), "n_funded": len(funded), "n_aligned": int(funded["aligned"].sum()),
                          "peers_aligned": float(funded["p_exp"].sum()), "lift": lift, "se": se, "z": lift / se if se > 0 else np.nan})
    ss = df.groupby(["bioguide", "sector", "subsector", "label"]).apply(agg_s, include_groups=False).reset_index()
    con.execute("CREATE OR REPLACE TABLE member_sector_scores AS SELECT * FROM ss")


def lpm(df: pd.DataFrame, xs: list[str], fes: list[str]) -> tuple[np.ndarray, np.ndarray, int]:
    d = df[["aligned_f"] + xs + fes + ["bioguide"]].dropna().reset_index(drop=True)
    M = d[["aligned_f"] + xs].astype(float).copy()
    for _ in range(40):
        before = M.to_numpy().copy()
        for f in fes:
            M = M - M.groupby(d[f]).transform("mean")
        if np.abs(M.to_numpy() - before).max() < 1e-9:
            break
    yv, X = M["aligned_f"].to_numpy(), M[xs].to_numpy()
    xtx = X.T @ X
    beta = np.linalg.solve(xtx, X.T @ yv)
    e = yv - X @ beta
    s = pd.DataFrame(X * e[:, None]).groupby(d["bioguide"].to_numpy()).sum().to_numpy()
    inv = np.linalg.inv(xtx)
    v = inv @ (s.T @ s) @ inv * (len(s) / (len(s) - 1))
    return beta, np.sqrt(np.diag(v)), len(d)


def timing() -> pd.DataFrame:
    df = con.execute("SELECT * FROM donor_alignment_scored WHERE vdate < DATE '2024-01-01'").df()
    df["aligned_f"] = df["aligned"].astype(float)
    df["lg_recent"] = np.log1p(df["pac_2y"].clip(lower=0) / 1000.0)
    df["lg_after"] = np.log1p(df["pac_f2y"].clip(lower=0) / 1000.0)
    df["lg_other"] = np.log1p((df["pac_total_6y"] - df["pac_6y"]).clip(lower=0) / 1000.0)
    df["fe"] = df["rc"].astype(str) + "|" + df["sector"] + "|" + df["subsector"] + "|" + df["party"]
    scale = float(np.log1p(50.0)) * 100
    specs = [
        ("Money before the vote only", ["lg_recent"], ["fe"]),
        ("Money after the vote only", ["lg_after"], ["fe"]),
        ("Both together", ["lg_recent", "lg_after"], ["fe"]),
        ("Both, plus ideology, district lean and overall fundraising", ["lg_recent", "lg_after", "nominate_dim1", "own_share", "local_z", "lg_other"], ["fe"]),
        ("Both, same member compared with themselves over time", ["lg_recent", "lg_after"], ["fe", "bioguide"]),
    ]
    groups = [("All coded votes", df), ("Banks", df[df["subsector"] == "banks"]), ("Oil and gas", df[df["subsector"] == "oil_gas"]), ("Labor (unions)", df[df["sector"] == "Labor"])]
    rows = []
    for group, sub in groups:
        for label, xs, fes in specs:
            try:
                b, se, n = lpm(sub, xs, fes)
            except (np.linalg.LinAlgError, ValueError):
                continue
            for i, term in enumerate(xs[:2]):
                rows.append({"group": group, "spec": label, "term": {"lg_recent": "money in the 2 years before", "lg_after": "money in the 2 years after"}[term],
                             "effect_pts": b[i] * scale, "se_pts": se[i] * scale, "n": n})
    out = pd.DataFrame(rows)
    con.execute("CREATE OR REPLACE TABLE timing_test AS SELECT * FROM out")
    return out


if __name__ == "__main__":
    scores = build_scores()
    info = build_info()
    build_sector_lines()
    pd.set_option("display.width", 250); pd.set_option("display.max_colwidth", 60)
    print(con.execute("SELECT variant, sector_label, votes, members_ranked FROM coverage_stats ORDER BY variant, votes DESC").df().to_string(index=False))
    r = scores[(scores["variant"] == "all") & (scores["sector_label"] == "All business") & scores["ranked"]].merge(info[["bioguide", "name", "party", "state"]], on="bioguide")
    cols = ["name", "party", "state", "n_funded", "n_funded_aligned", "peers_funded_aligned", "index", "z", "top_sectors"]
    r = r.sort_values("lift", ascending=False)
    print("\nMOST donor-loyal beyond peers (business sectors, all evidence):\n", r[cols].head(10).round(2).to_string(index=False))
    print("\nLEAST:\n", r[cols].tail(8).iloc[::-1].round(2).to_string(index=False))
    t = timing()
    print("\nTiming test (pts per $50K):\n", t[t["spec"].str.startswith("Both, plus")].round(1).to_string(index=False))
