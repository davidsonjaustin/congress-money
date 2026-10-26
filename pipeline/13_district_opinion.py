"""District (House) and state (Senate) opinion on the issue behind each mapped roll call, and how members voted against it.

Inputs
  data/raw/district/ces_policy_prefs.tab     Cumulative CES Policy Preferences (Dagonel; doi:10.7910/DVN/OSXDQO), 1 = support, 2 = oppose
  data/raw/district/ces_cumulative.feather   Cumulative CES Common Content (Kuriwaki; doi:10.7910/DVN/II2DB6): respondent state, district, weights
  pipeline/definitions/rollcall_issue_map.csv   locked roll call -> survey item map
  analysis.duckdb.district_lean               district presidential share and MRP ideology (predictors for shrinkage)
Outputs (analysis.duckdb)
  district_opinion(congress, chamber, state, district, item, est, sd, raw, n_resp, n_eff, tau)
  vote_vs_district(one row per member per mapped roll call, with district opinion and verdict)

Method (no full MRP: a transparent model-assisted estimate)
  1. For Congress c, use respondents surveyed in the election year before it (their *upcoming* district), and in its
     first and second year (their *current* district). Weighted share supporting = raw estimate per district.
  2. Empirical-Bayes shrinkage: regress district raw estimates on district presidential share and ideology, estimate the
     spread tau of true district opinion around that line, and pull each district toward the line in proportion to how
     noisy its raw estimate is (normal-normal model). Reports a posterior mean and standard deviation.
  3. Verdict: 'supports' / 'opposes' only if the posterior probability that a majority supports (opposes) is >= 90%;
     otherwise 'uncertain'. A member votes AGAINST their constituents only in a confident verdict.
"""
import math
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
import pyarrow.feather as pf

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw" / "district"
CONFIDENT = 0.90
# The moment estimate of the unexplained spread can collapse to ~0 in small samples (e.g. 51 states), which would make the
# regression line look perfectly certain. Never allow less than 2 points of true district-to-district spread.
TAU_FLOOR = 0.02
# (item, year) pairs the source file codes backwards. Found by the party-gap check in load_survey(): in 2014 the ACA
# repeal item shows 11% of Republicans and 81% of Democrats "supporting" repeal, against 75-88% / 17-36% in every other year.
# The policy-preferences guide (v3) says it stopped recoding 2014, but the 2014 responses are still reversed.
FLIP = {("healthcare_aca", 2014)}
# Single-year items cannot be checked against other years, so check the party gap against the sign we know they must have
# (Democrats more supportive than Republicans of every bill below).
DEM_MORE_SUPPORTIVE = {"cces10_stimulus", "cces10_schip", "cces10_cleanenergy", "cces10_aca", "cces10_kagan", "cces10_finreform", "cces10_dadt"}
# CCES 2010 common content roll-call battery (CC332A-J): variable -> item name. 1 = support, 2 = oppose, blank = skipped.
CCES10 = {"CC332A": "cces10_stimulus", "CC332B": "cces10_schip", "CC332C": "cces10_cleanenergy", "CC332D": "cces10_aca",
          "CC332E": "cces10_kagan", "CC332F": "cces10_finreform", "CC332G": "cces10_dadt"}

phi = np.frompyfunc(lambda z: 0.5 * (1 + math.erf(z / math.sqrt(2))), 1, 1)


def load_survey(items: list[str]) -> pd.DataFrame:
    own = [i for i in items if not i.startswith("cces10_")]
    pp = pd.read_csv(RAW / "ces_policy_prefs.tab", sep="\t", usecols=["year", "case_id"] + own, low_memory=False)
    if any(i.startswith("cces10_") for i in items):
        b = pd.read_pickle(RAW / "cces2010_battery.pkl").rename(columns={"V100": "case_id", **CCES10})
        b["year"] = 2010
        b = b[["year", "case_id"] + [i for i in CCES10.values() if i in items]]
        pp = pd.concat([pp, b], ignore_index=True)
    geo =pf.read_table(RAW / "ces_cumulative.feather", columns=["year", "case_id", "weight", "st", "cong", "dist", "cong_up", "dist_up", "pid3"]).to_pandas()
    pp["case_id"] = pp["case_id"].astype("int64")
    geo["case_id"] = geo["case_id"].astype("int64")
    df = pp.merge(geo, on=["year", "case_id"], how="inner")
    print(f"  survey rows matched to respondent geography: {len(df):,} of {len(pp):,}")
    # Voteview numbers an at-large seat 1; the survey codes it 0 or 1.
    for c in ("dist", "dist_up"):
        df.loc[df[c] == 0, c] = 1
    sign_check(df, items)
    return df


