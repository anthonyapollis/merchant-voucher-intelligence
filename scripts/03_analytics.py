"""
03_analytics.py
===============
The semantic / KPI layer. Every number that appears in the Power BI report, the Excel
workbook, the HTML dashboard and the written submission is produced HERE, once, from the
gold star schema in DuckDB. That is what guarantees the figures align across deliverables.

Each aggregate below has a 1:1 counterpart in the DAX measure library (/dax/measures.dax);
the SQL is the reference definition that the DAX is validated against.

Outputs -> data/analytics/*.parquet  +  docs/analytics_summary.json
"""
from __future__ import annotations

from pathlib import Path
import json
import numpy as np
import pandas as pd
import duckdb

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "analytics"
OUT.mkdir(parents=True, exist_ok=True)
con = duckdb.connect(str(ROOT / "data" / "mvi.duckdb"))

DELAY_DAYS = 7
packs: dict[str, pd.DataFrame] = {}
summary: dict = {}
q = lambda sql: con.execute(sql).df()


def save(name: str, df: pd.DataFrame) -> pd.DataFrame:
    df.to_parquet(OUT / f"{name}.parquet", index=False)
    packs[name] = df
    print(f"  {name:34s} rows={len(df):>6,}")
    return df


# =============================================================================
# A wide, reusable "merchant x month" spine — the backbone of most KPIs
# =============================================================================
print("\nBuilding core aggregates")

save("kpi_merchant_month", q("""
WITH s AS (
    SELECT f.MerchantKey, d.YearMonth, d.MonthStartDate,
           SUM(f.SalesValue)   AS SalesValue,
           SUM(f.Transactions) AS Transactions
    FROM fact_merchant_sales f JOIN dim_date d USING(DateKey)
    GROUP BY 1,2,3
),
v AS (
    SELECT f.MerchantKey, d.YearMonth,
           COUNT(*)                                     AS VouchersSold,
           SUM(CASE WHEN f.IsRedeemed THEN 1 ELSE 0 END) AS VouchersRedeemed,
           SUM(f.VoucherValue)                          AS VoucherValueSold,
           SUM(f.RedeemedValue)                         AS VoucherValueRedeemed,
           SUM(f.OutstandingValue)                      AS OutstandingValue,
           AVG(f.DaysToRedeem)                          AS AvgDaysToRedeem,
           SUM(CASE WHEN f.IsDelayedRedemption THEN 1 ELSE 0 END) AS DelayedRedemptions
    FROM fact_voucher_redemptions f JOIN dim_date d ON d.DateKey = f.SoldDateKey
    GROUP BY 1,2
),
t AS (
    SELECT f.MerchantKey, d.YearMonth,
           COUNT(*)                                        AS Tickets,
           AVG(f.ResolutionHours)                          AS AvgResolutionHours,
           SUM(CASE WHEN f.IsSLABreach     THEN 1 ELSE 0 END) AS SLABreaches,
           SUM(CASE WHEN f.IsHighPriority  THEN 1 ELSE 0 END) AS HighPriorityTickets,
           SUM(CASE WHEN f.IsOpen          THEN 1 ELSE 0 END) AS OpenTickets
    FROM fact_support_tickets f JOIN dim_date d USING(DateKey)
    GROUP BY 1,2
),
g AS (
    SELECT f.MerchantKey, d.YearMonth, SUM(f.MonthlySalesTarget) AS SalesTarget
    FROM fact_merchant_target f JOIN dim_date d USING(DateKey)
    GROUP BY 1,2
)
SELECT m.Merchant, m.MerchantID, m.Region, m.Channel, m.ActiveStatus, m.AccountManager,
       m.MerchantSizeBand, s.YearMonth, s.MonthStartDate,
       s.SalesValue, s.Transactions,
       s.SalesValue / NULLIF(s.Transactions,0)                    AS AvgBasketValue,
       g.SalesTarget,
       s.SalesValue / NULLIF(g.SalesTarget,0)                     AS TargetAttainment,
       COALESCE(v.VouchersSold,0)      AS VouchersSold,
       COALESCE(v.VouchersRedeemed,0)  AS VouchersRedeemed,
       COALESCE(v.VouchersRedeemed,0)*1.0/NULLIF(v.VouchersSold,0) AS RedemptionRate,
       v.VoucherValueSold, v.VoucherValueRedeemed, v.OutstandingValue,
       v.AvgDaysToRedeem,
       COALESCE(v.DelayedRedemptions,0)*1.0/NULLIF(v.VouchersRedeemed,0) AS DelayedRedemptionRate,
       COALESCE(t.Tickets,0)             AS Tickets,
       t.AvgResolutionHours,
       COALESCE(t.SLABreaches,0)*1.0/NULLIF(t.Tickets,0) AS SLABreachRate,
       COALESCE(t.HighPriorityTickets,0) AS HighPriorityTickets,
       COALESCE(t.OpenTickets,0)         AS OpenTickets,
       COALESCE(t.Tickets,0)*1000.0/NULLIF(s.Transactions,0) AS TicketsPer1kTxn
FROM s
JOIN dim_merchant m USING(MerchantKey)
LEFT JOIN v ON v.MerchantKey=s.MerchantKey AND v.YearMonth=s.YearMonth
LEFT JOIN t ON t.MerchantKey=s.MerchantKey AND t.YearMonth=s.YearMonth
LEFT JOIN g ON g.MerchantKey=s.MerchantKey AND g.YearMonth=s.YearMonth
ORDER BY m.Merchant, s.YearMonth
"""))

