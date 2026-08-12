# Fabric notebook source
# ---------------------------------------------------------------------------
# nb_04_ai_anomaly_and_narrative
# ---------------------------------------------------------------------------
# The AI extension. Two gold tables the report reads directly:
#
#   FactAnomaly        unsupervised outlier and level-shift detection across
#                      sales, ticket volume and redemption lag
#   InsightNarrative   one plain-English paragraph per merchant explaining what
#                      changed month on month and what most likely caused it
#
# Method note. Anomaly scoring is median/MAD rather than mean/standard
# deviation: a single large spike inflates the standard deviation enough to
# hide itself, while the median absolute deviation does not move. Point
# detectors score each observation against the window that PRECEDES it, so a
# merchant that steps up to a new level is flagged at the step rather than
# quietly re-baselining itself over the following fortnight.
#
# The narrative is deliberately rule-based, not LLM-generated. It drives an
# operations work queue, so the same inputs must always produce the same
# sentence, and every claim in it must be traceable to a number in the model.
# See docs/04_AI_Extension.md for where an LLM does belong in this design.
#
# Attach to: lh_merchant_gold
# Depends on: nb_03_gold_star_schema
# ---------------------------------------------------------------------------

# PARAMETERS CELL ********************

z_threshold = 3.5           # robust z at which a point is flagged
level_shift_pct = 25.0      # month vs prior-3-month move that counts as a shift
ticket_shift_pct = 100.0    # same, for ticket counts
ticket_shift_min_abs = 8    # ... and the minimum absolute rise, so tiny
                            # merchants do not flag on two extra tickets

# CELL ********************

import numpy as np
import pandas as pd

GOLD = "lh_merchant_gold"

dim_date = spark.table(f"{GOLD}.DimDate").toPandas()
dim_merchant = spark.table(f"{GOLD}.DimMerchant").toPandas()
sales = spark.table(f"{GOLD}.FactMerchantSales").toPandas()
tickets = spark.table(f"{GOLD}.FactSupportTickets").toPandas()
redemptions = spark.table(f"{GOLD}.FactVoucherRedemptions").toPandas()

# The star schema is small enough at this grain to score in pandas on the
# driver. If the merchant book grows past a few thousand, convert the per-group
# loops to a pandas UDF over a Spark groupBy - the maths is unchanged.

d = dim_date[["DateKey", "Date", "MonthYear", "MonthYearSort"]]
m = dim_merchant[["MerchantKey", "Merchant", "Region", "Channel"]]
sales = sales.merge(d, on="DateKey").merge(m, on="MerchantKey")
tickets = tickets.merge(d, on="DateKey").merge(m, on="MerchantKey")
redemptions = redemptions.merge(
    d.rename(columns={"DateKey": "SoldDateKey", "Date": "SoldDate"}),
    on="SoldDateKey").merge(m, on="MerchantKey")

# MARKDOWN ******************************

# ## Scoring functions

# CELL ********************

def robust_z(series: pd.Series, mad_floor: float = 0.0) -> pd.Series:
    """Median/MAD z against the whole series.

    mad_floor guards the degenerate case where more than half the points are
    identical - common for sparse counts, where the median is 0, the MAD
    collapses to 0, and every spike would otherwise be silenced.
    """
    med = series.median()
    mad = max(float((series - med).abs().median()), mad_floor)
    if mad == 0 or np.isnan(mad):
        return pd.Series(0.0, index=series.index)
    return 0.6745 * (series - med) / mad


def trailing_robust_z(values: pd.Series, window: int, min_periods: int,
                      mad_floor_frac: float = 0.05):
    """Robust z of each point against the preceding window only."""
    med = values.shift(1).rolling(window, min_periods=min_periods).median()
    mad = (values.shift(1).rolling(window, min_periods=min_periods)
           .apply(lambda w: np.median(np.abs(w - np.median(w))), raw=True))
    mad = np.maximum(mad, med.abs() * mad_floor_frac)
    return 0.6745 * (values - med) / mad.replace(0, np.nan), med


def deseasonalise(frame: pd.DataFrame, value: str) -> pd.Series:
    """Strip the day-of-week profile so weekly rhythm is not read as anomaly."""
    profile = frame.groupby(frame["Date"].dt.dayofweek)[value].transform("median")
    return frame[value] - profile + frame[value].median()

# MARKDOWN ******************************

# ## Detectors

# CELL ********************

rows = []

# 1. Daily sales, scored against a trailing 28-day window ---------------------
daily = (sales.groupby(["MerchantKey", "Merchant", "Region", "Date"], as_index=False)
         .agg(SalesValue=("SalesValue", "sum")))
for (mk, name, region), grp in daily.groupby(["MerchantKey", "Merchant", "Region"]):
    grp = grp.sort_values("Date").reset_index(drop=True)
    grp["Adj"] = deseasonalise(grp, "SalesValue")
    z, expected = trailing_robust_z(grp["Adj"], 28, 14)
    for i in np.where(z.abs() >= z_threshold)[0]:
        rows.append(dict(
            AnomalyID=f"A-SAL-{mk}-{grp.loc[i, 'Date']:%Y%m%d}",
            Date=grp.loc[i, "Date"], MerchantKey=mk, Merchant=name, Region=region,
            Measure="Daily Sales Value", ActualValue=float(grp.loc[i, "SalesValue"]),
            ExpectedValue=float(expected[i]), Score=float(z[i]),
            ScoreType="Robust z",
            Direction="Above expected" if z[i] > 0 else "Below expected"))

