"""
build_insights.py
=================
Reads the certified gold layer and produces:

  data/gold/FactAnomaly.csv        anomaly table consumed by the report
  data/gold/InsightNarrative.csv   plain-English explanation per flagged merchant
  dashboard/data.json              every figure rendered by the offline dashboard
  docs/_computed_findings.json     the same figures, for the written insights doc

Anomaly method
--------------
Seasonal-naive residual + robust z-score (median / MAD). Each series is
de-seasonalised against its own day-of-week profile, then a point is flagged
when its residual sits more than 3.5 MAD from the series median. MAD is used
rather than standard deviation because a single large spike inflates SD enough
to hide itself; the median absolute deviation does not move.

Run:  python build/build_insights.py   (after build_gold.py)
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
GOLD = ROOT / "data" / "gold"
DASH = ROOT / "dashboard"
DOCS = ROOT / "docs"
DASH.mkdir(exist_ok=True)
DOCS.mkdir(exist_ok=True)

Z_THRESHOLD = 3.5
DELAY_THRESHOLD_DAYS = 7


def load() -> dict[str, pd.DataFrame]:
    t = {}
    for name in ("DimDate", "DimMerchant", "DimVoucherType", "DimTicketType",
                 "DimPriority", "FactMerchantSales", "FactVoucherRedemptions",
                 "FactSupportTickets"):
        t[name] = pd.read_csv(GOLD / f"{name}.csv")
    t["DimDate"]["Date"] = pd.to_datetime(t["DimDate"]["Date"])
    return t


def denorm(t: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    """Join keys back to attributes - the equivalent of the model's relationships."""
    d = t["DimDate"][["DateKey", "Date", "MonthYear", "MonthYearSort", "MonthShort"]]
    m = t["DimMerchant"][["MerchantKey", "Merchant", "Region", "Channel",
                          "ActiveStatus", "AccountManager", "BaseMonthlySalesTarget"]]

    sales = t["FactMerchantSales"].merge(d, on="DateKey").merge(m, on="MerchantKey")

    red = t["FactVoucherRedemptions"].merge(
        d.rename(columns={"DateKey": "SoldDateKey", "Date": "SoldDate"}),
        on="SoldDateKey",
    ).merge(m, on="MerchantKey")

    tick = t["FactSupportTickets"].merge(d, on="DateKey").merge(m, on="MerchantKey")
    tick = tick.merge(
        t["DimPriority"][["PriorityKey", "PrioritySort", "SLATargetHours"]],
        on="PriorityKey",
    ).merge(t["DimTicketType"][["TicketTypeKey", "TicketCategory"]],
            on="TicketTypeKey")
    return {"sales": sales, "red": red, "tick": tick, **t}


# ------------------------------------------------------------- anomalies ----
def robust_z(series: pd.Series, mad_floor: float = 0.0) -> pd.Series:
    """Median/MAD z-score against the whole series.

    mad_floor guards the degenerate case where more than half the points are
    identical (common for sparse counts, where the median is 0 and the MAD
    collapses to 0, which would otherwise silence every spike).
    """
    med = series.median()
    mad = max(float((series - med).abs().median()), mad_floor)
    if mad == 0 or np.isnan(mad):
        return pd.Series(0.0, index=series.index)
    # 0.6745 scales MAD to a standard-deviation equivalent for normal data.
    return 0.6745 * (series - med) / mad


def trailing_robust_z(values: pd.Series, window: int, min_periods: int,
                      mad_floor_frac: float = 0.05) -> tuple[pd.Series, pd.Series]:
    """Robust z of each point against the *preceding* window only.

    A whole-series median cannot see a sustained level shift: after a merchant
    steps up in May, the series median lands between the two levels and neither
    regime looks unusual. Scoring each point against the window that came before
    it flags the step at the point it happens, which is what the business needs.

    Returns (z, expected) where expected is the trailing median.
    """
    med = values.shift(1).rolling(window, min_periods=min_periods).median()
    mad = (values.shift(1)
           .rolling(window, min_periods=min_periods)
           .apply(lambda w: np.median(np.abs(w - np.median(w))), raw=True))
    floor = med.abs() * mad_floor_frac
    mad = np.maximum(mad, floor)
    z = 0.6745 * (values - med) / mad.replace(0, np.nan)
    return z, med


