"""Member-level rows from the every-vote screen: on votes where an industry's money lines up strongly with how members voted, who went with the money?

A vote counts for an industry only if the screen (20_all_votes_money.py) found a strong link, stronger than 99.9% of what shuffled money produces
(|t| >= 3.13). The side the industry's money pulls toward is then the side we treat as the industry's side. That is an inference from the money
pattern, not a statement by the industry, so these rows are tagged evidence_level = 'inferred' and kept apart from the sourced votes.

To keep a member from deciding their own score:
  * members are split into 5 folds within party; the pull direction used for a member's fold is estimated only from the other four folds;
  * the chance a member would have voted that way anyway comes from a model fitted on the other four folds that uses only ideology (by party),
    party, district lean, district ideology, overall fundraising and the weight of the industry in the member's state economy, never the industry's money.
A member counts as 'aligned' if they voted the way the money pulls. p_exp is the model's chance they would have anyway.

Output (analysis.duckdb): inferred_alignment (same shape as donor_alignment's scoring columns), inferred_votes (the votes and pull direction used).
16_scores.py then ranks members on these rows as the 'inferred' evidence variant.
"""
import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd

_spec = importlib.util.spec_from_file_location("a20", Path(__file__).with_name("20_all_votes_money.py"))
a20 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(a20)
con = a20.con

NOT_INDUSTRY = ("Candidate committee", "Leadership PAC", "Ideological / Single-Issue / Unsorted", "Business (sector not yet assigned)")
T_STRONG = 3.13          # 99.9th percentile of |t| with shuffled money (see all_vote_null)
FOLDS = 5


def main() -> None:
    mid, labels, M, TOT, last_full = a20.build_money()
    CM, CT = a20.cum(M), a20.cum(TOT)
    lab_ix = {l: i for i, l in enumerate(labels)}
    thr = float(con.execute("SELECT quantile_cont(abs(t_only), 0.999) FROM all_vote_null").fetchone()[0])
    strong = con.execute(f"""SELECT congress, chamber, rollnumber, label, b_only, t_only FROM all_vote_money
                             WHERE abs(t_only) >= {thr} AND label NOT IN {NOT_INDUSTRY}""").df()
    print(f"strong links: {len(strong):,} across {strong[['congress','chamber','rollnumber']].drop_duplicates().shape[0]:,} votes (|t| >= {thr:.2f})")
    mv = con.execute(f"""
        SELECT v.congress, v.chamber, v.rollnumber, v.rc, r.vote_date AS vdate, v.bioguide, v.party, v.state, v.nominate_dim1 AS dim1, v.own_share, v.mrp_ideology AS mrp, v.yea
        FROM member_vote v JOIN c.rollcalls r USING (congress, chamber, rollnumber)
        WHERE r.vote_date >= DATE '{a20.START}' AND v.yea IN (0, 1) AND v.party IN ('D', 'R')""").df()
    keys = strong[["congress", "chamber", "rollnumber"]].drop_duplicates()
    mv = mv.merge(keys, on=["congress", "chamber", "rollnumber"])
    mv["vdate"] = pd.to_datetime(mv["vdate"])
    mv["mid"] = mv["bioguide"].map(mid)
    mv["m"] = a20.month_index(mv["vdate"])
    mv = mv.dropna(subset=["dim1", "own_share", "mrp"])
    sg = {k: g for k, g in strong.groupby(["congress", "chamber", "rollnumber"])}
    lg = lambda a: np.log1p(np.clip(a, 0, None) / 1000.0)
    lzmap = a20.local_lookup(labels)
    zero = np.zeros(len(labels))
    rng = np.random.default_rng(7)
    out = []
    for (cg, ch, rn), g in mv.groupby(["congress", "chamber", "rollnumber"], sort=False):
        y = g["yea"].to_numpy(dtype=float)
        n = len(y)
        m = int(g["m"].iloc[0])
        ids = g["mid"].to_numpy()
        d = (g["party"].to_numpy() == "D").astype(float)
        dim1 = g["dim1"].to_numpy()
        tb = CT[ids, m] - CT[ids, m - a20.WINDOW]
        C = np.column_stack([np.ones(n), dim1, dim1 * d, d, g["own_share"].to_numpy(), g["mrp"].to_numpy(), lg(tb)])
        fold = np.zeros(n, dtype=int)
        for p in ("D", "R"):
            ix = np.where(g["party"].to_numpy() == p)[0]
            fold[rng.permutation(ix)] = np.arange(len(ix)) % FOLDS
        for _, row in sg[(cg, ch, rn)].iterrows():
            j = lab_ix[row["label"]]
            x = lg(CM[ids, m, j] - CM[ids, m - a20.WINDOW, j])
            lzj = np.array([lzmap.get((st_, int(g['vdate'].iloc[0].year)), zero)[j] for st_ in g['state']])
            Cj = np.column_stack([C, lzj])                      # the industry's weight in the member's state is a legitimate reason to vote with it
            m6 = np.clip(CM[ids, m, j] - CM[ids, m - 72, j], 0, None)
            aligned = np.zeros(n)
            pexp = np.zeros(n)
            sign = np.zeros(n)
            for f in range(FOLDS):
                tr, te = fold != f, fold == f
                if te.sum() == 0:
                    continue
                b0 = np.linalg.lstsq(Cj[tr], y[tr], rcond=None)[0]
                bj = np.linalg.lstsq(np.column_stack([Cj[tr], x[tr]]), y[tr], rcond=None)[0][-1]
                s = 1.0 if bj > 0 else -1.0
                p0 = np.clip(Cj[te] @ b0, 0.02, 0.98)
                sign[te] = s
                pexp[te] = np.where(s > 0, p0, 1 - p0)
                aligned[te] = np.where(s > 0, y[te] == 1, y[te] == 0)
            keep = m6 > 0
            out.append(pd.DataFrame({
                "congress": cg, "chamber": ch, "rollnumber": rn, "rc": g["rc"].to_numpy()[keep], "bioguide": g["bioguide"].to_numpy()[keep], "party": g["party"].to_numpy()[keep],
                "label": row["label"], "sector": "Labor" if row["label"] == "Labor" else "Business", "subsector": "", "aligned": aligned[keep].astype(int),
                "p_exp": np.clip(pexp[keep], 0.02, 0.98), "pac_6y": m6[keep], "pull_yea": (sign[keep] > 0).astype(int), "t_only": row["t_only"], "evidence_level": "inferred"}))
    ia = pd.concat(out, ignore_index=True)
    iv = strong.assign(pull_toward=np.where(strong["b_only"] > 0, "Yea", "Nay"))
    con.execute("CREATE OR REPLACE TABLE inferred_alignment AS SELECT * FROM ia")
    con.execute("CREATE OR REPLACE TABLE inferred_votes AS SELECT * FROM iv")
    f = ia[ia["pac_6y"] >= 10_000]
    print(f"rows: {len(ia):,} | funded (>= $10K in 6y): {len(f):,} | aligned share among funded {f['aligned'].mean():.3f} vs expected {f['p_exp'].mean():.3f}")
    print(f.groupby("label").agg(rows=("aligned", "size"), aligned=("aligned", "mean"), expected=("p_exp", "mean")).round(3).to_string())


if __name__ == "__main__":
    main()