# =============================================================================
# 1. Executive KPIs
# =============================================================================
print("\nExecutive KPIs")
ex = q("""
SELECT
  (SELECT SUM(SalesValue)   FROM fact_merchant_sales) AS TotalSales,
  (SELECT SUM(Transactions) FROM fact_merchant_sales) AS TotalTransactions,
  (SELECT SUM(MonthlySalesTarget) FROM fact_merchant_target) AS TotalTarget,
  (SELECT COUNT(*) FROM fact_voucher_redemptions) AS VouchersSold,
  (SELECT SUM(CASE WHEN IsRedeemed THEN 1 ELSE 0 END) FROM fact_voucher_redemptions) AS VouchersRedeemed,
  (SELECT SUM(VoucherValue)     FROM fact_voucher_redemptions) AS VoucherValueSold,
  (SELECT SUM(RedeemedValue)    FROM fact_voucher_redemptions) AS VoucherValueRedeemed,
  (SELECT SUM(OutstandingValue) FROM fact_voucher_redemptions) AS OutstandingLiability,
  (SELECT AVG(DaysToRedeem)     FROM fact_voucher_redemptions WHERE IsRedeemed) AS AvgDaysToRedeem,
  (SELECT SUM(CASE WHEN IsDelayedRedemption THEN 1 ELSE 0 END) FROM fact_voucher_redemptions) AS DelayedRedemptions,
  (SELECT COUNT(*)              FROM fact_support_tickets) AS TotalTickets,
  (SELECT AVG(ResolutionHours)  FROM fact_support_tickets) AS AvgResolutionHours,
  (SELECT SUM(CASE WHEN IsSLABreach THEN 1 ELSE 0 END) FROM fact_support_tickets) AS SLABreaches,
  (SELECT SUM(CASE WHEN IsOpen      THEN 1 ELSE 0 END) FROM fact_support_tickets) AS OpenTickets,
  (SELECT COUNT(*) FROM dim_merchant) AS Merchants,
  (SELECT COUNT(*) FROM dim_merchant WHERE ActiveStatus='At Risk') AS AtRiskMerchants
""").iloc[0]

k = {
    "TotalSales": float(ex.TotalSales),
    "TotalTransactions": int(ex.TotalTransactions),
    "AvgBasketValue": float(ex.TotalSales / ex.TotalTransactions),
    "TotalTarget": float(ex.TotalTarget),
    "TargetAttainment": float(ex.TotalSales / ex.TotalTarget),
    "VouchersSold": int(ex.VouchersSold),
    "VouchersRedeemed": int(ex.VouchersRedeemed),
    "RedemptionRate": float(ex.VouchersRedeemed / ex.VouchersSold),
    "VoucherValueSold": float(ex.VoucherValueSold),
    "VoucherValueRedeemed": float(ex.VoucherValueRedeemed),
    "ValueRedemptionRate": float(ex.VoucherValueRedeemed / ex.VoucherValueSold),
    "OutstandingLiability": float(ex.OutstandingLiability),
    "AvgDaysToRedeem": float(ex.AvgDaysToRedeem),
    "DelayedRedemptionRate": float(ex.DelayedRedemptions / ex.VouchersRedeemed),
    "TotalTickets": int(ex.TotalTickets),
    "AvgResolutionHours": float(ex.AvgResolutionHours),
    "SLABreachRate": float(ex.SLABreaches / ex.TotalTickets),
    "OpenTickets": int(ex.OpenTickets),
    "TicketsPer1kTxn": float(ex.TotalTickets * 1000 / ex.TotalTransactions),
    "Merchants": int(ex.Merchants),
    "AtRiskMerchants": int(ex.AtRiskMerchants),
}
summary["exec_kpis"] = k
for kk, vv in k.items():
    print(f"  {kk:24s} {vv:,.4f}" if isinstance(vv, float) else f"  {kk:24s} {vv:,}")

# =============================================================================
# 2. Monthly trend (company level) with MoM and 3-month moving average
# =============================================================================
mt = q("""
WITH s AS (SELECT d.YearMonth, d.MonthStartDate, SUM(f.SalesValue) SalesValue,
                  SUM(f.Transactions) Transactions
           FROM fact_merchant_sales f JOIN dim_date d USING(DateKey) GROUP BY 1,2),
     v AS (SELECT d.YearMonth, COUNT(*) VouchersSold,
                  SUM(CASE WHEN f.IsRedeemed THEN 1 ELSE 0 END) VouchersRedeemed,
                  AVG(f.DaysToRedeem) AvgDaysToRedeem
           FROM fact_voucher_redemptions f JOIN dim_date d ON d.DateKey=f.SoldDateKey GROUP BY 1),
     t AS (SELECT d.YearMonth, COUNT(*) Tickets, AVG(f.ResolutionHours) AvgResolutionHours,
                  SUM(CASE WHEN f.IsSLABreach THEN 1 ELSE 0 END)*1.0/COUNT(*) SLABreachRate
           FROM fact_support_tickets f JOIN dim_date d USING(DateKey) GROUP BY 1),
     g AS (SELECT d.YearMonth, SUM(f.MonthlySalesTarget) SalesTarget
           FROM fact_merchant_target f JOIN dim_date d USING(DateKey) GROUP BY 1)
SELECT s.YearMonth, s.MonthStartDate, s.SalesValue, s.Transactions, g.SalesTarget,
       s.SalesValue/NULLIF(g.SalesTarget,0) TargetAttainment,
       s.SalesValue/NULLIF(s.Transactions,0) AvgBasketValue,
       v.VouchersSold, v.VouchersRedeemed,
       v.VouchersRedeemed*1.0/v.VouchersSold RedemptionRate,
       v.AvgDaysToRedeem, t.Tickets, t.AvgResolutionHours, t.SLABreachRate
FROM s JOIN v USING(YearMonth) JOIN t USING(YearMonth) JOIN g USING(YearMonth)
ORDER BY s.YearMonth
""")
mt["SalesMoM"] = mt.SalesValue.pct_change()
mt["TxnMoM"] = mt.Transactions.pct_change()
mt["Sales3MA"] = mt.SalesValue.rolling(3).mean()
save("kpi_monthly_trend", mt)