def deseasonalise(frame: pd.DataFrame, value: str) -> pd.Series:
    """Remove the day-of-week profile so weekly rhythm is not flagged as anomaly."""
    dow = frame["Date"].dt.dayofweek
    profile = frame.groupby(dow)[value].transform("median")
    overall = frame[value].median()
    return frame[value] - profile + overall


def detect_anomalies(f: dict[str, pd.DataFrame]) -> pd.DataFrame:
    rows: list[dict] = []

    # --- daily sales value per merchant, scored against a 28-day trail ------
    daily = (f["sales"].groupby(["MerchantKey", "Merchant", "Region", "Date"],
                                as_index=False)
             .agg(SalesValue=("SalesValue", "sum"),
                  Transactions=("Transactions", "sum")))
    for (mk, merchant, region), grp in daily.groupby(
            ["MerchantKey", "Merchant", "Region"]):
        grp = grp.sort_values("Date").reset_index(drop=True)
        grp["Adj"] = deseasonalise(grp, "SalesValue")
        z, expected = trailing_robust_z(grp["Adj"], window=28, min_periods=14)
        for i in np.where(z.abs() >= Z_THRESHOLD)[0]:
            rows.append({
                "AnomalyID": f"A-SAL-{mk}-{grp.loc[i, 'Date']:%Y%m%d}",
                "Date": grp.loc[i, "Date"], "MerchantKey": mk,
                "Merchant": merchant, "Region": region, "Measure": "Daily Sales Value",
                "ActualValue": round(float(grp.loc[i, "SalesValue"]), 2),
                "ExpectedValue": round(float(expected[i]), 2),
                "Score": round(float(z[i]), 2),
                "Direction": "Above expected" if z[i] > 0 else "Below expected",
            })

    # --- monthly sales level shift per merchant ----------------------------
    # Point outliers and level shifts are different questions. This one asks
    # "did this merchant move to a new normal?" against its prior 3 months.
    monthly = (f["sales"].groupby(["MerchantKey", "Merchant", "Region",
                                   "MonthYear", "MonthYearSort"], as_index=False)
               .agg(SalesValue=("SalesValue", "sum")))
    for (mk, merchant, region), grp in monthly.groupby(
            ["MerchantKey", "Merchant", "Region"]):
        grp = grp.sort_values("MonthYearSort").reset_index(drop=True)
        base = grp["SalesValue"].shift(1).rolling(3, min_periods=3).mean()
        shift_pct = (grp["SalesValue"] / base - 1) * 100
        for i in np.where(shift_pct.abs() >= 25)[0]:
            rows.append({
                "AnomalyID": f"A-LVL-{mk}-{int(grp.loc[i, 'MonthYearSort'])}",
                "Date": pd.Timestamp(f"{int(grp.loc[i, 'MonthYearSort']) // 100}-"
                                     f"{int(grp.loc[i, 'MonthYearSort']) % 100:02d}-01"),
                "MerchantKey": mk, "Merchant": merchant, "Region": region,
                "Measure": "Monthly Sales Level Shift",
                "ActualValue": round(float(grp.loc[i, "SalesValue"]), 2),
                "ExpectedValue": round(float(base[i]), 2),
                "Score": round(float(shift_pct[i]), 2),
                "Direction": "Above expected" if shift_pct[i] > 0 else "Below expected",
            })

    # --- weekly ticket volume per merchant ---------------------------------
    # Weekly rather than daily: most merchants log zero tickets on most days,
    # so the daily series is too sparse for a stable baseline.
    calendar = f["DimDate"][["Date"]]
    calendar = calendar[calendar["Date"] <= f["tick"]["Date"].max()].copy()
    calendar["WeekStart"] = calendar["Date"] - pd.to_timedelta(
        calendar["Date"].dt.dayofweek, unit="D")
    weeks = pd.DataFrame({"WeekStart": sorted(calendar["WeekStart"].unique())})

    tk = f["tick"].copy()
    tk["WeekStart"] = tk["Date"] - pd.to_timedelta(tk["Date"].dt.dayofweek, unit="D")
    tick_weekly = (tk.groupby(["MerchantKey", "Merchant", "Region", "WeekStart"],
                              as_index=False).agg(Tickets=("TicketID", "count")))
    for (mk, merchant, region), grp in tick_weekly.groupby(
            ["MerchantKey", "Merchant", "Region"]):
        # Weeks with no ticket are genuine zeros, not missing data.
        grp = (weeks.merge(grp, on="WeekStart", how="left")
               .assign(Tickets=lambda x: x["Tickets"].fillna(0))
               .sort_values("WeekStart").reset_index(drop=True))
        # Trailing 8-week baseline, same reasoning as sales: a merchant that
        # steps up to a new ticket level would otherwise pull its own baseline
        # up and stop looking unusual after two or three weeks.
        z, expected = trailing_robust_z(grp["Tickets"], window=8, min_periods=4,
                                        mad_floor_frac=0.0)
        mad_guard = grp["Tickets"].shift(1).rolling(8, min_periods=4).apply(
            lambda w: np.median(np.abs(w - np.median(w))), raw=True)
        # Counts need an absolute floor, not a proportional one: a merchant
        # sitting at zero tickets has a MAD of zero and would flag on a single
        # routine ticket.
        z = 0.6745 * (grp["Tickets"] - expected) / np.maximum(mad_guard, 1.0)
        for i in np.where((z >= Z_THRESHOLD) & (grp["Tickets"] >= 5))[0]:
            rows.append({
                "AnomalyID": f"A-TKT-{mk}-{grp.loc[i, 'WeekStart']:%Y%m%d}",
                "Date": grp.loc[i, "WeekStart"], "MerchantKey": mk,
                "Merchant": merchant, "Region": region,
                "Measure": "Weekly Ticket Volume",
                "ActualValue": round(float(grp.loc[i, "Tickets"]), 2),
                "ExpectedValue": round(float(expected[i]), 2),
                "Score": round(float(z[i]), 2), "Direction": "Above expected",
            })

    # --- monthly ticket level shift per merchant ---------------------------
    tick_monthly = (f["tick"].groupby(["MerchantKey", "Merchant", "Region",
                                       "MonthYearSort"], as_index=False)
                    .agg(Tickets=("TicketID", "count")))
    all_months = sorted(f["sales"]["MonthYearSort"].unique())
    for (mk, merchant, region), grp in tick_monthly.groupby(
            ["MerchantKey", "Merchant", "Region"]):
        grp = (pd.DataFrame({"MonthYearSort": all_months})
               .merge(grp, on="MonthYearSort", how="left")
               .assign(Tickets=lambda x: x["Tickets"].fillna(0))
               .sort_values("MonthYearSort").reset_index(drop=True))
        base = grp["Tickets"].shift(1).rolling(3, min_periods=3).mean()
        shift_pct = (grp["Tickets"] / base.replace(0, np.nan) - 1) * 100
        # Require both a large relative move and a material absolute one.
        hit = (shift_pct >= 100) & (grp["Tickets"] - base >= 8)
        for i in np.where(hit.fillna(False))[0]:
            ms = int(grp.loc[i, "MonthYearSort"])
            rows.append({
                "AnomalyID": f"A-TLV-{mk}-{ms}",
                "Date": pd.Timestamp(f"{ms // 100}-{ms % 100:02d}-01"),
                "MerchantKey": mk, "Merchant": merchant, "Region": region,
                "Measure": "Monthly Ticket Level Shift",
                "ActualValue": round(float(grp.loc[i, "Tickets"]), 2),
                "ExpectedValue": round(float(base[i]), 2),
                "Score": round(float(shift_pct[i]), 2),
                "Direction": "Above expected",
            })

    # --- weekly time-to-redeem per region x voucher type --------------------
    red = f["red"][f["red"]["IsRedeemed"] == 1].copy()
    red["WeekStart"] = red["SoldDate"] - pd.to_timedelta(
        red["SoldDate"].dt.dayofweek, unit="D")
    weekly = (red.groupby(["Region", "VoucherTypeKey", "WeekStart"], as_index=False)
              .agg(AvgDays=("DaysToRedeem", "mean"), Vouchers=("VoucherID", "count")))
    weekly = weekly[weekly["Vouchers"] >= 20]  # ignore thin weeks
    for (region, vt), grp in weekly.groupby(["Region", "VoucherTypeKey"]):
        grp = grp.sort_values("WeekStart").reset_index(drop=True)
        z = robust_z(grp["AvgDays"])
        expected = grp["AvgDays"].median()
        for i in np.where(z >= Z_THRESHOLD)[0]:
            rows.append({
                "AnomalyID": f"A-RED-{region[:3].upper()}-{vt[:3].upper()}"
                             f"-{grp.loc[i, 'WeekStart']:%Y%m%d}",
                "Date": grp.loc[i, "WeekStart"], "MerchantKey": None,
                "Merchant": f"{region} / {vt}", "Region": region,
                "Measure": "Avg Days To Redeem (weekly)",
                "ActualValue": round(float(grp.loc[i, "AvgDays"]), 2),
                "ExpectedValue": round(float(expected), 2),
                "Score": round(float(z[i]), 2), "Direction": "Above expected",
            })

    out = pd.DataFrame(rows)
    if out.empty:
        return out

    # ZScore carries a robust z for the point detectors and a percentage move
    # for the level-shift detector, so severity is banded per measure.
    out["ScoreType"] = np.where(
        out["Measure"].isin(["Monthly Sales Level Shift",
                             "Monthly Ticket Level Shift"]),
        "Percent change", "Robust z")
    is_pct = out["ScoreType"] == "Percent change"
    mag = out["Score"].abs()
    out["Severity"] = np.where(
        is_pct,
        np.where(mag >= 40, "High", np.where(mag >= 30, "Medium", "Low")),
        np.where(mag >= 8, "High", np.where(mag >= 5, "Medium", "Low")))
    # Deviation from expected, comparable across every detector.
    out["DeviationPct"] = (
        (out["ActualValue"] - out["ExpectedValue"])
        / out["ExpectedValue"].replace(0, np.nan) * 100).round(1)
    return out.sort_values(["Measure", "Date"]).reset_index(drop=True)


