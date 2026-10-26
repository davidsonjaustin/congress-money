"""Split the three broad PAC sectors where industries inside them want opposite things.

  Energy & Natural Resources -> oil_gas | refining | coal_mining | electric_utilities | chemicals_forest | other_energy
  Health                     -> pharma | pharma_distribution | insurers | hospitals_providers | physicians_clinicians | other_health
  Finance, Insurance & RE    -> banks | credit_unions | securities | insurance | real_estate | accounting | other_finance

Rules are ordered regexes over the PAC's name plus its connected organization; first match wins. This is a name-based
label, so it is an estimate: check the printout (top PACs per subsector) after any edit.
Output: analysis.duckdb.committee_subsector(cmte_id, sector, subsector, pac_name)
"""
import re
from pathlib import Path

import duckdb
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent


def rx(p: str) -> re.Pattern:
    return re.compile(p)


RULES = {
    "Energy & Natural Resources": [
        ("other_energy", rx(r"UNITED MINE WORKERS")),          # a union, not the coal industry
        ("coal_mining", rx(r"\bCOAL|\bMINING\b|\bMINE\b|PEABODY|ARCH RESOURCES|CONSOL ENERGY|MURRAY ENERGY|NATIONAL MINING ASSOCIATION|MINEPAC")),
        ("refining", rx(r"VALERO|MARATHON PETROLEUM|PHILLIPS 66|HOLLYFRONTIER|HF SINCLAIR|\bPBF\b|TESORO|ANDEAVOR|WESTERN REFINING|DELEK|CVR |CALUMET|AMERICAN FUEL & PETROCHEMICAL|REFIN")),
        ("electric_utilities", rx(r"NEXTERA|DUKE ENERGY|EXELON|EDISON ELECTRIC|DOMINION|ENTERGY|PG&E|SOUTHERN COMPANY|EDISON INTERNATIONAL|AMERICAN ELECTRIC POWER|"
                                  r"FIRSTENERGY|DTE ENERGY|SEMPRA|XCEL|\bPPL\b|LG&E|RURAL ELECTRIC|NUCLEAR ENERGY INSTITUTE|ELECTRIC|\bPOWER\b|UTILIT|AMEREN|CMS ENERGY|NISOURCE|"
                                  r"CONSOLIDATED EDISON|PUBLIC SERVICE|PINNACLE WEST|ALLIANT|WEC ENERGY|EVERSOURCE|\bNRG\b|CONSTELLATION|CENTERPOINT|TENNESSEE VALLEY|AES CORP")),
        ("oil_gas", rx(r"EXXON|CHEVRON|CONOCO|OCCIDENTAL|HALLIBURTON|SCHLUMBERGER|BAKER HUGHES|WILLIAMS COMPANIES|EXPAND ENERGY|CHESAPEAKE|\bBP\b|\bSHELL\b|ENBRIDGE|TRANSCANADA|ONEOK|TARGA|CHENIERE|CONTINENTAL RESOURCES|DIAMONDBACK|DEVON|EOG|PIONEER NATURAL|"
                        r"APACHE|MURPHY OIL|MARATHON OIL|\bHESS\b|ANADARKO|NOBLE ENERGY|KINDER MORGAN|ENTERPRISE PRODUCTS|ENERGY TRANSFER|PETROLEUM|\bOIL\b|\bGAS\b|"
                        r"PIPELINE|DRILLING|\bAPI\b|INDEPENDENT PETROLEUM|IPAA|ENERGY MARKETERS|GASOLINE|FUEL")),
        ("chemicals_forest", rx(r"BASF|\bDOW\b|CHEMISTRY|CHEMICAL|PAPER|FOREST|WEYERHAEUSER|TIMBER|LUMBER|DUPONT")),
    ],
    "Health": [
        ("pharma", rx(r"PFIZER|AMGEN|ABBOTT|ELI LILLY|\bLILLY\b|MERCK|JOHNSON & JOHNSON|ZENECA|GLAXO|\bGSK\b|ABBVIE|NOVARTIS|BRISTOL|BIOGEN|GILEAD|REGENERON|SANOFI|TAKEDA|"
                      r"\bBAYER\b|GENENTECH|ROCHE|PHARMACEUTICAL RESEARCH|PHRMA|BIOTECHNOLOGY|\bBIO\b|VERTEX|ALLERGAN|\bTEVA\b|MYLAN|VIATRIS|NOVO NORDISK|BOEHRINGER|CELGENE|"
                      r"WYETH|SCHERING|PHARMA|DRUG MANUFACTURERS|GENERIC")),
        ("pharma_distribution", rx(r"MCKESSON|CENCORA|AMERISOURCE|CARDINAL HEALTH|WHOLESALE DRUG")),
        ("insurers", rx(r"ELEVANCE|ANTHEM|WELLPOINT|UNITEDHEALTH|CIGNA|HUMANA|AETNA|CENTENE|MOLINA|BLUE CROSS|HEALTH INSURANCE")),
        ("hospitals_providers", rx(r"HOSPITAL|HEALTH CARE ASSOCIATION|HEALTHCARE ASSOCIATION|NURSING|DAVITA|\bHCA\b|TENET|COMMUNITY HEALTH|DIALYSIS|ONCOLOGY|SENIORS HOUSING|HOME CARE|HOME HEALTH")),
        ("physicians_clinicians", rx(r"PHYSICIAN|SURGEON|MEDICAL ASSOCIATION|ANESTHESIOLOG|ORTHOPA?EDIC|OPTOMETR|DENTAL|DENTIST|RADIOLOG|CARDIOLOG|DERMATOLOG|OPHTHALMOLOG|"
                                      r"PEDIATRIC|PODIATRIC|OSTEOPATHIC|PATHOLOG|PSYCHIATR|PSYCHOLOG|NURSE|CHIROPRACT|PHYSICAL THERAPY|ACADEMY OF|COLLEGE OF|SOCIETY OF|VETERINARY|PHARMACISTS|"
                                      r"MEDICINE|EMERGENCY|SURGERY|UROLOG|ONCOLOGISTS")),
    ],
    "Finance, Insurance & Real Estate": [
        ("credit_unions", rx(r"CREDIT UNION")),
        ("accounting", rx(r"DELOITTE|PRICEWATERHOUSE|\bPWC\b|ERNST|KPMG|CERTIFIED PUBLIC ACCOUNTANTS|ACCOUNTING|GRANT THORNTON|\bBDO\b")),
        ("real_estate", rx(r"REALTORS|REAL ESTATE|MULTIFAMILY|APARTMENT|\bREIT|HOUSING|TITLE ASSOCIATION|HOMEBUILDERS")),
        ("insurance", rx(r"INSURANCE|\bLIFE\b|MUTUAL|AFLAC|ANNUIT|PRUDENTIAL|METLIFE|ALLSTATE|STATE FARM|LIBERTY|TRAVELERS|HARTFORD|\bAIG\b|NATIONWIDE|USAA|PROGRESSIVE|AGENTS|BROKERS|BENEFITS")),
        ("securities", rx(r"GOLDMAN|MORGAN STANLEY|\bUBS\b|FIDELITY|\bFMR\b|INVESTMENT COMPANY|SECURITIES|\bCME\b|BLACKROCK|CARLYLE|BLACKSTONE|\bKKR\b|PRIVATE EQUITY|VENTURE|HEDGE|"
                          r"ASSET MANAGEMENT|TRADING|CAPITAL MARKETS|SIFMA|NASDAQ|EXCHANGE|STATE STREET|ROWE PRICE|VANGUARD|FINSECA|INVESTMENT BANK|LAZARD")),
        ("banks", rx(r"BANKERS|\bBANK\b|BANKING|BANCORP|CITIGROUP|\bCITI\b|JPMORGAN|WELLS FARGO|CAPITAL ONE|AMERICAN EXPRESS|DISCOVER|\bVISA\b|MASTERCARD|\bPNC\b|SUNTRUST|TRUIST|REGIONS|"
                     r"FIFTH THIRD|KEYCORP|SYNCHRONY|HSBC|BARCLAYS|CONSUMER BANKERS|FINANCIAL SERVICES ROUNDTABLE|FARM CREDIT|MORTGAGE|FINANCIAL SERVICES|CREDIT|LENDING|LENDERS")),
    ],
}
DEFAULT = {"Energy & Natural Resources": "other_energy", "Health": "other_health", "Finance, Insurance & Real Estate": "other_finance"}


