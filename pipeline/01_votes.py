"""Load Voteview votes + member crosswalk (Voteview <-> bioguide <-> FEC IDs) into DuckDB.

Scope: 109th Congress (2005) onward.
"""
import json
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
DB = ROOT / "data" / "congress.duckdb"
MIN_CONGRESS = 109

con = duckdb.connect(str(DB))

con.execute(f"""
    CREATE OR REPLACE TABLE rollcalls AS
    SELECT congress, chamber, rollnumber, CAST(date AS DATE) AS vote_date, session,
           yea_count, nay_count, bill_number, vote_result, vote_desc, vote_question, dtl_desc
    FROM read_csv_auto('{(RAW / "HSall_rollcalls.csv").as_posix()}', header=true, sample_size=-1)
    WHERE congress >= {MIN_CONGRESS} AND chamber IN ('House', 'Senate')
""")

# cast_code: 1-3 Yea, 4-6 Nay, 7-9 Present/Abstain, 0 not a member
con.execute(f"""
    CREATE OR REPLACE TABLE votes AS
    SELECT congress, chamber, rollnumber, icpsr, cast_code,
           prob,  -- Voteview's NOMINATE-model probability of the vote actually cast (low = surprising given ideology)
           CASE WHEN cast_code IN (1,2,3) THEN 'Yea'
                WHEN cast_code IN (4,5,6) THEN 'Nay'
                WHEN cast_code IN (7,8,9) THEN 'Abstain' END AS vote
    FROM read_csv_auto('{(RAW / "HSall_votes.csv").as_posix()}', header=true)
    WHERE congress >= {MIN_CONGRESS} AND cast_code BETWEEN 1 AND 9
""")

con.execute(f"""
    CREATE OR REPLACE TABLE member_terms AS
    SELECT congress, chamber, icpsr, state_abbrev AS state, district_code AS district,
           party_code, bioname, bioguide_id, nominate_dim1
    FROM read_csv_auto('{(RAW / "HSall_members.csv").as_posix()}', header=true, sample_size=-1)
    WHERE congress >= {MIN_CONGRESS} AND chamber IN ('House', 'Senate')
""")

# bioguide -> FEC candidate IDs (a member can have several: House run, Senate run, ...)
rows = []
for name in ("legislators-current.json", "legislators-historical.json"):
    for leg in json.loads((RAW / name).read_text(encoding="utf-8")):
        ids = leg["id"]
        if "bioguide" not in ids:
            continue
        for fec in ids.get("fec", []) or [None]:
            rows.append((ids["bioguide"], fec, ids.get("opensecrets"), ids.get("govtrack"),
                         leg["name"].get("official_full") or f'{leg["name"]["first"]} {leg["name"]["last"]}'))
con.execute("CREATE OR REPLACE TABLE id_crosswalk (bioguide VARCHAR, fec_id VARCHAR, opensecrets VARCHAR, govtrack INT, full_name VARCHAR)")
con.executemany("INSERT INTO id_crosswalk VALUES (?,?,?,?,?)", rows)

for t in ("rollcalls", "votes", "member_terms", "id_crosswalk"):
    print(t, con.execute(f"SELECT count(*) FROM {t}").fetchone()[0])
print(con.execute("SELECT chamber, count(*), min(vote_date), max(vote_date) FROM rollcalls GROUP BY 1").fetchall())
