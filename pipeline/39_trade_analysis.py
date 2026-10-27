"""Members' stock trades by industry.

Matches each House Periodic Transaction Report to a member, puts each stock in an industry from the company's SEC standard industrial classification (SIC) code, and
totals the trades by member and industry. Amounts are reported only as ranges, so totals are given as a low-high pair and never as a single figure.

Industry from SIC: the company's code is read from the SEC's own submissions file for its ticker. Tickers the SEC no longer lists (delisted or renamed) fall back to the
keyword rules used for PACs on the asset's name, and anything still unplaced is 'Unclassified'. Mutual funds, ETFs, bonds and Treasuries are 'Funds, bonds and other'.

Output (data/trades.duckdb):
  ticker_sic(ticker, cik, title, sic, sic_desc)
  trade_clean(doc_id, bioguide, year, tx_date, tx, owner, asset, ticker, sector, lo, hi)
  trade_member(bioguide, year, n, buys, sells, lo, hi)
  trade_sector_member(bioguide, sector, n, buys, sells, lo, hi, tickers)
  trade_unmatched(last, first, state_dst, n)                     reports whose filer could not be matched to one member
"""
import importlib.util
import re
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import duckdb
import pandas as pd
import requests

ROOT = Path(__file__).resolve().parent.parent
H = {"User-Agent": "CongressMoneyResearch personal-project research tool", "Accept-Encoding": "gzip, deflate"}
FUNDS = {"MF", "EF", "GS", "CS", "CT", "OT", "PS", "DB", "AB", "BA", "FN", "IR", "OL", "RE", "HE"}   # funds, ETFs, bonds, government securities, crypto, other


def load(name: str):
    spec = importlib.util.spec_from_file_location(name.replace(".py", "_m"), Path(__file__).with_name(name))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def sic_sector(sic: int) -> str | None:
    d2, d3, d4 = sic // 100, sic // 10, sic
    if d2 <= 9: return "Agribusiness & Food"
    if d2 == 12 or d2 == 13 or d2 in (10, 14): return "Energy & Natural Resources"
    if 15 <= d2 <= 17: return "Construction"
    if d2 in (20, 21): return "Agribusiness & Food"
    if d3 == 283: return "Health"
    if d2 == 28 or d2 in (22, 23, 24, 25, 26, 30, 31, 32, 33): return "Manufacturing & Industrial"
    if d2 == 27: return "Tech, Telecom & Media"
    if d2 == 29: return "Energy & Natural Resources"
    if d3 == 348: return "Defense & Aerospace"
    if d2 == 34: return "Manufacturing & Industrial"
    if d3 == 357 or d2 == 36 or d3 == 737: return "Tech, Telecom & Media"
    if d2 == 35: return "Manufacturing & Industrial"
    if d3 in (372, 373, 376) or d4 == 3812: return "Defense & Aerospace"
    if d3 in (371, 374, 375, 379): return "Transportation"
    if d2 == 37: return "Manufacturing & Industrial"
    if d3 == 384 or d3 == 385 or d4 == 3841 or d4 == 3845: return "Health"
    if d2 == 38: return "Manufacturing & Industrial"
    if d2 == 39: return "Manufacturing & Industrial"
    if d2 == 46: return "Energy & Natural Resources"
    if d2 == 47: return "Travel, Lodging & Leisure"
    if 40 <= d2 <= 45: return "Transportation"
    if d2 == 48: return "Tech, Telecom & Media"
    if d2 == 49: return "Energy & Natural Resources"
    if d4 == 5122 or d4 == 5912 or d2 == 80: return "Health"
    if d4 in (5141, 5140) or d2 == 54: return "Agribusiness & Food"
    if d4 == 5171 or d4 == 5172: return "Energy & Natural Resources"
    if 50 <= d2 <= 59: return "Retail & Consumer"
    if 60 <= d2 <= 67: return "Finance, Insurance & Real Estate"
    if d2 in (70,) or d2 == 79: return "Travel, Lodging & Leisure"
    if d3 == 737 or d2 == 73: return "Tech, Telecom & Media"
    if d2 == 78: return "Tech, Telecom & Media"
    if d2 == 82: return "Education"
    if d2 == 87: return "Construction" if d4 in (8711, 8712, 8741, 8742) else "Health"
    return None


