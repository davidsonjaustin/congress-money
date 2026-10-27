"""Classify individual donors into sectors from their stated employer + occupation.

Order of evidence: (1) employer says nothing (retired / none / self-employed ...) -> use occupation;
(2) employer matches a rule -> sector; (3) otherwise occupation; (4) else unclassified.
Every row records the rule that fired. Output: indiv.duckdb.employer_sector(employer, occupation, sector, basis)
for every (employer, occupation) pair with >= $500 total; anything not in the table is 'Other / unclassified'.
"""
import importlib.util
import re
import time
from pathlib import Path

import duckdb
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "indiv.duckdb"
MIN_PAIR_TOTAL = 500

# Reuse the PAC keyword rules (word-boundary regexes), minus their broad 'Labor' rule ("UNION" would hit
# Union Bank / Western Union / Union Pacific when applied to employers).
_spec = importlib.util.spec_from_file_location("sectors", Path(__file__).with_name("03_sectors.py"))
_sectors = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_sectors)
PAC_RULES = [(s, rx) for s, rx in _sectors.RULES_RE if s != "Labor"]


def rx(p: str) -> re.Pattern:
    return re.compile(r"\b(?:" + p + r")\b")


NO_INFO = re.compile(
    r"^(NONE|N/?A|NA|N\.A\.?|NOT EMPLOYED|NOT-EMPLOYED|UNEMPLOYED|RETIRED|SELF|SELF[- ]?EMPLOYED|HOMEMAKER|HOUSEWIFE|"
    r"HOUSE ?WIFE|HOUSEHUSBAND|STUDENT|DISABLED|REQUESTED|INFORMATION REQUESTED.*|INFO REQUESTED.*|NOT APPLICABLE|"
    r"N/A/RETIRED.*|RETIRED/.*|.*/RETIRED|\.|-|--|X+|UNKNOWN|NONE/?NONE|NOT PROVIDED|REFUSED|PENDING|"
    # job titles / placeholders typed into the employer box -- they say nothing about WHICH employer
    r"ENTREPRENEUR|CEO|OWNER|PRESIDENT|EXECUTIVE|CONSULTANT|BEST EFFORTS?|SUBJECT MATTER|AT HOME|HOME|NO EMPLOYER|"
    r"INFO\.? ?REQ\.?|.*HOMEMAKER.*|.*RETIRED.*)$")