# 2. Monthly sales level shift ------------------------------------------------
monthly = (sales.groupby(["MerchantKey", "Merchant", "Region", "MonthYearSort"],
                         as_index=False).agg(SalesValue=("SalesValue", "sum")))
for (mk, name, region), grp in monthly.groupby(["MerchantKey", "Merchant", "Region"]):
    grp = grp.sort_values("MonthYearSort").reset_index(drop=True)
    base = grp["SalesValue"].shift(1).rolling(3, min_periods=3).mean()
    move = (grp["SalesValue"] / base - 1) * 100
    for i in np.where(move.abs() >= level_shift_pct)[0]:
        ms = int(grp.loc[i, "MonthYearSort"])
        rows.append(dict(
            AnomalyID=f"A-LVL-{mk}-{ms}",
            Date=pd.Timestamp(f"{ms // 100}-{ms % 100:02d}-01"),
            MerchantKey=mk, Merchant=name, Region=region,
            Measure="Monthly Sales Level Shift",
            ActualValue=float(grp.loc[i, "SalesValue"]), ExpectedValue=float(base[i]),
            Score=float(move[i]), ScoreType="Percent change",
            Direction="Above expected" if move[i] > 0 else "Below expected"))

# 3. Monthly ticket level shift ----------------------------------------------
all_months = sorted(sales["MonthYearSort"].unique())
tick_monthly = (tickets.groupby(["MerchantKey", "Merchant", "Region", "MonthYearSort"],
                                as_index=False).agg(Tickets=("TicketID", "count")))
for (mk, name, region), grp in tick_monthly.groupby(["MerchantKey", "Merchant", "Region"]):
    grp = (pd.DataFrame({"MonthYearSort": all_months})
           .merge(grp, on="MonthYearSort", how="left")
           .assign(Tickets=lambda x: x["Tickets"].fillna(0))
           .sort_values("MonthYearSort").reset_index(drop=True))
    base = grp["Tickets"].shift(1).rolling(3, min_periods=3).mean()
    move = (grp["Tickets"] / base.replace(0, np.nan) - 1) * 100
    hit = (move >= ticket_shift_pct) & (grp["Tickets"] - base >= ticket_shift_min_abs)
    for i in np.where(hit.fillna(False))[0]:
        ms = int(grp.loc[i, "MonthYearSort"])
        rows.append(dict(
            AnomalyID=f"A-TLV-{mk}-{ms}",
            Date=pd.Timestamp(f"{ms // 100}-{ms % 100:02d}-01"),
            MerchantKey=mk, Merchant=name, Region=region,
            Measure="Monthly Ticket Level Shift",
            ActualValue=float(grp.loc[i, "Tickets"]), ExpectedValue=float(base[i]),
            Score=float(move[i]), ScoreType="Percent change",
            Direction="Above expected"))

# 4. Weekly redemption lag by region and voucher type -------------------------
red = redemptions[redemptions["IsRedeemed"] == 1].copy()
red["WeekStart"] = red["SoldDate"] - pd.to_timedelta(red["SoldDate"].dt.dayofweek, "D")
weekly = (red.groupby(["Region", "VoucherTypeKey", "WeekStart"], as_index=False)
          .agg(AvgDays=("DaysToRedeem", "mean"), Vouchers=("VoucherID", "count")))
weekly = weekly[weekly["Vouchers"] >= 20]  # thin weeks are noise, not signal
for (region, vtype), grp in weekly.groupby(["Region", "VoucherTypeKey"]):
    grp = grp.sort_values("WeekStart").reset_index(drop=True)
    z = robust_z(grp["AvgDays"])
    expected = grp["AvgDays"].median()
    for i in np.where(z >= z_threshold)[0]:
        rows.append(dict(
            AnomalyID=f"A-RED-{region[:3].upper()}-{vtype[:3].upper()}"
                      f"-{grp.loc[i, 'WeekStart']:%Y%m%d}",
            Date=grp.loc[i, "WeekStart"], MerchantKey=None,
            Merchant=f"{region} / {vtype}", Region=region,
            Measure="Avg Days To Redeem (weekly)",
            ActualValue=float(grp.loc[i, "AvgDays"]), ExpectedValue=float(expected),
            Score=float(z[i]), ScoreType="Robust z", Direction="Above expected"))

anomaly = pd.DataFrame(rows)
mag = anomaly["Score"].abs()
is_pct = anomaly["ScoreType"] == "Percent change"
anomaly["Severity"] = np.where(
    is_pct, np.where(mag >= 40, "High", np.where(mag >= 30, "Medium", "Low")),
    np.where(mag >= 8, "High", np.where(mag >= 5, "Medium", "Low")))
