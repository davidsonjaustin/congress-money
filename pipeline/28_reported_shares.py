"""Company-reported US government share of revenue, read directly from the 10-K filings on SEC EDGAR.

Every number below was read by hand from the filing text (Item 1A or Item 1 customer paragraph, or the revenue-by-customer note) on 2026-10-27, replacing the
earlier values that came from search-result quotations. Where a company states only dollars, the share is computed here from the filing's own dollar figures.
This script holds the numbers and writes pipeline/definitions/company_reported_share.csv; it fetches the SEC filing index only to attach the exact document URL.

Year label = calendar year of the fiscal year end less 14 days (so a 52/53-week year ending January 2 belongs to the year before), the same label the revenue
table in 24_company_dependence.py uses.

Columns: company, year, share (as the filing states it, or computed from its dollars), share_with_fms (only when the filing lets us add foreign military sales that
it reports outside its US government line; derived and approximate), basis, source_url, how_obtained.
"""
import csv
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "pipeline" / "definitions" / "company_reported_share.csv"
H = {"User-Agent": "CongressMoneyResearch personal-project research tool", "Accept-Encoding": "gzip, deflate"}
READ = "2026-10-27"

# company -> (cik, basis text)
CO = {
    "Lockheed Martin": ("936468", "Net sales derived from the U.S. Government as a prime contractor or subcontractor. Lockheed reports foreign military sales (FMS) inside its International line, so this figure excludes them"),
    "RTX (Raytheon / United Technologies)": ("101829", "Sales to the U.S. government as a share of total net sales; the filing says it EXCLUDES foreign military sales through the U.S. government and gives no FMS amount"),
    "Boeing": ("12927", "Revenue from the U.S. government including foreign military sales through the U.S. government, share of consolidated revenue (all of Boeing, mostly commercial aircraft)"),
    "General Dynamics": ("40533", "Total U.S. government revenue (DoD, other agencies and foreign military sales) as a share of total revenue, as the filing states it"),
    "Northrop Grumman": ("1133421", "Sales to the U.S. government, prime or subcontractor with the government as ultimate customer, share of sales. Foreign military sales are counted in its International line (12 to 14% of sales), not here, and the filing does not split them out"),
    "L3Harris (Harris / L3)": ("202058", "Revenue from U.S. Government customers, directly or through prime contractors, including foreign military sales funded through the U.S. Government, as the filing states it"),
    "Huntington Ingalls": ("1501585", "Revenue from federal customers divided by total sales and service revenues (customer-type table in the revenue note)"),
    "Leidos (and SAIC before 2014)": ("1336920", "Revenue from U.S. government agencies (including the military), as prime or subcontractor, share of total revenue, as the filing states it (approximately)"),
    "Science Applications International (SAIC)": ("1571123", "Revenues attributable to prime contracts with the U.S. government or subcontracts with other contractors engaged in work for the U.S. government, as the filing states it"),
    "Booz Allen Hamilton": ("1443646", "Revenue from contracts with U.S. government agencies, prime or subcontractor, as the filing states it (fiscal year ends March 31)"),
    "CACI": ("16058", "Defense and federal civilian customers together, computed as 100% minus the 'commercial and other' share in the revenue-by-customer table (fiscal year ends June 30)"),
    "KBR": ("1357615", "U.S. government revenue as a percentage of consolidated revenue (major-customer note; includes civilian agencies such as NASA)"),
    "Fluor": ("1124198", "Revenue earned from agencies of the U.S. government as a share of total revenue (largely non-defense: DOE, NASA and other civilian work)"),
    "Honeywell": ("773840", "Total sales to the U.S. government (DoD and other agencies, from the 10-K table) divided by net sales; computed here"),
    "General Electric": ("40545", "Total sales of equipment and services to agencies of the U.S. Government as a share of total revenue, as the filing states it"),
    "Textron": ("217346", "Contracts with the U.S. Government, including the U.S. Government-sponsored foreign military sales program, as a share of total revenues (approximately)"),
    "Oshkosh": ("775158", "Sales to the U.S. government as a share of net sales (approximately)"),
    "Palantir": ("1321655", "Revenue from U.S. government customers divided by total revenue; computed here (the 2024 and 2025 dollar figures are rounded to $0.1 billion in the filing, so those two shares are approximate)"),
}

