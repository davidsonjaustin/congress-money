"""Assign each FEC committee a sector.

Rule-based and deliberately transparent: every assignment records the rule that matched
(`basis`), so the UI can show *why* a PAC was labelled as it was. Manual corrections in
pipeline/sector_overrides.csv (cmte_id,sector,note) always win.
"""
import csv
import re
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "congress.duckdb"
OVERRIDES = Path(__file__).with_name("sector_overrides.csv")
CODES = Path(__file__).with_name("sector_codes.csv")  # compact id,code labels from committee names
CODE_SECTORS = {
    "FIN": "Finance, Insurance & Real Estate", "DEF": "Defense & Aerospace", "HEA": "Health",
    "ENE": "Energy & Natural Resources", "TEC": "Tech, Telecom & Media", "TRA": "Transportation",
    "AGR": "Agribusiness & Food", "CON": "Construction", "LAW": "Lawyers & Lobbyists",
    "RET": "Retail & Consumer", "LAB": "Labor", "MAN": "Manufacturing & Industrial",
    "BUS": "General Business Associations", "TRV": "Travel, Lodging & Leisure",
    "IDE": "Ideological / Single-Issue", "CAU": "Caucus & Party-Aligned PACs", "EDU": "Education",
}

# Ordered: first match wins. Patterns are matched with word boundaries on
# "<committee name> | <connected org name>".
RULES: list[tuple[str, str]] = [
    ("Labor", r"UNION|AFL-?CIO|TEAMSTERS|IBEW|ELECTRICAL WORKERS|LABORERS|STEELWORKERS|MACHINISTS|CARPENTERS|PLUMBERS|PIPEFITTERS|AFSCME|SEIU|UAW|AUTO WORKERS|FIREFIGHTERS|COMMUNICATIONS WORKERS|LETTER CARRIERS|OPERATING ENGINEERS|IRONWORKERS|BRICKLAYERS|SHEET METAL|BOILERMAKERS|NATIONAL EDUCATION ASSOCIATION|AMERICAN FEDERATION|TEACHERS|BUILDING TRADES|LONGSHORE|FLIGHT ATTENDANTS|PILOTS ASSOCIATION|AIR LINE PILOTS|TRANSPORT WORKERS|UNITED FOOD AND COMMERCIAL|NURSES UNITED|MARINE ENGINEERS|AIR TRAFFIC CONTROLLERS|POSTAL SUPERVISORS|POSTMASTERS"),
    ("Defense & Aerospace", r"LOCKHEED|BOEING|RAYTHEON|NORTHROP|GENERAL DYNAMICS|HONEYWELL|AEROSPACE|DEFENSE|BAE SYSTEMS|HUNTINGTON INGALLS|LEIDOS|BOOZ ALLEN|SAIC|TEXTRON|L3HARRIS|L-3|LOCKHEED|SPACEX|ANDURIL|PALANTIR"),
    ("Health", r"HEALTH|MEDICAL|HOSPITAL|PHARMA\w*|DRUG|BIOTECH\w*|PFIZER|MERCK|ABBVIE|AMGEN|LILLY|JOHNSON & JOHNSON|CVS|WALGREENS|ANTHEM|UNITEDHEALTH|CIGNA|HUMANA|PHYSICIANS?|DENTAL|DENTISTS?|NURSES?|OPTOMETR\w*|CHIROPRACT\w*|AMBULANCE|PHARMACISTS?|SURGEONS?|ANESTHESIOLOG\w*|ORTHOPAEDIC|PEDIATRIC\w*|CLINICAL|MEDICINE|MEDICARE|PSYCHIATR\w*|RADIOLOG\w*|OPHTHALM\w*|DERMATOL\w*|HMO|BLUE CROSS"),
    ("Finance, Insurance & Real Estate", r"BANK\w*|BANC\w*|FINANCIAL?|CAPITAL|INSURANCE|MORTGAGE|CREDIT UNIONS?|SECURITIES|INVESTMENT\w*|REALTORS?|REAL ESTATE|GOLDMAN|JPMORGAN|MORGAN STANLEY|CITIGROUP|WELLS FARGO|VISA|MASTERCARD|BLACKROCK|HEDGE|PRIVATE EQUITY|ASSET MANAGEMENT|AFLAC|PRUDENTIAL|METLIFE|TITLE (INSURANCE|COMPANY)|BROKERS?|BANKERS|LENDING|LENDERS|ACCOUNTANTS|CPAS?|CPA|ERNST & YOUNG|DELOITTE|PRICEWATERHOUSE\w*|KPMG|USAA|UNITED SERVICES AUTOMOBILE|REALTY|PROPERTIES|APARTMENT"),
    ("Energy & Natural Resources", r"OIL|GAS|PETROLEUM|ENERGY|ELECTRIC|POWER|UTILIT\w*|COAL|MINING|EXXON\w*|CHEVRON|KOCH|CONOCO\w*|NUCLEAR|PIPELINES?|SOLAR|WIND|REFIN\w*|FUELS?|PROPANE|TIMBER|FOREST\w*|PAPER|WATER|MINERALS?|STEEL|CHEMICAL\w*|DOW"),
    ("Tech, Telecom & Media", r"GOOGLE|ALPHABET|MICROSOFT|APPLE|AMAZON|META|FACEBOOK|ORACLE|IBM|INTEL|CISCO|QUALCOMM|DELL|SOFTWARE|TECHNOLOG\w*|COMPUTER\w*|INTERNET|ELECTRONICS?|SEMICONDUCTOR\w*|AT&T|VERIZON|COMCAST|T-MOBILE|CHARTER|TELECOM\w*|WIRELESS|CABLE|BROADCAST\w*|COMMUNICATIONS|MEDIA|NETFLIX|DISNEY|NEWS CORP|TIME WARNER|VIACOM|ENTERTAINMENT|MOTION PICTURE|BROADBAND|CYBER\w*|DATA"),
    ("Transportation", r"AIRLINES?|AIR LINES|DELTA|FEDEX|UPS|UNITED PARCEL|RAIL\w*|CSX|UNION PACIFIC|NORFOLK|BNSF|TRUCK\w*|AUTOMOBILE|AUTOMOTIVE|MOTORS?|FORD|TOYOTA|HONDA|DEALERS?|SHIPPING|MARITIME|TRANSPORT\w*|AVIATION|AIRPORTS?|AIRCRAFT|TRUCKERS|FREIGHT|LOGISTICS"),
    ("Agribusiness & Food", r"FARM\w*|AGRI\w*|CROPS?|CORN|SOYBEAN|WHEAT|COTTON|SUGAR|DAIRY|CATTLE\w*|BEEF|PORK|POULTRY|EGG|FOODS?|BEVERAGES?|COCA|PEPSI|TYSON|CARGILL|MONSANTO|BAYER|SYNGENTA|TOBACCO|ALTRIA|FERTILIZER|ETHANOL|BREWERS?|WINE|SPIRITS|DISTILL\w*|BEER|CANDY|CONFECTION\w*|RESTAURANT\w*|GROCER\w*|RANCHERS?"),
    ("Construction", r"CONSTRUCT\w*|CONTRACTORS?|BUILDERS?|HOME BUILDERS|ENGINEERING|CIVIL ENGINEERS|ARCHITECTS?|CEMENT|CONCRETE|ASPHALT|LUMBER|HOUSING"),
    ("Lawyers & Lobbyists", r"ATTORNEYS?|TRIAL LAWYERS|LAWYERS?|LOBBY\w*|AKIN GUMP|HOLLAND & KNIGHT|SQUIRE PATTON|BRACEWELL|DLA PIPER"),
    ("Retail & Consumer", r"RETAIL\w*|WALMART|HOME DEPOT|TARGET|COSTCO|STORES?|MERCHANTS?|SHOPPING|CONSUMER"),
]
RULES_RE = [(s, re.compile(r"\b(?:" + p + r")\b")) for s, p in RULES]