anomaly["DeviationPct"] = ((anomaly["ActualValue"] - anomaly["ExpectedValue"])
                           / anomaly["ExpectedValue"].replace(0, np.nan) * 100)

(spark.createDataFrame(anomaly).write.format("delta").mode("overwrite")
 .option("overwriteSchema", "true").saveAsTable(f"{GOLD}.FactAnomaly"))

display(anomaly.sort_values("Severity"))

# MARKDOWN ******************************

# ## Narrative generation
#
# Each sentence decomposes the move into transaction volume against average
# basket size, because "sales fell 40%" is not actionable while "sales fell 40%
# on volume, not basket size, in the same month tickets went from 3 to 37" is.

# CELL ********************

cur, prev = all_months[-1], all_months[-2]
sm = (sales.groupby(["MerchantKey", "Merchant", "Region", "Channel", "MonthYearSort"],
                    as_index=False)
      .agg(SalesValue=("SalesValue", "sum"), Transactions=("Transactions", "sum")))
c = sm[sm["MonthYearSort"] == cur].set_index("MerchantKey")
p = sm[sm["MonthYearSort"] == prev].set_index("MerchantKey")
tk = (tickets.groupby(["MerchantKey", "MonthYearSort"], as_index=False)
      .agg(Tickets=("TicketID", "count")))
tc = tk[tk["MonthYearSort"] == cur].set_index("MerchantKey")["Tickets"]
tp = tk[tk["MonthYearSort"] == prev].set_index("MerchantKey")["Tickets"]
rr = (redemptions.groupby(["MerchantKey", "MonthYearSort"], as_index=False)
      .agg(Rate=("IsRedeemed", "mean")))
rc = rr[rr["MonthYearSort"] == cur].set_index("MerchantKey")["Rate"]
rp = rr[rr["MonthYearSort"] == prev].set_index("MerchantKey")["Rate"]

out = []
for mk in c.index.intersection(p.index):
    delta = (c.loc[mk, "SalesValue"] / p.loc[mk, "SalesValue"] - 1) * 100
    tx = (c.loc[mk, "Transactions"] / p.loc[mk, "Transactions"] - 1) * 100
    aov_now = c.loc[mk, "SalesValue"] / c.loc[mk, "Transactions"]
    aov_then = p.loc[mk, "SalesValue"] / p.loc[mk, "Transactions"]
    aov = (aov_now / aov_then - 1) * 100
    t_now, t_then = int(tc.get(mk, 0)), int(tp.get(mk, 0))

    headline, flag = (
        ("Sharp decline", "Investigate") if delta <= -15 else
        ("Softening", "Monitor") if delta <= -5 else
        ("Strong growth", "Replicate") if delta >= 15 else
        ("Growing", "Healthy") if delta >= 5 else ("Stable", "Healthy"))

    if abs(tx) > abs(aov) * 1.5:
        driver = (f"driven by transaction volume ({tx:+.1f}%) rather than basket "
                  f"size ({aov:+.1f}%)")
    elif abs(aov) > abs(tx) * 1.5:
        driver = (f"driven by average basket size ({aov:+.1f}%) rather than "
                  f"transaction volume ({tx:+.1f}%)")
    else:
        driver = f"volume and basket size moved together ({tx:+.1f}% and {aov:+.1f}%)"

    parts = [f"{c.loc[mk, 'Merchant']} ({c.loc[mk, 'Region']}, "
             f"{c.loc[mk, 'Channel']}) {headline.lower()}: sales {delta:+.1f}% "
             f"month on month, {driver}."]
    if t_then > 0 and t_now >= t_then * 2 and t_now >= 5:
        parts.append(f"Support tickets rose from {t_then} to {t_now} over the same "
                     f"period, which is the most likely operational cause.")
    elif t_now > 0:
        parts.append(f"Support ticket volume was {t_now} versus {t_then} last month.")
    if mk in rc.index and mk in rp.index and abs(rc[mk] - rp[mk]) * 100 >= 3:
        parts.append(f"Redemption rate moved {(rc[mk] - rp[mk]) * 100:+.1f} points "
                     f"to {rc[mk] * 100:.1f}%.")

    out.append(dict(MerchantKey=mk, Merchant=c.loc[mk, "Merchant"],
                    Region=c.loc[mk, "Region"], Channel=c.loc[mk, "Channel"],
                    Headline=headline, ActionFlag=flag,
                    SalesMoMPct=round(float(delta), 2),
                    TransactionsMoMPct=round(float(tx), 2),
                    AvgBasketMoMPct=round(float(aov), 2),
                    TicketsThisMonth=t_now, TicketsPrevMonth=t_then,
                    Narrative=" ".join(parts)))

narrative = pd.DataFrame(out).sort_values("SalesMoMPct")
(spark.createDataFrame(narrative).write.format("delta").mode("overwrite")
 .option("overwriteSchema", "true").saveAsTable(f"{GOLD}.InsightNarrative"))

display(narrative[narrative["ActionFlag"] != "Healthy"])

print(f"{len(anomaly)} anomalies, "
      f"{(anomaly.Severity == 'High').sum()} high severity. "
      f"{len(narrative)} merchant narratives.")
