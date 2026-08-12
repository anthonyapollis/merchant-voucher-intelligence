"""
42_build_data_dictionary.py — a data dictionary generated from the tables themselves.

Written from the gold layer at build time rather than maintained by hand. A hand-kept
dictionary is wrong the first time a column is added and nobody updates the document; this
one cannot drift, because it reads the actual files.

Column descriptions come from three places, in order of authority:

  1. The supplied DataDictionary.csv — the data owner's own words, quoted verbatim.
  2. docs/source_column_lineage.csv — where a source column landed, and any modelling note.
  3. Naming conventions applied as rules, and LABELLED as inferred so nobody mistakes a
     convention for a definition.

That ordering matters. 12 of the 34 source columns are documented by the supplier; the rest
are inferred, and the dictionary says which is which rather than presenting all of it with
equal confidence.

Writes docs/data_dictionary.csv.
"""
import csv
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
GOLD = ROOT / "data" / "gold"
DOCS = ROOT / "docs"
SRC = Path.home() / "Downloads" / "BI_Developer_Interview_Synthetic_CSV_Data"
sys.path.insert(0, str(Path(__file__).parent))
from _table_registry import TABLES as REG, TIERS

# Tables that form the semantic model, in the order a reader should meet them. ML byproducts
# and staging artifacts are deliberately excluded — a dictionary that lists everything is a
# file listing, not a dictionary.
TABLES = [
    ("DimDate", "Conformed calendar. Built, not supplied — the README requires it."),
    ("DimMerchant", "Conformed merchant dimension. The single filter path for every fact."),
    ("DimVoucherType", "Voucher type, shared by the sales and redemption facts."),
    ("DimPriority", "Ticket priority with the SLA target attached."),
    ("DimTicketType", "Ticket category and impact area."),
    ("FactMerchantSales", "Daily sales. Grain: date x merchant x voucher type."),
    ("FactVoucherRedemptions", "Accumulating snapshot. Grain: one row per voucher."),
    ("FactSupportTickets", "Grain: one row per ticket."),
    ("DimMerchantSegment", "K-Means segment plus the authoritative health score."),
    ("MerchantValueRisk", "Lifetime value, attrition risk and fraud-adjacent signals."),
    ("RecControls", "Reconciliation control results, including expected variances."),
    ("ModelGuide", "Where each table came from and why it exists."),
]

# ---------------------------------------------------------------- authority 1: the supplier
supplied = {}
dd = SRC / "DataDictionary.csv"
if dd.exists():
    with open(dd, encoding="utf-8-sig") as fh:
        for r in csv.DictReader(fh):
            supplied[r["Column"].strip().lower()] = r["Description"].strip()

# ---------------------------------------------------------------- authority 2: the lineage
lineage = {}
lin = DOCS / "source_column_lineage.csv"
if lin.exists():
    for r in pd.read_csv(lin).itertuples():
        if r.GoldTable != "DROPPED" and isinstance(r.GoldColumn, str):
            note = "" if pd.isna(r.ModellingNote) else str(r.ModellingNote)
            lineage[(r.GoldTable, r.GoldColumn)] = (r.SourceFile, r.SourceColumn, note)

