"""Every roll call vote since 2008 against every industry's PAC money, with no need to know which side the industry wanted.

For each vote (House and Senate separately) and each industry label we ask: among the members who voted, did the ones who had received more of that
industry's PAC money in the two years BEFORE the vote vote Yea (or Nay) more often, once we account for their ideology (separately by party), party,
district lean, district ideology and how much PAC money they raised overall? The sign of the slope says which way that industry's money pulls on that
vote; its size says how strongly.

Then the timing check, on the same votes: money received in the two years AFTER the vote is entered next to the money from before. Giving that follows the
vote cannot have moved it, so it shows how much of the link is donors backing members who already vote their way. Influence would leave an extra link
for the money that came first.

A reference distribution comes from shuffling each industry's money across members of the same party and chamber on the same vote.

Outputs (analysis.duckdb)
  all_vote_money(congress, chamber, rollnumber, vdate, label, n, minority, b_only, t_only, b_before, t_before, b_after, t_after, has_after)
      b_* = points of Yea probability per $50K of that industry's PAC money (log scale)
      *_only   = money before the vote on its own
      *_before / *_after = both windows entered together (only for votes whose two following years are fully observed)
  all_vote_null: same columns, money shuffled within party and chamber
"""
import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("rob19", Path(__file__).with_name("19_robustness.py"))
r19 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(r19)
con = r19.con

np.seterr(all="ignore")
START = "2008-01-01"
WINDOW = 24            # months
MIN_MINORITY = 8       # votes with fewer members on the minority side carry no information about money
SCALE = float(np.log1p(50.0)) * 100


def month_index(ts: pd.Series) -> np.ndarray:
    return ((ts.dt.year - 2000) * 12 + (ts.dt.month - 1)).to_numpy()


def build_money():
    w = r19.weekly_by_label()
    labels = sorted(w["label"].unique())
    tot = con.execute("SELECT bioguide, week, amount FROM pac_sub_weekly").df()
    members = sorted(set(w["bioguide"]) | set(tot["bioguide"]) | set(con.execute("SELECT DISTINCT bioguide FROM member_vote").df()["bioguide"]))
    mid = {b: i for i, b in enumerate(members)}
    T = (2027 - 2000) * 12
    lab_ix = {l: i for i, l in enumerate(labels)}
    M = np.zeros((len(members), T, len(labels)), dtype=np.float32)
    mi = w["bioguide"].map(mid).to_numpy()
    ti = month_index(pd.to_datetime(w["week"]))
    li = w["label"].map(lab_ix).to_numpy()
    np.add.at(M, (mi, ti, li), w["amount"].to_numpy(dtype=np.float32))
    TOT = np.zeros((len(members), T), dtype=np.float32)
    np.add.at(TOT, (tot["bioguide"].map(mid).to_numpy(), month_index(pd.to_datetime(tot["week"]))), tot["amount"].to_numpy(dtype=np.float32))
    last = pd.Timestamp(con.execute("SELECT max(week) FROM pac_sub_weekly").fetchone()[0])
    last_full = int(month_index(pd.Series([last]))[0]) - 1            # last month with every week observed
    return mid, labels, M, TOT, last_full


def cum(A: np.ndarray) -> np.ndarray:
    """C[..., t] = money in months before t."""
    z = np.zeros(A.shape[:1] + (1,) + A.shape[2:], dtype=np.float64) if A.ndim == 3 else np.zeros((A.shape[0], 1))
    return np.concatenate([z, np.cumsum(A, axis=1, dtype=np.float64)], axis=1)


def resid(Q: np.ndarray, Z: np.ndarray) -> np.ndarray:
    return Z - Q @ (Q.T @ Z)


def stats(y, ctrl, Xb, Xa):
    """Per-label slopes of y on the money columns after partialling out ctrl. Xa may be None (before-only)."""
    n = len(y)
    Q, _ = np.linalg.qr(ctrl)
    ry = y - Q @ (Q.T @ y)
    Zb = resid(Q, Xb)
    Gbb = (Zb ** 2).sum(0)
    ok = Gbb > 1e-9
    Gbb_s = np.where(ok, Gbb, np.nan)
    b1 = (Zb.T @ ry) / Gbb_s
    e1 = ry[:, None] - Zb * b1
    se1 = np.sqrt(((e1 ** 2) * (Zb ** 2)).sum(0) * n / max(n - ctrl.shape[1] - 1, 1)) / Gbb_s
    out = {"b_only": b1 * SCALE, "t_only": b1 / se1}
    if Xa is not None:
        Za = resid(Q, Xa)
        Gaa, Gba = (Za ** 2).sum(0), (Zb * Za).sum(0)
        det = Gbb * Gaa - Gba ** 2
        det = np.where(np.abs(det) > 1e-9 * np.maximum(Gbb * Gaa, 1e-12), det, np.nan)
        sb, sa = Zb.T @ ry, Za.T @ ry
        bb = (Gaa * sb - Gba * sa) / det
        ba = (Gbb * sa - Gba * sb) / det
        e = ry[:, None] - Zb * bb - Za * ba
        e2 = (e ** 2) * n / max(n - ctrl.shape[1] - 2, 1)
        Mbb, Maa, Mba = (e2 * Zb ** 2).sum(0), (e2 * Za ** 2).sum(0), (e2 * Zb * Za).sum(0)
        vb = (Gaa ** 2 * Mbb - 2 * Gaa * Gba * Mba + Gba ** 2 * Maa) / det ** 2
        va = (Gba ** 2 * Mbb - 2 * Gba * Gbb * Mba + Gbb ** 2 * Maa) / det ** 2
        out.update({"b_before": bb * SCALE, "t_before": bb / np.sqrt(vb), "b_after": ba * SCALE, "t_after": ba / np.sqrt(va)})
    return out