# =============================================================================
# 3. Region performance + declining-region detection
# =============================================================================
rm = q("""
SELECT m.Region, d.YearMonth, d.MonthStartDate,
       SUM(f.SalesValue) SalesValue, SUM(f.Transactions) Transactions
FROM fact_merchant_sales f
JOIN dim_merchant m USING(MerchantKey) JOIN dim_date d USING(DateKey)
GROUP BY 1,2,3 ORDER BY 1,2
""")
rm["SalesMoM"] = rm.groupby("Region").SalesValue.pct_change()
rm["TxnMoM"] = rm.groupby("Region").Transactions.pct_change()
save("kpi_region_month", rm)

# Linear slope of monthly sales per region = trend direction
reg_rows = []
for r, gdf in rm.groupby("Region"):
    y = gdf.SalesValue.values.astype(float)
    x = np.arange(len(y))
    slope = np.polyfit(x, y, 1)[0]
    reg_rows.append({
        "Region": r,
        "TotalSales": y.sum(),
        "TotalTransactions": int(gdf.Transactions.sum()),
        "AvgMonthlySales": y.mean(),
        "TrendSlopePerMonth": slope,
        "TrendPctOfAvg": slope / y.mean(),
        "LastMonthMoM": gdf.SalesMoM.iloc[-1],
        "Last2MonthAvgMoM": gdf.SalesMoM.iloc[-2:].mean(),
        "PeakMonth": gdf.loc[gdf.SalesValue.idxmax(), "YearMonth"],
        "SalesVsPeak": y[-1] / y.max() - 1,
    })
region_perf = pd.DataFrame(reg_rows).sort_values("TotalSales", ascending=False)
region_perf["SalesShare"] = region_perf.TotalSales / region_perf.TotalSales.sum()
save("kpi_region_performance", region_perf)

# Region x VoucherType redemption lag (surfaces the April Western Cape / Bill Payment issue)
rvt = q(f"""
SELECT m.Region, vt.VoucherType, d.YearMonth,
       COUNT(*) VouchersSold,
       SUM(CASE WHEN f.IsRedeemed THEN 1 ELSE 0 END)*1.0/COUNT(*) RedemptionRate,
       AVG(f.DaysToRedeem) AvgDaysToRedeem,
       SUM(CASE WHEN f.IsDelayedRedemption THEN 1 ELSE 0 END)*1.0
         /NULLIF(SUM(CASE WHEN f.IsRedeemed THEN 1 ELSE 0 END),0) DelayedRate
FROM fact_voucher_redemptions f
JOIN dim_merchant m USING(MerchantKey)
JOIN dim_voucher_type vt USING(VoucherTypeKey)
JOIN dim_date d ON d.DateKey = f.SoldDateKey
GROUP BY 1,2,3 ORDER BY 1,2,3
""")
save("kpi_region_vouchertype_month", rvt)

# =============================================================================
# 4. Voucher type performance
# =============================================================================
vtp = q(f"""
WITH v AS (
  SELECT vt.VoucherType, vt.VoucherCategory, vt.MarginBand,
         COUNT(*) VouchersSold,
         SUM(CASE WHEN f.IsRedeemed THEN 1 ELSE 0 END) VouchersRedeemed,
         SUM(f.VoucherValue) VoucherValueSold,
         SUM(f.RedeemedValue) VoucherValueRedeemed,
         SUM(f.OutstandingValue) OutstandingValue,
         AVG(f.DaysToRedeem) AvgDaysToRedeem,
         MEDIAN(f.DaysToRedeem) MedianDaysToRedeem,
         SUM(CASE WHEN f.IsDelayedRedemption THEN 1 ELSE 0 END) DelayedRedemptions
  FROM fact_voucher_redemptions f JOIN dim_voucher_type vt USING(VoucherTypeKey)
  GROUP BY 1,2,3),
s AS (
  SELECT vt.VoucherType, SUM(f.SalesValue) SalesValue, SUM(f.Transactions) Transactions
  FROM fact_merchant_sales f JOIN dim_voucher_type vt USING(VoucherTypeKey) GROUP BY 1)
SELECT v.*, s.SalesValue, s.Transactions,
       v.VouchersRedeemed*1.0/v.VouchersSold RedemptionRate,
       v.VoucherValueRedeemed/v.VoucherValueSold ValueRedemptionRate,
       v.DelayedRedemptions*1.0/NULLIF(v.VouchersRedeemed,0) DelayedRate,
       s.SalesValue/NULLIF(s.Transactions,0) AvgBasketValue
FROM v JOIN s USING(VoucherType) ORDER BY RedemptionRate DESC
""")
vtp["SalesShare"] = vtp.SalesValue / vtp.SalesValue.sum()
save("kpi_voucher_type", vtp)
summary["best_voucher_type"] = {
    "VoucherType": vtp.iloc[0].VoucherType,
    "RedemptionRate": float(vtp.iloc[0].RedemptionRate),
    "worst": vtp.iloc[-1].VoucherType,
    "worst_rate": float(vtp.iloc[-1].RedemptionRate),
}