def fetch_sic(args):
    ticker, cik = args
    for attempt in range(3):
        try:
            r = requests.get(f"https://data.sec.gov/submissions/CIK{int(cik):010d}.json", headers=H, timeout=40)
            if r.status_code == 200:
                j = r.json()
                return ticker, cik, j.get("name", ""), int(j["sic"]) if str(j.get("sic", "")).isdigit() else None, j.get("sicDescription", "")
            if r.status_code == 404:
                break
        except requests.RequestException:
            time.sleep(1 + attempt)
        time.sleep(0.2)
    return ticker, cik, "", None, ""


def plain(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c)).lower()


def main() -> None:
    con = duckdb.connect(str(ROOT / "data" / "trades.duckdb"))
    con.execute(f"ATTACH '{(ROOT / 'data' / 'congress.duckdb').as_posix()}' AS c (READ_ONLY)")

    # 1. ticker -> SIC from the SEC
    have = {r[0] for r in con.execute("SELECT ticker FROM ticker_sic").fetchall()} if con.execute("SELECT count(*) FROM information_schema.tables WHERE table_name = 'ticker_sic'").fetchone()[0] else set()
    want = [r[0] for r in con.execute("SELECT DISTINCT upper(ticker) FROM house_trades WHERE ticker <> '' AND asset_type IN ('ST', 'OP')").fetchall()]
    tk = requests.get("https://www.sec.gov/files/company_tickers.json", headers=H, timeout=60).json()
    cik_of = {v["ticker"].upper(): v["cik_str"] for v in tk.values()}
    todo = [(t, cik_of[t]) for t in want if t in cik_of and t not in have]
    print(f"{len(want)} tickers traded; {len(todo)} to look up at the SEC", flush=True)
    rows = []
    with ThreadPoolExecutor(max_workers=5) as pool:
        for k, r in enumerate(pool.map(fetch_sic, todo)):
            rows.append(r)
            if k % 500 == 0:
                print(k, "looked up", flush=True)
    if rows:
        df = pd.DataFrame(rows, columns=["ticker", "cik", "title", "sic", "sic_desc"])
        con.execute("CREATE TABLE IF NOT EXISTS ticker_sic (ticker VARCHAR, cik VARCHAR, title VARCHAR, sic INT, sic_desc VARCHAR)")
        con.execute("INSERT INTO ticker_sic SELECT * FROM df")
    sic = {r[0]: r[1] for r in con.execute("SELECT ticker, sic FROM ticker_sic WHERE sic IS NOT NULL").fetchall()}

    # 2. filer -> member
    ptr = con.execute("SELECT doc_id, year, last, first, state_dst, filed FROM house_ptr").df()
    terms = con.execute("SELECT congress, bioguide_id AS bioguide, bioname, state, district FROM c.member_terms WHERE chamber = 'House' AND bioguide_id IS NOT NULL").df()
    terms["last"] = terms["bioname"].str.split(",").str[0].map(plain)
    terms["firstn"] = terms["bioname"].str.split(",").str[1].fillna("").str.strip().str.split().str[0].map(plain)
    ptr["state"] = ptr["state_dst"].str[:2]
    ptr["dist"] = pd.to_numeric(ptr["state_dst"].str[2:], errors="coerce")
    ptr["fy"] = pd.to_datetime(ptr["filed"], errors="coerce").dt.year.fillna(ptr["year"]).astype(int)
    ptr["congress"] = (ptr["fy"] - 1789) // 2 + 1
    ptr["l"] = ptr["last"].map(plain).str.replace(r"[^a-z\- ]", "", regex=True).str.strip()
    ptr["f"] = ptr["first"].map(plain).str.split().str[0].fillna("")
    out, bad = {}, {}
    for r in ptr.itertuples(index=False):
        cand = terms[(terms["congress"] == r.congress) & (terms["state"] == r.state)]
        hit = cand[cand["last"] == r.l]
        if len(hit) != 1 and len(hit) > 1:
            hit = hit[hit["firstn"].str[:3] == r.f[:3]]
        if len(hit) != 1:
            hit = cand[(cand["district"] == r.dist) & cand["last"].map(lambda x: x.split()[-1] == r.l.split()[-1] if r.l else False)]
        if len(hit) == 1:
            out[r.doc_id] = hit.iloc[0]["bioguide"]
        else:
            bad[(r.last, r.first, r.state_dst)] = bad.get((r.last, r.first, r.state_dst), 0) + 1
    print(f"matched {len(out)} of {len(ptr)} reports to a member; {len(bad)} filer names unmatched")
    bm = pd.DataFrame(list(out.items()), columns=["doc_id", "bioguide"])
    con.execute("CREATE OR REPLACE TABLE ptr_member AS SELECT * FROM bm")
    ub = pd.DataFrame([(k[0], k[1], k[2], v) for k, v in bad.items()], columns=["last", "first", "state_dst", "n"])
    con.execute("CREATE OR REPLACE TABLE trade_unmatched AS SELECT * FROM ub")

    # 3. industry for each trade
    s03 = load("03_sectors.py")
    t = con.execute("""
        SELECT t.doc_id, m.bioguide, p.year, strptime(t.tx_date, '%m/%d/%Y')::DATE AS tx_date, t.tx, t.owner, t.asset, upper(t.ticker) AS ticker, t.asset_type, t.lo, t.hi
        FROM house_trades t JOIN ptr_member m USING (doc_id) JOIN house_ptr p USING (doc_id)""").df()

    def sector(r) -> str:
        if r.asset_type in FUNDS:
            return "Funds, bonds and other"
        s = sic.get(r.ticker)
        if s is not None:
            x = sic_sector(s)
            if x:
                return x
        name = (r.asset or "").upper()
        for sec, rx in s03.RULES_RE:
            if sec not in ("Labor", "Ideological / Single-Issue", "Lawyers & Lobbyists", "General Business Associations") and rx.search(name):
                return sec
        return "Unclassified"

    t["sector"] = [sector(r) for r in t.itertuples(index=False)]
    con.execute("CREATE OR REPLACE TABLE trade_clean AS SELECT doc_id, bioguide, year, tx_date, tx, owner, asset, ticker, sector, lo, hi FROM t")
    con.execute("""
        CREATE OR REPLACE TABLE trade_member AS
        SELECT bioguide, year(tx_date) AS year, count(*) AS n, count(*) FILTER (WHERE tx = 'P') AS buys, count(*) FILTER (WHERE tx = 'S') AS sells, sum(lo) AS lo, sum(hi) AS hi
        FROM trade_clean WHERE tx_date IS NOT NULL GROUP BY 1, 2""")
    con.execute("""
        CREATE OR REPLACE TABLE trade_sector_member AS
        SELECT bioguide, sector, count(*) AS n, count(*) FILTER (WHERE tx = 'P') AS buys, count(*) FILTER (WHERE tx = 'S') AS sells, sum(lo) AS lo, sum(hi) AS hi,
               string_agg(DISTINCT ticker, ' ' ORDER BY ticker) FILTER (WHERE ticker <> '') AS tickers
        FROM trade_clean WHERE tx_date >= DATE '2014-01-01' GROUP BY 1, 2""")
    pd.set_option("display.width", 200)
    print(con.execute("SELECT sector, count(*) AS trades, round(sum(lo) / 1e6, 1) AS low_m, round(sum(hi) / 1e6, 1) AS high_m FROM trade_clean GROUP BY 1 ORDER BY 2 DESC").df().to_string(index=False))
    print(con.execute("SELECT count(*) AS trades, count(DISTINCT bioguide) AS members FROM trade_clean").fetchone())


if __name__ == "__main__":
    main()