def run(shuffle: bool, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    mid, labels, M, TOT, last_full = build_money()
    CM, CT = cum(M), cum(TOT)
    mv = con.execute(f"""
        SELECT v.congress, v.chamber, v.rollnumber, r.vote_date AS vdate, v.bioguide, v.party, v.nominate_dim1 AS dim1, v.own_share, v.mrp_ideology AS mrp, v.yea
        FROM member_vote v JOIN c.rollcalls r USING (congress, chamber, rollnumber)
        WHERE r.vote_date >= DATE '{START}' AND v.yea IN (0, 1) AND v.party IN ('D', 'R')""").df()
    mv["vdate"] = pd.to_datetime(mv["vdate"])
    mv["mid"] = mv["bioguide"].map(mid)
    mv["m"] = month_index(mv["vdate"])
    mv = mv.dropna(subset=["dim1", "own_share", "mrp"])
    rows = []
    L = len(labels)
    for (cg, ch, rn), g in mv.groupby(["congress", "chamber", "rollnumber"], sort=False):
        y = g["yea"].to_numpy(dtype=float)
        n, ny = len(y), int(y.sum())
        minority = min(ny, n - ny)
        if n < 40 or minority < MIN_MINORITY:
            continue
        m = int(g["m"].iloc[0])
        ids = g["mid"].to_numpy()
        has_after = m + 1 + WINDOW <= last_full + 1
        lo, hi = m - WINDOW, m                      # months [m-24, m-1]
        before = CM[ids, hi, :] - CM[ids, lo, :]
        tb = CT[ids, hi] - CT[ids, lo]
        if has_after:
            after = CM[ids, m + 1 + WINDOW, :] - CM[ids, m + 1, :]
            ta = CT[ids, m + 1 + WINDOW] - CT[ids, m + 1]
        d = (g["party"].to_numpy() == "D").astype(float)
        dim1 = g["dim1"].to_numpy()
        base = [np.ones(n), dim1, dim1 * d, d, g["own_share"].to_numpy(), g["mrp"].to_numpy()]
        lg = lambda a: np.log1p(np.clip(a, 0, None) / 1000.0)       # refunds can make a window's net total negative
        Xb = lg(before)
        ctrl_b = np.column_stack(base + [lg(tb)])
        if has_after:
            Xa = lg(after)
            ctrl_j = np.column_stack(base + [lg(tb), lg(ta)])
        if shuffle:
            perm = np.arange(n)
            for p in ("D", "R"):
                ix = np.where(g["party"].to_numpy() == p)[0]
                perm[ix] = rng.permutation(ix)
            Xb, ctrl_b = Xb[perm], ctrl_b.copy()
            ctrl_b[:, 6] = ctrl_b[perm, 6]
            if has_after:
                Xa = Xa[perm]
                ctrl_j = ctrl_j.copy(); ctrl_j[:, 6] = ctrl_j[perm, 6]; ctrl_j[:, 7] = ctrl_j[perm, 7]
        try:
            s1 = stats(y, ctrl_b, Xb, None)
            sj = stats(y, ctrl_j, Xb, Xa) if has_after else {}
        except np.linalg.LinAlgError:
            continue
        df = pd.DataFrame({"label": labels, "b_only": s1["b_only"], "t_only": s1["t_only"]})
        for k in ("b_before", "t_before", "b_after", "t_after"):
            df[k] = sj[k] if has_after else np.nan
        df["congress"], df["chamber"], df["rollnumber"], df["vdate"] = cg, ch, rn, g["vdate"].iloc[0]
        df["n"], df["minority"], df["has_after"] = n, minority, has_after
        rows.append(df)
    out = pd.concat(rows, ignore_index=True)
    return out[["congress", "chamber", "rollnumber", "vdate", "label", "n", "minority", "b_only", "t_only", "b_before", "t_before", "b_after", "t_after", "has_after"]]


def summarize(real: pd.DataFrame, null: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for lab in sorted(real["label"].unique()):
        r, z = real[real["label"] == lab], null[null["label"] == lab]
        ra, za = r[r["has_after"]], z[z["has_after"]]
        rows.append({"label": lab, "votes": r["t_only"].notna().sum(),
                     "share_only": (r["t_only"].abs() > 2).mean(), "share_only_null": (z["t_only"].abs() > 2).mean(),
                     "share_before": (ra["t_before"].abs() > 2).mean(), "share_before_null": (za["t_before"].abs() > 2).mean(),
                     "share_after": (ra["t_after"].abs() > 2).mean(), "share_after_null": (za["t_after"].abs() > 2).mean()})
    return pd.DataFrame(rows)


if __name__ == "__main__":
    pd.set_option("display.width", 220)
    real = run(False)
    print("votes screened:", real[["congress", "chamber", "rollnumber"]].drop_duplicates().shape[0], "| rows:", len(real))
    nulldf = run(True, seed=1)
    con.execute("CREATE OR REPLACE TABLE all_vote_money AS SELECT * FROM real")
    con.execute("CREATE OR REPLACE TABLE all_vote_null AS SELECT * FROM nulldf")
    s = summarize(real, nulldf)
    print(s.round(3).to_string(index=False))
