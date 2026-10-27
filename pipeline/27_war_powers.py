"""Votes on resolutions directing the removal of US forces from hostilities (War Powers Resolution), 2008 to 2026.

Selection rule (written before looking at who voted how): a roll call counts if it is a vote ON the resolution itself, a House or Senate concurrent or joint
resolution whose title says it directs the President to remove, or directs the removal of, US Armed Forces from hostilities, and the question is passage,
agreeing to the resolution, discharge, motion to proceed, or a veto override. Procedural rules (HRES), motions to table, recommit, point of order, previous question
and 'as amended' versions are left out because a Yea on them does not mean the same thing.
A Yea is a vote to constrain unauthorized military action. That is the only meaning attached to it: it is not a vote about any industry.

Output (analysis.duckdb): war_vote(congress, chamber, rollnumber, vote_date, bill_number, vote_question, vote_desc, yea_count, nay_count, vote_result),
war_member(bioguide, n, constrain, n119, constrain119).
"""
from pathlib import Path

import duckdb
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
con = duckdb.connect(str(ROOT / "data" / "analysis.duckdb"))
con.execute(f"ATTACH '{(ROOT / 'data' / 'congress.duckdb').as_posix()}' AS c (READ_ONLY)")
con.execute("""
    CREATE OR REPLACE TABLE war_vote AS
    SELECT congress, chamber, rollnumber, vote_date, bill_number, vote_question, vote_desc, yea_count, nay_count, vote_result
    FROM c.rollcalls
    WHERE vote_date >= DATE '2008-01-01'
      AND bill_number SIMILAR TO '(HCONRES|SCONRES|HJRES|SJRES)[0-9]+'
      AND (vote_desc ILIKE '%remov%Armed Forces%' OR vote_desc ILIKE '%War Powers Resolution%')
      AND vote_question NOT ILIKE '%table%' AND vote_question NOT ILIKE '%commit%' AND vote_question NOT ILIKE '%point of order%'
      AND vote_question NOT ILIKE '%previous question%' AND vote_question NOT ILIKE '%as amended%'
      AND (vote_question ILIKE '%passage%' OR vote_question ILIKE '%agreeing to the resolution%' OR vote_question ILIKE '%discharge%' OR vote_question ILIKE '%motion to proceed%'
           OR vote_question ILIKE '%veto%' OR vote_question ILIKE '%joint resolution%' OR vote_question ILIKE '%concurrent resolution%')""")
con.execute("""
    CREATE OR REPLACE TABLE war_member AS
    SELECT v.bioguide, count(*) AS n, sum(v.yea) AS constrain, count(*) FILTER (WHERE v.congress = 119) AS n119, sum(v.yea) FILTER (WHERE v.congress = 119) AS constrain119
    FROM member_vote v JOIN war_vote w USING (congress, chamber, rollnumber) GROUP BY 1""")
pd.set_option("display.width", 220)
print(con.execute("SELECT count(*) AS votes, count(*) FILTER (WHERE congress = 119) AS in_119th FROM war_vote").df().to_string(index=False))
print(con.execute("""SELECT w.chamber, v.party, count(DISTINCT v.bioguide) AS members, round(avg(v.yea) * 100, 1) AS pct_to_constrain
                     FROM member_vote v JOIN war_vote w USING (congress, chamber, rollnumber) WHERE w.congress = 119 AND v.party IN ('D', 'R') GROUP BY 1, 2 ORDER BY 1, 2""").df().to_string(index=False))