def main() -> None:
    con = duckdb.connect(str(ROOT / "data" / "analysis.duckdb"))
    con.execute(f"ATTACH '{(ROOT / 'data' / 'congress.duckdb').as_posix()}' AS c (READ_ONLY)")
    df = con.execute("""
        SELECT s.cmte_id, s.sector, s.name, coalesce(s.connected_org, '') AS org,
               coalesce(sum(TRY_CAST(p.TRANSACTION_AMT AS DOUBLE)) FILTER (WHERE p.TRANSACTION_TP = '24K'), 0) AS pac_k
        FROM c.committee_sector s LEFT JOIN c.fec_pas2 p ON p.CMTE_ID = s.cmte_id
        WHERE s.sector IN ('Energy & Natural Resources', 'Health', 'Finance, Insurance & Real Estate')
        GROUP BY 1, 2, 3, 4""").df()
    subs = []
    for sector, name, org in zip(df["sector"], df["name"], df["org"]):
        text = f"{name} {org}".upper()
        sub = DEFAULT[sector]
        for label, r in RULES[sector]:
            if r.search(text):
                sub = label
                break
        subs.append(sub)
    df["subsector"] = subs
    out = df[["cmte_id", "sector", "subsector", "name"]].rename(columns={"name": "pac_name"})
    con.execute("CREATE OR REPLACE TABLE committee_subsector AS SELECT * FROM out")

    print("PAC direct gifts by subsector ($M, all years) and the largest PACs in each, to eyeball the labels:")
    for (sector, sub), g in df.groupby(["sector", "subsector"]):
        g = g.sort_values("pac_k", ascending=False)
        top = "; ".join(f"{n[:34]} {v/1e6:.1f}" for n, v in zip(g["name"].head(5), g["pac_k"].head(5)))
        print(f"  {sector[:12]:12s} {sub:22s} ${g['pac_k'].sum()/1e6:7.1f}M  {len(g):>4} PACs | {top}")


if __name__ == "__main__":
    main()