# (company, year, share or (numerator, denominator), source fiscal-year label, where in the filing, share_with_fms inputs or None, extra note)
R = []


def add(company, year, share, src, where, fms=None, note=""):
    R.append((company, year, share, src, where, fms, note))


# Lockheed: stated share; FMS share of international sales is stated each year, so add FMS to the US Government line (all $M).
for yr, stated, usg, intl, fmsp, tot in [(2022, .73, 48515, 16931, .74, 65984), (2023, .73, 49423, 17644, .75, 67571), (2024, .73, 52044, 18515, .73, 71043), (2025, .72, 53412, 21343, .77, 75048)]:
    add("Lockheed Martin", yr, stated, yr, "Item 1A risk factor on reliance on the U.S. Government; sales-by-customer table; FMS share of international sales stated in Item 1", (usg, intl, fmsp, tot),
        "Filing states 72% for 2025; its own sales-by-customer table gives 71.2% ($53.4B of $75.0B)" if yr == 2025 else "")
for yr, v in [(2021, .48), (2022, .45), (2023, .46), (2024, .40), (2025, .38)]:
    add("RTX (Raytheon / United Technologies)", yr, v, 2025 if yr >= 2023 else 2023, "Sales to the U.S. government as a percentage of total net sales, in the customer table of the segment note")
for yr, v, bds in [(2020, .51, None), (2021, .49, None), (2022, .40, .89), (2023, .37, .91), (2024, .42, .91), (2025, .35, .91)]:
    add("Boeing", yr, v, 2022 if yr <= 2021 else yr, "Revenue note: 'Revenues from the U.S. government ... represented X% of consolidated revenues'",
        None, f"Its Defense, Space & Security segment alone: {round(bds * 100)}% from the U.S. government including FMS" if bds else "")
for yr, v in [(2021, .70), (2022, .70), (2023, .72), (2024, .69), (2025, .68)]:
    add("General Dynamics", yr, v, 2023 if yr == 2021 else yr, "Item 1 'U.S. Government' table: Total U.S. government revenue and % of total revenue")
for yr, v in [(2021, .85), (2022, .86), (2023, .86), (2024, .87), (2025, .84)]:
    add("Northrop Grumman", yr, v, 2023 if yr in (2021, 2022) else yr, "Revenue note, 'Sales by Customer Type' table, Total row")
for yr, v in [(2022, .74), (2023, .76), (2024, .76), (2025, .75)]:
    add("L3Harris (Harris / L3)", yr, v, yr, "Item 1 'Government Contracts' paragraph")
for yr, n, d in [(2022, 10625, 10676), (2023, 11430, 11454), (2024, 11527, 11535), (2025, 12470, 12484)]:
    add("Huntington Ingalls", yr, (n, d), 2024 if yr == 2022 else (2025 if yr == 2023 else yr), "Revenue note, 'Customer Type' table: Federal vs total sales and service revenues ($M)",
        None, "The filing also says it depends on the U.S. Government for substantially all of its business")
for yr, v in [(2022, .86), (2023, .87), (2024, .87), (2025, .87)]:
    add("Leidos (and SAIC before 2014)", yr, v, 2024 if yr in (2022, 2023) else yr, "Item 1A risk factor on dependence on U.S. government contracts")
for yr, src in [(2022, 2024), (2023, 2024), (2024, 2024), (2025, 2025), (2026, 2026)]:
    add("Science Applications International (SAIC)", yr, .98, src, "Item 1 'Key Customers' paragraph (fiscal year ends around Jan 31)")
for yr, v, src, note in [(2023, .97, 2023, ""), (2024, .98, 2024, ""), (2025, .98, 2025, "")]:
    add("Booz Allen Hamilton", yr, v, src, "Item 1A risk factor: U.S. government agencies accounted for X% of revenue", None, note)