# Voucher type x month redemption trend
save("kpi_voucher_type_month", q("""
SELECT vt.VoucherType, d.YearMonth, COUNT(*) VouchersSold,
       SUM(CASE WHEN f.IsRedeemed THEN 1 ELSE 0 END)*1.0/COUNT(*) RedemptionRate,
       AVG(f.DaysToRedeem) AvgDaysToRedeem
FROM fact_voucher_redemptions f JOIN dim_voucher_type vt USING(VoucherTypeKey)
JOIN dim_date d ON d.DateKey=f.SoldDateKey GROUP BY 1,2 ORDER BY 1,2
"""))

# =============================================================================
# 5. Merchant scorecard  (the drill-through target table)
# =============================================================================
print("\nMerchant scorecard")
ms = packs["kpi_merchant_month"]
rows = []
for merchant, g in ms.groupby("Merchant"):
    g = g.sort_values("YearMonth")
    y = g.SalesValue.values.astype(float)
    first3, last3 = y[:3].mean(), y[-3:].mean()
    slope = np.polyfit(np.arange(len(y)), y, 1)[0]
    rows.append({
        "Merchant": merchant,
        "MerchantID": g.MerchantID.iloc[0],
        "Region": g.Region.iloc[0],
        "Channel": g.Channel.iloc[0],
        "AccountManager": g.AccountManager.iloc[0],
        "ActiveStatus": g.ActiveStatus.iloc[0],
        "MerchantSizeBand": g.MerchantSizeBand.iloc[0],
        "TotalSales": y.sum(),
        "TotalTransactions": int(g.Transactions.sum()),
        "AvgBasketValue": y.sum() / g.Transactions.sum(),
        "SalesTarget": g.SalesTarget.sum(),
        "TargetAttainment": y.sum() / g.SalesTarget.sum(),
        "LatestMonthSales": y[-1],
        "PriorMonthSales": y[-2],
        "MoMChange": y[-1] / y[-2] - 1,
        "Last3vsFirst3": last3 / first3 - 1,
        "TrendSlopePerMonth": slope,
        "TrendPctOfAvg": slope / y.mean(),
        "VouchersSold": int(g.VouchersSold.sum()),
        "RedemptionRate": g.VouchersRedeemed.sum() / g.VouchersSold.sum(),
        "AvgDaysToRedeem": np.average(g.AvgDaysToRedeem, weights=g.VouchersRedeemed),
        "OutstandingValue": g.OutstandingValue.sum(),
        "Tickets": int(g.Tickets.sum()),
        "TicketsPer1kTxn": g.Tickets.sum() * 1000 / g.Transactions.sum(),
        "AvgResolutionHours": np.average(g.AvgResolutionHours.fillna(0), weights=g.Tickets.clip(lower=1e-9))
                              if g.Tickets.sum() else np.nan,
        "HighPriorityTickets": int(g.HighPriorityTickets.sum()),
        "OpenTickets": int(g.OpenTickets.sum()),
    })
sc = pd.DataFrame(rows)

# SLA breach rate per merchant straight from the fact (weighted average would distort)
slab = q("""SELECT m.Merchant,
                   SUM(CASE WHEN f.IsSLABreach THEN 1 ELSE 0 END)*1.0/COUNT(*) SLABreachRate
            FROM fact_support_tickets f JOIN dim_merchant m USING(MerchantKey) GROUP BY 1""")
sc = sc.merge(slab, on="Merchant", how="left")

sc = sc.sort_values("TotalSales", ascending=False).reset_index(drop=True)
sc["SalesRank"] = sc.TotalSales.rank(ascending=False, method="min").astype(int)
sc["TxnRank"] = sc.TotalTransactions.rank(ascending=False, method="min").astype(int)
sc["SalesShare"] = sc.TotalSales / sc.TotalSales.sum()
sc["CumulativeShare"] = sc.SalesShare.cumsum()
sc["ParetoBand"] = np.where(sc.CumulativeShare <= 0.80, "Top 80% of revenue", "Long tail")

# ---- Target calibration -----------------------------------------------------
# DATA QUALITY: the supplied BaseMonthlySalesTarget sits ~6x below realised sales for every
# merchant, so raw attainment (614%) is not a usable executive KPI. Rather than silently
# rescaling the client's number we keep it, flag it, and expose a *relative* index:
#   TargetAttainmentIndex = merchant attainment / portfolio attainment  (1.00 = on par)
# This is comparable across merchants and is immune to the calibration error.
portfolio_attainment = sc.TotalSales.sum() / sc.SalesTarget.sum()
sc["TargetAttainmentIndex"] = sc.TargetAttainment / portfolio_attainment
summary["target_calibration"] = {
    "portfolio_attainment_raw": float(portfolio_attainment),
    "implied_scaling_factor": float(portfolio_attainment),
    "note": ("Supplied BaseMonthlySalesTarget is ~6.1x below realised monthly sales for all 25 "
             "merchants. Treated as a calibration/basis error; reported as a relative index "
             "pending business confirmation."),
}

