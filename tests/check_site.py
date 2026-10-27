"""Checks that the numbers and wording on the site agree with the data. Run with the server up:

    .venv\\Scripts\\python.exe tests\\check_site.py            (defaults to http://127.0.0.1:8000)

Each check prints PASS or FAIL; the exit code is the number of failures. These guard against the mistakes found in the 2026-10-27 audit: text that says a thing is
not built after it is, counts that differ between pages, rankings that ignore the party control, labels that differ by page, and non-numbers in the data.
"""
import csv
import json
import math
import re
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
FAILS = []


def check(name: str, ok: bool, detail: str = ""):
    print(("PASS " if ok else "FAIL ") + name + ("" if ok or not detail else f"  -> {detail}"))
    if not ok:
        FAILS.append(name)


def get(path: str):
    r = requests.get(BASE + path, timeout=120)
    r.raise_for_status()
    return json.loads(r.text, parse_constant=lambda c: (_ for _ in ()).throw(ValueError(f"{c} in {path}")))


def no_bad_numbers(obj) -> bool:
    if isinstance(obj, float):
        return math.isfinite(obj)
    if isinstance(obj, dict):
        return all(no_bad_numbers(v) for v in obj.values())
    if isinstance(obj, list):
        return all(no_bad_numbers(v) for v in obj)
    return True


# ---- every endpoint answers and contains no NaN/Infinity
ENDPOINTS = ["/api/scoreboard?variant=all&sector=All%20business", "/api/scoreboard?variant=lobbied&sector=All%20business", "/api/method", "/api/allvotes/summary",
             "/api/allvotes/top?label=oil%20gas&min_t=3.13&limit=10", "/api/defense/overview", "/api/defense/war", "/api/defense/promises", "/api/members", "/api/definitions",
             "/api/lobbying/overview", "/api/lobbying/sector?sector=Health", "/api/companies", "/api/company/pfizer", "/api/outside/overview", "/api/member/E000071/outside", "/api/pledges",
             "/api/moneycoverage", "/api/freshness", "/api/trades/overview", "/api/presidential", "/api/revolving/overview", "/api/member/E000071/trades", "/api/member/E000071/earmarks"]
data = {}
for ep in ENDPOINTS:
    try:
        data[ep] = get(ep)
        check(f"endpoint {ep.split('?')[0]} answers with finite numbers", no_bad_numbers(data[ep]))
    except Exception as e:  # noqa: BLE001
        check(f"endpoint {ep.split('?')[0]} answers", False, str(e)[:120])

sb = data.get(ENDPOINTS[0])
if sb:
    cov = sb["coverage"]
    check("landmark votes by match add up", sum(cov["landmark_by_match"].values()) == cov["landmark_votes"], f"{cov['landmark_by_match']} vs {cov['landmark_votes']}")
    check("no industry has more documented votes than exist", max(cov["coded_by_label"].values()) <= cov["coded_since_2008"])
    check("defense has documented votes (it was once described as missing)", cov["coded_by_label"].get("Defense & Aerospace", 0) >= 100)
    check("lobbying data reaches the current Congress", (cov.get("lobbied_through") or "") >= "2025-01-01", str(cov.get("lobbied_through")))
    labels = [s["label"] for s in sb["sectors"]]
    util = (ROOT / "web" / "src" / "util.ts").read_text(encoding="utf-8")
    block = util[util.index("INDUSTRY_NAME"):util.index("export const industryName")]
    mapped = {a or b for a, b in re.findall(r"[{,]\s*(?:'([^']+)'|(\w+))\s*:", block)}
    bad = [l for l in labels if l[0].islower() and l not in mapped]
    check("every lowercase industry label has a display name", not bad, str(bad))

top = data.get(ENDPOINTS[4])
if top:
    check("linked strong links are a subset of all", top["total_linked"] <= top["total_all"])
    check("linked strong links hold no procedural vote", not any(r["procedural"] for r in top["rows"]))
    check("every linked strong link is lobbied or has a documented side", all(r["lobbied"] or r["coded_side"] for r in top["rows"]))