for yr, comm, src in [(2022, .052, 2023), (2023, .052, 2023), (2024, .049, 2024), (2025, .043, 2026), (2026, .044, 2026)]:
    add("CACI", yr, round(1 - comm, 3), src, "MD&A 'Revenues by customer type' table: 100% less commercial and other")
for yr, v, src in [(2022, .61, 2024), (2023, .58, 2024), (2024, .56, 2025), (2025, .57, 2025)]:
    add("KBR", yr, v, src, "Notes, 'major customers' table: U.S. government % of consolidated revenue")
for yr, v in [(2024, .16), (2025, .17)]:
    add("Fluor", yr, v, yr, "Item 1 'Significant Clients' paragraph")
for yr, n, d in [(2023, 3358, 33009), (2024, 4266, 34717), (2025, 4752, 37442)]:
    add("Honeywell", yr, (n, d), 2025, "Item 1 'U.S. government sales' table ($M) and net sales from the income statement of the same 10-K")
for yr, v in [(2023, .14), (2024, .12), (2025, .10)]:
    add("General Electric", yr, v, 2025, "Statement of earnings note: sales of equipment and services to agencies of the U.S. Government as % of total revenue")
for yr, v in [(2022, .22), (2023, .21), (2024, .25), (2025, .27)]:
    add("Textron", yr, v, yr, "Item 1 customer paragraph: U.S. Government contracts including FMS, approximately X% of total revenues")
for yr, v in [(2022, .25), (2023, .19), (2024, .20), (2025, .20)]:
    add("Oshkosh", yr, v, yr, "Item 1 'Customers and Backlog' paragraph")
for yr, n, d, src in [(2022, 826.3, 1905.871, 2023), (2023, 921.2, 2225.012, 2023), (2024, 1200, 2865.507, 2024), (2025, 1900, 4475.446, 2025)]:
    add("Palantir", yr, (n, d), src, "MD&A: 'Revenue from U.S. government customers was ...' with total revenue from the income statement",
        None, "All governments, US and allied, were 54% of 2025 revenue" if yr == 2025 else "")


def filings(cik: str) -> dict[int, str]:
    j = requests.get(f"https://data.sec.gov/submissions/CIK{int(cik):010d}.json", headers=H, timeout=60).json()["filings"]["recent"]
    out = {}
    for form, rd, acc, doc in zip(j["form"], j["reportDate"], j["accessionNumber"], j["primaryDocument"]):
        if form == "10-K":
            out[(pd.Timestamp(rd) - pd.Timedelta(days=14)).year] = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc.replace('-', '')}/{doc}"
    return out


idx = {c: filings(cik) for c, (cik, _) in CO.items()}
rows = []
for company, year, share, src, where, fms, note in R:
    url = idx[company].get(src)
    assert url, (company, src)
    s = share[0] / share[1] if isinstance(share, tuple) else share
    if company == "Palantir" and year >= 2024:
        s = round(s, 2)  # numerator is rounded to $0.1B in the filing
    wf = ""
    if fms:
        usg, intl, fp, tot = fms
        wf = round((usg + intl * fp) / tot, 3)
    basis = CO[company][1] + (f". {note}" if note else "")
    rows.append({"company": company, "year": year, "share": round(s, 4), "share_with_fms": wf, "basis": basis, "source_url": url,
                 "how_obtained": f"Read in the 10-K on SEC EDGAR on {READ}. Where: {where}" + ("; with-FMS figure is derived: US Government sales plus the stated FMS percentage of international sales, approximate" if fms else "")})
with open(OUT, "w", encoding="utf-8", newline="") as f:
    w = csv.DictWriter(f, fieldnames=["company", "year", "share", "share_with_fms", "basis", "source_url", "how_obtained"])
    w.writeheader()
    w.writerows(rows)
d = pd.DataFrame(rows)
print(d.pivot(index="company", columns="year", values="share").round(3).to_string())
print(d[d.share_with_fms != ""][["company", "year", "share", "share_with_fms"]].to_string(index=False))
