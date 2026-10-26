"""Turn interest-group scorecard positions into locked vote-direction rows.

AFL-CIO (data/raw/positions/aflcio_keyvotes.json, read from aflcio.org/scorecard/votes in the user's own browser)
  "This legislation is good/bad for working people" -> the vote that helps the Labor sector is Yea/Nay on the measure's final vote.
LCV (data/raw/positions/lcv_votes.json, read from each lcv.org roll-call-vote page)
  "Pro-environment vote: Yes/No" -> for fossil-fuel subsectors the vote that helps them is the opposite, and only for votes LCV tags
  Dirty Energy, Climate Change or Clean Air (not confirmations, not clean-energy subsidies, which the industries do not uniformly oppose).

Each position is matched to a Voteview roll call by chamber, date or number, and title text. Anything not matched confidently is written to
data/raw/positions/unmatched_*.csv for review and is NOT used. Output: pipeline/definitions/vote_direction_aflcio.csv / _lcv.csv
(evidence_level 'scorecard'), to be locked like the others before any model sees them.
"""
import datetime as dt
import json
import re
import sys
from pathlib import Path

import duckdb
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
POS = ROOT / "data" / "raw" / "positions"
DEFS = ROOT / "pipeline" / "definitions"
FINAL = re.compile(r"passage|conference report|concur|joint resolution|nomination|agreeing to the resolution|on the resolution|suspend the rules and pass|objections|ratification|motion to pass", re.I)
STOP = set("the and for act bill that this with from have been will would which their about into more than other such only also over under after before shall states state united federal congress house senate resolution joint committee amend amendment title code section".split())
BILL = re.compile(r"\b(H\.? ?R\.?|S\.?|H\.? ?J\.? ?Res\.?|S\.? ?J\.? ?Res\.?|H\.? ?Res\.?|S\.? ?Res\.?|H\.? ?Con\.? ?Res\.?|S\.? ?Con\.? ?Res\.?)\s*(\d{1,5})\b")


def bill_key(prefix: str, num: str) -> str:
    p = re.sub(r"[^A-Za-z]", "", prefix).upper()
    return f"{p}{int(num)}"


def words(s: str) -> set[str]:
    return {w for w in re.findall(r"[a-z]{4,}", (s or "").lower()) if w not in STOP}


def load_rollcalls() -> pd.DataFrame:
    con = duckdb.connect(str(ROOT / "data" / "analysis.duckdb"), read_only=True)
    con.execute(f"ATTACH '{(ROOT / 'data' / 'congress.duckdb').as_posix()}' AS c (READ_ONLY)")
    df = con.execute("""
        SELECT r.congress, r.chamber, r.rollnumber, r.vote_date, r.bill_number, r.vote_question, r.vote_desc, r.vote_result, r.yea_count, r.nay_count,
               coalesce(t.title, '') AS title
        FROM c.rollcalls r LEFT JOIN rollcall_topic t USING (congress, chamber, rollnumber)""").df()
    con.close()
    df["vote_date"] = pd.to_datetime(df["vote_date"])
    df["text_words"] = [words(f"{a} {b} {c}") for a, b, c in zip(df["vote_desc"].fillna(""), df["title"], df["bill_number"].fillna(""))]
    df["final"] = df["vote_question"].fillna("").map(lambda q: bool(FINAL.search(q)))
    return df


