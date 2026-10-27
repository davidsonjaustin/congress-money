"""Campaign pledges against what the member's campaign actually received.

Pledge lists live in definitions/pledges.csv with the page they were read from. For each pledge we match signers to members of the 119th Congress and report, year by
year, the money the pledge was about (for the No Fossil Fuel Money pledge: PAC gifts from oil and gas, coal and refining PACs), and how the signer voted on the coded fossil-fuel votes
next to other members of the same party.

What the pledge covers matters. The No Fossil Fuel Money pledge also covers fossil-fuel executives and lobbyists, which this data cannot separate from other donors, so
only PAC gifts are tested. The pledge list carries no signing dates, so every year since 2019 is shown and the reader can see when the money stopped or did not.

Output (data/pledges.duckdb):
  pledge_member(pledge, bioguide, name, chamber, state, party)
  pledge_money(pledge, bioguide, year, pac_pledged_industry, pac_all)
  pledge_gifts(pledge, bioguide, year, committee, amount)    each gift from a fossil-fuel PAC to a signer since 2019
  pledge_votes(bioguide, party, n, aligned)        votes on the documented fossil-fuel votes (oil and gas, coal), everyone who voted on at least 5
"""
import unicodedata
from pathlib import Path

import duckdb
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
FOSSIL = ("oil_gas", "coal_mining", "refining")


def plain(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c)).lower().replace("'", "").replace('"', "")