# Employer-specific rules, checked BEFORE the generic PAC keywords. First match wins.
EMP_FIRST = [
    ("Education", rx(r"UNIVERSITY|COLLEGE|SCHOOLS?|ACADEMY|HARVARD|STANFORD|YALE|PRINCETON|COLUMBIA|MIT|SCHOOL DISTRICT")),
    ("Government / Public sector", rx(r"U\.?S\.? (GOVERNMENT|ARMY|NAVY|AIR FORCE|MARINES?|DEPARTMENT)|FEDERAL GOVERNMENT|STATE OF|CITY OF|COUNTY OF|"
                                       r"DEPARTMENT OF|DEPT\.? OF|UNITED STATES (OF AMERICA|GOVERNMENT|SENATE|HOUSE)|HOUSE OF REPRESENTATIVES|US SENATE|"
                                       r"U\.?S\.? CONGRESS|STATE GOVERNMENT|POLICE DEPARTMENT|FIRE DEPARTMENT")),
    ("Finance, Insurance & Real Estate", rx(r"ERNST & YOUNG|DELOITTE|PRICEWATERHOUSE\w*|PWC|KPMG|GRANT THORNTON|BDO|"
                                             r"BLACKSTONE|APOLLO GLOBAL|APOLLO|BAIN CAPITAL|KKR|CARLYLE|TPG|WARBURG|ADVENT|THOMA BRAVO|ARES|OAKTREE|CITADEL|"
                                             r"BRIDGEWATER|TWO SIGMA|D\.? ?E\.? SHAW|RENAISSANCE|JANE STREET|SUSQUEHANNA|VANGUARD|FIDELITY|MERRILL( LYNCH)?|"
                                             r"CAPITAL GROUP|T\.? ROWE PRICE|STATE STREET|LAZARD|EVERCORE|MORGAN|GOLDMAN( SACHS)?|JPM\w*|CITI|CITIGROUP|BARCLAYS|"
                                             r"UBS|CREDIT SUISSE|DEUTSCHE BANK|LEHMAN|BEAR STEARNS|PIMCO|BLACKROCK|SCHWAB|CBRE|JLL")),
    ("Lawyers & Lobbyists", rx(r"LLP|L\.L\.P\.?|LAW (OFFICES?|FIRM|GROUP|CENTER)|ATTORNEYS?( AT LAW)?|GOVERNMENT (AFFAIRS|RELATIONS)|PUBLIC AFFAIRS|"
                                r"BGR GROUP|VAN SCOYOC|AKIN GUMP|KIRKLAND( & ELLIS)?|LATHAM|SKADDEN|SIDLEY|JONES DAY|COVINGTON|HOLLAND & KNIGHT|"
                                r"SQUIRE PATTON|BRACEWELL|PODESTA|CASSIDY|CAPITOL COUNSEL|FEDERAL STRATEGIES|STRATEGIES GROUP|ADVOCACY")),
    ("Labor", rx(r"SEIU|TEAMSTERS|AFL-?CIO|AFSCME|UAW|IBEW|UNITE HERE|NEA|AFT|LABORERS|UNITED STEELWORKERS|MACHINISTS|IAM|CWA|AFGE|"
                 r"INTERNATIONAL BROTHERHOOD|LOCAL \d+")),
    ("Tech, Telecom & Media", rx(r"TWITTER|UBER|LYFT|AIRBNB|PAYPAL|STRIPE|SALESFORCE|ADOBE|NVIDIA|SNAP|OPENAI|ANTHROPIC|TESLA|INVARIANT|"
                                  r"NEW YORK TIMES|WASHINGTON POST|NBC|CNN|FOX NEWS|HBO|WARNER|UNIVERSAL|PARAMOUNT|SONY")),
    ("Health", rx(r"KAISER|MAYO CLINIC|CLEVELAND CLINIC|MEDICAL CENTER|HOSPITALS?|CLINIC|PHYSICIANS|MEDICAL GROUP")),
]
EMP_RULES = EMP_FIRST + PAC_RULES

OCC_RULES = [
    ("Lawyers & Lobbyists", rx(r"ATTORNEYS?|LAWYERS?|COUNSEL|LEGAL|LOBBYISTS?|PARALEGAL|ATTORNEY AT LAW")),
    ("Health", rx(r"PHYSICIANS?|DOCTORS?|SURGEONS?|DENTISTS?|NURSES?|PHARMACISTS?|M\.?D\.?|PSYCHIATRISTS?|PSYCHOLOGISTS?|THERAPISTS?|VETERINARIANS?|"
                   r"OPTOMETRISTS?|CHIROPRACTORS?|RADIOLOGISTS?|ANESTHESIOLOGISTS?|CARDIOLOGISTS?|PEDIATRICIANS?|DERMATOLOGISTS?|ORTHODONTISTS?|"
                   r"HEALTHCARE|HEALTH CARE|MEDICAL|CLINICIANS?|PHYSICIAN ASSISTANT")),
    ("Finance, Insurance & Real Estate", rx(r"BANKERS?|INVESTORS?|INVESTMENTS?|FINANCE|FINANCIAL( ADVISOR| PLANNER)?|ACCOUNTANTS?|CPA|INSURANCE|BROKERS?|TRADERS?|"
                                             r"HEDGE FUND|PRIVATE EQUITY|VENTURE CAPITAL(IST)?|WEALTH|REAL ESTATE|REALTORS?|MORTGAGE|APPRAISERS?|LOAN OFFICER")),
    ("Agribusiness & Food", rx(r"FARMERS?|RANCHERS?|AGRICULTUR\w*|GROWERS?|FARMING|CATTLE|DAIRY")),
    ("Education", rx(r"PROFESSORS?|TEACHERS?|EDUCATORS?|ACADEMIC|LECTURER|SCHOOL \w+")),
    ("Tech, Telecom & Media", rx(r"SOFTWARE|PROGRAMMERS?|COMPUTER|TECHNOLOGY|DATA SCIENTIST|CYBER\w*|WEB DEVELOPER|"
                                  r"WRITERS?|AUTHORS?|JOURNALISTS?|PRODUCERS?|ACTORS?|ACTRESS|FILM|MUSICIANS?|ARTISTS?|EDITORS?|REPORTERS?|BROADCAST\w*")),
    ("Construction", rx(r"CONSTRUCTION|CONTRACTORS?|BUILDERS?|ARCHITECTS?")),
    ("Energy & Natural Resources", rx(r"OIL|GAS|PETROLEUM|GEOLOGISTS?|ENERGY|MINING|UTILITY")),
    ("Transportation", rx(r"PILOTS?|TRUCK DRIVERS?|TRUCKERS?|AIRLINE|FLIGHT ATTENDANTS?|RAILROAD")),
    ("Government / Public sector", rx(r"GOVERNMENT|MILITARY|POLICE|FIREFIGHTERS?|CIVIL SERVANT|FEDERAL EMPLOYEE|STATE EMPLOYEE")),
    ("Retail & Consumer", rx(r"RETAIL|STORE OWNER")),
]
NOT_IDENTIFIABLE = "Not identifiable (retired / unemployed / no employer)"