def sign_check(df: pd.DataFrame, items: list[str]) -> None:
    """Republican-minus-Democrat support gap by year; a year whose sign opposes the item's usual sign is a coding error."""
    for it in items:
        x = df[df[it].isin([1, 2])]
        gap = {}
        for y, g in x.groupby("year"):
            r, d = g[g["pid3"] == 2], g[g["pid3"] == 1]
            if len(r) >= 150 and len(d) >= 150:
                gap[int(y)] = np.average(r[it] == 1, weights=r["weight"]) - np.average(d[it] == 1, weights=d["weight"])
        if len(gap) == 1 and it in DEM_MORE_SUPPORTIVE:
            (y, v), = gap.items()
            if v > -0.1:
                raise SystemExit(f"{it} {y}: Republican-minus-Democrat gap is {v:+.2f}, expected clearly negative; check coding")
            print(f"  ok {it} {y}: party gap {v:+.2f} (Democrats more supportive, as expected)")
            continue
        if len(gap) < 2:
            continue
        med = float(np.median(list(gap.values())))
        for y, v in gap.items():
            reversed_ = np.sign(v) != np.sign(med) and abs(v) > 0.15 and abs(med) > 0.15
            if (it, y) in FLIP:
                if not reversed_:
                    raise SystemExit(f"{it} {y} is in FLIP but its party gap ({v:+.2f}) matches the usual sign ({med:+.2f})")
                m = (df["year"] == y) & df[it].isin([1, 2])
                df.loc[m, it] = 3 - df.loc[m, it]
                print(f"  flipped {it} {y}: party gap was {v:+.2f} (usual {med:+.2f}); source codes it backwards")
            elif reversed_:
                print(f"  WARNING {it} {y}: party gap {v:+.2f} vs usual {med:+.2f}; not in FLIP, check before using")


def congress_start(c: int) -> int:
    return 2005 + 2 * (c - 109)


def respondents(df: pd.DataFrame, item: str, c: int) -> pd.DataFrame:
    y0 = congress_start(c)
    parts = []
    for year, which in ((y0 - 1, "up"), (y0, "cur"), (y0 + 1, "cur")):
        d = df[(df["year"] == year) & df[item].isin([1, 2])]
        d = d[d["cong_up" if which == "up" else "cong"] == c]
        parts.append(pd.DataFrame({"year": year, "st": d["st"], "district": d["dist_up" if which == "up" else "dist"],
                                   "w": d["weight"], "sup": (d[item] == 1).astype(float)}))
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()


def respondents_for(df: pd.DataFrame, item: str, c: int, chamber: str, proxy: bool) -> tuple[pd.DataFrame, int]:
    """Respondents for (item, Congress). A proxy item with no survey in its own years borrows the nearest Congress that has one: for the
    Senate (state-level opinion) in either direction; for the House only from Congresses on the same district map (113th onward)."""
    r = respondents(df, item, c)
    if not r.empty or not proxy:
        return r, c
    for step in range(1, 12):
        for cand in (c - step, c + step):
            if chamber == "House" and (cand < 113 or c < 113 or cand > 119):
                continue
            if cand < 109 or cand > 119:
                continue
            r = respondents(df, item, cand)
            if not r.empty:
                return r, cand
    return r, c