# ------------------------------------------------------------- narrative ----
def build_narrative(f: dict[str, pd.DataFrame], anomalies: pd.DataFrame
                    ) -> pd.DataFrame:
    """Rule-based plain-English explanation of each merchant's month-on-month move.

    Deliberately deterministic rather than LLM-generated: the same inputs always
    produce the same sentence, which is what an operations team needs from a
    field that drives a work queue. See docs/04_AI_Extension.md.
    """
    s = f["sales"]
    monthly = (s.groupby(["MerchantKey", "Merchant", "Region", "Channel",
                          "MonthYear", "MonthYearSort"], as_index=False)
               .agg(SalesValue=("SalesValue", "sum"),
                    Transactions=("Transactions", "sum")))
    monthly = monthly.sort_values(["MerchantKey", "MonthYearSort"])
    last_month = monthly["MonthYearSort"].max()
    prev_month = sorted(monthly["MonthYearSort"].unique())[-2]

    cur = monthly[monthly["MonthYearSort"] == last_month].set_index("MerchantKey")
    prv = monthly[monthly["MonthYearSort"] == prev_month].set_index("MerchantKey")

    tick = f["tick"]
    tick_m = (tick.groupby(["MerchantKey", "MonthYearSort"], as_index=False)
              .agg(Tickets=("TicketID", "count"),
                   AvgRes=("ResolutionHours", "mean"),
                   Breaches=("IsSLABreach", "sum")))
    tc = tick_m[tick_m["MonthYearSort"] == last_month].set_index("MerchantKey")
    tp = tick_m[tick_m["MonthYearSort"] == prev_month].set_index("MerchantKey")

    red = f["red"]
    red_m = (red.groupby(["MerchantKey", "MonthYearSort"], as_index=False)
             .agg(Rate=("IsRedeemed", "mean"), Vouchers=("VoucherID", "count")))
    rc = red_m[red_m["MonthYearSort"] == last_month].set_index("MerchantKey")
    rp = red_m[red_m["MonthYearSort"] == prev_month].set_index("MerchantKey")

    rows = []
    for mk in cur.index:
        if mk not in prv.index:
            continue
        sales_now, sales_then = cur.loc[mk, "SalesValue"], prv.loc[mk, "SalesValue"]
        delta = (sales_now / sales_then - 1) * 100
        tx_delta = (cur.loc[mk, "Transactions"] / prv.loc[mk, "Transactions"] - 1) * 100
        aov_now = sales_now / cur.loc[mk, "Transactions"]
        aov_then = sales_then / prv.loc[mk, "Transactions"]
        aov_delta = (aov_now / aov_then - 1) * 100

        t_now = int(tc.loc[mk, "Tickets"]) if mk in tc.index else 0
        t_then = int(tp.loc[mk, "Tickets"]) if mk in tp.index else 0
        r_now = float(rc.loc[mk, "Rate"]) * 100 if mk in rc.index else np.nan
        r_then = float(rp.loc[mk, "Rate"]) * 100 if mk in rp.index else np.nan

        if delta <= -15:
            headline, flag = "Sharp decline", "Investigate"
        elif delta <= -5:
            headline, flag = "Softening", "Monitor"
        elif delta >= 15:
            headline, flag = "Strong growth", "Replicate"
        elif delta >= 5:
            headline, flag = "Growing", "Healthy"
        else:
            headline, flag = "Stable", "Healthy"

        # Volume vs basket-size decomposition: which side moved the number?
        if abs(tx_delta) > abs(aov_delta) * 1.5:
            driver = (f"driven by transaction volume ({tx_delta:+.1f}%) rather than "
                      f"basket size ({aov_delta:+.1f}%)")
        elif abs(aov_delta) > abs(tx_delta) * 1.5:
            driver = (f"driven by average basket size ({aov_delta:+.1f}%) rather than "
                      f"transaction volume ({tx_delta:+.1f}%)")
        else:
            driver = (f"volume and basket size moved together "
                      f"({tx_delta:+.1f}% and {aov_delta:+.1f}%)")

        parts = [f"{cur.loc[mk, 'Merchant']} ({cur.loc[mk, 'Region']}, "
                 f"{cur.loc[mk, 'Channel']}) {headline.lower()}: sales "
                 f"{delta:+.1f}% month on month, {driver}."]

        if t_then > 0 and t_now >= t_then * 2 and t_now >= 5:
            parts.append(f"Support tickets rose from {t_then} to {t_now} over the "
                         f"same period, which is the most likely operational cause.")
        elif t_now >= 5 and t_then == 0:
            parts.append(f"Support tickets appeared this month ({t_now}) having been "
                         f"absent last month.")
        elif t_now > 0:
            parts.append(f"Support ticket volume was {t_now} versus {t_then} "
                         f"last month.")

        if not np.isnan(r_now) and not np.isnan(r_then) and abs(r_now - r_then) >= 3:
            parts.append(f"Redemption rate moved {r_now - r_then:+.1f} points to "
                         f"{r_now:.1f}%.")

        rows.append({
            "MerchantKey": mk, "Merchant": cur.loc[mk, "Merchant"],
            "Region": cur.loc[mk, "Region"], "Channel": cur.loc[mk, "Channel"],
            "Headline": headline, "ActionFlag": flag,
            "SalesMoMPct": round(float(delta), 2),
            "TransactionsMoMPct": round(float(tx_delta), 2),
            "AvgBasketMoMPct": round(float(aov_delta), 2),
            "TicketsThisMonth": t_now, "TicketsPrevMonth": t_then,
            "Narrative": " ".join(parts),
        })

    order = {"Investigate": 0, "Monitor": 1, "Replicate": 2, "Healthy": 3}
    out = pd.DataFrame(rows)
    out["_o"] = out["ActionFlag"].map(order)
    return out.sort_values(["_o", "SalesMoMPct"]).drop(columns="_o").reset_index(drop=True)


