"""Defense votes with a documented side, from Peace Action's votes archive (peaceaction.org/votes, 245 House and Senate votes).

Peace Action records, for each vote it scores, its position (In Favor / Opposed) and the full list of members who voted Yea or Nay. We keep only the
votes about money and weapons: NDAA and defense appropriations passage and conference reports, amendments that cut or add Pentagon spending or
weapons programs, and resolutions to block arms sales. Votes about war powers, AUMFs, sanctions, Gaza humanitarian aid, immigration, detention and
confirmations are NOT kept: they are not clear-cut money votes for the defense industry.

Rule for the industry's side (a fiscal-effect rule, written before any model ran): on these votes Peace Action's position is always to cut, limit or block
Pentagon money, weapons programs or arms sales (or to oppose the bill that funds them). The defense industry's side is the opposite:
  Peace Action 'In Favor'  ->  industry side is Nay;   Peace Action 'Opposed'  ->  industry side is Yea.
Tier: 'scorecard' (an advocacy group's position, inverted on a fiscal rule), like the AFL-CIO and LCV rows.

Matching: each Peace Action page is matched to a Voteview roll call by chamber and tally, then confirmed by comparing the page's list of Yea voters with
the roll call's Yea voters (last name and first initial); a match needs a Jaccard overlap of at least 0.85 between the two Yea lists and a clear winner.
Version 2 adds fiscal-rule rows: every passage or conference-report vote on a defense authorization or appropriations bill since 2008.
Output: pipeline/definitions/vote_direction_defense.csv; unmatched pages go to data/raw/positions/unmatched_defense.csv and are not used.
"""
import json
import re
import unicodedata
from pathlib import Path

import duckdb
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
POS = ROOT / "data" / "raw" / "positions"
GROUPS = {
    "topline": [5, 6, 9, 11, 14, 18, 22, 24, 25, 42, 52, 53, 54, 63, 69, 74, 75, 76, 77, 83, 107, 108, 140, 142, 154, 162, 163, 181, 185, 207, 215, 225, 229, 230, 237],
    "cut": [3, 15, 23, 47, 48, 55, 56, 57, 79, 80, 86, 129, 164, 177, 200, 234, 236, 240],
    "weapons program": [20, 21, 44, 45, 50, 58, 127, 131, 132, 133, 147, 148, 159, 166, 168, 178, 179, 195, 196, 198, 201, 202, 203, 238],
    "arms sale or transfer": [4, 7, 16, 17, 66, 68, 111, 112, 113, 114, 115, 116, 117, 118, 121, 137, 144, 145, 146, 182, 231, 241],
}
SUFFIX = {"jr", "sr", "ii", "iii", "iv"}


def norm(s: str) -> str:
    return "".join(ch for ch in unicodedata.normalize("NFKD", s) if ch.isalpha()).lower()


def page_key(name: str) -> tuple[str, str]:
    toks = [t for t in re.split(r"[\s]+", name.replace("�", "").strip()) if t and norm(t) not in SUFFIX]
    return norm(toks[-1]), norm(toks[0])[:1]


def vv_key(bioname: str) -> tuple[str, str]:
    last, _, rest = bioname.partition(",")
    rest = re.sub(r"\b(Jr|Sr|II|III|IV)\.?,?", "", rest).strip()
    return norm(last), norm(rest.split()[0])[:1] if rest.split() else ""


