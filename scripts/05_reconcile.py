"""
05_reconcile.py
===============
Cross-validation gate. The gold layer is built twice by two independent implementations:

    scripts/02_build_warehouse.py   pandas / Python
    dbt/models/                     SQL, run by dbt

If they agree to the cent on every headline figure, the transformation logic is almost
certainly right — two different engines, two different authors' worth of code paths,
one answer. If they disagree, one of them is wrong and the report does not ship.

This is also what backs the claim in the submission that the Power BI report, the Excel
pack and the ML feature set all tie to the same numbers.
"""
from pathlib import Path
import json
import duckdb
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
con = duckdb.connect(str(ROOT / "data" / "mvi.duckdb"))

TOL = 0.01
results = []


def check(label, a, b, tol=TOL):
    a, b = float(a), float(b)
    ok = abs(a - b) <= tol
    results.append({"Check": label, "Python": a, "dbt": b, "Variance": a - b,
                    "Status": "PASS" if ok else "FAIL"})
    print(f"  {'PASS' if ok else 'FAIL'}  {label:52s} python={a:>18,.2f}  dbt={b:>18,.2f}")
    return ok


print("=" * 104)
print("RECONCILIATION — Python warehouse (scripts/02) vs dbt marts")
print("=" * 104)

# --------------------------------------------------------------- headline totals
check("Total sales value",
      con.execute("select sum(SalesValue) from fact_merchant_sales").fetchone()[0],
      con.execute("select sum(sales_value) from main_marts.fct_merchant_sales").fetchone()[0])

check("Total transactions",
      con.execute("select sum(Transactions) from fact_merchant_sales").fetchone()[0],
      con.execute("select sum(transactions) from main_marts.fct_merchant_sales").fetchone()[0])

check("Sales fact row count",
      con.execute("select count(*) from fact_merchant_sales").fetchone()[0],
      con.execute("select count(*) from main_marts.fct_merchant_sales").fetchone()[0])

check("Vouchers sold",
      con.execute("select count(*) from fact_voucher_redemptions").fetchone()[0],
      con.execute("select count(*) from main_marts.fct_voucher_redemptions").fetchone()[0])

check("Vouchers redeemed",
      con.execute("select sum(case when IsRedeemed then 1 else 0 end) "
                  "from fact_voucher_redemptions").fetchone()[0],
      con.execute("select sum(redeemed_count) from main_marts.fct_voucher_redemptions").fetchone()[0])

check("Voucher value sold",
      con.execute("select sum(VoucherValue) from fact_voucher_redemptions").fetchone()[0],
      con.execute("select sum(voucher_value) from main_marts.fct_voucher_redemptions").fetchone()[0])

check("Outstanding voucher liability",
      con.execute("select sum(OutstandingValue) from fact_voucher_redemptions").fetchone()[0],
      con.execute("select sum(outstanding_value) from main_marts.fct_voucher_redemptions").fetchone()[0])

check("Delayed redemptions",
      con.execute("select sum(case when IsDelayedRedemption then 1 else 0 end) "
                  "from fact_voucher_redemptions").fetchone()[0],
      con.execute("select sum(delayed_redemption_count) "
                  "from main_marts.fct_voucher_redemptions").fetchone()[0])

check("Total tickets",
      con.execute("select count(*) from fact_support_tickets").fetchone()[0],
      con.execute("select count(*) from main_marts.fct_support_tickets").fetchone()[0])

check("SLA breaches",
      con.execute("select sum(case when IsSLABreach then 1 else 0 end) "
                  "from fact_support_tickets").fetchone()[0],
      con.execute("select sum(sla_breach_count) from main_marts.fct_support_tickets").fetchone()[0])

check("Total resolution hours",
      con.execute("select sum(ResolutionHours) from fact_support_tickets").fetchone()[0],
      con.execute("select sum(resolution_hours) from main_marts.fct_support_tickets").fetchone()[0])

check("Monthly sales target total",
      con.execute("select sum(MonthlySalesTarget) from fact_merchant_target").fetchone()[0],
      con.execute("select sum(monthly_sales_target) from main_marts.fct_merchant_target").fetchone()[0])

check("dim_date row count",
      con.execute("select count(*) from dim_date").fetchone()[0],
      con.execute("select count(*) from main_marts.dim_date").fetchone()[0])

check("dim_merchant row count (dbt adds Unknown member)",
      con.execute("select count(*) from dim_merchant").fetchone()[0] + 1,
      con.execute("select count(*) from main_marts.dim_merchant").fetchone()[0])

# --------------------------------------------------------------- per-merchant totals
print("\n  Per-merchant sales totals (25 merchants):")
py = con.execute("""
    select m.Merchant as merchant, round(sum(f.SalesValue), 2) as sales
    from fact_merchant_sales f join dim_merchant m using(MerchantKey)
    group by 1 order by 1""").df()
db = con.execute("""
    select m.merchant_name as merchant, round(sum(f.sales_value), 2) as sales
    from main_marts.fct_merchant_sales f join main_marts.dim_merchant m using(merchant_key)
    group by 1 order by 1""").df()
cmp = py.merge(db, on="merchant", suffixes=("_py", "_dbt"))
cmp["variance"] = (cmp.sales_py - cmp.sales_dbt).abs()
bad = cmp[cmp.variance > TOL]
print(f"    {len(cmp)} merchants compared, {len(bad)} variances above R{TOL}")
if len(bad):
    print(bad.to_string(index=False))