# ---------------------------------------------------------------- figures ----
def build_figures(f: dict[str, pd.DataFrame], anomalies: pd.DataFrame,
                  narrative: pd.DataFrame) -> dict:
    s, red, tick = f["sales"], f["red"], f["tick"]

    months = (f["DimDate"][["MonthYear", "MonthYearSort"]].drop_duplicates()
              .sort_values("MonthYearSort"))
    months = months[months["MonthYearSort"] <= int(
        s["MonthYearSort"].max())]["MonthYear"].tolist()

    total_sales = float(s["SalesValue"].sum())
    total_tx = int(s["Transactions"].sum())
    redemption_rate = float(red["IsRedeemed"].mean() * 100)
    avg_res = float(tick["ResolutionHours"].mean())
    sla_breach = float(tick["IsSLABreach"].mean() * 100)
    delayed = float(red.loc[red["IsRedeemed"] == 1, "IsDelayedRedemption"].mean() * 100)
    avg_days = float(red.loc[red["IsRedeemed"] == 1, "DaysToRedeem"].mean())

    cur_ms, prev_ms = sorted(s["MonthYearSort"].unique())[-1], sorted(
        s["MonthYearSort"].unique())[-2]
    cur_sales = float(s.loc[s["MonthYearSort"] == cur_ms, "SalesValue"].sum())
    prev_sales = float(s.loc[s["MonthYearSort"] == prev_ms, "SalesValue"].sum())

    def by(frame, keys, **aggs):
        return frame.groupby(keys, as_index=False).agg(**aggs)

    monthly_sales = by(s, ["MonthYear", "MonthYearSort"],
                       SalesValue=("SalesValue", "sum"),
                       Transactions=("Transactions", "sum")).sort_values("MonthYearSort")

    monthly_region = (by(s, ["Region", "MonthYear", "MonthYearSort"],
                         SalesValue=("SalesValue", "sum"))
                      .sort_values(["Region", "MonthYearSort"]))
    region_series = {
        r: [round(float(v), 2) for v in g["SalesValue"]]
        for r, g in monthly_region.groupby("Region")
    }

    region_totals = by(s, ["Region"], SalesValue=("SalesValue", "sum"),
                       Transactions=("Transactions", "sum")).sort_values(
        "SalesValue", ascending=False)
    # Region momentum: last month vs the average of the three before it.
    reg_mom = []
    for r, g in monthly_region.groupby("Region"):
        g = g.sort_values("MonthYearSort")
        last = float(g["SalesValue"].iloc[-1])
        base = float(g["SalesValue"].iloc[-4:-1].mean())
        reg_mom.append({"Region": r, "LastMonth": round(last, 2),
                        "Prior3MonthAvg": round(base, 2),
                        "MomentumPct": round((last / base - 1) * 100, 2)})
    reg_mom.sort(key=lambda x: x["MomentumPct"])

    merch = by(s, ["MerchantKey", "Merchant", "Region", "Channel"],
               SalesValue=("SalesValue", "sum"),
               Transactions=("Transactions", "sum")).sort_values(
        "SalesValue", ascending=False)
    merch["SharePct"] = merch["SalesValue"] / merch["SalesValue"].sum() * 100
    merch["CumSharePct"] = merch["SharePct"].cumsum()
    merch["Rank"] = range(1, len(merch) + 1)
    merch["AvgBasket"] = merch["SalesValue"] / merch["Transactions"]

    merch_red = by(red, ["MerchantKey"], RedemptionRate=("IsRedeemed", "mean"),
                   Vouchers=("VoucherID", "count"))
    merch_red["RedemptionRate"] *= 100
    merch_tick = by(tick, ["MerchantKey"], Tickets=("TicketID", "count"),
                    AvgResolutionHours=("ResolutionHours", "mean"),
                    SLABreaches=("IsSLABreach", "sum"))
    merch_full = (merch.merge(merch_red, on="MerchantKey", how="left")
                  .merge(merch_tick, on="MerchantKey", how="left"))
    merch_full[["Tickets", "SLABreaches"]] = merch_full[
        ["Tickets", "SLABreaches"]].fillna(0)
    merch_full["SLABreachPct"] = np.where(
        merch_full["Tickets"] > 0,
        merch_full["SLABreaches"] / merch_full["Tickets"] * 100, 0)
    merch_full["TicketsPer1kTx"] = merch_full["Tickets"] / merch_full[
        "Transactions"] * 1000
    merch_full = merch_full.merge(
        narrative[["MerchantKey", "SalesMoMPct", "Headline", "ActionFlag",
                   "Narrative"]], on="MerchantKey", how="left")

    voucher = by(s, ["VoucherTypeKey"], SalesValue=("SalesValue", "sum"),
                 Transactions=("Transactions", "sum"))
    vred = by(red, ["VoucherTypeKey"], RedemptionRate=("IsRedeemed", "mean"),
              Vouchers=("VoucherID", "count"),
              AvgDaysToRedeem=("DaysToRedeem", "mean"))
    vred["RedemptionRate"] *= 100
    vdelay = (red[red["IsRedeemed"] == 1].groupby("VoucherTypeKey", as_index=False)
              .agg(DelayedPct=("IsDelayedRedemption", "mean")))
    vdelay["DelayedPct"] *= 100
    voucher = (voucher.merge(vred, on="VoucherTypeKey")
               .merge(vdelay, on="VoucherTypeKey")
               .sort_values("RedemptionRate", ascending=False))

    monthly_red = (red.groupby(["MonthYear", "MonthYearSort"], as_index=False)
                   .agg(RedemptionRate=("IsRedeemed", "mean"))
                   .sort_values("MonthYearSort"))
    monthly_red["RedemptionRate"] *= 100

    # Region x voucher type time-to-redeem heat grid (April delay evidence)
    rr = red[red["IsRedeemed"] == 1]
    lag_grid = (rr.groupby(["Region", "VoucherTypeKey", "MonthYear", "MonthYearSort"],
                           as_index=False).agg(AvgDays=("DaysToRedeem", "mean"),
                                               Vouchers=("VoucherID", "count"))
                .sort_values("MonthYearSort"))

    monthly_tick = (tick.groupby(["MonthYear", "MonthYearSort"], as_index=False)
                    .agg(Tickets=("TicketID", "count"),
                         AvgResolutionHours=("ResolutionHours", "mean"),
                         Breaches=("IsSLABreach", "sum"))
                    .sort_values("MonthYearSort"))
    monthly_tick["SLABreachPct"] = (monthly_tick["Breaches"]
                                    / monthly_tick["Tickets"] * 100)

    prio = (tick.groupby(["PriorityKey", "PrioritySort"], as_index=False)
            .agg(Tickets=("TicketID", "count"),
                 AvgResolutionHours=("ResolutionHours", "mean"),
                 Breaches=("IsSLABreach", "sum"),
                 SLATargetHours=("SLATargetHours", "max"))
            .sort_values("PrioritySort"))
    prio["SLABreachPct"] = prio["Breaches"] / prio["Tickets"] * 100

    ttype = (tick.groupby(["TicketTypeKey", "TicketCategory"], as_index=False)
             .agg(Tickets=("TicketID", "count"),
                  AvgResolutionHours=("ResolutionHours", "mean"),
                  Breaches=("IsSLABreach", "sum"))
             .sort_values("Tickets", ascending=False))
    ttype["SLABreachPct"] = ttype["Breaches"] / ttype["Tickets"] * 100

    status = (tick.groupby("Status", as_index=False).agg(Tickets=("TicketID", "count"))
              .sort_values("Tickets", ascending=False))

    # --- does operational friction track weaker performance? ---------------
    # Correlate per-merchant ticket intensity against month-on-month growth.
    corr_frame = merch_full.dropna(subset=["SalesMoMPct"])
    corr_tickets = float(np.corrcoef(corr_frame["TicketsPer1kTx"],
                                     corr_frame["SalesMoMPct"])[0, 1])
    corr_res = float(np.corrcoef(corr_frame["AvgResolutionHours"].fillna(0),
                                 corr_frame["SalesMoMPct"])[0, 1])
    corr_breach = float(np.corrcoef(corr_frame["SLABreachPct"],
                                    corr_frame["SalesMoMPct"])[0, 1])

    # Same test at merchant-month grain, which is where the real signal sits.
    sm = (s.groupby(["MerchantKey", "MonthYearSort"], as_index=False)
          .agg(SalesValue=("SalesValue", "sum")))
    sm = sm.sort_values(["MerchantKey", "MonthYearSort"])
    sm["PrevSales"] = sm.groupby("MerchantKey")["SalesValue"].shift(1)
    sm["MoMPct"] = (sm["SalesValue"] / sm["PrevSales"] - 1) * 100
    tm = (tick.groupby(["MerchantKey", "MonthYearSort"], as_index=False)
          .agg(Tickets=("TicketID", "count")))
    panel = sm.merge(tm, on=["MerchantKey", "MonthYearSort"], how="left")
    panel["Tickets"] = panel["Tickets"].fillna(0)
    panel["PrevTickets"] = panel.groupby("MerchantKey")["Tickets"].shift(1)
    panel = panel.dropna(subset=["MoMPct", "PrevTickets"])
    panel["TicketSurge"] = panel["Tickets"] - panel["PrevTickets"]
    corr_panel = float(np.corrcoef(panel["TicketSurge"], panel["MoMPct"])[0, 1])
    surge = panel[panel["TicketSurge"] >= 10]
    no_surge = panel[panel["TicketSurge"] < 10]

    figures = {
        "meta": {
            "period_start": str(f["DimDate"]["Date"].min().date()),
            "period_end": str(s.merge(f["DimDate"][["MonthYear", "MonthYearSort"]]
                                      .drop_duplicates(), on="MonthYear")
                              .pipe(lambda _: "")) or "2026-07-31",
            "months": months,
            "merchants": int(s["MerchantKey"].nunique()),
            "regions": int(s["Region"].nunique()),
            "voucher_types": int(s["VoucherTypeKey"].nunique()),
            "currency": "ZAR",
        },
        "kpi": {
            "total_sales": round(total_sales, 2),
            "total_transactions": total_tx,
            "avg_basket": round(total_sales / total_tx, 2),
            "redemption_rate": round(redemption_rate, 2),
            "avg_resolution_hours": round(avg_res, 2),
            "sla_breach_pct": round(sla_breach, 2),
            "delayed_redemption_pct": round(delayed, 2),
            "avg_days_to_redeem": round(avg_days, 2),
            "total_tickets": int(len(tick)),
            "open_tickets": int(tick["IsOpen"].sum()),
            "vouchers_sold": int(len(red)),
            "voucher_value": round(float(red["VoucherValue"].sum()), 2),
            "current_month_sales": round(cur_sales, 2),
            "prev_month_sales": round(prev_sales, 2),
            "mom_pct": round((cur_sales / prev_sales - 1) * 100, 2),
        },
        "monthly_sales": monthly_sales.round(2).to_dict("records"),
        "monthly_redemption": monthly_red.round(2).to_dict("records"),
        "monthly_tickets": monthly_tick.round(2).to_dict("records"),
        "region_totals": region_totals.round(2).to_dict("records"),
        "region_series": region_series,
        "region_momentum": reg_mom,
        "merchants": merch_full.round(2).to_dict("records"),
        "voucher_types": voucher.round(2).to_dict("records"),
        "lag_grid": lag_grid.round(2).to_dict("records"),
        "priority": prio.round(2).to_dict("records"),
        "ticket_types": ttype.round(2).to_dict("records"),
        "ticket_status": status.to_dict("records"),
        "anomalies": (anomalies.assign(Date=anomalies["Date"].dt.strftime("%Y-%m-%d"))
                      .to_dict("records") if not anomalies.empty else []),
        "narrative": narrative.to_dict("records"),
        "correlation": {
            "tickets_per_1k_tx_vs_mom": round(corr_tickets, 3),
            "avg_resolution_hours_vs_mom": round(corr_res, 3),
            "sla_breach_pct_vs_mom": round(corr_breach, 3),
            "ticket_surge_vs_mom_panel": round(corr_panel, 3),
            "mom_when_ticket_surge": round(float(surge["MoMPct"].mean()), 2),
            "mom_when_no_surge": round(float(no_surge["MoMPct"].mean()), 2),
            "surge_month_count": int(len(surge)),
        },
        "concentration": {
            "top5_share": round(float(merch["SharePct"].head(5).sum()), 2),
            "top10_share": round(float(merch["SharePct"].head(10).sum()), 2),
            "merchants_to_80pct": int((merch["CumSharePct"] <= 80).sum() + 1),
        },
    }
    figures["meta"]["period_end"] = "2026-07-31"
    return figures


