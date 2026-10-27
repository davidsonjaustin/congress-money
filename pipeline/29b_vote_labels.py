"""Readable labels for amendment votes.

House: join the Clerk roll-call files (29_clerk_votes.py) to Voteview roll calls by date, bill and the Yea/Nay totals (Voteview's roll numbers are not the Clerk's),
and label the vote with who offered the amendment. Senate: Voteview already carries the amendment's purpose, so use it.

Output (analysis.duckdb): vote_label(congress, chamber, rollnumber, label), only for amendment votes since 2008, plus a printout of the match rate.
"""
import re
from pathlib import Path

import duckdb
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
clerk = pd.read_csv(ROOT / "data" / "raw" / "clerk" / "clerk_rolls.csv", dtype=str).fillna("")
clerk["date"] = pd.to_datetime(clerk["date"], format="%d-%b-%Y", errors="coerce")
clerk["bill"] = clerk["legis_num"].str.replace(r"\s+", "", regex=True).str.upper()
clerk["yea"] = pd.to_numeric(clerk["yea"], errors="coerce")
clerk["nay"] = pd.to_numeric(clerk["nay"], errors="coerce")
clerk["roll"] = clerk["roll"].astype(int)
clerk = clerk.sort_values(["year", "roll"])

con = duckdb.connect(str(ROOT / "data" / "analysis.duckdb"))
con.execute(f"ATTACH '{(ROOT / 'data' / 'congress.duckdb').as_posix()}' AS c (READ_ONLY)")
house = con.execute("""SELECT congress, rollnumber, vote_date AS date, bill_number AS bill, yea_count AS yea, nay_count AS nay
                       FROM c.rollcalls WHERE chamber = 'House' AND vote_date >= DATE '2008-01-01' AND vote_question ILIKE '%mendment%' ORDER BY congress, rollnumber""").df()

# Several amendments can share a date, bill and tally; pair them in roll order.
house["date"] = pd.to_datetime(house["date"])
house["k"] = house.groupby(["date", "bill", "yea", "nay"]).cumcount()
clerk["k"] = clerk.groupby(["date", "bill", "yea", "nay"]).cumcount()
m = house.merge(clerk[["date", "bill", "yea", "nay", "k", "roll", "amendment_num", "amendment_author", "question"]], on=["date", "bill", "yea", "nay", "k"], how="left")
# Second pass: early rolls (2008-09, a few later) differ from the Clerk's by a vote or two. Where a day's amendments to one bill have the same count on both sides, pair them in order.
used = set(zip(m.dropna(subset=["roll"])["date"], m.dropna(subset=["roll"])["bill"], m.dropna(subset=["roll"])["roll"]))
amend = clerk[clerk["question"].str.contains("mendment", na=False)]
for (d, b), g in m[m["roll"].isna()].groupby(["date", "bill"]):
    cand = amend[(amend["date"] == d) & (amend["bill"] == b)]
    cand = cand[[(d, b, r) not in used for r in cand["roll"]]].sort_values("roll")
    if len(cand) == len(g):
        for idx, (_, c) in zip(g.sort_values("rollnumber").index, cand.iterrows()):
            for col in ("roll", "amendment_num", "amendment_author", "question"):
                m.loc[idx, col] = c[col]
print(f"House amendment votes since 2008: {len(house)}, matched to a Clerk roll: {m['roll'].notna().sum()} ({100 * m['roll'].notna().mean():.1f}%)")


def label_house(r) -> str | None:
    if pd.isna(r["roll"]):
        return None
    who = re.sub(r"\s+", " ", str(r["amendment_author"] or "")).strip()
    bill = str(r["bill"])
    nice = re.sub(r"^(HR|HRES|HJRES|HCONRES)(\d+)$", lambda x: {"HR": "H.R. ", "HRES": "H.Res. ", "HJRES": "H.J.Res. ", "HCONRES": "H.Con.Res. "}[x.group(1)] + x.group(2), bill)
    if who:
        return f"Amendment to {nice} offered by {who}"
    return f"Amendment {r['amendment_num']} to {nice}" if r["amendment_num"] else None


m["label"] = m.apply(label_house, axis=1)
hl = m.dropna(subset=["label"])[["congress", "rollnumber", "label"]].assign(chamber="House")

sen = con.execute("""SELECT congress, rollnumber, bill_number AS bill, vote_desc FROM c.rollcalls
                     WHERE chamber = 'Senate' AND vote_date >= DATE '2008-01-01' AND vote_question ILIKE '%mendment%' AND vote_desc IS NOT NULL""").df()
sen["label"] = sen.apply(lambda r: f"Amendment to {r['bill']}: {str(r['vote_desc']).strip()}", axis=1)
sl = sen[["congress", "rollnumber", "label"]].assign(chamber="Senate")

out = pd.concat([hl, sl], ignore_index=True)[["congress", "chamber", "rollnumber", "label"]]
con.execute("CREATE OR REPLACE TABLE vote_label AS SELECT * FROM out")
print(len(out), "labels written;", out.groupby("chamber").size().to_dict())
print(out.sample(4, random_state=1).to_string(index=False))
