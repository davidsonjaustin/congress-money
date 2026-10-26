"""Committee assignments, 109th-119th Congress -> data/analysis.duckdb.committee_assignment

  committee_assignment(congress, chamber, icpsr, bioguide, committee_id, committee_name, start_date, end_date,
                       majority, rank, source)

Sources
  stewart_woon  House / Senate standing-committee assignments with real start and end dates, 109th-117th
                (Charles Stewart III & Jonathan Woon, Harvard Dataverse doi:10.7910/DVN/XLIHUC and EQ6KC7).
  snapshot      118th (end of Dec 2024) and 119th (current): unitedstates/congress-legislators membership lists.
                Full committees only. These are snapshots: NO start/end dates, and a member who left a committee
                before the snapshot date is absent -- do not use them for timing (join/leave) tests.
"""
import datetime as dt
from pathlib import Path

import duckdb
import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw" / "committees"
MIN_CONGRESS = 109


def excel_date(v):
    if pd.isna(v):
        return pd.NaT
    if isinstance(v, (dt.datetime, pd.Timestamp)):
        return pd.Timestamp(v)
    try:
        return pd.Timestamp("1899-12-30") + pd.to_timedelta(int(float(v)), unit="D")
    except (TypeError, ValueError):        # 'Unknown' and similar placeholders in the source
        return pd.to_datetime(v, errors="coerce")


def stewart_woon() -> pd.DataFrame:
    h = pd.read_excel(RAW / "House_assignments_103-117.xls", header=1, engine="xlrd")
    h = h.rename(columns={"Committee code": "committee_id", "ID #": "icpsr", "Committee Name": "committee_name",
                          "Maj/Min": "majority", "Rank Within Party Status": "rank",
                          "Date of Assignment": "start_date", "Date of Termination": "end_date"})
    h["chamber"] = "House"
    s = pd.read_csv(RAW / "Senate_assignments_103-117.tab", sep="\t", skiprows=1, quotechar='"')
    s = s.rename(columns={"Committee Code": "committee_id", "ID #": "icpsr", "Committee Name": "committee_name",
                          "Maj/Min": "majority", "Rank Within Party": "rank",
                          "Date of Appointment": "start_date", "Date of Termination": "end_date"})
    s["chamber"] = "Senate"
    out = []
    for df in (h, s):
        df = df.rename(columns={"Congress": "congress"})
        df = df[pd.to_numeric(df["congress"], errors="coerce") >= MIN_CONGRESS].copy()
        df["congress"] = df["congress"].astype(int)
        df["icpsr"] = pd.to_numeric(df["icpsr"], errors="coerce").astype("Int64")
        df["start_date"] = df["start_date"].map(excel_date)
        df["end_date"] = df["end_date"].map(excel_date)
        df["majority"] = pd.to_numeric(df["majority"], errors="coerce").eq(1)
        df["committee_id"] = df["committee_id"].astype(str)
        df["committee_name"] = df["committee_name"].astype(str).str.strip().str.title()
        df["rank"] = pd.to_numeric(df["rank"], errors="coerce")
        out.append(df[["congress", "chamber", "icpsr", "committee_id", "committee_name", "start_date", "end_date", "majority", "rank"]])
    r = pd.concat(out, ignore_index=True)
    r["source"] = "stewart_woon"
    return r


def snapshot(membership_yaml: Path, committees_yaml: Path, congress: int) -> pd.DataFrame:
    members = yaml.safe_load(membership_yaml.read_text(encoding="utf-8"))
    names = {}
    for c in yaml.safe_load(committees_yaml.read_text(encoding="utf-8")):
        names[c["thomas_id"]] = (c["type"], c["name"])
    rows = []
    for cid, people in members.items():
        if cid not in names:           # subcommittee codes (e.g. HSAG15) are not in the top-level list
            continue
        typ, name = names[cid]
        if typ not in ("house", "senate"):
            continue
        for p in people:
            rows.append({"congress": congress, "chamber": "House" if typ == "house" else "Senate", "bioguide": p["bioguide"],
                         "committee_id": cid, "committee_name": name.replace("House Committee on ", "").replace("Senate Committee on ", "").strip(),
                         "start_date": pd.NaT, "end_date": pd.NaT, "majority": p.get("party") == "majority",
                         "rank": p.get("rank"), "source": "snapshot"})
    return pd.DataFrame(rows)


def main() -> None:
    con = duckdb.connect(str(ROOT / "data" / "analysis.duckdb"))
    con.execute(f"ATTACH '{(ROOT / 'data' / 'congress.duckdb').as_posix()}' AS c (READ_ONLY)")
    mt = con.execute("SELECT DISTINCT congress, chamber, icpsr, bioguide_id AS bioguide FROM c.member_terms").df()
    mt["icpsr"] = mt["icpsr"].astype("Int64")

    sw = stewart_woon()
    sw = sw.merge(mt, on=["congress", "chamber", "icpsr"], how="left")
    snaps = []
    for congress, mem, com in ((118, "membership_2024-12.yaml", "committees_2024-12.yaml"),
                               (119, "committee-membership-current.json", "committees-current.json")):
        if mem.endswith(".json"):                # the current files are JSON; the dated ones YAML (JSON is valid YAML)
            pass
        sn = snapshot(RAW / mem, RAW / com, congress)
        sn = sn.merge(mt, on=["congress", "chamber", "bioguide"], how="left")
        snaps.append(sn)
    out = pd.concat([sw] + snaps, ignore_index=True)[
        ["congress", "chamber", "icpsr", "bioguide", "committee_id", "committee_name", "start_date", "end_date", "majority", "rank", "source"]]
    con.execute("CREATE OR REPLACE TABLE committee_assignment AS SELECT * FROM out")

    print("committee_assignment rows:", len(out))
    print("\nmember-terms with >=1 committee, by Congress (excl. delegates):")
    for r in con.execute("""
        SELECT m.congress, m.chamber, count(*) total, count(*) FILTER (WHERE EXISTS (
            SELECT 1 FROM committee_assignment a WHERE a.congress=m.congress AND a.chamber=m.chamber AND a.bioguide=m.bioguide_id)) with_c
        FROM c.member_terms m WHERE m.state NOT IN ('DC','PR','GU','VI','AS','MP') GROUP BY 1,2 ORDER BY 1,2""").fetchall():
        print(f"  {r[0]}th {r[1]:6s} {r[3]:>4}/{r[2]:<4} ({100*r[3]/r[2]:.0f}%)")
    print("\ncommittees (House, 117th snapshot of names):")
    for n, cnt in con.execute("""SELECT committee_name, count(*) FROM committee_assignment WHERE congress=117 AND chamber='House' GROUP BY 1 ORDER BY 2 DESC""").fetchall():
        print(f"  {n:60s} {cnt}")
    print("\ncommittees (Senate, 117th):")
    for n, cnt in con.execute("""SELECT committee_name, count(*) FROM committee_assignment WHERE congress=117 AND chamber='Senate' GROUP BY 1 ORDER BY 2 DESC""").fetchall():
        print(f"  {n:60s} {cnt}")


if __name__ == "__main__":
    main()
