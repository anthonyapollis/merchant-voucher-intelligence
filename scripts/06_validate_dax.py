"""
06_validate_dax.py
==================
DAX cannot be executed outside Power BI, so each measure is validated a different way:
every measure has a SQL reference definition, and this script evaluates that SQL against
the gold layer to produce the EXPECTED value.

The output (docs/dax_validation.csv) is the acceptance test for the report. After the
measures are entered in Power BI, each card is checked against this table. Any measure that
does not match its expected value to the stated precision is wrong, and the difference
points at which of the two definitions drifted.

This is also what makes "the Excel pack, the Power BI report and the notebook all agree"
a verifiable claim rather than an assertion.
"""
from pathlib import Path
import pandas as pd
import duckdb

ROOT = Path(__file__).resolve().parents[1]
con = duckdb.connect(str(ROOT / "data" / "mvi.duckdb"))

# (Measure name, SQL reference definition, format, notes)
MEASURES = [
    ("Total Sales",
     "select sum(SalesValue) from fact_merchant_sales", "R #,##0.00",
     "Grand total across all 26,500 fact rows."),
    ("Total Transactions",
     "select sum(Transactions) from fact_merchant_sales", "#,##0", ""),
    ("Average Basket Value",
     "select sum(SalesValue)/sum(Transactions) from fact_merchant_sales", "R #,##0.00",
     "SUM/SUM, not AVG of a ratio."),
    ("Sales Target",
     "select sum(MonthlySalesTarget) from fact_merchant_target", "R #,##0.00", ""),
    ("Target Attainment %",
     "select (select sum(SalesValue) from fact_merchant_sales)"
     "/(select sum(MonthlySalesTarget) from fact_merchant_target)", "0.0%",
     "Reads ~614% - supplied targets are mis-calibrated. Known issue."),
    ("Vouchers Sold",
     "select count(*) from fact_voucher_redemptions", "#,##0", ""),
    ("Vouchers Redeemed",
     "select sum(case when IsRedeemed then 1 else 0 end) from fact_voucher_redemptions",
     "#,##0", ""),
    ("Redemption Rate %",
     "select sum(case when IsRedeemed then 1 else 0 end)*1.0/count(*) "
     "from fact_voucher_redemptions", "0.00%", "Volume-based."),
    ("Value Redemption Rate %",
     "select sum(RedeemedValue)/sum(VoucherValue) from fact_voucher_redemptions", "0.00%",
     "Value-based; differs from volume rate."),
    ("Voucher Value Sold",
     "select sum(VoucherValue) from fact_voucher_redemptions", "R #,##0.00", ""),
    ("Outstanding Liability",
     "select sum(OutstandingValue) from fact_voucher_redemptions", "R #,##0.00",
     "Balance-sheet liability, not lost revenue."),
    ("Avg Days to Redeem",
     "select avg(DaysToRedeem) from fact_voucher_redemptions where IsRedeemed", "0.00",
     "Redeemed vouchers only; AVERAGE ignores BLANK in DAX."),
    ("Median Days to Redeem",
     "select median(DaysToRedeem) from fact_voucher_redemptions where IsRedeemed", "0.0",
     "Distribution is right-skewed."),
    ("Delayed Redemptions",
     "select sum(case when IsDelayedRedemption then 1 else 0 end) "
     "from fact_voucher_redemptions", "#,##0", "> 7 days."),
    ("Delayed Redemption Rate %",
     "select sum(case when IsDelayedRedemption then 1 else 0 end)*1.0"
     "/sum(case when IsRedeemed then 1 else 0 end) from fact_voucher_redemptions", "0.0%",
     "Denominator is REDEEMED vouchers."),
    ("Total Tickets",
     "select count(*) from fact_support_tickets", "#,##0", ""),
    ("Avg Resolution Hours",
     "select avg(ResolutionHours) from fact_support_tickets", "0.00", ""),
    ("Median Resolution Hours",
     "select median(ResolutionHours) from fact_support_tickets", "0.0",
     "Mean 23.7 vs median 16.4 - heavy right tail."),
    ("SLA Breaches",
     "select sum(case when IsSLABreach then 1 else 0 end) from fact_support_tickets",
     "#,##0", ""),
    ("SLA Breach Rate %",
     "select sum(case when IsSLABreach then 1 else 0 end)*1.0/count(*) "
     "from fact_support_tickets", "0.00%", ""),
    ("Avg SLA Breach Hours",
     "select avg(SLABreachHours) from fact_support_tickets where IsSLABreach", "0.00",
     "Breaching tickets only."),
    ("Total Breach Hours",
     "select sum(SLABreachHours) from fact_support_tickets", "#,##0", ""),
    ("High Priority Tickets",
     "select sum(case when IsHighPriority then 1 else 0 end) from fact_support_tickets",
     "#,##0", ""),
    ("Open Tickets",
     "select sum(case when IsOpen then 1 else 0 end) from fact_support_tickets", "#,##0", ""),
    ("Tickets per 1k Transactions",
     "select (select count(*) from fact_support_tickets)*1000.0"
     "/(select sum(Transactions) from fact_merchant_sales)", "0.00",
     "Size-dependent - screening measure only."),
    ("Breach Concentration in High Priority %",
     "select sum(case when IsSLABreach and IsHighPriority then 1 else 0 end)*1.0"
     "/sum(case when IsSLABreach then 1 else 0 end) from fact_support_tickets", "0.0%",
     "Headline operational finding."),
    ("Implied SLA Required for 90% Compliance",
     "select quantile_cont(ResolutionHours, 0.90) from fact_support_tickets", "0.0",
     "What the SLA should be if the process is unchanged."),
    ("Revenue Concentration (Top 5) %",
     """select sum(s)/(select sum(SalesValue) from fact_merchant_sales) from (
            select sum(f.SalesValue) s from fact_merchant_sales f
            group by f.MerchantKey order by s desc limit 5)""", "0.0%",
     "Concentration risk."),
    ("Active Merchants",
     "select count(distinct MerchantKey) from fact_merchant_sales where SalesValue > 0",
     "#,##0", ""),
    ("Sales MoM % (July vs June)",
     """select (select sum(f.SalesValue) from fact_merchant_sales f join dim_date d
                using(DateKey) where d.YearMonth='2026-07')
             / (select sum(f.SalesValue) from fact_merchant_sales f join dim_date d
                using(DateKey) where d.YearMonth='2026-06') - 1""", "+0.0%;-0.0%",
     "Latest month movement."),
    ("Revenue at Risk",
     "select sum(revenue_at_risk_annualised) from main_marts.mart_merchant_scorecard",
     "R #,##0.00", "Annualised shortfall vs own baseline."),
]

rows = []
print("=" * 110)
print(f"{'Measure':<42} {'Expected value':>22}  {'Format':<14} Reference")
print("=" * 110)
for name, sql, fmt, note in MEASURES:
    val = con.execute(sql).fetchone()[0]
    val = float(val) if val is not None else None
    rows.append({"Measure": name, "ExpectedValue": val, "FormatString": fmt,
                 "SQLReference": " ".join(sql.split()), "Notes": note})
    print(f"{name:<42} {val:>22,.4f}  {fmt:<14} {note[:38]}")

df = pd.DataFrame(rows)
df.to_csv(ROOT / "docs" / "dax_validation.csv", index=False)
df.to_parquet(ROOT / "data" / "analytics" / "dax_validation.parquet", index=False)
print("\n" + "=" * 110)
print(f"{len(df)} measures with SQL-derived expected values -> docs/dax_validation.csv")
print("After entering the measures in Power BI, each card must match these to the stated")
print("precision. A mismatch means the DAX and the SQL definitions have drifted.")
con.close()