# ---- Recent-deterioration signals ------------------------------------------
# The health score must react to the CURRENT month, not average a collapse away.
mom_last = ms.sort_values("YearMonth").groupby("Merchant").SalesValue
sc = sc.merge(
    ms.sort_values("YearMonth").groupby("Merchant").apply(
        lambda g: pd.Series({
            # latest month vs the mean of the prior three -> catches a single-month collapse
            "SalesVsPrior3Avg": g.SalesValue.iloc[-1] / g.SalesValue.iloc[-4:-1].mean() - 1,
            "TicketsVsPrior3Avg": (g.Tickets.iloc[-1] / g.Tickets.iloc[-4:-1].mean() - 1)
                                   if g.Tickets.iloc[-4:-1].mean() > 0 else np.nan,
            "LatestMonthTickets": int(g.Tickets.iloc[-1]),
            "PeakMonth": g.loc[g.SalesValue.idxmax(), "YearMonth"],
            "SalesVsPeak": g.SalesValue.iloc[-1] / g.SalesValue.max() - 1,
        }), include_groups=False).reset_index(),
    on="Merchant", how="left")

# ---- Merchant Health Score (0-100 composite; documented in the report) ------
def pct_rank(s, higher_is_better=True):
    """Match ANSI SQL PERCENT_RANK() exactly: (rank - 1) / (n - 1), spanning 0..1.

    pandas' rank(pct=True) returns rank/n (spanning 1/n..1) which is a DIFFERENT statistic.
    Using the two interchangeably made the Python and dbt Health Scores disagree by up to
    9.7 points — caught by scripts/05_reconcile.py, not by any unit test.
    """
    s = s if higher_is_better else -s
    return (s.rank(method="min") - 1) / (len(s) - 1)

sc["_recent"] = pct_rank(sc.SalesVsPrior3Avg)          # current momentum  (most important)
sc["_mom"] = pct_rank(sc.MoMChange)
sc["_growth"] = pct_rank(sc.Last3vsFirst3)             # structural trend
sc["_target"] = pct_rank(sc.TargetAttainmentIndex)
sc["_redeem"] = pct_rank(sc.RedemptionRate)
sc["_speed"] = pct_rank(sc.AvgDaysToRedeem, False)
sc["_ops"] = pct_rank(sc.TicketsVsPrior3Avg.fillna(0), False)   # ops *deterioration*, not level
sc["_sla"] = pct_rank(sc.SLABreachRate.fillna(0), False)
WEIGHTS = {"_recent": .25, "_mom": .15, "_growth": .15, "_target": .15,
           "_redeem": .10, "_speed": .05, "_ops": .10, "_sla": .05}
sc["HealthScore"] = (sum(sc[c] * w for c, w in WEIGHTS.items()) * 100).round(1)
# Rounded to 1dp in BOTH implementations so the reconciliation compares like with like.
sc["HealthBand"] = pd.cut(sc.HealthScore, [-1, 35, 55, 75, 101],
                          labels=["Critical", "Watch", "Healthy", "Star"])

# ---- Revenue at Risk & focus prioritisation --------------------------------
# Severity alone misranks: a 45% drop on R92k/month matters less than a 10% drop on R900k.
# RevenueAtRisk annualises the current shortfall against the merchant's own recent baseline.
sc["MonthlyBaseline"] = sc.LatestMonthSales / (1 + sc.SalesVsPrior3Avg)
sc["MonthlyShortfall"] = (sc.MonthlyBaseline - sc.LatestMonthSales).clip(lower=0)
sc["RevenueAtRiskAnnualised"] = sc.MonthlyShortfall * 12
sc["FocusPriorityScore"] = (
    (100 - sc.HealthScore) * 0.5
    + pct_rank(sc.RevenueAtRiskAnnualised) * 100 * 0.35
    + pct_rank(sc.TicketsVsPrior3Avg.fillna(0)) * 100 * 0.15
).round(1)
sc = sc.drop(columns=[c for c in sc.columns if c.startswith("_")])
sc = sc.sort_values("TotalSales", ascending=False).reset_index(drop=True)
save("kpi_merchant_scorecard", sc)

# ---- Rules-based deterioration alerts (feeds the AI / anomaly page) ---------
alerts = []
for _, r in sc.iterrows():
    if r.SalesVsPrior3Avg <= -0.20:
        alerts.append((r.Merchant, r.Region, "Sales collapse", "Critical",
                       f"Latest month sales {r.SalesVsPrior3Avg:+.1%} vs prior 3-month average",
                       r.RevenueAtRiskAnnualised))
    elif r.SalesVsPrior3Avg <= -0.08:
        alerts.append((r.Merchant, r.Region, "Sales decline", "High",
                       f"Latest month sales {r.SalesVsPrior3Avg:+.1%} vs prior 3-month average",
                       r.RevenueAtRiskAnnualised))
    if pd.notna(r.TicketsVsPrior3Avg) and r.TicketsVsPrior3Avg >= 1.5 and r.LatestMonthTickets >= 10:
        alerts.append((r.Merchant, r.Region, "Support ticket spike", "Critical",
                       f"{int(r.LatestMonthTickets)} tickets in latest month, "
                       f"{r.TicketsVsPrior3Avg:+.0%} vs prior 3-month average", 0.0))
    if r.SLABreachRate is not None and r.SLABreachRate >= 0.40 and r.Tickets >= 20:
        alerts.append((r.Merchant, r.Region, "SLA breach concentration", "High",
                       f"{r.SLABreachRate:.0%} of {int(r.Tickets)} tickets breached SLA", 0.0))
    if r.RedemptionRate <= 0.80:
        alerts.append((r.Merchant, r.Region, "Low redemption rate", "Medium",
                       f"Redemption rate {r.RedemptionRate:.1%} vs portfolio "
                       f"{k['RedemptionRate']:.1%}", 0.0))
    if r.ActiveStatus == "At Risk":
        alerts.append((r.Merchant, r.Region, "Flagged At Risk in CRM", "Medium",
                       "ActiveStatus = 'At Risk' in MerchantReference", 0.0))