def main() -> None:
    t = load()
    f = denorm(t)

    anomalies = detect_anomalies(f)
    narrative = build_narrative(f, anomalies)

    anomalies_out = anomalies.copy()
    if not anomalies_out.empty:
        anomalies_out["Date"] = anomalies_out["Date"].dt.strftime("%Y-%m-%d")
    anomalies_out.to_csv(GOLD / "FactAnomaly.csv", index=False)
    narrative.to_csv(GOLD / "InsightNarrative.csv", index=False)

    figures = build_figures(f, anomalies, narrative)
    (DASH / "data.json").write_text(json.dumps(figures, indent=1, default=str),
                                    encoding="utf8")
    (DOCS / "_computed_findings.json").write_text(
        json.dumps(figures, indent=1, default=str), encoding="utf8")

    print(f"FactAnomaly.csv          {len(anomalies):>6,} rows")
    print(f"InsightNarrative.csv     {len(narrative):>6,} rows")
    print(f"dashboard/data.json      written")
    print()
    if not anomalies.empty:
        print("Anomalies by measure and severity:")
        print(anomalies.groupby(["Measure", "Severity"]).size().to_string())
        print()
        print("Top 12 by |z|:")
        top = anomalies.reindex(anomalies["Score"].abs().sort_values(
            ascending=False).index).head(12)
        print(top[["Date", "Merchant", "Measure", "ActualValue", "ExpectedValue",
                   "Score", "Severity"]].to_string(index=False))
    print()
    print("Merchants flagged for action:")
    print(narrative[narrative["ActionFlag"].isin(["Investigate", "Monitor",
                                                  "Replicate"])]
          [["Merchant", "ActionFlag", "SalesMoMPct", "TicketsPrevMonth",
            "TicketsThisMonth"]].to_string(index=False))
    print()
    print("Correlation block:", json.dumps(figures["correlation"], indent=1))


if __name__ == "__main__":
    main()
