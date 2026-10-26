"""Revealed-interest check: whom does a PAC fund, relative to whom each sector's PACs fund?

For PAC T and sector S:  score = cosine(v_T - m, c_S - m)
  v_T = T's giving spread across members (rows normalised to sum 1, 24K direct contributions, 2005-now)
  c_S = mean of the normalised vectors of the other PACs in S
  m   = mean vector over ALL business PACs -> removes the generic "business funds incumbents/majority" pattern
Calibration: the same score for PACs already confidently in each sector, scored against their own sector.
"""
import sys
import time
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "congress.duckdb"
MIN_TOTAL = 50_000
EXCLUDED = ("Conduit (excluded)", "Candidate committee", "Party committee", "Leadership PAC", "Joint fundraising",
            "Unclassified", "Business (sector not yet assigned)", "Ideological / Single-Issue / Unsorted",
            "Caucus & Party-Aligned PACs", "Ideological / Single-Issue")
TARGETS = {"C00334581": "Komatsu Mining", "C00014555": "FMI (food retail trade group)",
           "C00148031": "Caterpillar", "C00204099": "Deere & Co"}
SHOW = ["Energy & Natural Resources", "Manufacturing & Industrial", "Construction", "Agribusiness & Food",
        "Retail & Consumer", "Transportation", "Finance, Insurance & Real Estate", "Health", "Labor"]


def connect() -> duckdb.DuckDBPyConnection:
    for _ in range(60):
        try:
            return duckdb.connect(str(DB), read_only=True)
        except duckdb.IOException:
            time.sleep(10)  # classifier rerun holds the write lock for a few minutes
    sys.exit("database stayed locked")


def cosine(a: np.ndarray, b: np.ndarray) -> float:
    d = np.linalg.norm(a) * np.linalg.norm(b)
    return float(a @ b / d) if d else float("nan")


def main() -> None:
    con = connect()
    ex = ",".join(f"'{s}'" for s in EXCLUDED)
    df = con.execute(f"""
        SELECT p.CMTE_ID AS cmte, s.sector, x.bioguide, sum(TRY_CAST(p.TRANSACTION_AMT AS DOUBLE)) AS amt
        FROM fec_pas2 p
        JOIN committee_sector s ON s.cmte_id = p.CMTE_ID
        JOIN (SELECT DISTINCT fec_id, bioguide FROM id_crosswalk WHERE fec_id IS NOT NULL) x ON x.fec_id = p.CAND_ID
        WHERE p.TRANSACTION_TP = '24K' AND s.sector NOT IN ({ex})
        GROUP BY ALL HAVING sum(TRY_CAST(p.TRANSACTION_AMT AS DOUBLE)) > 0""").df()
    sector_of = df.drop_duplicates("cmte").set_index("cmte")["sector"]
    mat = df.pivot_table(index="cmte", columns="bioguide", values="amt", aggfunc="sum", fill_value=0.0)
    mat = mat[mat.sum(axis=1) >= MIN_TOTAL]
    mat = mat.div(mat.sum(axis=1), axis=0)
    sec = sector_of.reindex(mat.index)
    m = mat.mean(axis=0).to_numpy()
    print(f"{len(mat)} PACs with >= ${MIN_TOTAL:,} to {mat.shape[1]} members\n")

    def score(cmte: str, sector: str) -> float:
        others = mat[(sec == sector) & (mat.index != cmte)]
        if len(others) < 5:
            return float("nan")
        return cosine(mat.loc[cmte].to_numpy() - m, others.mean(axis=0).to_numpy() - m)

    # Calibration: how well do PACs fit their OWN sector vs the other sectors? (sampled, fixed seed)
    rng = np.random.default_rng(7)
    print("Calibration (median score of sector members against own sector | against all other shown sectors):")
    for s in SHOW:
        members = list(mat.index[sec == s])
        if len(members) < 10:
            continue
        pick = rng.choice(members, size=min(60, len(members)), replace=False)
        own = [score(c, s) for c in pick]
        oth = [score(c, o) for c in pick for o in SHOW if o != s]
        print(f"  {s:34s} own {np.nanmedian(own):5.2f} | others {np.nanmedian(oth):5.2f}   (n={len(members)} PACs)")

    print("\nTarget PACs: revealed-interest score against each sector (higher = funds the same members, beyond the generic business pattern)")
    print(f"  {'':30s}" + "".join(f"{s.split(',')[0].split(' &')[0][:10]:>11s}" for s in SHOW))
    for cid, label in TARGETS.items():
        if cid not in mat.index:
            print(f"  {label}: below ${MIN_TOTAL:,} threshold or missing")
            continue
        vals = [score(cid, s) for s in SHOW]
        print(f"  {label:30s}" + "".join(f"{v:11.2f}" for v in vals) + f"   [labelled: {sector_of[cid]}]")


if __name__ == "__main__":
    main()