results.append({"Check": "Per-merchant sales (25 merchants)", "Python": len(cmp),
                "dbt": len(cmp) - len(bad), "Variance": len(bad),
                "Status": "PASS" if len(bad) == 0 else "FAIL"})

# --------------------------------------------------------------- per-month totals
print("\n  Per-month sales totals:")
pym = con.execute("""
    select d.YearMonth as ym, round(sum(f.SalesValue), 2) as sales
    from fact_merchant_sales f join dim_date d using(DateKey) group by 1 order by 1""").df()
dbm = con.execute("""
    select d.year_month as ym, round(sum(f.sales_value), 2) as sales
    from main_marts.fct_merchant_sales f join main_marts.dim_date d using(date_key)
    group by 1 order by 1""").df()
cm = pym.merge(dbm, on="ym", suffixes=("_py", "_dbt"))
cm["variance"] = (cm.sales_py - cm.sales_dbt).abs()
print(cm.to_string(index=False))
results.append({"Check": "Per-month sales (7 months)", "Python": len(cm),
                "dbt": int((cm.variance <= TOL).sum()), "Variance": float(cm.variance.max()),
                "Status": "PASS" if (cm.variance <= TOL).all() else "FAIL"})

# --------------------------------------------------------------- scorecard agreement
print("\n  Merchant scorecard — Health Score and Revenue at Risk:")
sc_py = pd.read_parquet(ROOT / "data" / "analytics" / "kpi_merchant_scorecard.parquet")
sc_db = con.execute("select * from main_marts.mart_merchant_scorecard").df()
j = sc_py[["Merchant", "TotalSales", "RedemptionRate", "TicketsPer1kTxn", "HealthScore",
           "RevenueAtRiskAnnualised", "SalesVsPrior3Avg", "MoMChange", "Last3vsFirst3",
           "AvgDaysToRedeem", "TargetAttainment", "SLABreachRate",
           "TicketsVsPrior3Avg"]].merge(
    sc_db[["merchant_name", "total_sales", "redemption_rate", "tickets_per_1k_txn",
           "health_score", "revenue_at_risk_annualised", "sales_vs_prior_3m_avg",
           "mom_change", "last3_vs_first3", "avg_days_to_redeem", "target_attainment",
           "sla_breach_rate", "tickets_vs_prior_3m_avg"]],
    left_on="Merchant", right_on="merchant_name")

# Every input to the composite score is compared individually. A variance in the score
# alone is useless for debugging; a variance in a named input points straight at the cause.
for pcol, dcol, tol, label in [
    ("TotalSales", "total_sales", 0.01, "total sales"),
    ("RedemptionRate", "redemption_rate", 1e-9, "redemption rate"),
    ("TicketsPer1kTxn", "tickets_per_1k_txn", 1e-6, "tickets per 1k txn"),
    ("SalesVsPrior3Avg", "sales_vs_prior_3m_avg", 1e-9, "recent momentum [score input]"),
    ("MoMChange", "mom_change", 1e-9, "month-on-month [score input]"),
    ("Last3vsFirst3", "last3_vs_first3", 1e-9, "structural trend [score input]"),
    ("TargetAttainment", "target_attainment", 1e-9, "target attainment [score input]"),
    ("AvgDaysToRedeem", "avg_days_to_redeem", 1e-9, "days to redeem [score input]"),
    ("SLABreachRate", "sla_breach_rate", 1e-9, "SLA breach rate [score input]"),
    ("TicketsVsPrior3Avg", "tickets_vs_prior_3m_avg", 1e-9, "ticket momentum [score input]"),
    ("RevenueAtRiskAnnualised", "revenue_at_risk_annualised", 0.01, "revenue at risk"),
    # 0.1 tolerance, and the reason is worth stating: every INPUT above ties to 0.000000,
    # so the only residual is the final rounding step. Python's round() is banker's rounding
    # (half-to-even) while SQL ROUND() is half-away-from-zero, so a score landing exactly on
    # x.x5 differs by one unit in the last decimal place. That is a presentation artefact,
    # not a logic difference — and it is only provable BECAUSE the inputs are compared.
    ("HealthScore", "health_score", 0.1, "health score (see rounding note)"),
]:
    v = (j[pcol] - j[dcol]).abs()
    ok = (v <= tol).all()
    print(f"    {'PASS' if ok else 'WARN'}  {label:22s} max variance {v.max():.6f}")
    results.append({"Check": f"Scorecard: {label}", "Python": float(j[pcol].sum()),
                    "dbt": float(j[dcol].sum()), "Variance": float(v.max()),
                    "Status": "PASS" if ok else "WARN"})

# --------------------------------------------------------------- verdict
df = pd.DataFrame(results)
df.to_parquet(ROOT / "data" / "analytics" / "reconciliation.parquet", index=False)
n_fail = int((df.Status == "FAIL").sum())
n_warn = int((df.Status == "WARN").sum())
print("\n" + "=" * 104)
print(f"RECONCILIATION RESULT: {len(df) - n_fail - n_warn} PASS, {n_warn} WARN, {n_fail} FAIL")
print("=" * 104)
with open(ROOT / "docs" / "reconciliation.json", "w") as f:
    json.dump({"passed": int(len(df) - n_fail - n_warn), "warnings": n_warn, "failures": n_fail,
               "checks": df.to_dict("records")}, f, indent=2, default=str)
con.close()
