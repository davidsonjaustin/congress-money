"""Did members vote the way the donors behind them wanted?

For every direction-coded vote (pipeline/definitions/vote_direction.csv: which way helps which donor sector) and every
member who cast it, record
  aligned    1 if the member voted the way that helps the sector, else 0
  pac_6y     direct PAC gifts from that sector (or subsector) in the 6 years BEFORE the vote
  pac_2y     same, last 2 years only
  share_6y   pac_6y as a share of all the member's PAC gifts in the same window (how much they lean on that sector)
Output: analysis.duckdb.vote_direction, pac_sub_weekly, donor_alignment

Then two descriptive looks, no causal claim:
  A. aligned share by how much sector money the member had received, split by party
  B. linear model: aligned ~ log(sector money), with a fixed effect for every roll call x party (so it compares members of
     the SAME party on the SAME vote) plus ideology and district lean as controls, standard errors clustered by member.
Money follows ideology, so B can still overstate any effect of money; it is a first filter, not a verdict.
"""
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
con = duckdb.connect(str(ROOT / "data" / "analysis.duckdb"))
con.execute(f"ATTACH '{(ROOT / 'data' / 'congress.duckdb').as_posix()}' AS c (READ_ONLY)")


def build() -> None:
    files = sorted((ROOT / "pipeline" / "definitions").glob("vote_direction*.csv"))
    d = pd.concat([pd.read_csv(f, keep_default_na=False, dtype=str) for f in files], ignore_index=True)
    d["congress"], d["rollnumber"] = d["congress"].astype(int), d["rollnumber"].astype(int)
    d = d.drop_duplicates(["congress", "chamber", "rollnumber", "sector", "subsector"])
    d["date"] = pd.to_datetime(d["date"]).dt.date
    d["subsector"] = d["subsector"].fillna("")
    con.execute("CREATE OR REPLACE TABLE vote_direction AS SELECT * FROM d")

    # direct PAC gifts (FEC 24K) by member, week, sector and subsector ('' where the sector is not split)
    con.execute("""
    CREATE OR REPLACE TABLE pac_sub_weekly AS
    WITH xw AS (SELECT DISTINCT fec_id, bioguide FROM c.id_crosswalk WHERE fec_id IS NOT NULL)
    SELECT xw.bioguide, date_trunc('week', TRY_STRPTIME(p.TRANSACTION_DT, '%m%d%Y'))::DATE AS week,
           s.sector, coalesce(sub.subsector, '') AS subsector, sum(TRY_CAST(p.TRANSACTION_AMT AS DOUBLE)) AS amount
    FROM c.fec_pas2 p
    JOIN xw ON xw.fec_id = p.CAND_ID
    JOIN c.committee_sector s ON s.cmte_id = p.CMTE_ID
    LEFT JOIN committee_subsector sub ON sub.cmte_id = p.CMTE_ID
    WHERE p.TRANSACTION_TP = '24K'
      AND TRY_STRPTIME(p.TRANSACTION_DT, '%m%d%Y') BETWEEN DATE '2000-01-01' AND DATE '2026-12-31'
    GROUP BY ALL""")

    con.execute("""
    CREATE OR REPLACE TABLE donor_alignment AS
    WITH mv AS (
        SELECT v.rc, v.congress, v.chamber, v.rollnumber, v.bioguide, v.party, v.state, v.district, v.yea, v.nominate_dim1, v.own_share,
               d.bill, d.date AS vdate, d.sector, d.subsector, d.helps_vote, d.evidence_level
        FROM member_vote v
        JOIN vote_direction d ON d.congress = v.congress AND d.chamber = v.chamber AND d.rollnumber = v.rollnumber
        WHERE v.party IN ('D', 'R')),
    m AS (
        SELECT mv.rc, mv.bioguide, mv.sector, mv.subsector,
               coalesce(sum(w.amount) FILTER (WHERE w.week >= mv.vdate - INTERVAL 6 YEAR AND w.week < mv.vdate), 0) AS pac_6y,
               coalesce(sum(w.amount) FILTER (WHERE w.week >= mv.vdate - INTERVAL 2 YEAR AND w.week < mv.vdate), 0) AS pac_2y,
               coalesce(sum(w.amount) FILTER (WHERE w.week >= mv.vdate AND w.week < mv.vdate + INTERVAL 2 YEAR), 0) AS pac_f2y
        FROM mv LEFT JOIN pac_sub_weekly w
          ON w.bioguide = mv.bioguide AND w.sector = mv.sector AND (mv.subsector = '' OR w.subsector = mv.subsector)
        GROUP BY ALL),
    tot AS (
        SELECT mv.rc, mv.bioguide, mv.sector, mv.subsector,
               coalesce(sum(w.amount) FILTER (WHERE w.week >= mv.vdate - INTERVAL 6 YEAR AND w.week < mv.vdate), 0) AS pac_total_6y
        FROM mv LEFT JOIN pac_sub_weekly w ON w.bioguide = mv.bioguide
        GROUP BY ALL)
    SELECT mv.*, ((mv.yea = 1 AND mv.helps_vote = 'Yea') OR (mv.yea = 0 AND mv.helps_vote = 'Nay'))::INT AS aligned,
           m.pac_6y, m.pac_2y, m.pac_f2y, tot.pac_total_6y, CASE WHEN tot.pac_total_6y > 0 THEN m.pac_6y / tot.pac_total_6y END AS share_6y,
           coalesce(ls.z, 0) AS local_z, ls.share AS local_share
    FROM mv JOIN m USING (rc, bioguide, sector, subsector) JOIN tot USING (rc, bioguide, sector, subsector)
    LEFT JOIN local_stake ls ON ls.state = mv.state AND ls.year = least(year(mv.vdate), 2026)
         AND ls.subsector = CASE WHEN mv.sector = 'Labor' THEN 'Labor' WHEN mv.subsector <> '' THEN mv.subsector
                                 WHEN mv.sector = 'Defense & Aerospace' THEN 'Defense contracts' WHEN mv.sector = 'Tech, Telecom & Media' THEN 'Tech'
                                 WHEN mv.sector = 'Retail & Consumer' THEN 'Retail' ELSE mv.sector END""")


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
    return beta, np.sqrt(np.diag(v)), len(d), len(s)