def classify(name: str, org: str, cmte_tp: str, dsgn: str, org_tp: str) -> tuple[str, str]:
    text = f"{name or ''} | {org or ''}".upper()
    if re.search(r"\bWINRED\b|\bACTBLUE\b", text):
        return "Conduit (excluded)", "conduit"
    if cmte_tp in ("H", "S", "P"):
        return "Candidate committee", f"cmte_tp={cmte_tp}"
    if cmte_tp in ("X", "Y", "Z"):
        return "Party committee", f"cmte_tp={cmte_tp}"
    if dsgn == "D":
        return "Leadership PAC", "designation=D"
    if dsgn == "J" or cmte_tp == "U":
        return "Joint fundraising", "designation=J"
    for sector, rx in RULES_RE:
        m = rx.search(text)
        if m:
            return sector, f"keyword:{m.group(0).lower()}"
    if org_tp == "L":
        return "Labor", "org_tp=L"
    if org_tp in ("C", "M", "T", "V", "W"):
        # Tied to a company/association but no keyword matched: needs a sector in overrides.
        return "Business (sector not yet assigned)", f"org_tp={org_tp}"
    if cmte_tp in ("N", "Q", "O", "V", "W"):
        return "Ideological / Single-Issue / Unsorted", "nonconnected"
    return "Unclassified", "none"


def main() -> None:
    con = duckdb.connect(str(DB))
    rows = con.execute("""
        SELECT CMTE_ID, arg_max(CMTE_NM, cycle), arg_max(CONNECTED_ORG_NM, cycle), arg_max(CMTE_TP, cycle),
               arg_max(CMTE_DSGN, cycle), arg_max(ORG_TP, cycle)
        FROM fec_cm GROUP BY 1
    """).fetchall()
    overrides = {}
    if OVERRIDES.exists():
        with OVERRIDES.open(encoding="utf-8") as f:
            overrides = {r["cmte_id"]: r for r in csv.DictReader(f)}

    codes = {}
    if CODES.exists():
        with CODES.open(encoding="utf-8") as f:
            codes = {r["cmte_id"]: CODE_SECTORS[r["code"]] for r in csv.DictReader(f)}

    out = []
    for cid, nm, org, tp, dsgn, orgtp in rows:
        if cid in overrides:
            o = overrides[cid]
            sector, basis = o["sector"], f'manual override ({o["confidence"]}): {o["note"]}'
        elif cid in codes:
            sector, basis = codes[cid], "name-based label (judgment)"
        else:
            sector, basis = classify(nm, org, tp, dsgn, orgtp)
        out.append((cid, nm, org, sector, basis))
    con.execute("CREATE OR REPLACE TABLE committee_sector (cmte_id VARCHAR, name VARCHAR, connected_org VARCHAR, sector VARCHAR, basis VARCHAR)")
    con.executemany("INSERT INTO committee_sector VALUES (?,?,?,?,?)", out)

    print("Direct PAC contributions (24K) by sector, $M, all cycles:")
    for sector, n, mm in con.execute("""
        SELECT s.sector, count(*), round(sum(TRY_CAST(p.TRANSACTION_AMT AS DOUBLE))/1e6, 1)
        FROM fec_pas2 p JOIN committee_sector s ON s.cmte_id = p.CMTE_ID
        WHERE p.TRANSACTION_TP = '24K' GROUP BY 1 ORDER BY 3 DESC""").fetchall():
        print(f"  {sector:36s} {n:>9,d} rows  ${mm:>9,.1f}M")


if __name__ == "__main__":
    main()
