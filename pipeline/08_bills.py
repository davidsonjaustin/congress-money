"""Download GovInfo BILLSTATUS bulk XML (no API key needed) for the 109th-119th Congresses and load
bill metadata into data/bills.duckdb:

  bills(congress, bill_type, bill_number, title, policy_area, subjects, sponsor_bioguide, origin_chamber,
        introduced, became_law, latest_action, summary)
bill_type uses Voteview/LDA style: hr, s, hjres, sjres, hconres, sconres, hres, sres.
"""
import re
import sys
import time
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

import duckdb
import requests

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw" / "billstatus"
DB = ROOT / "data" / "bills.duckdb"
CONGRESSES = range(109, 120)
TYPES = ["hr", "s", "hjres", "sjres", "hconres", "sconres", "hres", "sres"]
TAGS = re.compile(r"<[^>]+>")


def text(el: ET.Element | None, path: str) -> str | None:
    if el is None:
        return None
    node = el.find(path)
    return node.text.strip() if node is not None and node.text else None


def parse(xml_bytes: bytes):
    root = ET.fromstring(xml_bytes)
    b = root.find("bill")
    if b is None:
        return None
    subjects = [n.text for n in b.findall("subjects/legislativeSubjects/item/name") if n.text]
    summaries = b.findall("summaries/summary")
    summary = text(summaries[-1], "text") if summaries else None
    if summary:
        summary = TAGS.sub(" ", summary)
        summary = re.sub(r"\s+", " ", summary).strip()[:3000]
    return (
        int(text(b, "congress")), (text(b, "type") or text(b, "billType") or "").lower(),
        int(text(b, "number") or text(b, "billNumber")),  # a few older files use the billNumber/billType layout
        text(b, "title"), text(b, "policyArea/name"), "; ".join(subjects) or None,
        text(b, "sponsors/item/bioguideId"), text(b, "originChamber"), text(b, "introducedDate"),
        len(b.findall("laws/item")) > 0, text(b, "latestAction/text"), summary,
    )


def main() -> None:
    RAW.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(DB))
    con.execute("""CREATE TABLE IF NOT EXISTS bills (congress INT, bill_type VARCHAR, bill_number INT, title VARCHAR,
        policy_area VARCHAR, subjects VARCHAR, sponsor_bioguide VARCHAR, origin_chamber VARCHAR, introduced DATE,
        became_law BOOLEAN, latest_action VARCHAR, summary VARCHAR)""")
    con.execute("CREATE TABLE IF NOT EXISTS bills_done (congress INT, bill_type VARCHAR, n INT)")
    done = {(r[0], r[1]) for r in con.execute("SELECT congress, bill_type FROM bills_done").fetchall()}
    for c in CONGRESSES:
        for t in TYPES:
            if (c, t) in done:
                continue
            dest = RAW / f"BILLSTATUS-{c}-{t}.zip"
            if not dest.exists():
                r = requests.get(f"https://www.govinfo.gov/bulkdata/BILLSTATUS/{c}/{t}/BILLSTATUS-{c}-{t}.zip", timeout=600)
                if r.status_code != 200:
                    print(f"{c} {t}: HTTP {r.status_code}, skipped")
                    continue
                dest.write_bytes(r.content)
            rows, skipped = [], []
            with zipfile.ZipFile(dest) as z:
                for name in z.namelist():
                    if name.lower().endswith(".xml"):
                        try:
                            row = parse(z.read(name))
                        except (ET.ParseError, TypeError, ValueError):
                            skipped.append(name)
                            continue
                        if row:
                            rows.append(row)
            if skipped:
                print(f"  {c} {t}: skipped {len(skipped)} unparseable file(s): {skipped[:3]}")
            con.execute("DELETE FROM bills WHERE congress=? AND bill_type=?", [c, t])
            con.executemany("INSERT INTO bills VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", rows)
            con.execute("INSERT INTO bills_done VALUES (?,?,?)", [c, t, len(rows)])
            print(f"{time.strftime('%H:%M:%S')} {c} {t}: {len(rows):,} bills")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
