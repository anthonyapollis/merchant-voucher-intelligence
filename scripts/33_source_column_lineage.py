"""
33_source_column_lineage.py — reconcile the SUPPLIED DataDictionary.csv against reality.

The drop contains six files. Four are data, one is the README, and one — DataDictionary.csv —
was not referenced anywhere in this build until now. That was an oversight: it is the panel's
own description of their data, and ignoring it means ignoring the one place they stated what
they think each column means.

Reconciling it produces three things worth having:

  1. Coverage. The supplied dictionary documents 12 columns. The four CSVs contain more than
     that, so most columns arrive undocumented and every meaning below is inferred from
     profiling. Stating which is which matters — an inferred meaning is an assumption.

  2. Column-level lineage. Every source column is traced to the gold table and column it
     ends up in, or explicitly marked DROPPED with the reason. A column that silently
     disappears between source and star schema is indistinguishable from a bug.

  3. A check that nothing vanished by accident. Anything neither mapped nor deliberately
     dropped fails the build.
"""
import csv
import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SRC = Path.home() / "Downloads" / "BI_Developer_Interview_Synthetic_CSV_Data"
GOLD = ROOT / "data" / "gold"
OUT = ROOT / "docs"
OUT.mkdir(exist_ok=True)

FILES = ["MerchantReference.csv", "MerchantSales.csv",
         "VoucherRedemptions.csv", "SupportTickets.csv"]

# Where each source column ends up. "DROPPED" carries the reason, because dropping a column
# from a warehouse is a decision, not an accident.
LINEAGE = {
    ("MerchantReference.csv", "MerchantID"): ("DimMerchant", "MerchantKey", "Surrogate key issued; natural key retained as MerchantID"),
    ("MerchantReference.csv", "Merchant"): ("DimMerchant", "Merchant", ""),
    ("MerchantReference.csv", "Region"): ("DimMerchant", "Region", "Single source of truth for region — the copy on the sales fact is dropped"),
    ("MerchantReference.csv", "Channel"): ("DimMerchant", "Channel", ""),
    ("MerchantReference.csv", "ActiveStatus"): ("DimMerchant", "ActiveStatus", "Also surfaced as active_status on MerchantValueRisk — a churned merchant must not be scored as an attrition risk"),
    ("MerchantReference.csv", "OnboardedDate"): ("DimMerchant", "OnboardedDate", "Derives TenureMonths and TenureBand"),
    ("MerchantReference.csv", "AccountManager"): ("DimMerchant", "AccountManager", "The owner an at-risk merchant is routed to — carried onto MerchantValueRisk so the risk register is actionable"),
    ("MerchantReference.csv", "BaseMonthlySalesTarget"): ("DimMerchant", "BaseMonthlySalesTarget", "Denominator for target attainment, which is the measure behind the tickets-vs-attainment question"),

    ("MerchantSales.csv", "Date"): ("FactMerchantSales", "DateKey", "Converted to an integer date key joining DimDate"),
    ("MerchantSales.csv", "MerchantID"): ("FactMerchantSales", "MerchantKey", "Resolved to the surrogate key"),
    ("MerchantSales.csv", "Merchant"): ("DROPPED", "", "100% agreement with MerchantReference (profiled). Keeping it would allow two competing versions of merchant name in one model"),
    ("MerchantSales.csv", "Region"): ("DROPPED", "", "100% agreement with MerchantReference (profiled). Region belongs on the dimension"),
    ("MerchantSales.csv", "Channel"): ("DROPPED", "", "100% agreement with MerchantReference (profiled)"),
    ("MerchantSales.csv", "VoucherType"): ("FactMerchantSales", "VoucherTypeKey", "Resolved against DimVoucherType — conformed with the redemption fact"),
    ("MerchantSales.csv", "SalesValue"): ("FactMerchantSales", "SalesValue", "Additive measure"),
    ("MerchantSales.csv", "Transactions"): ("FactMerchantSales", "Transactions", "Additive measure"),

    ("VoucherRedemptions.csv", "VoucherID"): ("FactVoucherRedemptions", "VoucherID", "Degenerate dimension — unique by construction, which is why duplicate-redemption fraud cannot be detected in this extract"),
    ("VoucherRedemptions.csv", "MerchantID"): ("FactVoucherRedemptions", "MerchantKey", ""),
    ("VoucherRedemptions.csv", "VoucherType"): ("FactVoucherRedemptions", "VoucherTypeKey", ""),
    ("VoucherRedemptions.csv", "VoucherValue"): ("FactVoucherRedemptions", "VoucherValue", ""),
    ("VoucherRedemptions.csv", "SoldDate"): ("FactVoucherRedemptions", "SoldDateKey", "ACTIVE relationship to DimDate"),
    ("VoucherRedemptions.csv", "Redeemed"): ("FactVoucherRedemptions", "IsRedeemed", "Yes/No text converted to 1/0 so it sums"),
    ("VoucherRedemptions.csv", "RedeemedDate"): ("FactVoucherRedemptions", "RedeemedDateKey", "INACTIVE relationship, activated by USERELATIONSHIP. Blank when unredeemed — kept blank, not defaulted"),
    ("VoucherRedemptions.csv", "Merchant"): ("DROPPED", "", "Redundant copy of the merchant name — resolved via DimMerchant"),

    ("SupportTickets.csv", "TicketID"): ("FactSupportTickets", "TicketID", "Degenerate dimension"),
    ("SupportTickets.csv", "MerchantID"): ("FactSupportTickets", "MerchantKey", ""),
    ("SupportTickets.csv", "Date"): ("FactSupportTickets", "DateKey", "Ticket created date"),
    ("SupportTickets.csv", "Merchant"): ("DROPPED", "", "Redundant copy of the merchant name — resolved via DimMerchant"),
    ("SupportTickets.csv", "Region"): ("DROPPED", "", "Redundant copy of region — resolved via DimMerchant so one hierarchy governs every fact"),
    ("SupportTickets.csv", "Status"): ("FactSupportTickets", "Status", "Derives IsOpen. Open tickets have elapsed-hours in ResolutionHours rather than a final duration, so they are excluded from average resolution time"),
    ("SupportTickets.csv", "Priority"): ("FactSupportTickets", "PriorityKey", "Resolved against DimPriority"),
    ("SupportTickets.csv", "TicketType"): ("FactSupportTickets", "TicketTypeKey", "Resolved against DimTicketType"),
    ("SupportTickets.csv", "ResolutionHours"): ("FactSupportTickets", "ResolutionHours", ""),
    ("SupportTickets.csv", "SLAHours"): ("FactSupportTickets", "SLAHours", "Stored ON the fact, not resolved from DimPriority, so a future SLA policy change cannot retrospectively restate whether a historic ticket breached"),
}