def lpm_fe2(df: pd.DataFrame, y: str, xs: list[str], fes: list[str], cluster: str):
    """Same model with several sets of fixed effects, swept out by alternating demeaning."""
    d = df[[y] + xs + fes + [cluster]].dropna().reset_index(drop=True)
    cols = [y] + xs
    M = d[cols].astype(float).copy()
    for _ in range(40):
        before = M.to_numpy().copy()
        for f in fes:
            M = M - M.groupby(d[f]).transform("mean")
        if np.abs(M.to_numpy() - before).max() < 1e-9:
            break
    yv = M[y].to_numpy()
    X = M[xs].to_numpy()
    xtx = X.T @ X
    beta = np.linalg.solve(xtx, X.T @ yv)
    e = yv - X @ beta
    s = pd.DataFrame(X * e[:, None]).groupby(d[cluster].to_numpy()).sum().to_numpy()
    inv = np.linalg.inv(xtx)
    v = inv @ (s.T @ s) @ inv * (len(s) / (len(s) - 1))
    return beta, np.sqrt(np.diag(v)), len(d), len(s)


def report() -> None:
    df = con.execute("SELECT * FROM donor_alignment").df()
    df["group"] = df["sector"].str[:10] + "/" + df["subsector"].replace("", "all")
    print(f"\ndonor_alignment: {len(df):,} member-votes, {df['rc'].nunique()} votes, {df['bioguide'].nunique()} members")

    print("\n=== A. Share of members who voted the donors' way, by how much sector money they had received (6 years before the vote) ===")
    bins = [-0.1, 0, 10_000, 50_000, 200_000, 1e12]
    labels = ["$0", "<$10K", "$10-50K", "$50-200K", "$200K+"]
    df["bin"] = pd.cut(df["pac_6y"], bins=bins, labels=labels)
    for grp, g in df.groupby("group"):
        nv = g["rc"].nunique()
        line = [f"{grp:28s} {nv:>2} votes, all members {100 * g['aligned'].mean():4.0f}% aligned |"]
        for p in ("R", "D"):
            gp = g[g["party"] == p]
            cells = []
            for lab in labels:
                x = gp[gp["bin"] == lab]
                cells.append(f"{100 * x['aligned'].mean():3.0f}%({len(x):>4})" if len(x) >= 15 else "    –     ")
            line.append(f"{p}: " + " ".join(cells) + " |")
        print(" ".join(line))
    print(f"{'':28s} {'':26s} bins: " + "  ".join(labels) + "   (n member-votes in brackets; needs >= 15)")

    print("\n=== B. Same party, same vote: does more sector money go with voting the donors' way? ===")
    print("effect = change in percentage points in the chance of voting the donors' way when sector money goes from $0 to $50K (6 yrs); se clustered by member")
    df["lg"] = np.log1p(df["pac_6y"].clip(lower=0) / 1000.0)                      # net refunds can make a window negative
    df["lg_other"] = np.log1p((df["pac_total_6y"] - df["pac_6y"]).clip(lower=0) / 1000.0)   # all OTHER PAC money: overall fundraising size
    df["fe"] = df["rc"].astype(str) + "|" + df["sector"] + "|" + df["subsector"] + "|" + df["party"]   # one baseline per vote, sector and party
    df["aligned_f"] = df["aligned"].astype(float)
    scale = float(np.log1p(50.0))
    def run(sub: pd.DataFrame, label: str) -> None:
        if sub["rc"].nunique() < 1 or len(sub) < 200 or sub["lg"].nunique() < 3:
            print(f"  {label:26s} too little variation"); return
        out = []
        for xs, fes in ((["lg"], ["fe"]), (["lg", "nominate_dim1", "own_share"], ["fe"]), (["lg", "lg_other", "nominate_dim1", "own_share"], ["fe"]),
                        (["lg", "nominate_dim1", "own_share"], ["fe", "state"])):
            try:
                b, se, n, g = lpm_fe2(sub, "aligned_f", xs, fes, "bioguide")
                out.append(f"{b[0] * scale * 100:+5.1f} (se {se[0] * scale * 100:4.1f})")
            except np.linalg.LinAlgError:
                out.append("  singular    ")
        print(f"  {label:26s} votes {sub['rc'].nunique():>2} n={len(sub):>5} | money only {out[0]} | +ideology,district {out[1]} | +other-PAC size {out[2]} | +state effects {out[3]}")
    run(df, "ALL coded votes")
    run(df[df["evidence_level"] == "documented"], "documented direction only")
    for grp, g in df.groupby("group"):
        run(g, grp)
    for ch in ("House", "Senate"):
        run(df[df["chamber"] == ch], f"all, {ch} only")


if __name__ == "__main__":
    build()
    report()