def match_afl(rc: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    rows = json.loads((POS / "aflcio_keyvotes.json").read_text(encoding="utf-8"))
    out, bad = [], []
    for r in rows:
        date = pd.to_datetime(r["date"], format="%b %d %Y")
        ch = r["chamber"]
        text = f"{r['title']} {r['desc']}"
        keys = {bill_key(m.group(1), m.group(2)) for m in BILL.finditer(r["title"])} or {bill_key(m.group(1), m.group(2)) for m in BILL.finditer(r["desc"])}
        w = words(re.sub(BILL, " ", r["title"])) | words(r["desc"][:200])
        is_amend = bool(re.match(r"\s*(amendment|motion)", r["title"], re.I) or re.search(r"amendment (to|#|no)", r["title"], re.I))
        best = None
        for slack in (0, 1, 2):
            cand = rc[(rc["chamber"] == ch) & ((rc["vote_date"] - date).abs() <= pd.Timedelta(days=slack))]
            if cand.empty:
                continue
            scored = []
            for _, c in cand.iterrows():
                q = (c["vote_question"] or "").lower()
                type_ok = ("amendment" in q or "motion" in q) if is_amend else bool(c["final"])
                if is_amend and "motion to table" in q:
                    type_ok = False
                key_hit = bool(keys) and (c["bill_number"] in keys)
                ov = len(w & c["text_words"]) / max(1, min(len(w), len(c["text_words"])))
                score = (2.0 if key_hit else 0.0) + ov + (0.25 if type_ok else -0.5)
                scored.append((score, key_hit, ov, c, type_ok))
            scored.sort(key=lambda x: -x[0])
            s0, kh, ov, c, type_ok = scored[0]
            # a bill-number hit on a final vote, or strong title overlap; amendments need strong overlap (their text is rarely in the roll call)
            if type_ok and ((kh and not is_amend) or ov >= (0.6 if is_amend else 0.5) or (kh and ov >= 0.25)):
                best = (s0, kh, ov, c, slack)
                break
        rec = {"year": r["year"], "chamber": ch, "date": r["date"], "title": r["title"], "position": r["position"], "href": r["href"]}
        if best is None:
            bad.append(rec)
            continue
        s, kh, ov, c, slack = best
        helps = "Yea" if "good" in r["position"] else "Nay"
        out.append({"congress": int(c["congress"]), "chamber": ch, "rollnumber": int(c["rollnumber"]), "bill": c["bill_number"] or "", "date": c["vote_date"].strftime("%Y-%m-%d"),
                    "sector": "Labor", "subsector": "", "helps_vote": helps, "evidence_level": "scorecard",
                    "evidence": f"AFL-CIO scorecard: {r['position'].replace('This legislation is ', '')} ({r['title'][:70]})",
                    "source_url": "https://aflcio.org" + r["href"], "_score": round(s, 2), "_vote": f"{c['vote_question']} | {c['vote_result']} {c['yea_count']}-{c['nay_count']}"})
    return pd.DataFrame(out), pd.DataFrame(bad)


LCV_TAGS = ["Public Engagement & Right to Know", "Public Lands & Oceans", "Environmental Justice", "Climate Change", "Clean Energy", "Dirty Energy", "Confirmations",
            "Appropriations", "Agriculture", "Transportation", "Clean Water", "Clean Air", "Wildlife", "Toxics", "Other"]
LABOR_WORDS = re.compile(r"union|collective bargaining|labor|worker|wage|overtime|pension|nlrb|osha|workplace|apprentice|right.to.work|davis-bacon|strike|employee|employer|sick leave|paid leave|unemployment|prevailing|picket|organiz|bargaining|workforce|labor secretary|retirement", re.I)
FOSSIL_TAGS = {"Dirty Energy", "Climate Change", "Clean Air"}
NOISE_WORDS = re.compile(r"nuclear|ethanol|biofuel|biodiesel|uranium|default on america|environmental justice|hardrock|retirement|contractor|data center|marine mammal|bristol bay|delaware river|national forest|permission to pollute|clean water|waters|gulf oil spill|military", re.I)
FOSSIL_WORDS = re.compile(r"drill|oil|gas|coal|pipeline|keystone|carbon|power plant|methane|fracking|refiner|arctic|anwr|offshore|fuel|royalt|mining|stream|clean power|greenhouse|emission|ozone|mercury|cross-state|coal ash|tar sands|fossil|renewable fuel|energy tax|subsid", re.I)


def parse_tags(issues: str) -> list[str]:
    """Issue tags come first in the page text, then the description; consume known tags from the front."""
    s = (issues or "").strip()
    tags = []
    while True:
        for t in LCV_TAGS:
            if s.startswith(t):
                tags.append(t)
                s = s[len(t):].strip()
                break
        else:
            return tags


def match_lcv(rc: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    items = json.loads((POS / "lcv_votes.txt").read_text(encoding="utf-8"))
    rc = rc.copy()
    rc["year"] = rc["vote_date"].dt.year
    first_max = {}
    for (c, ch), g in rc.groupby(["congress", "chamber"]):
        first_year = 1789 + 2 * (c - 1)
        first_max[(c, ch)] = int(g.loc[g["year"] == first_year, "rollnumber"].max()) if (g["year"] == first_year).any() else 0
    idx = rc.set_index(["congress", "chamber", "rollnumber"])
    out, bad = [], []
    for it in items:
        if not it.get("scorecard") or it.get("roll") is None or it.get("chamber") is None:
            bad.append({"title": it.get("title"), "why": "not a scorecard vote or no roll number"}); continue
        y, ch, roll = int(it["year"]), it["chamber"], int(it["roll"])
        c = (y - 1789) // 2 + 1
        sess2 = (y - 1789) % 2 == 1
        expected = roll + (first_max.get((c, ch), 0) if sess2 else 0)
        # LCV's House roll numbers do not line up with Voteview's (an audit found 128 of 130 House matches wrong when matched by number alone),
        # so match on the vote TALLY LCV prints for each vote: same Congress, chamber and year, same Yea and Nay counts, nearest to the expected number.
        yes, no = it.get("yes"), it.get("no")
        cand = rc[(rc["congress"] == c) & (rc["chamber"] == ch) & (rc["year"] == y) & (rc["yea_count"] == yes) & (rc["nay_count"] == no)]
        if cand.empty:
            bad.append({"title": it["title"], "why": f"no roll call with tally {yes}-{no} in {y}"}); continue
        cand = cand.assign(dist=(cand["rollnumber"] - expected).abs()).sort_values("dist")
        if int(cand.iloc[0]["dist"]) > 40:
            bad.append({"title": it["title"], "why": f"tally {yes}-{no} found only far from expected roll {expected}"}); continue
        r = cand.iloc[0]
        vv = int(r["rollnumber"])
        tags = parse_tags(it.get("issues", ""))
        ov = len(words(it["title"] + " " + it.get("desc", "")[:200]) & r["text_words"]) / max(1, min(len(words(it["title"])), len(r["text_words"])))
        rec = {"year": y, "chamber": ch, "roll": roll, "vv": vv, "title": it["title"], "proEnv": it.get("proEnv"), "tags": "|".join(tags), "overlap": round(ov, 2),
               "vote": f"{r['vote_question']} {r['yea_count']}-{r['nay_count']}", "bill": r["bill_number"], "date": r["vote_date"].strftime("%Y-%m-%d")}
        relevant = ("Dirty Energy" in tags) or (bool({"Climate Change", "Clean Air"} & set(tags)) and bool(FOSSIL_WORDS.search(it["title"])))
        if relevant and NOISE_WORDS.search(it["title"]):
            relevant = False
        if (not relevant) or "Confirmations" in tags or re.search(r"confirmation|nomination", it["title"], re.I) or it.get("proEnv") not in ("Yes", "No"):
            rec["used"] = False
            bad.append({**rec, "why": "not a fossil-fuel-relevant LCV tag"}); continue
        helps = "Yea" if it["proEnv"] == "No" else "Nay"
        for sub in ("oil_gas", "coal_mining"):
            out.append({"congress": int(c), "chamber": ch, "rollnumber": int(vv), "bill": r["bill_number"] or "", "date": rec["date"], "sector": "Energy & Natural Resources",
                        "subsector": sub, "helps_vote": helps, "evidence_level": "scorecard",
                        "evidence": f"LCV scorecard: pro-environment vote is {it['proEnv']} on '{it['title'][:60]}' ({', '.join(t for t in tags if t in FOSSIL_TAGS)}), so the fossil-fuel side is {helps}",
                        "source_url": it["url"], "_overlap": rec["overlap"], "_vote": rec["vote"], "_title": it["title"]})
    return pd.DataFrame(out), pd.DataFrame(bad)


if __name__ == "__main__":
    rc = load_rollcalls()
    what = sys.argv[1] if len(sys.argv) > 1 else "afl"
    if what == "afl":
        ok, bad = match_afl(rc)
        ok = ok.drop_duplicates(["congress", "chamber", "rollnumber"])
        titles = {r["href"]: r["title"] + " " + r["desc"] for r in json.loads((POS / "aflcio_keyvotes.json").read_text(encoding="utf-8"))}
        ok["_text"] = ok["source_url"].map(lambda u: titles.get(u.replace("https://aflcio.org", ""), ""))
        keep = ok["_text"].map(lambda t: bool(LABOR_WORDS.search(t)))
        print(f"labor-relevance filter keeps {int(keep.sum())} of {len(ok)}; dropped examples:")
        print(ok.loc[~keep, "evidence"].str.slice(0, 110).sample(min(12, int((~keep).sum())), random_state=1).to_string(index=False))
        ok = ok[keep].drop(columns=["_text"])
        print(f"AFL-CIO key votes matched to a roll call: {len(ok)} of {len(ok) + len(bad)}")
        bad.to_csv(POS / "unmatched_aflcio.csv", index=False)
        ok.drop(columns=["_score", "_vote"]).to_csv(DEFS / "vote_direction_aflcio.csv", index=False)
        pd.set_option("display.width", 250); pd.set_option("display.max_colwidth", 70)
        print(ok.sample(20, random_state=3)[["congress", "chamber", "rollnumber", "date", "helps_vote", "_score", "evidence", "_vote"]].to_string(index=False))
        print("\nunmatched sample:\n", bad.head(12)[["year", "chamber", "date", "title"]].to_string(index=False))

    if what == "lcv":
        ok, bad = match_lcv(rc)
        pd.set_option("display.width", 250); pd.set_option("display.max_colwidth", 80)
        print(f"LCV fossil-relevant votes matched: {len(ok) // 2}; set aside / unmatched: {len(bad)}")
        if len(bad):
            print(bad.get("why", pd.Series(dtype=str)).value_counts().head(8).to_string())
        bad.to_csv(POS / "unmatched_lcv.csv", index=False)
        ok1 = ok[ok["subsector"] == "oil_gas"]
        print("low-overlap matches (check these):", ok1[ok1["_overlap"] < 0.1][["congress", "chamber", "rollnumber", "date", "_title", "_vote"]].head(15).to_string(index=False))
        print("sample:", ok1.sample(min(15, len(ok1)), random_state=2)[["congress", "chamber", "rollnumber", "date", "helps_vote", "_title", "_vote"]].to_string(index=False))
        ok.drop(columns=["_overlap", "_vote", "_title"]).to_csv(DEFS / "vote_direction_lcv.csv", index=False)