# ---------------------------------------------------------------- read supplied dictionary
documented = {}
with open(SRC / "DataDictionary.csv", encoding="utf-8-sig") as fh:
    for r in csv.DictReader(fh):
        documented[(r["File"].strip(), r["Column"].strip())] = r["Description"].strip()

rows = []
missing_lineage = []
for f in FILES:
    cols = list(pd.read_csv(SRC / f, nrows=0).columns)
    for c in cols:
        key = (f, c)
        desc = documented.get(key, "")
        if key in LINEAGE:
            tbl, gcol, note = LINEAGE[key]
        else:
            tbl, gcol, note = "UNMAPPED", "", ""
            missing_lineage.append(f"{f}.{c}")
        rows.append({
            "SourceFile": f,
            "SourceColumn": c,
            "DocumentedBySupplier": "Yes" if desc else "No  (meaning inferred by profiling)",
            "SupplierDescription": desc,
            "GoldTable": tbl,
            "GoldColumn": gcol,
            "ModellingNote": note,
        })

# dictionary entries that name a column which does not exist in the file
orphans = []
actual = {(f, c) for f in FILES for c in pd.read_csv(SRC / f, nrows=0).columns}
for key in documented:
    if key not in actual:
        orphans.append(f"{key[0]}.{key[1]}")

df = pd.DataFrame(rows)
out = OUT / "source_column_lineage.csv"
df.to_csv(out, index=False, encoding="utf-8")

n = len(df)
doc = int((df["DocumentedBySupplier"] == "Yes").sum())
dropped = int((df["GoldTable"] == "DROPPED").sum())

print(f"  source columns across {len(FILES)} files : {n}")
print(f"  documented in supplied DataDictionary   : {doc}  ({doc/n:.0%})")
print(f"  meaning inferred by profiling           : {n - doc}")
print(f"  carried into the star schema            : {n - dropped - len(missing_lineage)}")
print(f"  deliberately dropped (reason recorded)  : {dropped}")
if orphans:
    print(f"  dictionary entries with no such column  : {', '.join(orphans)}")
print(f"  wrote {out.relative_to(ROOT)}")

if missing_lineage:
    raise SystemExit("Source columns with no recorded destination — a column must be mapped "
                     "or explicitly dropped, never silently lost:\n  "
                     + "\n  ".join(missing_lineage))