alert_df = pd.DataFrame(alerts, columns=["Merchant", "Region", "AlertType", "Severity",
                                         "Detail", "RevenueAtRiskAnnualised"])
sev_order = {"Critical": 0, "High": 1, "Medium": 2}
alert_df["_o"] = alert_df.Severity.map(sev_order)
alert_df = alert_df.sort_values(["_o", "RevenueAtRiskAnnualised"],
                                ascending=[True, False]).drop(columns="_o").reset_index(drop=True)
save("kpi_alerts", alert_df)
print(alert_df.head(15).to_string(index=False))

# --- Does the CRM 'At Risk' flag actually track deterioration? -----------------
# The business already has a manual risk flag. If it worked, a computed health score would
# be redundant. Testing that assumption is the honest way to justify the analytics, and the
# answer here is unambiguous.
flagged = set(sc[sc.ActiveStatus == "At Risk"].Merchant)
critical = set(sc[sc.HealthBand == "Critical"].Merchant)
crm_check = sc[(sc.ActiveStatus == "At Risk") | (sc.HealthBand == "Critical")][
    ["Merchant", "Region", "ActiveStatus", "HealthBand", "HealthScore", "SalesVsPrior3Avg",
     "RevenueAtRiskAnnualised"]].sort_values("HealthScore")
save("kpi_crm_flag_check", crm_check)
summary["crm_flag_check"] = {
    "flagged_at_risk": sorted(flagged),
    "computed_critical": sorted(critical),
    "overlap": sorted(flagged & critical),
    "n_flagged": len(flagged),
    "n_critical": len(critical),
    "n_overlap": len(flagged & critical),
    "missed_revenue_at_risk": float(
        sc[sc.Merchant.isin(critical - flagged)].RevenueAtRiskAnnualised.sum()),
    "interpretation": (
        "The CRM At-Risk flag and computed deterioration have zero overlap. Both flagged "
        "merchants are growing and score Healthy; every merchant in genuine decline — "
        "including the one losing R571k annualised — is flagged 'Active'. The existing "
        "manual flag is not detecting the problem it exists to detect."),
}
print("\n  CRM 'At Risk' flag vs computed health:")
print(crm_check.to_string(index=False))
print(f"  Flagged: {len(flagged)}   Computed Critical: {len(critical)}   "
      f"Overlap: {len(flagged & critical)}")

summary["top_merchants"] = sc.head(5)[["Merchant", "Region", "TotalSales", "TotalTransactions",
                                       "SalesShare"]].to_dict("records")
summary["bottom_merchants"] = sc.tail(5)[["Merchant", "Region", "TotalSales",
                                          "TotalTransactions"]].to_dict("records")
summary["revenue_concentration"] = {
    "top5_share": float(sc.head(5).SalesShare.sum()),
    "top10_share": float(sc.head(10).SalesShare.sum()),
    "hhi": float((sc.SalesShare ** 2).sum() * 10_000),
    "merchants_for_80pct": int((sc.CumulativeShare <= 0.80).sum() + 1),
}

# =============================================================================
# 6. Operational view
# =============================================================================
print("\nOperational aggregates")
save("kpi_ticket_type", q("""
SELECT tt.TicketType, tt.TicketCategory, tt.ImpactArea, COUNT(*) Tickets,
       AVG(f.ResolutionHours) AvgResolutionHours,
       MEDIAN(f.ResolutionHours) MedianResolutionHours,
       MAX(f.ResolutionHours) MaxResolutionHours,
       SUM(CASE WHEN f.IsSLABreach THEN 1 ELSE 0 END)*1.0/COUNT(*) SLABreachRate,
       SUM(CASE WHEN f.IsHighPriority THEN 1 ELSE 0 END) HighPriorityTickets,
       SUM(CASE WHEN f.IsOpen THEN 1 ELSE 0 END) OpenTickets,
       SUM(f.SLABreachHours) TotalBreachHours
FROM fact_support_tickets f JOIN dim_ticket_type tt USING(TicketTypeKey)
GROUP BY 1,2,3 ORDER BY Tickets DESC
"""))

save("kpi_priority", q("""
SELECT p.Priority, p.PrioritySort, p.TargetSLAHours, COUNT(*) Tickets,
       AVG(f.ResolutionHours) AvgResolutionHours,
       MEDIAN(f.ResolutionHours) MedianResolutionHours,
       SUM(CASE WHEN f.IsSLABreach THEN 1 ELSE 0 END) SLABreaches,
       SUM(CASE WHEN f.IsSLABreach THEN 1 ELSE 0 END)*1.0/COUNT(*) SLABreachRate,
       AVG(f.SLABreachHours) AvgBreachHours,
       SUM(CASE WHEN f.IsOpen THEN 1 ELSE 0 END) OpenTickets
FROM fact_support_tickets f JOIN dim_priority p USING(PriorityKey)
GROUP BY 1,2,3 ORDER BY p.PrioritySort
"""))

