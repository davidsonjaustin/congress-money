"""Load constituency data: district / state partisan lean and ideology, per Congress.

Source: American Ideology Project (Tausanovitch & Warshaw) v2022, Harvard Dataverse doi:10.7910/DVN/BQKU4M
  aip_cd_ideology_v2022a.tab    congressional-district MRP ideology + Dem two-party presidential share
                                for the 111th, 114th, 116th, 117th, 118th Congress district maps
  aip_states_ideology_v2022a.tab / aip_state_pvote.tab   same, by state (Senate)
Output: data/analysis.duckdb.district_lean(congress, chamber, state, district, demshare_pres, pres_year,
        mrp_ideology, mrp_ideology_se, sample_size, map_congress, lines_match)

A Congress without its own district file borrows the nearest map (MAP_FOR). Where we know a state redrew
its lines in between, lines_match = 'approx' so downstream analysis can drop or flag those districts.
mrp_ideology: higher = more conservative.
"""
from pathlib import Path

import duckdb
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw" / "district"

# Congress -> district-map Congress in the AIP file. 109-112 all ran on the 2002-census maps (the 111th file),
# 113-115 on the 2012 maps (114th file), 116/117 have own files, 119 borrows the 2022 maps (118th file).
MAP_FOR = {109: 111, 110: 111, 111: 111, 112: 111, 113: 114, 114: 114, 115: 114, 116: 116, 117: 117, 118: 118, 119: 118}
# Known mid-decade redraws that make a borrowed map imperfect (state, Congress).
APPROX = ({("TX", c) for c in (109, 110, 111, 112)} | {("GA", c) for c in (109, 110)}
          | {(s, 115) for s in ("FL", "VA", "NC")}
          | {(s, 119) for s in ("AL", "LA", "NY", "NC")})
# Presidential election year whose result we attach to a Senate seat's state, by Congress.
PRES_YEAR = {109: 2008, 110: 2008, 111: 2008, 112: 2012, 113: 2012, 114: 2016, 115: 2016, 116: 2020, 117: 2020, 118: 2020, 119: 2020}


def main() -> None:
    st = pd.read_csv(RAW / "aip_states_ideology_v2022a.tab", sep="\t")
    fips_to_abb = dict(zip(st["fips"], st["abb"]))
    name_to_abb = dict(zip(st["state"], st["abb"]))

    cd = pd.read_csv(RAW / "aip_cd_ideology_v2022a.tab", sep="\t")
    cd["state"] = cd["cd_fips"] // 100
    cd["state"] = cd["state"].map(fips_to_abb)
    cd["district"] = cd["cd_fips"] % 100
    # Voteview numbers an at-large seat district 1; the AIP file uses 0.
    cd.loc[cd["district"] == 0, "district"] = 1
    cd = cd.dropna(subset=["state"]).rename(columns={"congress": "map_congress", "presidential_year": "pres_year"})
    keep = ["state", "district", "map_congress", "pres_year", "demshare_pres", "mrp_ideology", "mrp_ideology_se", "sample_size"]
    cd = cd[keep]

    rows = []
    for congress, mc in MAP_FOR.items():
        sub = cd[cd["map_congress"] == mc].copy()
        sub.insert(0, "congress", congress)
        sub.insert(1, "chamber", "House")
        sub["lines_match"] = ["approx" if (s, congress) in APPROX else "exact" for s in sub["state"]]
        rows.append(sub)

    # Senate: state-level, nearest presidential-year estimate available in the file.
    pv = pd.read_csv(RAW / "aip_state_pvote.tab", sep="\t").rename(columns={"year": "pres_year"})
    pv["state"] = pv["state"].map(name_to_abb)
    # The source omits Minnesota's 2012 row; fill any such hole with the mean of the neighbouring election years.
    full = pv.pivot(index="state", columns="pres_year", values="demshare_pres")
    for y in full.columns:
        prev, nxt = y - 4, y + 4
        fill = full[[c for c in (prev, nxt) if c in full.columns]].mean(axis=1)
        full[y] = full[y].fillna(fill)
    pv = full.reset_index().melt(id_vars="state", var_name="pres_year", value_name="demshare_pres")
    sid = st.rename(columns={"abb": "state_abb"})[["state_abb", "presidential_year", "mrp_ideology", "mrp_ideology_se", "sample_size"]]
    for congress, py in PRES_YEAR.items():
        ideo_years = sorted(sid["presidential_year"].unique())
        iy = min(ideo_years, key=lambda y: (abs(y - py), y))
        s = pv[pv["pres_year"] == py][["state", "pres_year", "demshare_pres"]].copy()
        i = sid[sid["presidential_year"] == iy].rename(columns={"state_abb": "state"})[["state", "mrp_ideology", "mrp_ideology_se", "sample_size"]]
        s = s.merge(i, on="state", how="left")
        s.insert(0, "congress", congress)
        s.insert(1, "chamber", "Senate")
        s["district"] = 0
        s["map_congress"] = congress
        s["lines_match"] = "exact"
        rows.append(s)

    out = pd.concat(rows, ignore_index=True)[["congress", "chamber", "state", "district", "demshare_pres", "pres_year",
                                              "mrp_ideology", "mrp_ideology_se", "sample_size", "map_congress", "lines_match"]]
    con = duckdb.connect(str(ROOT / "data" / "analysis.duckdb"))
    con.execute("CREATE OR REPLACE TABLE district_lean AS SELECT * FROM out")
    print("district_lean rows:", len(out))
    print(con.execute("SELECT chamber, count(*), count(demshare_pres), count(mrp_ideology), sum((lines_match='approx')::INT) FROM district_lean GROUP BY 1").fetchall())

    # Coverage check against who actually sat: every House member-term should find a district row.
    con.execute(f"ATTACH '{(ROOT / 'data' / 'congress.duckdb').as_posix()}' AS c (READ_ONLY)")
    print("\nmember-terms with no district match (House, excl. territories / DC):")
    for r in con.execute("""
        SELECT m.congress, count(*) FILTER (WHERE d.state IS NULL) AS unmatched, count(*) AS total
        FROM c.member_terms m LEFT JOIN district_lean d
          ON d.congress=m.congress AND d.chamber=m.chamber AND d.state=m.state AND d.district=m.district
        WHERE m.chamber='House' AND m.state NOT IN ('DC','PR','GU','VI','AS','MP')
        GROUP BY 1 ORDER BY 1""").fetchall():
        print(f"  {r[0]}th: {r[1]:>3} of {r[2]} unmatched")
    print("\nSenate member-terms unmatched:", con.execute("""
        SELECT count(*) FROM c.member_terms m LEFT JOIN district_lean d
          ON d.congress=m.congress AND d.chamber='Senate' AND d.state=m.state
        WHERE m.chamber='Senate' AND d.state IS NULL""").fetchone()[0])


if __name__ == "__main__":
    main()