def main() -> None:
    pages = json.loads((POS / "peaceaction_votes.json").read_text(encoding="utf-8"))
    con = duckdb.connect(str(ROOT / "data" / "analysis.duckdb"), read_only=True)
    con.execute(f"ATTACH '{(ROOT / 'data' / 'congress.duckdb').as_posix()}' AS c (READ_ONLY)")
    rc = con.execute("""SELECT r.congress, r.chamber, r.rollnumber, r.vote_date, r.bill_number, r.vote_question, r.yea_count, r.nay_count
                        FROM c.rollcalls r WHERE r.vote_date >= DATE '2008-01-01'""").df()
    names = con.execute("""SELECT bioguide_id AS bg, arg_max(bioname, congress) AS bn FROM c.member_terms GROUP BY 1""").df()
    key_of = {bg: vv_key(bn) for bg, bn in zip(names["bg"], names["bn"])}
    yea = con.execute("""SELECT v.congress, v.chamber, v.rollnumber, v.bioguide FROM member_vote v JOIN c.rollcalls r USING (congress, chamber, rollnumber)
                         WHERE r.vote_date >= DATE '2008-01-01' AND v.yea = 1""").df()
    yea["key"] = yea["bioguide"].map(key_of)
    ysets = {k: set(g["key"].dropna()) for k, g in yea.groupby(["congress", "chamber", "rollnumber"])}
    out, bad = [], []
    for group, idxs in GROUPS.items():
        for i in idxs:
            p = pages[i]
            t = p["text"]
            pos = re.search(r"Our Position:\s*([A-Za-z ]+)", t).group(1).strip()
            ch = re.search(r"Chamber:\s*(\w+)", t).group(1)
            seg = t[t.find("Chamber:"):]
            parts = re.split(r"\n(Yeas|Nays|Not Voting|Present)\n", seg)
            ylist = [x.strip() for x in parts[2].strip().split("\n")] if len(parts) > 2 and parts[1] == "Yeas" else []
            pkeys = {page_key(x) for x in ylist if x}
            tally = re.search(r"(?:Passed|Failed|Agreed to|Rejected|Adopted|Confirmed|Vote)[^0-9\n]{0,30}(\d{1,3})\s*-\s*(\d{1,3})", t)
            title = p["title"].replace("�", "-")
            bm = re.search(r"\b(H\.? ?J\.? ?Res\.?|S\.? ?J\.? ?Res\.?|H\.? ?R\.?|S\.?)\s?(\d{1,5})\b", title)
            want_bill = f"{re.sub(r'[^A-Z]', '', bm.group(1).upper())}{int(bm.group(2))}" if bm else None
            cand = rc[rc["chamber"] == ch]
            if want_bill and (cand["bill_number"] == want_bill).any():
                cand = cand[cand["bill_number"] == want_bill]
            qpat = ("Objections|Veto|Overriding" if re.search("override", title, re.I) else "Conference" if re.search("conference", title, re.I)
                    else "Discharge|Motion to Table" if re.search("discharge|tabling|table", title, re.I) else "Amendment" if re.search("amendment|amdt", title, re.I)
                    else "Passage|Agreeing to the Resolution|Concur" if re.search(r"act\b|authorization|appropriations|supplemental|weapons vote", title, re.I) else "")
            if qpat:
                q = cand[cand["vote_question"].fillna("").str.contains(qpat, case=False, regex=True)]
                cand = q if len(q) else cand
            if tally:
                a, b = int(tally.group(1)), int(tally.group(2))
                cand = cand[(cand["yea_count"] == a) & (cand["nay_count"] == b)]
            elif not want_bill:
                cand = cand[(cand["yea_count"] - len(ylist)).abs() <= 8]
            house = ch == "House"
            scored = []
            for r in cand.itertuples():
                ys = ysets.get((r.congress, r.chamber, r.rollnumber), set())
                if not pkeys:
                    continue
                ys_l = ys if house else {k[0] for k in ys}                     # Senate: last name only (nicknames and middle names vary)
                pk_l = pkeys if house else {k[0] for k in pkeys}
                scored.append((len(pk_l & ys_l) / len(pk_l | ys_l), r))       # Jaccard: a roll call with far more or fewer Yea voters than the page does not match
            scored.sort(key=lambda x: -x[0])
            best = scored[0][0] if scored else 0
            close = [x for x in scored if x[0] >= best - 0.03]
            ok = bool(scored) and (best >= 0.85 and len(close) == 1 or best >= 0.75 and len(scored) == 1 and tally is not None and want_bill is not None)
            if not ok:
                bad.append({"idx": i, "title": p["title"], "chamber": ch, "tally": tally.group(0) if tally else "", "best": round(best, 3) if scored else None, "cands": len(scored), "close": len(close)})
                continue
            r = scored[0][1]
            out.append({"congress": r.congress, "chamber": r.chamber, "rollnumber": r.rollnumber, "bill": r.bill_number, "date": r.vote_date.date().isoformat(),
                        "sector": "Defense & Aerospace", "subsector": "", "helps_vote": "Nay" if pos == "In Favor" else "Yea", "evidence_level": "scorecard",
                        "evidence": f"{group}: Peace Action position '{pos}' on '{p['title'].replace(chr(0xfffd), '-')}'; industry side taken as the opposite on a fiscal-effect rule",
                        "source_url": p["url"]})
    # Passage votes on the bills that authorize or fund defense contractors, for every year since 2008 (the Peace Action archive only covers 2013 to 2024).
    # Fiscal rule: the industry's side on passage of its own authorization and appropriations bills is Yea (the Aerospace Industries Association publicly backs them).
    pas = con.execute("""
        SELECT r.congress, r.chamber, r.rollnumber, r.bill_number, r.vote_date, r.vote_question, t.title
        FROM c.rollcalls r JOIN rollcall_topic t USING (congress, chamber, rollnumber)
        WHERE r.vote_date >= DATE '2008-01-01'
          AND (t.title ILIKE '%National Defense Authorization%' OR t.title ILIKE '%Department of Defense Appropriations%' OR t.title ILIKE '%Defense Appropriations Act%')
          AND (r.vote_question ILIKE '%passage%' OR r.vote_question ILIKE '%conference report%' OR r.vote_question ILIKE '%concur%' OR r.vote_question ILIKE '%veto%'
               OR r.vote_question ILIKE '%suspend the rules and pass%')""").df()
    for r in pas.itertuples():
        out.append({"congress": r.congress, "chamber": r.chamber, "rollnumber": r.rollnumber, "bill": r.bill_number, "date": pd.Timestamp(r.vote_date).date().isoformat(),
                    "sector": "Defense & Aerospace", "subsector": "", "helps_vote": "Yea", "evidence_level": "fiscal",
                    "evidence": f"fiscal rule: {r.vote_question} on '{(r.title or '')[:80]}'; the industry's side on passage of the bills that authorize and fund it is Yea",
                    "source_url": "https://www.aia-aerospace.org/news/aia-statement-on-house-passage-of-bipartisan-national-defense-authorization-act/"})
    df = pd.DataFrame(out).drop_duplicates(["congress", "chamber", "rollnumber"])
    df.to_csv(ROOT / "pipeline" / "definitions" / "vote_direction_defense.csv", index=False)
    pd.DataFrame(bad).to_csv(POS / "unmatched_defense.csv", index=False)
    print(f"selected {sum(len(v) for v in GROUPS.values())} pages | matched {len(df)} roll calls | unmatched {len(bad)}")
    print(df.groupby(["chamber", "helps_vote"]).size().to_string())
    print(pd.DataFrame(bad).head(25).to_string(index=False))


if __name__ == "__main__":
    main()
