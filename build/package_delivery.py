"""
package_delivery.py
===================
Bundles everything needed to open the solution into one zip, so it can be moved
to another machine without the repo.

Contents:
  MerchantVoucherIntelligence.pbit   the Power BI template
  data/gold/*.csv                    the tables it loads
  index.html                         the offline dashboard (works on its own)
  OPEN_ME_FIRST.txt                  three-step instructions

Run:  python build/package_delivery.py
"""

from __future__ import annotations

import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GOLD = ROOT / "data" / "gold"
OUT = ROOT / "MerchantVoucherIntelligence_PowerBI.zip"

INSTRUCTIONS = """\
MERCHANT SALES & VOUCHER INTELLIGENCE - Power BI deliverable
============================================================

WHAT IS IN HERE
  MerchantVoucherIntelligence.pbit   Power BI template - the report + model
  data/gold/                         the 13 tables it loads
  index.html                         the same report as a standalone web page

--------------------------------------------------------------------
OPTION 1 - just look at it (no install, 5 seconds)
--------------------------------------------------------------------
Double-click index.html. It opens in any browser and needs nothing else -
no Power BI, no internet, no data connection. Six pages, working slicers,
drill-through, and a South African province map.

--------------------------------------------------------------------
OPTION 2 - open it in Power BI Desktop
--------------------------------------------------------------------
1. Extract this whole zip to a folder, keeping the structure intact.

2. Double-click MerchantVoucherIntelligence.pbit.
   Power BI Desktop will ask for one parameter, GoldFolder.

3. Paste the full path to the extracted data\\gold folder, for example
      C:\\Users\\You\\Downloads\\MerchantVoucherIntelligence\\data\\gold
   then click Load.

   Desktop builds the model, loads 150,000 rows and opens the report.

4. File > Save As  ->  MerchantVoucherIntelligence.pbix

   That save is what turns the template into a .pbix. A .pbix stores its
   model as a compressed Analysis Services backup that only Power BI
   Desktop can write, which is why this ships as a template - Desktop has
   to do that step itself.

--------------------------------------------------------------------
WHAT YOU GET
--------------------------------------------------------------------
Model     13 tables, 14 relationships (one inactive role-playing date),
          50 DAX measures in 7 display folders
Report    6 pages - Executive Overview, Merchant Analysis, Operational
          View, Geographic Intelligence, Intelligence & ML, Insights

--------------------------------------------------------------------
THE THREE FINDINGS
--------------------------------------------------------------------
1. The support queue is worked in REVERSE priority order.
   Critical: 12h target, 52.7h actual, 98.3% breach.
   Low:      48h target, 11.3h actual,  0.2% breach.
   Cheapest fix available. Needs no new data.

2. Umhlanga Value Mart fell 44.7% month on month - on transaction volume
   (-48.1%), not basket size (+6.4%) - in the same month its tickets went
   from 3 to 37. Operational, not market.

3. Ticket volume leads sales (r = -0.49); resolution speed does not
   (r = +0.19). Durban Cash Hub, the largest merchant, has had an 8-fold
   ticket rise since June with sales not yet affected.

--------------------------------------------------------------------
HONEST NOTE
--------------------------------------------------------------------
The .pbit was authored to the Power BI file format and statically
validated - every one of the 55 visuals references a field that exists in
the model, the package structure and encodings are correct, and the model
is internally consistent. But Power BI Desktop was not installed on the
build machine, so the template has never actually been rendered.

index.html HAS been tested end to end in a browser. If anything in the
.pbit misbehaves on first open, that is the surface to fall back on.
"""


def main() -> None:
    pbit = ROOT / "powerbi" / "MerchantVoucherIntelligence.pbit"
    dash = ROOT / "dashboard" / "index.html"
    for f in (pbit, dash):
        if not f.exists():
            raise SystemExit(f"missing {f} - run build/run_all.py first")

    with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        z.writestr("OPEN_ME_FIRST.txt", INSTRUCTIONS)
        z.write(pbit, "MerchantVoucherIntelligence.pbit")
        z.write(dash, "index.html")
        for csv in sorted(GOLD.glob("*.csv")):
            z.write(csv, f"data/gold/{csv.name}")

    n_csv = len(list(GOLD.glob("*.csv")))
    print(f"Wrote {OUT.name}  ({OUT.stat().st_size / 1024 / 1024:.1f} MB)")
    print(f"  MerchantVoucherIntelligence.pbit")
    print(f"  index.html")
    print(f"  data/gold/ - {n_csv} CSVs")
    print(f"  OPEN_ME_FIRST.txt")


if __name__ == "__main__":
    main()
