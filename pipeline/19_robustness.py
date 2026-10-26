"""Two stronger tests of whether money moves votes, beyond the before/after split.

A. Placebo industries.  For votes an industry cares about, regress "voted the donors' way" on trailing-6-year PAC money from EVERY industry at once
   (same party, same vote, controlling for ideology, district lean and local stake). If money moves votes, the coefficient on the industry the
   vote concerns should dominate; if money from unrelated industries predicts the vote about as well, the link is a general fundraising or
   ideology marker, not a sector-specific effect.
B. Committee moves.  A natural experiment: when a member joins a committee with jurisdiction over an industry, that industry's money to them
   jumps (it follows the gavel, not the person). Compare member-years before and after joining with members who never joined (member and year
   fixed effects). If votes shift toward the industry after joining while the money jumps, that is what influence would look like; if money
   jumps and votes do not move, the money is chasing power rather than buying votes.
Outputs (analysis.duckdb): placebo_test, committee_did.
"""
import importlib.util
import re
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("scores16", Path(__file__).with_name("16_scores.py"))
_s16 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_s16)
con = _s16.con


def labels_of(df: pd.DataFrame) -> pd.Series:
    return pd.Series([_s16.sector_label(a, b) for a, b in zip(df["sector"], df["subsector"])], index=df.index)


def weekly_by_label() -> pd.DataFrame:
    w = con.execute("""SELECT bioguide, week, sector, subsector, amount FROM pac_sub_weekly WHERE week BETWEEN DATE '2000-01-01' AND DATE '2026-12-31'""").df()
    w["label"] = labels_of(w)
    # money that falls under a coded subsector label also counts for the sector-wide label of the others; placebo set = the 12 biggest labels
    top = w.groupby("label")["amount"].sum().sort_values(ascending=False).head(14).index.tolist()
    for need in ("oil gas", "coal mining", "banks", "pharma", "Labor", "Retail"):
        if need not in top:
            top.append(need)
    w = w[w["label"].isin(top)]
    w["week"] = pd.to_datetime(w["week"])
    return w.groupby(["bioguide", "label", "week"], as_index=False)["amount"].sum()


def trailing(w: pd.DataFrame, pairs: pd.DataFrame, years: int = 6) -> pd.DataFrame:
    """For each (bioguide, vdate) pair, trailing-`years` PAC money by label (log of $K)."""
    pairs = pairs.reset_index(drop=True).copy()
    pairs["pid"] = np.arange(len(pairs))
    out = pairs.copy()
    for lab, g in w.groupby("label"):
        g = g.sort_values("week").copy()
        g["cum"] = g.groupby("bioguide")["amount"].cumsum()
        g = g[["bioguide", "week", "cum"]]
        hi = pd.merge_asof(pairs.sort_values("vdate"), g, left_on="vdate", right_on="week", by="bioguide", direction="backward").set_index("pid")["cum"]
        lo_in = pairs.assign(vdate=pairs["vdate"] - pd.DateOffset(years=years)).sort_values("vdate")
        lo = pd.merge_asof(lo_in, g, left_on="vdate", right_on="week", by="bioguide", direction="backward").set_index("pid")["cum"]
        diff = (hi.reindex(out["pid"]).fillna(0).to_numpy() - lo.reindex(out["pid"]).fillna(0).to_numpy()).clip(min=0)
        out[f"lg_{lab}"] = np.log1p(diff / 1000.0)
    return out.drop(columns=["pid"])


def placebo() -> pd.DataFrame:
    df = con.execute("SELECT * FROM donor_alignment_scored").df()
    df["vdate"] = pd.to_datetime(df["vdate"])
    df["aligned_f"] = df["aligned"].astype(float)
    df["fe"] = df["rc"].astype(str) + "|" + df["sector"] + "|" + df["subsector"] + "|" + df["party"]
    pairs = df[["bioguide", "vdate"]].drop_duplicates().reset_index(drop=True)
    pm = trailing(weekly_by_label(), pairs)
    df = df.merge(pm, on=["bioguide", "vdate"], how="left")
    lg_cols = [c for c in df.columns if c.startswith("lg_")]
    df[lg_cols] = df[lg_cols].fillna(0.0)
    scale = float(np.log1p(50.0)) * 100
    rows = []
    groups = {"oil and gas votes": df[df["subsector"] == "oil_gas"], "bank votes": df[df["subsector"] == "banks"], "labor votes": df[df["sector"] == "Labor"]}
    own = {"oil and gas votes": "lg_oil gas", "bank votes": "lg_banks", "labor votes": "lg_Labor"}
    for name, sub in groups.items():
        xs = lg_cols + ["nominate_dim1", "own_share", "local_z"]
        b, se, n = _s16.lpm(sub, xs, ["fe"])
        for i, c in enumerate(lg_cols):
            rows.append({"vote_group": name, "money_from": c[3:], "is_own": c == own[name], "effect_pts": b[i] * scale, "se_pts": se[i] * scale, "n": n})
    out = pd.DataFrame(rows)
    con.execute("CREATE OR REPLACE TABLE placebo_test AS SELECT * FROM out")
    return out