save("kpi_ticket_month", q("""
SELECT d.YearMonth, d.MonthStartDate, p.Priority, COUNT(*) Tickets,
       AVG(f.ResolutionHours) AvgResolutionHours,
       SUM(CASE WHEN f.IsSLABreach THEN 1 ELSE 0 END)*1.0/COUNT(*) SLABreachRate
FROM fact_support_tickets f JOIN dim_date d USING(DateKey) JOIN dim_priority p USING(PriorityKey)
GROUP BY 1,2,3 ORDER BY 1,3
"""))

save("kpi_status", q("""
SELECT st.Status, st.StatusGroup, COUNT(*) Tickets,
       AVG(f.ResolutionHours) AvgResolutionHours
FROM fact_support_tickets f JOIN dim_ticket_status st USING(StatusKey)
GROUP BY 1,2 ORDER BY Tickets DESC
"""))

# --- Backlog ownership: who is actually holding the open tickets? ---------------
# A single "239 open tickets" figure conflates two different operational problems.
# "Pending Merchant" is waiting on the customer; "Open" and "Escalated" are waiting on us.
# They need different remediation, and reporting one number hides that entirely.
backlog = q("""
SELECT CASE WHEN st.Status = 'Closed' THEN 'Resolved'
            WHEN st.Status = 'Pending Merchant' THEN 'Awaiting customer'
            ELSE 'Awaiting us' END AS Ownership,
       COUNT(*) Tickets, AVG(f.ResolutionHours) AvgResolutionHours
FROM fact_support_tickets f JOIN dim_ticket_status st USING(StatusKey)
GROUP BY 1 ORDER BY 2 DESC
""")
save("kpi_backlog_ownership", backlog)
_open = backlog[backlog.Ownership != "Resolved"]
summary["backlog_ownership"] = {
    "awaiting_us": int(_open[_open.Ownership == "Awaiting us"].Tickets.iloc[0]),
    "awaiting_customer": int(_open[_open.Ownership == "Awaiting customer"].Tickets.iloc[0]),
    "total_open": int(_open.Tickets.sum()),
    "pct_awaiting_customer": float(
        _open[_open.Ownership == "Awaiting customer"].Tickets.iloc[0] / _open.Tickets.sum()),
}
print("\n  Backlog ownership:")
print(backlog.to_string(index=False))

# =============================================================================
# 7. Does operational friction track weaker merchant performance?
# =============================================================================
print("\nOps friction vs performance")
corr_src = sc[["Merchant", "TicketsPer1kTxn", "SLABreachRate", "AvgResolutionHours",
               "HighPriorityTickets", "Last3vsFirst3", "MoMChange", "TargetAttainment",
               "RedemptionRate", "HealthScore"]].copy()
corrs = {}
for a in ["TicketsPer1kTxn", "SLABreachRate", "AvgResolutionHours", "HighPriorityTickets"]:
    for b in ["Last3vsFirst3", "MoMChange", "TargetAttainment", "RedemptionRate"]:
        cc = corr_src[[a, b]].dropna()
        corrs[f"{a}~{b}"] = {
            "pearson": float(cc[a].corr(cc[b])),
            "spearman": float(cc[a].corr(cc[b], method="spearman")),
            "n": int(len(cc)),
        }
summary["ops_correlations"] = corrs
for kk, vv in corrs.items():
    print(f"  {kk:44s} r={vv['pearson']:+.3f}  rho={vv['spearman']:+.3f}")

# Merchant-month panel correlation — far more statistical power than 25 merchant rows
panel = ms.dropna(subset=["Tickets", "SalesValue"]).copy()
panel["SalesMoM"] = panel.groupby("Merchant").SalesValue.pct_change()
panel["TicketsMoM"] = panel.groupby("Merchant").Tickets.diff()
pc = panel.dropna(subset=["SalesMoM", "TicketsMoM"])
summary["panel_correlation"] = {
    "TicketsDelta_vs_SalesMoM_pearson": float(pc.TicketsMoM.corr(pc.SalesMoM)),
    "TicketsDelta_vs_SalesMoM_spearman": float(pc.TicketsMoM.corr(pc.SalesMoM, method="spearman")),
    "n_observations": int(len(pc)),
}
save("kpi_merchant_ops_panel", panel)

# Quartile view: does the high-friction quartile actually grow slower?
sc2 = sc.dropna(subset=["TicketsPer1kTxn"]).copy()
sc2["FrictionQuartile"] = pd.qcut(sc2.TicketsPer1kTxn, 4,
                                  labels=["Q1 lowest friction", "Q2", "Q3", "Q4 highest friction"])
fq = sc2.groupby("FrictionQuartile", observed=True).agg(
    Merchants=("Merchant", "count"),
    AvgTicketsPer1kTxn=("TicketsPer1kTxn", "mean"),
    AvgGrowthLast3vsFirst3=("Last3vsFirst3", "mean"),
    AvgTargetAttainment=("TargetAttainment", "mean"),
    AvgRedemptionRate=("RedemptionRate", "mean"),
    AvgHealthScore=("HealthScore", "mean"),
).reset_index()
save("kpi_friction_quartiles", fq)
print(fq.to_string(index=False))

# --- Honest caveat: is TicketsPer1kTxn just a proxy for merchant size? -------
# Small merchants have few transactions, so the ratio inflates. If friction correlates
# strongly with size, the "friction hurts performance" reading is confounded and must be
# reported as such rather than presented as causal.
size_r = float(sc.TicketsPer1kTxn.corr(np.log(sc.TotalSales)))
size_rho = float(sc.TicketsPer1kTxn.corr(sc.TotalSales, method="spearman"))
# Partial correlation of friction ~ attainment, controlling for log(size)
def resid(y, x):
    b = np.polyfit(x, y, 1)
    return y - np.polyval(b, x)