# ---------------------------------------------------------------- authority 2b: stated here
# Derived columns have no source row to trace and no supplier definition, so they are defined
# explicitly. Leaving them to the naming convention produced 76 columns reading "Undocumented"
# in a dictionary being handed to a reviewer — which is worse than a plain sentence each.
EXPLICIT = {
    # calendar
    "Year": "Calendar year.", "Quarter": "Calendar quarter, e.g. Q3.",
    "QuarterNumber": "Quarter as 1-4, for sorting.",
    "MonthNumber": "Month as 1-12, for sorting.",
    "MonthName": "Full month name.", "MonthShort": "Three-letter month abbreviation.",
    "MonthYear": "Month and year for display, e.g. Jul 2026.",
    "MonthYearSort": "Integer YYYYMM so MonthYear sorts chronologically, not alphabetically.",
    "DayOfMonth": "Day number within the month.",
    "DayOfWeek": "ISO weekday, Monday = 1.",
    "DayName": "Full weekday name.", "DayShort": "Three-letter weekday abbreviation.",
    "WeekOfYear": "ISO week number.", "YearWeek": "Year and ISO week, e.g. 2026-W31.",
    "IsWeekend": "True for Saturday and Sunday.",
    "MonthStartDate": "First day of the month this date falls in.",
    "MonthEndDate": "Last day of the month this date falls in.",
    "IsInFactWindow": "True inside the REPORTING WINDOW (first to last sale). The calendar "
                      "extends past this to host the redemption tail — conflating the two "
                      "overstated targets by R984,046, see the worked example.",
    "RelativeMonthOffset": "Months from the latest activity month; 0 = current, -1 = prior.",
    "IsCurrentMonth": "True for the most recent month containing activity.",
    # merchant
    "TenureMonths": "Whole months between OnboardedDate and the end of the window.",
    "TenureBand": "Tenure grouped for reporting.",
    "MerchantName": "Merchant trading name.",
    # measures
    "SalesValue": "Sales value in ZAR. Additive.",
    "Transactions": "Transaction count. Additive.",
    "VoucherValue": "Face value of the voucher in ZAR.",
    "DaysToRedeem": "Days between sale and redemption. Null when unredeemed.",
    "IsDelayedRedemption": "1 when DaysToRedeem exceeds 7 — an assumption, no threshold "
                           "was supplied.",
    "ResolutionHours": "Hours to resolve, or elapsed hours if still open.",
    "SLAHours": "SLA target for the ticket, stored on the fact so a later policy change "
                "cannot restate historic breaches.",
    "IsSLABreach": "1 when ResolutionHours exceeds SLAHours.",
    "IsOpen": "1 when the ticket is not yet resolved.",
    "Status": "Ticket status as supplied.",
    # scores
    "HealthScore": "Weighted 0-100 composite of momentum, trend, target, redemption, speed "
                   "and operations. Authoritative version — see the single-banding note.",
    "RiskTier": "Health band: Critical, Watch, Healthy or Star.",
    "Segment": "K-Means segment label.", "SegmentID": "K-Means cluster number.",
    "SegmentProfile": "Plain-English description of the segment.",
    "PCA1": "First principal component, for the segment scatter.",
    "PCA2": "Second principal component, for the segment scatter.",
    "AvgBasket": "SalesValue divided by Transactions.",
    "TotalSales": "Sum of SalesValue for the merchant.",
    "TotalTransactions": "Sum of Transactions for the merchant.",
    "GrowthSlopePct": "Least-squares slope of monthly sales, as a percentage of the mean.",
    "Volatility": "Coefficient of variation of monthly sales.",
    "RedemptionRate": "Vouchers redeemed divided by vouchers sold.",
    "AvgDaysToRedeem": "Mean DaysToRedeem across redeemed vouchers.",
    "DelayedRate": "Share of redemptions taking more than 7 days.",
    "Tickets": "Ticket count for the merchant.",
    "TicketsPer1kTx": "Tickets per 1,000 transactions — size-adjusted, so a large merchant "
                      "is not flagged simply for being large.",
    "AvgResolutionHours": "Mean ResolutionHours, closed tickets only.",
    "SLABreachRate": "Share of tickets breaching their SLA.",
    "BaseMonthlySalesTarget": "Supplied monthly target. Not on the same scale as actual "
                              "sales — attainment runs 381% to 916%, so it is a relative "
                              "ranking device only.",
    "TargetAttainmentPct": "Actual divided by target. See the calibration caveat above.",
    # controls
    "control_order": "Display order.", "control_family": "Control grouping.",
    "control_name": "What the control asserts.",
    "expected_value": "Value the control expects.",
    "actual_value": "Value observed.", "variance": "Actual minus expected.",
    "variance_pct": "Variance as a share of expected.",
    "control_status": "PASS, WARN, EXPECTED or FAIL.",
    "txn_per_voucher": "Transactions per voucher, 4.217 — why the two facts differ.",
    "rationale": "Why the control exists and how to read a failure.",
    # model guide
    "Sort": "Display order.", "Origin": "How the table earns its place.",
    "Table": "Table name.", "Rows": "Row count.",
    "Why this table exists": "Justification for including the table.",
}