def committee_did() -> pd.DataFrame:
    ca = con.execute("SELECT congress, chamber, bioguide, committee_name, start_date, source FROM committee_assignment WHERE source = 'stewart_woon' AND bioguide IS NOT NULL AND start_date IS NOT NULL").df()
    ca["start_date"] = pd.to_datetime(ca["start_date"])
    cs = pd.read_csv(ROOT / "pipeline" / "definitions" / "committee_sector.csv")
    cs = cs[cs["tier"] == "strict"]
    target = {"oil and gas": ("Energy & Natural Resources", "oil_gas"), "banks": ("Finance, Insurance & Real Estate", "banks"), "labor": ("Labor", "")}
    w = weekly_by_label()
    w["year"] = w["week"].dt.year
    alg = con.execute("SELECT bioguide, vdate, sector, subsector, aligned, p_exp FROM donor_alignment_scored").df()
    alg["year"] = pd.to_datetime(alg["vdate"]).dt.year
    alg["resid"] = alg["aligned"] - alg["p_exp"]
    rows = []
    for name, (sector, sub) in target.items():
        pats = cs[(cs["sector"] == sector) | ((sector == "Labor") & (cs["sector"] == "Labor"))]
        hit = np.zeros(len(ca), dtype=bool)
        for _, r in pats.iterrows():
            hit |= ((ca["chamber"] == r["chamber"]) & ca["committee_name"].str.lower().str.contains(r["committee_pattern"], regex=True)).to_numpy()
        joins = ca[hit].groupby("bioguide")["start_date"].min().rename("join")
        # only people who were NOT already on such a committee when our data starts (a clean 'before')
        early = set(joins[joins <= pd.Timestamp("2005-07-01")].index)          # already on such a committee when the data starts: no 'before'
        joins = joins[joins > pd.Timestamp("2005-07-01")]
        label = {"oil and gas": "oil gas", "banks": "banks", "labor": "Labor"}[name]
        money = w[w["label"] == label].groupby(["bioguide", "year"])["amount"].sum().rename("money").reset_index()
        sel = alg[(alg["sector"] == sector) & (alg["subsector"] == sub)].groupby(["bioguide", "year"])["resid"].mean().rename("resid").reset_index()
        members = sorted((set(sel["bioguide"]) | set(money["bioguide"])) - early)
        panel = pd.MultiIndex.from_product([members, range(2005, 2025)], names=["bioguide", "year"]).to_frame(index=False)
        panel = panel.merge(money, on=["bioguide", "year"], how="left").merge(sel, on=["bioguide", "year"], how="left")
        panel["money"] = panel["money"].fillna(0)
        panel["lg_money"] = np.log1p(panel["money"].clip(lower=0) / 1000.0)
        panel = panel.merge(joins.reset_index(), on="bioguide", how="left")
        panel["post"] = (panel["join"].notna() & (panel["year"] >= panel["join"].dt.year + 1)).astype(float)  # first full year after joining
        panel["ever"] = panel["join"].notna()
        for outcome, col in (("sector money received (log $K)", "lg_money"), ("votes the donors' way, beyond peers (points)", "resid")):
            d = panel.dropna(subset=[col]).copy()
            d["aligned_f"] = d[col] * (100.0 if col == "resid" else 1.0)
            d["fe_m"], d["fe_y"] = d["bioguide"], d["year"]
            try:
                b, se, n = _s16.lpm(d, ["post"], ["fe_m", "fe_y"])
            except (np.linalg.LinAlgError, ValueError):
                continue
            rows.append({"industry": name, "outcome": outcome, "effect": float(b[0]), "se": float(se[0]), "joiners": int(joins.shape[0]), "n": int(n)})
    out = pd.DataFrame(rows)
    con.execute("CREATE OR REPLACE TABLE committee_did AS SELECT * FROM out")
    return out


if __name__ == "__main__":
    pd.set_option("display.width", 200)
    p = placebo()
    print("Placebo industries: points more likely to vote the donors' way per $50K from each industry's PACs (all at once)")
    for g, sub in p.groupby("vote_group"):
        print(f"\n  {g}  (n={sub['n'].iloc[0]:,})")
        for _, r in sub.sort_values("effect_pts", ascending=False).iterrows():
            print(f"    {'*' if r['is_own'] else ' '} {r['money_from']:26s} {r['effect_pts']:+6.1f}  (se {r['se_pts']:.1f})")
    d = committee_did()
    print("\nCommittee moves (difference-in-differences, member and year effects):")
    print(d.round(2).to_string(index=False))
