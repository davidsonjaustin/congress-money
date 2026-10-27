"""Lobbying endpoints for every industry: spending over time, next to PAC gifts and federal contracts, top clients, issue areas and the most-lobbied bills.

Reads data/lobbying.duckdb (pipeline/32_lobbying.py), attached read-only on first use.
"""
from fastapi import APIRouter, HTTPException

from server.api import attach_once, db, rows

router = APIRouter()

# Senate LDA general issue codes (the filing form's list)
ISSUES = {
    "ACC": "Accounting", "ADV": "Advertising", "AER": "Aerospace", "AGR": "Agriculture", "ALC": "Alcohol & Drug Abuse", "ANI": "Animals", "APP": "Apparel/Clothing Industry/Textiles",
    "ART": "Arts/Entertainment", "AUT": "Automotive Industry", "AVI": "Aviation/Aircraft/Airlines", "BAN": "Banking", "BNK": "Bankruptcy", "BEV": "Beverage Industry",
    "BUD": "Budget/Appropriations", "CDT": "Commodities (Big Ticket)", "CHM": "Chemicals/Chemical Industry", "CIV": "Civil Rights/Civil Liberties", "CAW": "Clean Air & Water (Quality)",
    "CSP": "Consumer Issues/Safety/Protection", "CON": "Constitution", "CPI": "Computer Industry", "CPT": "Copyright/Patent/Trademark", "DEF": "Defense", "DOC": "District of Columbia",
    "DIS": "Disaster Planning/Emergencies", "ECN": "Economics/Economic Development", "EDU": "Education", "ENG": "Energy/Nuclear", "ENV": "Environmental/Superfund", "FAM": "Family Issues/Abortion/Adoption",
    "FIR": "Firearms/Guns/Ammunition", "FIN": "Financial Institutions/Investments/Securities", "FOO": "Food Industry", "FOR": "Foreign Relations", "FUE": "Fuel/Gas/Oil",
    "GAM": "Gaming/Gambling/Casino", "GOV": "Government Issues", "HCR": "Health Issues", "HOM": "Homeland Security", "HOU": "Housing", "IMM": "Immigration", "IND": "Indian/Native American Affairs",
    "INS": "Insurance", "LBR": "Labor Issues/Antitrust/Workplace", "LAW": "Law Enforcement/Crime/Criminal Justice", "MAN": "Manufacturing", "MAR": "Marine/Maritime/Boating/Fisheries",
    "MIA": "Media (Information/Publishing)", "MED": "Medical/Disease Research/Clinical Labs", "MMM": "Medicare/Medicaid", "MON": "Minting/Money/Gold Standard", "NAT": "Natural Resources",
    "PHA": "Pharmacy", "POS": "Postal", "RRR": "Railroads", "RES": "Real Estate/Land Use/Conservation", "REL": "Religion", "RET": "Retirement", "ROD": "Roads/Highway", "SCI": "Science/Technology",
    "SMB": "Small Business", "SPO": "Sports/Athletics", "TAR": "Miscellaneous Tariff Bills", "TAX": "Taxation/Internal Revenue Code", "TEC": "Telecommunications", "TOB": "Tobacco",
    "TOR": "Torts", "TRD": "Trade (Domestic & Foreign)", "TRA": "Transportation", "TOU": "Travel/Tourism", "TRU": "Trucking/Shipping", "UNM": "Unemployment", "URB": "Urban Development/Municipal",
    "UTI": "Utilities", "VET": "Veterans", "WAS": "Waste (hazardous/solid/interstate/nuclear)", "WEL": "Welfare",
}


def ensure() -> None:
    attach_once("lob", "lobbying.duckdb")


@router.get("/api/lobbying/overview")
def overview():
    """Spending by sector and year, beside PAC gifts, employee gifts and contracts; how much spend could be put in an industry; the biggest clients in each."""
    ensure()
    with db() as con:
        years = rows(con, "SELECT sector, year, sum(spend) AS spend, sum(clients) AS clients FROM lob.industry_year GROUP BY 1, 2 ORDER BY 1, 2")
        money = rows(con, "SELECT sector, year, lobbying, pac, indiv, contracts FROM lob.money_year ORDER BY sector, year")
        cover = rows(con, """SELECT l.year, l.labelled, u.spend AS unlabelled FROM (SELECT year, sum(spend) AS labelled FROM lob.client_year GROUP BY 1) l
                             JOIN lob.unlabelled u USING (year) ORDER BY 1""")
        top = rows(con, """
            SELECT sector, client_id, any_value(client_name) AS name, any_value(label) AS label, sum(spend) AS spend, sum(spend) FILTER (WHERE year >= 2023) AS recent
            FROM lob.client_year GROUP BY sector, client_id QUALIFY row_number() OVER (PARTITION BY sector ORDER BY sum(spend) DESC) <= 12 ORDER BY sector, spend DESC""")
    slugs = {}
    if attach_once("co", "companies.duckdb", required=False):
        with db() as con:
            slugs = {r["client_id"]: r["slug"] for r in rows(con, "SELECT client_id, slug FROM co.client_company")}
    by = {}
    for r in top:
        r["slug"] = slugs.get(r["client_id"])
        by.setdefault(r["sector"], []).append(r)
    return {"years": years, "money": money, "coverage": cover, "top_clients": by}


@router.get("/api/lobbying/sector")
def sector(sector: str):
    """One sector: its issue areas, the bills its clients lobbied most with what happened to them, and the yearly spend of its biggest clients."""
    ensure()
    with db() as con:
        iss = rows(con, """SELECT issue_code AS code, sum(filings) AS filings FROM lob.issue_year WHERE sector = ? AND year >= 2018 GROUP BY 1 ORDER BY 2 DESC LIMIT 10""", [sector])
        for r in iss:
            r["name"] = ISSUES.get(r["code"], r["code"])
        bills = rows(con, """SELECT bill, congress, any_value(title) AS title, max(became_law)::BOOLEAN AS became_law, max(clients) AS clients, max(filings) AS filings,
                                    any_value(house_vote) AS house_vote, any_value(senate_vote) AS senate_vote
                             FROM lob.bill_lobbied WHERE sector = ? GROUP BY bill, congress ORDER BY max(clients) DESC, max(filings) DESC LIMIT 25""", [sector])
        series = rows(con, """
            WITH t AS (SELECT client_id FROM lob.client_year WHERE sector = ? GROUP BY 1 ORDER BY sum(spend) DESC LIMIT 5)
            SELECT any_value(client_name) AS name, year, sum(spend) AS spend FROM lob.client_year WHERE client_id IN (SELECT client_id FROM t) AND sector = ? GROUP BY client_id, year ORDER BY 1, 2""", [sector, sector])
    return {"issues": iss, "bills": bills, "series": series}