# MerchantValueRisk uses snake_case throughout (it comes from the dbt mart), so the
# PascalCase keys above do not reach it. Plus the dimension attributes that carry real
# business meaning rather than being self-evident.
EXPLICIT.update({
    "Day": "Calendar day number.",
    "VoucherType": "Voucher product, e.g. Airtime, Electricity, Gaming.",
    "SettlementModel": "How the voucher settles commercially.",
    "Priority": "Ticket priority: Critical, High, Medium or Low.",
    "PrioritySort": "Severity order for sorting, Critical first.",
    "SLATargetHours": "Contracted resolution target for the priority. Critical is 12h "
                      "against an observed P90 of 74h — the queue runs in reverse priority "
                      "order.",
    "TicketType": "Ticket reason as supplied.",
    "TicketCategory": "Grouping of ticket types: Fulfilment, Financial or Commercial.",
    "ActiveStatus": "Merchant standing at the last load. A churned merchant must not be "
                    "scored as an attrition risk.",
    "AccountManager": "Owner the merchant is routed to — makes the risk register actionable.",
    "merchant_name": "Merchant trading name.",
    "account_manager": "Owner the merchant is routed to.",
    "active_status": "Merchant standing at the last load.",
    "total_sales": "Sum of sales value for the merchant, in ZAR.",
    "total_transactions": "Sum of transaction count for the merchant.",
    "avg_basket_value": "Total sales divided by total transactions.",
    "avg_monthly_revenue": "Mean monthly sales across the reporting window.",
    "sales_vs_prior_3m_avg": "Latest month against the mean of the prior three.",
    "last3_vs_first3": "Last three months against the first three — structural trend.",
    "mom_change": "Month-on-month change in sales.",
    "outstanding_value": "Face value of vouchers sold but not yet redeemed.",
    "tickets": "Support ticket count for the merchant.",
    "tenure_months": "Whole months since onboarding.",
    "revenue_at_risk_annualised": "Recent run-rate shortfall, annualised. Ranks merchants by "
                                  "RAND exposed rather than by percentage decline.",
    "implied_lifetime_value": "Annualised run rate multiplied by expected retained years.",
    "reversal_tickets": "Tickets categorised as reversals — a fraud-adjacent signal.",
    "financial_tickets": "Tickets in the Financial category.",
    "reversal_per_1k_txn": "Reversal tickets per 1,000 transactions, size-adjusted.",
    "very_late_redemptions": "Redemptions far beyond the typical window.",
    "max_voucher_value": "Largest single voucher value for the merchant.",
    "value_outlier_vouchers": "Vouchers whose value is a statistical outlier for the merchant.",
    "value_at_stake_if_lost": "Implied lifetime value weighted by attrition risk — the "
                              "expected loss if the merchant churns.",
})


# ---------------------------------------------------------------- authority 3: conventions
def by_convention(col):
    c = col.lower()
    if c.endswith("_key") or c.endswith("key"):
        return "Surrogate key. Joins to the matching dimension.", "Convention"
    if c.startswith("is") or c.startswith("has"):
        return "Boolean flag stored as 1/0 so it sums.", "Convention"
    if "date" in c:
        return "Date value.", "Convention"
    if c.endswith("_pct") or c.endswith("rate") or "percent" in c:
        return "Percentage or rate.", "Convention"
    if c.endswith("_score"):
        return "Derived score. See the section that defines it.", "Convention"
    if c.endswith("band") or c.endswith("tier"):
        return "Banding of the matching score.", "Convention"
    return "", "Undocumented"


TYPE = {"i": "Integer", "f": "Decimal", "O": "Text", "b": "Boolean", "M": "Date"}

rows = []
missing = []
for table, purpose in TABLES:
    p = GOLD / f"{table}.csv"
    if not p.exists():
        missing.append(table)
        continue
    df = pd.read_csv(p)
    for col in df.columns:
        dtype = TYPE.get(df[col].dtype.kind, str(df[col].dtype))
        desc, source = "", ""
        lin_hit = lineage.get((table, col))
        sup = supplied.get(col.lower())
        if sup:
            desc, source = sup, "Supplied DataDictionary"
        elif col in EXPLICIT:
            desc, source = EXPLICIT[col], "Defined in this build"
        elif lin_hit:
            f, c, note = lin_hit
            desc = note or f"From {f.replace('.csv', '')}.{c}."
            source = f"Lineage — {f.replace('.csv','')}.{c}"
        else:
            desc, source = by_convention(col)
        nulls = int(df[col].isna().sum())
        rows.append({
            "Table": table, "Column": col, "Type": dtype,
            "Nulls": nulls, "Rows": len(df),
            "Definition": desc, "Definition source": source,
        })

out = DOCS / "data_dictionary.csv"
pd.DataFrame(rows).to_csv(out, index=False, encoding="utf-8")

n = len(rows)
by_src = pd.DataFrame(rows)["Definition source"].value_counts()
print(f"  {len(TABLES) - len(missing)} tables, {n} columns documented")
for k, v in by_src.items():
    print(f"    {k:<34} {v:>4}")
if missing:
    print(f"  NOT FOUND (skipped): {', '.join(missing)}")
print(f"  wrote {out.relative_to(ROOT)}")