def estimate(resp: pd.DataFrame, chamber: str, lean: pd.DataFrame) -> pd.DataFrame:
    keys = ["st"] if chamber == "Senate" else ["st", "district"]
    g = resp.assign(ws=resp["w"] * resp["sup"], w2=resp["w"] ** 2).groupby(keys).agg(
        sw=("w", "sum"), ss=("ws", "sum"), sw2=("w2", "sum"), n=("w", "size")).reset_index()
    g["raw"] = g["ss"] / g["sw"]
    g["n_eff"] = g["sw"] ** 2 / g["sw2"]
    p = (g["raw"] * g["n_eff"] + 0.5) / (g["n_eff"] + 1)               # keeps the variance off zero when everyone agrees
    g["se"] = np.sqrt(p * (1 - p) / (g["n_eff"] + 1))
    g = g.rename(columns={"st": "state"})
    if chamber == "Senate":
        g["district"] = 0
    # every district that exists, so seats with no respondents still get a (predictor-only) estimate
    full = lean.merge(g, on=["state", "district"], how="left")
    X = np.column_stack([np.ones(len(full)), full["demshare_pres"], full["mrp_ideology"]])
    ok = full["raw"].notna().to_numpy() & np.isfinite(X).all(axis=1)
    y, se = full["raw"].to_numpy(), full["se"].to_numpy()
    tau2 = 0.003
    for _ in range(8):
        w = 1 / (tau2 + se[ok] ** 2)
        beta = np.linalg.solve((X[ok] * w[:, None]).T @ X[ok], (X[ok] * w[:, None]).T @ y[ok])
        r = y[ok] - X[ok] @ beta
        tau2 = max(TAU_FLOOR ** 2, float(np.sum(r ** 2) / (ok.sum() - X.shape[1]) - np.mean(se[ok] ** 2)))
    pred = np.where(np.isfinite(X).all(axis=1), X @ beta, np.nan)
    se_f = np.where(np.isfinite(se), se, np.inf)
    shrink = tau2 / (tau2 + se_f ** 2)                                # weight on the district's own data
    raw_f = np.where(np.isfinite(y), y, 0.0)
    est = pred + shrink * (raw_f - pred)
    sd = np.sqrt(np.where(np.isinf(se_f), tau2, tau2 * se_f ** 2 / (tau2 + se_f ** 2)))
    out = full[["state", "district"]].copy()
    out["est"], out["sd"], out["raw"] = est, sd, y
    out["n_resp"], out["n_eff"], out["tau"] = full["n"].fillna(0).astype(int), full["n_eff"], math.sqrt(tau2)
    out["pred_corr_input"] = full["demshare_pres"]
    return out