def main() -> None:
    p = pd.read_csv(ROOT / "pipeline" / "definitions" / "pledges.csv", dtype=str).fillna("")
    con = duckdb.connect(str(ROOT / "data" / "pledges.duckdb"))
    con.execute(f"ATTACH '{(ROOT / 'data' / 'congress.duckdb').as_posix()}' AS c (READ_ONLY)")
    con.execute(f"ATTACH '{(ROOT / 'data' / 'analysis.duckdb').as_posix()}' AS a (READ_ONLY)")
    terms = con.execute("""SELECT bioguide_id AS bioguide, bioname, state, chamber, district, CASE party_code WHEN 100 THEN 'D' WHEN 200 THEN 'R' ELSE 'I' END AS party
                           FROM c.member_terms WHERE congress = 119 AND bioguide_id IS NOT NULL""").df()
    terms["last"] = terms["bioname"].str.split(",").str[0].map(plain)
    out, miss = [], []
    for r in p.itertuples(index=False):
        words = plain(r.name).replace('"', "").split()
        cands = terms[(terms["state"] == r.state) & (terms["chamber"] == r.chamber)]
        # last name = the last word, or the last two words joined for names like "Kamlager-Dove"; try the longest match
        hit = cands[cands["last"].map(lambda l: l in plain(r.name).split() or l.replace(" ", "") in plain(r.name).replace(" ", ""))]
        if len(hit) > 1 and r.district:
            hit = hit[hit["district"].astype(str) == str(int(r.district))] if (hit["district"].astype(str) == str(int(r.district))).any() else hit.iloc[:1]
        if len(hit) == 1:
            h = hit.iloc[0]
            out.append((r.pledge, h["bioguide"], r.name, r.chamber, r.state, h["party"]))
        else:
            miss.append((r.name, r.state, len(hit)))
    pm = pd.DataFrame(out, columns=["pledge", "bioguide", "name", "chamber", "state", "party"]).drop_duplicates(["pledge", "bioguide"])
    con.execute("CREATE OR REPLACE TABLE pledge_member AS SELECT * FROM pm")
    print(f"matched {len(pm)} of {len(p)} signers; not matched: {miss}")
    # the committees the pledge is about: oil and gas, coal and refining PACs by our classification, minus names that say clean or renewable fuels (the keyword rules put
    # a House clean-energy caucus PAC and the ethanol and biodiesel trade groups under energy, and they are not fossil-fuel PACs)
    con.execute(f"""
        CREATE OR REPLACE TABLE fossil_cmte AS
        SELECT cmte_id, pac_name FROM a.committee_subsector WHERE subsector IN {FOSSIL}
          AND NOT regexp_matches(upper(pac_name), 'SUSTAINABLE|RENEWABLE|CLEAN|ETHANOL|BIODIESEL|BIOFUEL|SOLAR|WIND |GREEN|ENVIRONMENT|COEUR|GOLD|SILVER|COPPER|FREEPORT|NEWMONT|HECLA|BARRICK|LITHIUM')""")
    con.execute("""
        CREATE OR REPLACE TABLE pledge_gifts_all AS
        SELECT m.pledge, m.bioguide, year(strptime(p.TRANSACTION_DT, '%m%d%Y')) AS year, f.pac_name AS committee, sum(TRY_CAST(p.TRANSACTION_AMT AS DOUBLE)) AS amount
        FROM c.fec_pas2 p JOIN fossil_cmte f ON f.cmte_id = p.CMTE_ID
        JOIN (SELECT DISTINCT fec_id, bioguide FROM c.id_crosswalk WHERE fec_id IS NOT NULL AND bioguide IS NOT NULL) x ON x.fec_id = p.CAND_ID
        JOIN pledge_member m ON m.bioguide = x.bioguide
        WHERE p.TRANSACTION_TP = '24K' AND length(p.TRANSACTION_DT) = 8 GROUP BY ALL""")
    con.execute("""
        CREATE OR REPLACE TABLE pledge_money AS
        WITH g AS (SELECT pledge, bioguide, year, sum(amount) AS fossil FROM pledge_gifts_all GROUP BY 1, 2, 3),
             t AS (SELECT bioguide, year(week) AS year, sum(amount) AS allpac FROM a.pac_sub_weekly WHERE week <= current_date AND year(week) >= 2015 GROUP BY 1, 2)
        SELECT m.pledge, m.bioguide, t.year, coalesce(g.fossil, 0) AS pac_pledged_industry, t.allpac AS pac_all
        FROM pledge_member m JOIN t USING (bioguide) LEFT JOIN g ON g.pledge = m.pledge AND g.bioguide = m.bioguide AND g.year = t.year""")
    con.execute("CREATE OR REPLACE TABLE pledge_gifts AS SELECT * FROM pledge_gifts_all WHERE year >= 2019")
    con.execute("DROP TABLE pledge_gifts_all")
    con.execute("""
        CREATE OR REPLACE TABLE pledge_votes AS
        SELECT d.bioguide, any_value(CASE t.party_code WHEN 100 THEN 'D' WHEN 200 THEN 'R' ELSE 'I' END) AS party, count(*) AS n, sum(d.aligned)::INT AS aligned
        FROM a.donor_alignment d JOIN (SELECT bioguide_id, arg_max(party_code, congress) AS party_code FROM c.member_terms GROUP BY 1) t ON t.bioguide_id = d.bioguide
        WHERE d.sector = 'Energy & Natural Resources' AND d.subsector IN ('oil_gas', 'coal_mining') GROUP BY 1 HAVING count(*) >= 5""")
    pd.set_option("display.width", 200)
    print(con.execute("""
        SELECT y.year, count(DISTINCT m.bioguide) AS signers, count(DISTINCT m.bioguide) FILTER (WHERE y.pac_pledged_industry > 0) AS got_fossil_pac, round(sum(y.pac_pledged_industry) / 1e3) AS fossil_pac_k
        FROM pledge_member m JOIN pledge_money y USING (bioguide, pledge) GROUP BY 1 ORDER BY 1""").df().to_string(index=False))
    print(con.execute("""
        SELECT CASE WHEN v.bioguide IN (SELECT bioguide FROM pledge_member) THEN 'signers' ELSE 'other ' || v.party END AS grp, count(*) AS members, round(100 * sum(v.aligned) / sum(v.n), 1) AS pct_with_industry
        FROM pledge_votes v WHERE v.party IN ('D', 'R') GROUP BY 1 ORDER BY 1""").df().to_string(index=False))


if __name__ == "__main__":
    main()
