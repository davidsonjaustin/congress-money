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


def batch_ols(D: np.ndarray, ry: np.ndarray, kc: int):
    """OLS of ry on each label's regressors D[l] (n x k), with heteroskedasticity-robust (HC1-style) standard errors. Returns beta (L x k), t (L x k)."""
    L, n, k = D.shape
    G = np.einsum("lnk,lnm->lkm", D, D)
    ok = G[:, 0, 0] > 1e-9
    Gi = np.linalg.inv(G + 1e-9 * np.eye(k)[None])
    beta = np.einsum("lkm,lm->lk", Gi, np.einsum("lnk,n->lk", D, ry))
    e = ry[None, :] - np.einsum("lnk,lk->ln", D, beta)
    meat = np.einsum("lnk,ln,lnm->lkm", D, e * e, D) * (n / max(n - kc - k, 1))
    V = Gi @ meat @ Gi
    se = np.sqrt(np.clip(np.einsum("lkk->lk", V), 0, None))
    t = beta / se
    beta[~ok], t[~ok] = np.nan, np.nan
    return beta, t


def stats(y, ctrl, Xb, Xa, Lz):
    """Per-label slopes of y on the money columns after partialling out ctrl and the label's own local-industry stake (Lz, n x L)."""
    Q, _ = np.linalg.qr(ctrl)
    ry = y - Q @ (Q.T @ y)
    Zb, ZL = resid(Q, Xb), resid(Q, Lz)
    kc = ctrl.shape[1]
    b1, t1 = batch_ols(np.stack([Zb, ZL], axis=2).transpose(1, 0, 2), ry, kc)
    out = {"b_only": b1[:, 0] * SCALE, "t_only": t1[:, 0]}
    if Xa is not None:
        Za = resid(Q, Xa)
        b2, t2 = batch_ols(np.stack([Zb, Za, ZL], axis=2).transpose(1, 0, 2), ry, kc)
        out.update({"b_before": b2[:, 0] * SCALE, "t_before": t2[:, 0], "b_after": b2[:, 1] * SCALE, "t_after": t2[:, 1]})
    return out


LOCAL_KEY = {"oil gas": "oil_gas", "coal mining": "coal_mining", "electric utilities": "electric_utilities", "banks": "banks", "pharma": "pharma",
             "physicians clinicians": "physicians_clinicians", "insurance": "insurance", "Labor": "Labor", "Defense & Aerospace": "Defense contracts",
             "Agribusiness & Food": "Agribusiness & Food", "Tech": "Tech", "Transportation": "Transportation", "Construction": "Construction", "Retail": "Retail"}


def local_lookup(labels: list[str]) -> dict:
    """(state, year) -> vector over labels of that industry's z-scored weight in the state's economy (0 when we have no measure)."""
    ls = con.execute("SELECT state, year, subsector, z FROM local_stake").df()
    piv = ls.pivot_table(index=["state", "year"], columns="subsector", values="z")
    out = {}
    for key, row in piv.iterrows():
        out[key] = np.array([row.get(LOCAL_KEY.get(l, ""), 0.0) if LOCAL_KEY.get(l) else 0.0 for l in labels], dtype=float)
    return {k: np.nan_to_num(v, nan=0.0) for k, v in out.items()}


def run(shuffle: bool, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    mid, labels, M, TOT, last_full = build_money()
    CM, CT = cum(M), cum(TOT)
    mv = con.execute(f"""
        SELECT v.congress, v.chamber, v.rollnumber, r.vote_date AS vdate, v.bioguide, v.party, v.state, v.nominate_dim1 AS dim1, v.own_share, v.mrp_ideology AS mrp, v.yea
        FROM member_vote v JOIN c.rollcalls r USING (congress, chamber, rollnumber)
        WHERE r.vote_date >= DATE '{START}' AND v.yea IN (0, 1) AND v.party IN ('D', 'R')""").df()
    mv["vdate"] = pd.to_datetime(mv["vdate"])
    mv["mid"] = mv["bioguide"].map(mid)
    mv["m"] = month_index(mv["vdate"])
    mv = mv.dropna(subset=["dim1", "own_share", "mrp"])
    rows = []
    L = len(labels)
    lzmap = local_lookup(labels)
    zero = np.zeros(L)
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
        Lz = np.array([lzmap.get((st_, int(g['vdate'].iloc[0].year)), zero) for st_ in g['state']])
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
            s1 = stats(y, ctrl_b, Xb, None, Lz)
            sj = stats(y, ctrl_j, Xb, Xa, Lz) if has_after else {}
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