def main() -> None:
    d = ROOT / "pipeline" / "definitions"
    mp = pd.concat([pd.read_csv(f) for f in sorted(d.glob("rollcall_issue_map*.csv"))], ignore_index=True)
    mp = mp.drop_duplicates(["congress", "chamber", "rollnumber"])
    items = sorted(mp["item"].unique())
    df = load_survey(items)
    con = duckdb.connect(str(ROOT / "data" / "analysis.duckdb"))
    con.execute(f"ATTACH '{(ROOT / 'data' / 'congress.duckdb').as_posix()}' AS c (READ_ONLY)")
    lean_all = con.execute("SELECT congress, chamber, state, district::INT AS district, demshare_pres, mrp_ideology FROM district_lean").df()

    rows, diag = [], []
    for (c, ch, item), _ in mp.groupby(["congress", "chamber", "item"]):
        is_proxy = bool((mp[(mp["congress"] == c) & (mp["chamber"] == ch) & (mp["item"] == item)]["match"] == "proxy").all())
        resp, used = respondents_for(df, item, int(c), ch, is_proxy)
        if resp.empty:
            print(f"!! no respondents for {item} in the {c}th"); continue
        lean = lean_all[(lean_all["congress"] == c) & (lean_all["chamber"] == ch)][["state", "district", "demshare_pres", "mrp_ideology"]]
        est = estimate(resp, ch, lean)
        est.insert(0, "item", item); est.insert(0, "chamber", ch); est.insert(0, "congress", int(c))
        est["years"] = ",".join(str(y) for y in sorted(resp["year"].unique())) + (f" (proxy: {used}th)" if used != int(c) else "")
        rows.append(est)
        ok = est["raw"].notna()
        diag.append((int(c), ch, item, est["years"].iloc[0], int(ok.sum()), float(est.loc[ok, "n_resp"].median()),
                     float(est["tau"].iloc[0]), float(np.corrcoef(est.loc[ok, "raw"], est.loc[ok, "pred_corr_input"])[0, 1]),
                     float(np.average(est["est"].dropna()))))
    dopin = pd.concat(rows, ignore_index=True).drop(columns=["pred_corr_input"])
    con.execute("CREATE OR REPLACE TABLE district_opinion AS SELECT * FROM dopin")

    print("District-opinion estimates (one per Congress x chamber x item):")
    print(f"{'Cong':>4} {'chamber':7s} {'item':19s} {'survey years':16s} {'seats':>5s} {'median n':>8s} {'tau':>6s} {'r(raw,pres vote)':>16s} {'mean est':>8s}")
    for c, ch, item, yrs, k, mn, tau, r, me in diag:
        print(f"{c:>4} {ch:7s} {item:19s} {yrs:16s} {k:>5d} {mn:>8.0f} {tau:>6.3f} {r:>16.2f} {me:>8.2f}")

    # ---- members vs. their constituents
    con.execute("CREATE OR REPLACE TABLE rollcall_issue AS SELECT * FROM mp")
    vv = con.execute("""
        SELECT v.congress, v.chamber, v.rollnumber, v.bioguide, v.party, v.state, v.district, v.yea, v.p_cast,
               m.item, m.yea_means, m."match" AS match, m.bill, m.note,
               o.est, o.sd, o.raw, o.n_resp
        FROM member_vote v
        JOIN rollcall_issue m ON m.congress = v.congress AND m.chamber = v.chamber AND m.rollnumber = v.rollnumber
        LEFT JOIN district_opinion o ON o.congress = v.congress AND o.chamber = v.chamber AND o.item = m.item AND o.state = v.state
             AND o.district = CASE WHEN v.chamber = 'Senate' THEN 0 ELSE v.district END""").df()
    vv["p_support"] = phi(((vv["est"] - 0.5) / vv["sd"]).astype(float)).astype(float)
    vv["district_view"] = np.where(vv["p_support"] >= CONFIDENT, "supports", np.where(vv["p_support"] <= 1 - CONFIDENT, "opposes", "uncertain"))
    vv.loc[vv["est"].isna(), "district_view"] = "unknown"
    vv["voted_for_item"] = np.where(vv["yea_means"] == "support", vv["yea"], 1 - vv["yea"])   # 1 = member took the pro-item side
    vv["with_district"] = np.where(vv["district_view"].isin(["supports", "opposes"]),
                                   ((vv["voted_for_item"] == 1) == (vv["district_view"] == "supports")).astype(float), np.nan)
    con.execute("CREATE OR REPLACE TABLE vote_vs_district AS SELECT * FROM vv")

    print("\nHow members voted against their district's (or state's) confident majority:")
    print(f"{'Cong':>4} {'ch':3s} {'roll':>4} {'bill':8s} {'item':19s} {'match':7s} {'members':>7} {'conf. view':>10} {'against D':>10} {'against R':>10}   (share of confident-view members voting against their constituents)")
    rep = []
    for (c, ch, rn), g in vv.groupby(["congress", "chamber", "rollnumber"]):
        conf = g[g["with_district"].notna()]
        def against(p):
            s = conf[conf["party"] == p]
            return f"{100 * (1 - s['with_district'].mean()):4.0f}% of {len(s):<3d}" if len(s) else "     –"
        rep.append((c, ch, rn, g["bill"].iloc[0], g["item"].iloc[0], g["match"].iloc[0], len(g), len(conf), against("D"), against("R")))
    for c, ch, rn, bill, item, match, n, nc, aD, aR in rep:
        print(f"{c:>4} {ch[:3]:3s} {rn:>4} {str(bill):8s} {item:19s} {match:7s} {n:>7} {nc:>10} {aD:>14s} {aR:>14s}")


if __name__ == "__main__":
    main()