s = data.get(ENDPOINTS[3])
if s:
    gaps = [r["aligned"] - r["expected"] for r in sorted(s["dose"], key=lambda r: r["k"])]
    check("more money goes with a higher gap at every step", all(b > a for a, b in zip(gaps, gaps[1:])), str([round(g, 3) for g in gaps]))

# ---- the pages added after the 2026-10-27 audit
lob = data.get("/api/lobbying/overview")
if lob:
    c25 = next((c for c in lob["coverage"] if c["year"] == 2025), None)
    check("more than two thirds of 2025 lobbying spend is placed in an industry", bool(c25) and c25["labelled"] / (c25["labelled"] + c25["unlabelled"]) > 0.66, str(c25))
cos = data.get("/api/companies")
if cos:
    check("at least 100 companies are followed", len(cos) >= 100, str(len(cos)))
    check("no company page claims a lobbying total of zero", all((c["lobbying"] or 0) > 0 for c in cos if c["slug"] not in ("palantir",)), str([c["slug"] for c in cos if not c["lobbying"]][:5]))
out = data.get("/api/outside/overview")
if out:
    g = {}
    for r in out["coverage"]:
        g[r["grp"]] = g.get(r["grp"], 0) + r["amount"]
    sorted_share = g.get("Sorted into an industry or group", 0) / max(1, sum(g.values()))
    check("outside-spending attribution sorts a meaningful share (and says how much)", 0.2 < sorted_share < 0.9, f"{sorted_share:.2f}")
pl = data.get("/api/pledges")
if pl:
    check("every pledge signer on the list was matched to a member", len(pl["members"]) == 71, str(len(pl["members"])))
    check("pledge gifts exclude clean-energy and non-coal mining committees", not any(re.search(r"SUSTAINABLE|RENEWABLE|COEUR|ETHANOL", g["committee"].upper()) for g in pl["gifts"]))
tr = data.get("/api/trades/overview")
if tr:
    check("trade ranges are ordered (low never above high)", all(x["lo"] <= x["hi"] for x in tr["sectors"]))
    check("most trade report lines were read since 2021", all(y["parsed"] >= 0.9 * y["expected"] for y in tr["coverage"]["parse_by_year"] if y["year"] >= 2022 and y["expected"] > 100), str(tr["coverage"]["parse_by_year"][-4:]))
pr = data.get("/api/presidential")
if pr:
    check("presidential data covers both 2020 nominees", {"Trump", "Biden / Harris"} <= {f["candidate"] for f in pr["funding"] if f["cycle"] == 2020})
rv = data.get("/api/revolving/overview")
if rv:
    check("lobbyist shares are fractions of lobbyists", all(s["with_position"] <= s["lobbyists"] and s["congress_roles"] <= s["with_position"] for s in rv["by_sector"]))
mc = data.get("/api/moneycoverage")
if mc:
    check("money coverage groups are present for individual gifts", any(m["source"] == "indiv" and m["grp"] == "sorted" for m in mc))

# ---- company-reported shares: read from the filings, linked to them
with open(ROOT / "pipeline" / "definitions" / "company_reported_share.csv", encoding="utf-8", newline="") as f:
    rows = list(csv.DictReader(f))
check("reported shares are between 0 and 1", all(0 < float(r["share"]) <= 1 for r in rows))
check("every reported share links to a SEC filing", all(r["source_url"].startswith("https://www.sec.gov/Archives/edgar/data/") for r in rows))
check("a share counting FMS is never below the stated share", all(not r["share_with_fms"] or float(r["share_with_fms"]) >= float(r["share"]) for r in rows))

# ---- wording: phrases that were true once and are not now
BANNED = [("not yet loaded", "lobbying is loaded"), ("Not built yet", "replaced by 'Not covered yet'"), ("pilot set", "the codebook is no longer a pilot"), ("Party explains most", "framing dropped"),
          ("39 landmark", "counts come from the data"), ("search-result quotation", "shares are read from the filings"), ("still downloading", "lobbying is downloaded"),
          ("thin or missing", "defense has 147 documented votes")]
text = "\n".join(p.read_text(encoding="utf-8") for p in (ROOT / "web" / "src").rglob("*.tsx"))
for phrase, why in BANNED:
    check(f"site text no longer says '{phrase}'", phrase not in text, why)

print(f"\n{len(FAILS)} failed")
sys.exit(len(FAILS))