_ls = np.log(sc.TotalSales.values)
part = float(np.corrcoef(resid(sc.TicketsPer1kTxn.values, _ls),
                         resid(sc.TargetAttainmentIndex.values, _ls))[0, 1])
summary["size_confounder"] = {
    "friction_vs_log_size_pearson": size_r,
    "friction_vs_size_spearman": size_rho,
    "partial_corr_friction_vs_attainment_controlling_size": part,
    "raw_corr_friction_vs_attainment": corrs["TicketsPer1kTxn~TargetAttainment"]["pearson"],
    "interpretation": ("Tickets per 1k transactions is strongly size-dependent, so the raw "
                       "negative correlation with target attainment is largely a size effect. "
                       "Controlling for log(total sales) the association weakens materially."),
}
print(f"\n  friction ~ log(size)        r={size_r:+.3f}")
print(f"  partial friction ~ attainment | size  r={part:+.3f}  "
      f"(raw {corrs['TicketsPer1kTxn~TargetAttainment']['pearson']:+.3f})")

# --- Event-level evidence: where do ticket spikes and sales breaks coincide? -
ev = []
for merchant, g in ms.sort_values("YearMonth").groupby("Merchant"):
    for i in range(3, len(g)):
        tprev = g.Tickets.iloc[i - 3:i].mean()
        sprev = g.SalesValue.iloc[i - 3:i].mean()
        if tprev >= 2 and g.Tickets.iloc[i] / tprev >= 2.5 and g.Tickets.iloc[i] >= 10:
            ev.append({
                "Merchant": merchant, "Region": g.Region.iloc[0], "Month": g.YearMonth.iloc[i],
                "Tickets": int(g.Tickets.iloc[i]), "PriorAvgTickets": round(tprev, 1),
                "TicketUplift": g.Tickets.iloc[i] / tprev - 1,
                "SalesValue": g.SalesValue.iloc[i],
                "SalesVsPrior3Avg": g.SalesValue.iloc[i] / sprev - 1,
            })
event_df = pd.DataFrame(ev)
save("kpi_ticket_spike_events", event_df)
summary["event_evidence"] = event_df.to_dict("records")
print("\n  Ticket-spike events coinciding with sales movement:")
print(event_df.to_string(index=False) if len(event_df) else "  (none)")

# =============================================================================
# 8. Business-question answers, computed not asserted
# =============================================================================
print("\nBusiness question answers")
ans = {}
ans["Q1_highest_sales"] = {
    "by_value": sc.iloc[0].Merchant, "value": float(sc.iloc[0].TotalSales),
    "share": float(sc.iloc[0].SalesShare),
    "by_transactions": sc.sort_values("TotalTransactions", ascending=False).iloc[0].Merchant,
    "transactions": int(sc.TotalTransactions.max()),
    "same_merchant": bool(sc.iloc[0].Merchant ==
                          sc.sort_values("TotalTransactions", ascending=False).iloc[0].Merchant),
}
ans["Q2_best_voucher_type"] = summary["best_voucher_type"]
declining = region_perf.sort_values("Last2MonthAvgMoM")
ans["Q3_declining_region"] = {
    "weakest_recent": declining.iloc[0].Region,
    "last2_avg_mom": float(declining.iloc[0].Last2MonthAvgMoM),
    "vs_peak": float(declining.iloc[0].SalesVsPeak),
    "table": declining[["Region", "TotalSales", "TrendPctOfAvg", "LastMonthMoM",
                        "Last2MonthAvgMoM", "SalesVsPeak"]].to_dict("records"),
}
ans["Q4_ops_vs_performance"] = {
    "merchant_level": corrs, "panel": summary["panel_correlation"],
    "quartiles": fq.to_dict("records"),
    "size_confounder": summary["size_confounder"],
    "event_evidence": summary["event_evidence"],
}
focus = sc.sort_values("FocusPriorityScore", ascending=False).head(5)
ans["Q5_focus_merchants"] = focus[["Merchant", "Region", "FocusPriorityScore", "HealthScore",
                                   "HealthBand", "TotalSales", "LatestMonthSales",
                                   "SalesVsPrior3Avg", "RevenueAtRiskAnnualised",
                                   "TicketsVsPrior3Avg", "LatestMonthTickets",
                                   "TargetAttainmentIndex", "SLABreachRate"]].to_dict("records")
summary["business_answers"] = ans
print(json.dumps({kk: (vv if not isinstance(vv, dict) else list(vv)[:6])
                  for kk, vv in ans.items()}, indent=2, default=str)[:1200])

# =============================================================================
# 9. Daily spine for sparkline / anomaly work downstream
# =============================================================================
save("kpi_merchant_daily", q("""
SELECT m.Merchant, m.Region, m.Channel, d.Date, d.YearMonth,
       SUM(f.SalesValue) SalesValue, SUM(f.Transactions) Transactions
FROM fact_merchant_sales f JOIN dim_merchant m USING(MerchantKey) JOIN dim_date d USING(DateKey)
GROUP BY 1,2,3,4,5 ORDER BY 1,4
"""))

with open(ROOT / "docs" / "analytics_summary.json", "w") as fh:
    json.dump(summary, fh, indent=2, default=str)
print("\nWrote docs/analytics_summary.json and", len(packs), "analytics tables")
con.close()