# Hand labels for the largest employers the keyword rules missed (definitions/employer_overrides.csv: employer, sector, basis). They win over every rule.
_OV = Path(__file__).with_name("definitions") / "employer_overrides.csv"
OVERRIDES: dict[str, str] = {}
if _OV.exists():
    import csv as _csv
    with _OV.open(encoding="utf-8", newline="") as _f:
        OVERRIDES = {r["employer"].strip().upper(): r["sector"] for r in _csv.DictReader(_f)}


def classify(employer: str, occupation: str) -> tuple[str, str]:
    emp = (employer or "").strip().upper()
    occ = (occupation or "").strip().upper()
    informative = bool(emp) and not NO_INFO.match(emp)
    if emp in OVERRIDES:
        return OVERRIDES[emp], "employer:hand-labeled"
    if informative:
        for sector, r in EMP_RULES:
            m = r.search(emp)
            if m:
                return sector, f"employer:{m.group(0).lower()}"
    for sector, r in OCC_RULES:
        m = r.search(occ)
        if m:
            return sector, f"occupation:{m.group(0).lower()}"
    if not informative:
        return NOT_IDENTIFIABLE, "no employer, occupation uninformative"
    return "Other / unclassified", "employer unmatched"


def main() -> None:
    t0 = time.time()
    con = duckdb.connect(str(DB))
    pairs = con.execute(f"""
        SELECT coalesce(employer,''), coalesce(occupation,''), sum(total)
        FROM indiv_agg GROUP BY 1, 2 HAVING sum(total) >= {MIN_PAIR_TOTAL}""").fetchall()
    print(f"classifying {len(pairs):,} (employer, occupation) pairs ...")
    cache: dict[tuple[str, str], tuple[str, str]] = {}
    out = []
    for emp, occ, _ in pairs:
        key = (emp, occ)
        res = cache.get(key) or classify(emp, occ)
        cache[key] = res
        out.append((emp, occ, res[0], res[1]))
    df = pd.DataFrame(out, columns=["employer", "occupation", "sector", "basis"])
    con.execute("CREATE OR REPLACE TABLE employer_sector AS SELECT * FROM df")  # bulk: executemany is far too slow here
    print(f"done in {time.time()-t0:.0f}s\n\nIndividual money by classified sector (all cycles, $M):")
    for sector, mm, pct in con.execute("""
        WITH t AS (SELECT coalesce(s.sector, 'Other / unclassified') sector, a.total
                   FROM indiv_agg a LEFT JOIN employer_sector s
                     ON s.employer = coalesce(a.employer,'') AND s.occupation = coalesce(a.occupation,''))
        SELECT sector, round(sum(total)/1e6,1), round(100*sum(total)/(SELECT sum(total) FROM t),1)
        FROM t GROUP BY 1 ORDER BY 2 DESC""").fetchall():
        print(f"  {sector:55s} ${mm:>8,.1f}M  {pct:>5.1f}%")


if __name__ == "__main__":
    main()
