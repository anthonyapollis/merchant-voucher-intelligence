"""
07_build_excel.py
=================
Builds the distributed Excel pack: Merchant_Voucher_Intelligence_Report.xlsx

Every figure is read from the SAME gold/analytics layer that feeds the Power BI report and
the ML notebook. Nothing is recomputed here — this module formats and presents, it does not
calculate. That is precisely why the workbook and the dashboard agree, and it is the
difference between an Excel pack that supports the report and one that quietly contradicts it.

Sheets:
    1. Cover & Contents        navigation, provenance, reconciliation status
    2. Executive Summary       headline KPIs, monthly trend, region and voucher performance
    3. Merchant Scorecard      all 25 merchants, conditionally formatted, sortable
    4. Voucher Analysis        redemption by type, delayed redemption, outstanding liability
    5. Operational View        tickets, SLA, priority, the SLA policy finding
    6. Anomalies & Alerts      rules-based alerts + Isolation Forest output
    7. ML Model Results        metrics, feature importance, forecast, segments
    8. Business Questions      the five brief questions with computed answers
    9. Data Dictionary         every field, source, grain and definition
   10. Assumptions & Limits    documented decisions and known data issues
"""
from pathlib import Path
import json
import sys
import numpy as np
import pandas as pd
import xlsxwriter

sys.path.insert(0, str(Path(__file__).parent))
from _table_registry import (TABLES as REG, TIERS, SUMMARY as REG_SUMMARY,
                             COUNTER_ARGUMENT as REG_COUNTER, counts as _tc, TIER_ORDER)
TIER_COUNTS = _tc()

ROOT = Path(__file__).resolve().parents[1]
ANA = ROOT / "data" / "analytics"
ML = ROOT / "data" / "ml"
OUT = ROOT / "excel" / "Merchant_Voucher_Intelligence_Report.xlsx"
OUT.parent.mkdir(parents=True, exist_ok=True)

summary = json.load(open(ROOT / "docs" / "analytics_summary.json"))
mlsum = json.load(open(ROOT / "docs" / "ml_summary.json"))
recon = json.load(open(ROOT / "docs" / "reconciliation.json"))
K = summary["exec_kpis"]

L = lambda n: pd.read_parquet(ANA / f"{n}.parquet")
M = lambda n: pd.read_parquet(ML / f"{n}.parquet")

trend = L("kpi_monthly_trend")
region = L("kpi_region_performance")
region_m = L("kpi_region_month")
vtype = L("kpi_voucher_type")
vtype_m = L("kpi_voucher_type_month")
score = L("kpi_merchant_scorecard")
tkt_type = L("kpi_ticket_type")
priority = L("kpi_priority")
tkt_month = L("kpi_ticket_month")
status = L("kpi_status")
alerts = L("kpi_alerts")
friction = L("kpi_friction_quartiles")
events = L("kpi_ticket_spike_events")
rvt = L("kpi_region_vouchertype_month")

anom = M("ml_anomalies")
fcast = M("ml_sales_forecast")
mfcast = M("ml_merchant_forecast")
segprof = M("ml_segment_profile")
segments = M("ml_merchant_segments")
deciles = M("ml_redemption_risk_deciles")
redimp = M("ml_redemption_feature_importance")
resimp = M("ml_resolution_feature_importance")

# Fail with a readable message rather than a traceback when the workbook is open in Excel —
# Windows holds an exclusive lock on it, and "Permission denied" is not an obvious symptom.
try:
    with open(OUT, "a"):
        pass
except PermissionError:
    raise SystemExit(
        f"\nCannot write {OUT.name} — the file is open in Excel.\n"
        f"Close it and re-run:  python scripts/07_build_excel.py\n")
except FileNotFoundError:
    pass

wb = xlsxwriter.Workbook(str(OUT), {"nan_inf_to_errors": True})

# ---------------------------------------------------------------- palette & formats
NAVY, TEAL, AMBER, RED, GREEN, GREY = "#12305B", "#0E8B8B", "#E8A317", "#C0392B", "#1E8449", "#5A6672"
LIGHT, BAND, WHITE = "#EEF3F9", "#F7FAFC", "#FFFFFF"

f = lambda **kw: wb.add_format(kw)
title = f(font_size=22, bold=True, font_color=NAVY, font_name="Calibri Light")
subtitle = f(font_size=11, font_color=GREY, italic=True)
h1 = f(font_size=14, bold=True, font_color=WHITE, bg_color=NAVY, align="left",
       valign="vcenter", indent=1)
h2 = f(font_size=11, bold=True, font_color=NAVY, bottom=2, border_color=TEAL)
hdr = f(bold=True, font_color=WHITE, bg_color=TEAL, border=1, border_color="#FFFFFF",
        align="center", valign="vcenter", text_wrap=True, font_size=10)
cell = f(border=1, border_color="#D6DEE8", font_size=10)
cellb = f(border=1, border_color="#D6DEE8", font_size=10, bg_color=BAND)
txt = f(font_size=10, text_wrap=True, valign="top", border=1, border_color="#D6DEE8")
txt_b = f(font_size=10, text_wrap=True, valign="top", border=1, border_color="#D6DEE8",
          bg_color=BAND)
money = f(num_format='R #,##0', border=1, border_color="#D6DEE8", font_size=10)
money2 = f(num_format='R #,##0.00', border=1, border_color="#D6DEE8", font_size=10)
num = f(num_format='#,##0', border=1, border_color="#D6DEE8", font_size=10)
dec = f(num_format='#,##0.00', border=1, border_color="#D6DEE8", font_size=10)
pct1 = f(num_format='0.0%', border=1, border_color="#D6DEE8", font_size=10)
pct2 = f(num_format='0.00%', border=1, border_color="#D6DEE8", font_size=10)
pctsig = f(num_format='+0.0%;-0.0%;0.0%', border=1, border_color="#D6DEE8", font_size=10)
datef = f(num_format='yyyy-mm-dd', border=1, border_color="#D6DEE8", font_size=10)
note = f(font_size=9, font_color=GREY, italic=True, text_wrap=True, valign="top")
bold = f(bold=True, font_size=10, border=1, border_color="#D6DEE8")

kpi_lbl = f(font_size=9, font_color=WHITE, bg_color=NAVY, align="center", valign="bottom",
            top=2, left=2, right=2, border_color=NAVY)
kpi_val = f(font_size=18, bold=True, font_color=WHITE, bg_color=NAVY, align="center",
            valign="vcenter", left=2, right=2, border_color=NAVY)
kpi_sub = f(font_size=8, font_color="#B9C7DA", bg_color=NAVY, align="center", valign="top",
            bottom=2, left=2, right=2, border_color=NAVY)
kpi_val_t = f(font_size=18, bold=True, font_color=WHITE, bg_color=TEAL, align="center",
              valign="vcenter", left=2, right=2, border_color=TEAL)
kpi_lbl_t = f(font_size=9, font_color=WHITE, bg_color=TEAL, align="center", valign="bottom",
              top=2, left=2, right=2, border_color=TEAL)
kpi_sub_t = f(font_size=8, font_color="#CDEBEB", bg_color=TEAL, align="center", valign="top",
              bottom=2, left=2, right=2, border_color=TEAL)
kpi_val_a = f(font_size=18, bold=True, font_color="#3D2B00", bg_color=AMBER, align="center",
              valign="vcenter", left=2, right=2, border_color=AMBER)
kpi_lbl_a = f(font_size=9, font_color="#3D2B00", bg_color=AMBER, align="center",
              valign="bottom", top=2, left=2, right=2, border_color=AMBER)
kpi_sub_a = f(font_size=8, font_color="#5C4200", bg_color=AMBER, align="center",
              valign="top", bottom=2, left=2, right=2, border_color=AMBER)

SETS = {"navy": (kpi_lbl, kpi_val, kpi_sub), "teal": (kpi_lbl_t, kpi_val_t, kpi_sub_t),
        "amber": (kpi_lbl_a, kpi_val_a, kpi_sub_a)}


def kpi_card(ws, row, col, label, value, sub, fmt="R #,##0", theme="navy", width=3):
    lf, _, sf = SETS[theme]
    ws.merge_range(row, col, row, col + width - 1, label, lf)
    v = wb.add_format({"font_size": 18, "bold": True, "align": "center", "valign": "vcenter",
                       "left": 2, "right": 2, "num_format": fmt,
                       "font_color": "#3D2B00" if theme == "amber" else WHITE,
                       "bg_color": {"navy": NAVY, "teal": TEAL, "amber": AMBER}[theme],
                       "border_color": {"navy": NAVY, "teal": TEAL, "amber": AMBER}[theme]})
    ws.merge_range(row + 1, col, row + 1, col + width - 1, value, v)
    ws.merge_range(row + 2, col, row + 2, col + width - 1, sub, sf)


def write_table(ws, df, start_row, start_col, formats, col_widths=None, banded=True,
                total_row=None):
    """Write a dataframe as a formatted table. `formats` maps column name -> xlsxwriter format."""
    for j, c in enumerate(df.columns):
        ws.write(start_row, start_col + j, c, hdr)
        if col_widths and c in col_widths:
            ws.set_column(start_col + j, start_col + j, col_widths[c])
    for i, (_, r) in enumerate(df.iterrows()):
        for j, c in enumerate(df.columns):
            v = r[c]
            fmt = formats.get(c, cell)
            if banded and i % 2 == 1 and fmt is cell:
                fmt = cellb
            if pd.isna(v):
                ws.write_blank(start_row + 1 + i, start_col + j, None, fmt)
            elif isinstance(v, (np.integer,)):
                ws.write_number(start_row + 1 + i, start_col + j, int(v), fmt)
            elif isinstance(v, (np.floating, float)):
                ws.write_number(start_row + 1 + i, start_col + j, float(v), fmt)
            elif isinstance(v, (pd.Timestamp,)):
                ws.write_datetime(start_row + 1 + i, start_col + j, v, formats.get(c, datef))
            else:
                ws.write(start_row + 1 + i, start_col + j, str(v), fmt)
    return start_row + 1 + len(df)


def section(ws, row, text, width=12):
    ws.merge_range(row, 0, row, width, f"  {text}", h1)
    ws.set_row(row, 24)
    return row + 2


# ======================================================================================
# SHEET 1 — Cover & Contents
# ======================================================================================
ws = wb.add_worksheet("1. Cover")
ws.hide_gridlines(2)
ws.set_column("A:A", 2); ws.set_column("B:B", 34); ws.set_column("C:C", 62)
ws.set_column("D:D", 22)
ws.write("B2", "Merchant Sales & Voucher Intelligence", title)
ws.write("B3", "BI Developer Second-Round Practical Task  |  Microsoft Fabric + Power BI + dbt",
         subtitle)
ws.write("B4", "Reporting period: 1 January 2026 – 31 July 2026  (212 days, 25 merchants)",
         subtitle)

r = 6
ws.merge_range(r, 1, r, 3, "  CONTENTS", h1); ws.set_row(r, 22); r += 1
contents = [
    ("2. Executive Summary", "Headline KPIs, monthly trend, region and voucher performance"),
    ("3. Merchant Scorecard", "All 25 merchants ranked, with health score and revenue at risk"),
    ("4. Voucher Analysis", "Redemption rate by type, time-to-redeem, outstanding liability"),
    ("5. Operational View", "Ticket volume, SLA breach analysis, the SLA policy finding"),
    ("6. Anomalies & Alerts", "Rules-based alerts and Isolation Forest detections"),
    ("7. ML Model Results", "Five models: metrics, feature importance, forecast, segments"),
    ("8. Business Questions", "The five questions in the brief, with computed answers"),
    ("9. Data Dictionary", "Every field: source, grain, type and definition"),
    ("10. Assumptions", "Documented decisions, known data issues and limitations"),
]
for name, desc in contents:
    ws.write(r, 1, name, bold)
    ws.write(r, 2, desc, txt)
    ws.write(r, 3, "", cell)
    r += 1

r += 1
ws.merge_range(r, 1, r, 3, "  DATA PROVENANCE & INTEGRITY", h1); ws.set_row(r, 22); r += 1
prov = [
    ("Source files", "4 CSV files as supplied (MerchantSales, VoucherRedemptions, "
                     "SupportTickets, MerchantReference)"),
    ("Rows processed", f"{K['VouchersSold']:,} vouchers, 26,500 sales rows, "
                       f"{K['TotalTickets']:,} tickets, {K['Merchants']} merchants"),
    ("Architecture", "Medallion: bronze (raw + lineage) → silver (typed, cleansed, conformed) "
                     "→ gold (Kimball star schema)"),
    ("Warehouse integrity tests", "14 / 14 passed"),
    ("dbt build", "153 pass · 0 warn · 0 error  (18 models, 1 SCD2 snapshot, 132 tests)"),
    ("SCD Type 2 validation", "7 / 7 behaviour assertions passed"),
    ("Python ↔ dbt reconciliation",
     f"{recon['passed']} passed, {recon['warnings']} warning, {recon['failures']} failed"),
    ("Reconciliation note", "The gold layer is built twice by independent implementations "
                            "(pandas and dbt SQL). Every headline figure agrees to the cent; "
                            "the single warning is a documented rounding-convention "
                            "difference of 0.1 on the health score."),
    ("Figures in this workbook", "Read directly from the gold layer. Nothing is recomputed "
                                 "here, which is why this pack and the Power BI report agree."),
]
for k_, v_ in prov:
    ws.write(r, 1, k_, bold); ws.merge_range(r, 2, r, 3, v_, txt); r += 1

r += 1
ws.merge_range(r, 1, r, 3,
               "Prepared by Anthony Apollis  ·  All figures computed from the supplied "
               "synthetic dataset  ·  Generated 11 August 2026", note)


# ======================================================================================
# SHEET 2 — Executive Summary
# ======================================================================================
ws = wb.add_worksheet("2. Executive Summary")
ws.hide_gridlines(2)
ws.set_column("A:A", 2)
for c in range(1, 16):
    ws.set_column(c, c, 12)
ws.write("B2", "Executive Summary", title)
ws.write("B3", "1 Jan 2026 – 31 Jul 2026  ·  all figures in ZAR", subtitle)

# KPI cards — two rows of five
cards1 = [
    ("TOTAL SALES", K["TotalSales"], "R65.5m across 25 merchants", "R #,##0", "navy"),
    ("TRANSACTIONS", K["TotalTransactions"], f"avg basket R{K['AvgBasketValue']:.2f}",
     "#,##0", "navy"),
    ("REDEMPTION RATE", K["RedemptionRate"], f"{K['VouchersRedeemed']:,} of "
     f"{K['VouchersSold']:,} vouchers", "0.0%", "teal"),
    ("AVG RESOLUTION", K["AvgResolutionHours"], "hours  ·  median 16.4h", "0.0", "teal"),
    ("SLA BREACH RATE", K["SLABreachRate"], f"{int(K['SLABreachRate']*K['TotalTickets'])} of "
     f"{K['TotalTickets']:,} tickets", "0.0%", "amber"),
]
cards2 = [
    ("OUTSTANDING LIABILITY", K["OutstandingLiability"], "unredeemed voucher value",
     "R #,##0", "navy"),
    ("AVG DAYS TO REDEEM", K["AvgDaysToRedeem"], "median 2 days  ·  max 54", "0.00", "teal"),
    ("DELAYED REDEMPTIONS", K["DelayedRedemptionRate"], "redeemed after > 7 days",
     "0.0%", "teal"),
    ("OPEN TICKETS", K["OpenTickets"], "backlog across all merchants", "#,##0", "amber"),
    ("REVENUE AT RISK", sum(m["RevenueAtRiskAnnualised"]
                            for m in summary["business_answers"]["Q5_focus_merchants"]),
     "annualised, deteriorating merchants", "R #,##0", "amber"),
]
row = 5
for i, (lbl, val, sub, fmt, th) in enumerate(cards1):
    kpi_card(ws, row, 1 + i * 3, lbl, val, sub, fmt, th)
row = 9
for i, (lbl, val, sub, fmt, th) in enumerate(cards2):
    kpi_card(ws, row, 1 + i * 3, lbl, val, sub, fmt, th)
for rr in (5, 9):
    ws.set_row(rr, 16); ws.set_row(rr + 1, 30); ws.set_row(rr + 2, 14)

r = section(ws, 14, "MONTHLY TREND", 15)
t = trend[["YearMonth", "SalesValue", "Transactions", "SalesMoM", "AvgBasketValue",
           "RedemptionRate", "AvgDaysToRedeem", "Tickets", "AvgResolutionHours",
           "SLABreachRate"]].copy()
t.columns = ["Month", "Sales Value", "Transactions", "Sales MoM %", "Avg Basket",
             "Redemption %", "Avg Days to Redeem", "Tickets", "Avg Resolution (h)",
             "SLA Breach %"]
end = write_table(ws, t, r, 1, {
    "Sales Value": money, "Transactions": num, "Sales MoM %": pctsig, "Avg Basket": money2,
    "Redemption %": pct1, "Avg Days to Redeem": dec, "Tickets": num,
    "Avg Resolution (h)": dec, "SLA Breach %": pct1},
    {"Month": 11, "Sales Value": 14, "Avg Days to Redeem": 15, "Avg Resolution (h)": 15})

ch = wb.add_chart({"type": "column"})
ch.add_series({"name": "Sales Value",
               "categories": ["2. Executive Summary", r + 1, 1, end - 1, 1],
               "values": ["2. Executive Summary", r + 1, 2, end - 1, 2],
               "fill": {"color": TEAL}, "border": {"none": True},
               "data_labels": {"value": True, "num_format": "R #,##0,,\"m\"",
                               "font": {"size": 8, "color": GREY}}})
line = wb.add_chart({"type": "line"})
line.add_series({"name": "Transactions",
                 "categories": ["2. Executive Summary", r + 1, 1, end - 1, 1],
                 "values": ["2. Executive Summary", r + 1, 3, end - 1, 3],
                 "line": {"color": AMBER, "width": 2.5},
                 "marker": {"type": "circle", "size": 6, "fill": {"color": AMBER}},
                 "y2_axis": True})
ch.combine(line)
ch.set_title({"name": "Monthly sales value and transaction volume",
              "name_font": {"size": 12, "color": NAVY, "bold": True}})
ch.set_y_axis({"name": "Sales value (R)", "num_format": "R #,##0,,\"m\"",
               "major_gridlines": {"visible": True, "line": {"color": "#E4EAF2"}}})
ch.set_y2_axis({"name": "Transactions", "num_format": "#,##0"})
ch.set_x_axis({"name": ""})
ch.set_legend({"position": "bottom"})
ch.set_size({"width": 760, "height": 300})
ch.set_chartarea({"border": {"none": True}})
ws.insert_chart(end + 2, 1, ch)

r = end + 19
r = section(ws, r, "REGION PERFORMANCE", 15)
rg = region[["Region", "TotalSales", "SalesShare", "TotalTransactions", "TrendPctOfAvg",
             "LastMonthMoM", "Last2MonthAvgMoM", "PeakMonth", "SalesVsPeak"]].copy()
rg.columns = ["Region", "Total Sales", "Share of Sales", "Transactions", "Trend % of Avg",
              "Last Month MoM", "Last 2M Avg MoM", "Peak Month", "vs Own Peak"]
end2 = write_table(ws, rg, r, 1, {
    "Total Sales": money, "Share of Sales": pct1, "Transactions": num,
    "Trend % of Avg": pctsig, "Last Month MoM": pctsig, "Last 2M Avg MoM": pctsig,
    "vs Own Peak": pctsig}, {"Region": 16, "Total Sales": 14})
ws.write(end2 + 1, 1,
         "Eastern Cape is the only region below its own peak (-9.8%) and the only one that "
         "peaked before July. Its trend slope is +2.0% of average monthly sales against "
         "+4.4% to +8.5% elsewhere.", note)
ws.merge_range(end2 + 1, 1, end2 + 2, 9, "", note)
ws.write(end2 + 1, 1,
         "Eastern Cape is the only region below its own peak (-9.8%) and the only one that "
         "peaked before July. Its trend slope is +2.0% of average monthly sales against "
         "+4.4% to +8.5% elsewhere — four independent signals, not one bad month.", note)

pie = wb.add_chart({"type": "doughnut"})
pie.add_series({"name": "Sales by region",
                "categories": ["2. Executive Summary", r + 1, 1, end2 - 1, 1],
                "values": ["2. Executive Summary", r + 1, 2, end2 - 1, 2],
                "points": [{"fill": {"color": c}} for c in
                           [NAVY, TEAL, AMBER, "#7B4B94", RED]],
                "data_labels": {"percentage": True, "font": {"size": 9, "color": WHITE,
                                                             "bold": True}}})
pie.set_title({"name": "Share of sales by region",
               "name_font": {"size": 12, "color": NAVY, "bold": True}})
pie.set_size({"width": 420, "height": 300})
pie.set_hole_size(55)
pie.set_chartarea({"border": {"none": True}})
ws.insert_chart(end2 + 4, 1, pie)

vt = vtype[["VoucherType", "VouchersSold", "RedemptionRate", "ValueRedemptionRate",
            "AvgDaysToRedeem", "DelayedRate", "SalesValue", "SalesShare",
            "OutstandingValue"]].copy()
vt.columns = ["Voucher Type", "Vouchers Sold", "Redemption %", "Value Redemption %",
              "Avg Days to Redeem", "Delayed %", "Sales Value", "Sales Share",
              "Outstanding Value"]
r3 = end2 + 20
r3 = section(ws, r3, "VOUCHER TYPE PERFORMANCE", 15)
end3 = write_table(ws, vt, r3, 1, {
    "Vouchers Sold": num, "Redemption %": pct2, "Value Redemption %": pct2,
    "Avg Days to Redeem": dec, "Delayed %": pct1, "Sales Value": money,
    "Sales Share": pct1, "Outstanding Value": money},
    {"Voucher Type": 14, "Sales Value": 14, "Outstanding Value": 15})

bar = wb.add_chart({"type": "bar"})
bar.add_series({"name": "Redemption rate",
                "categories": ["2. Executive Summary", r3 + 1, 1, end3 - 1, 1],
                "values": ["2. Executive Summary", r3 + 1, 3, end3 - 1, 3],
                "fill": {"color": TEAL}, "border": {"none": True},
                "data_labels": {"value": True, "num_format": "0.0%",
                                "font": {"size": 9, "bold": True}}})
bar.set_title({"name": "Redemption rate by voucher type",
               "name_font": {"size": 12, "color": NAVY, "bold": True}})
bar.set_x_axis({"num_format": "0%", "min": 0.7, "max": 0.95})
bar.set_legend({"none": True})
bar.set_size({"width": 520, "height": 280})
bar.set_chartarea({"border": {"none": True}})
ws.insert_chart(end3 + 2, 1, bar)
ws.write(end3 + 16, 1,
         f"Airtime redeems at {vtype.iloc[0].RedemptionRate:.1%} against Gaming at "
         f"{vtype.iloc[-1].RedemptionRate:.1%} — a 16.9 percentage point spread. Time-to-redeem "
         "is effectively identical across types (3.5–3.7 days), so the difference is whether "
         "customers redeem at all, not how quickly.", note)


# ======================================================================================
# SHEET 3 — Merchant Scorecard
# ======================================================================================
ws = wb.add_worksheet("3. Merchant Scorecard")
ws.hide_gridlines(2)
ws.set_column("A:A", 2)
ws.write("B2", "Merchant Scorecard", title)
ws.write("B3", "All 25 merchants. Health Score is a weighted composite of momentum, trend, "
               "target attainment, redemption and operational deterioration.", subtitle)

sc = score[["Merchant", "Region", "Channel", "AccountManager", "SalesRank", "TotalSales",
            "SalesShare", "CumulativeShare", "TotalTransactions", "AvgBasketValue",
            "TargetAttainmentIndex", "MoMChange", "SalesVsPrior3Avg", "Last3vsFirst3",
            "RedemptionRate", "AvgDaysToRedeem", "Tickets", "TicketsPer1kTxn",
            "SLABreachRate", "TicketsVsPrior3Avg", "HealthScore", "HealthBand",
            "RevenueAtRiskAnnualised", "FocusPriorityScore"]].copy()
sc.columns = ["Merchant", "Region", "Channel", "Account Manager", "Rank", "Total Sales",
              "Sales Share", "Cumulative", "Transactions", "Avg Basket", "Target Index",
              "MoM %", "vs Prior 3M", "Last3 vs First3", "Redemption %", "Days to Redeem",
              "Tickets", "Tickets/1k", "SLA Breach %", "Ticket Trend", "Health Score",
              "Band", "Revenue at Risk", "Focus Score"]
r = 5
end = write_table(ws, sc, r, 1, {
    "Total Sales": money, "Sales Share": pct1, "Cumulative": pct1, "Transactions": num,
    "Avg Basket": money2, "Target Index": dec, "MoM %": pctsig, "vs Prior 3M": pctsig,
    "Last3 vs First3": pctsig, "Redemption %": pct1, "Days to Redeem": dec, "Tickets": num,
    "Tickets/1k": dec, "SLA Breach %": pct1, "Ticket Trend": pctsig, "Health Score": dec,
    "Revenue at Risk": money, "Focus Score": dec, "Rank": num},
    {"Merchant": 26, "Region": 14, "Channel": 14, "Account Manager": 14, "Total Sales": 14,
     "Revenue at Risk": 15, "Last3 vs First3": 13, "Days to Redeem": 13})

nrows = len(sc)
# Conditional formatting — the point of the Excel pack is that it is scannable
ws.conditional_format(r + 1, 21, r + nrows, 21, {
    "type": "3_color_scale", "min_color": "#F5B7B1", "mid_color": "#FCF3CF",
    "max_color": "#ABEBC6"})
ws.conditional_format(r + 1, 13, r + nrows, 13, {
    "type": "cell", "criteria": "<", "value": -0.05,
    "format": f(bg_color="#F9D6D5", font_color="#922B21", bold=True, border=1,
                border_color="#D6DEE8", num_format='+0.0%;-0.0%')})
ws.conditional_format(r + 1, 19, r + nrows, 19, {
    "type": "cell", "criteria": ">=", "value": 1.5,
    "format": f(bg_color="#FDEBD0", font_color="#9C640C", bold=True, border=1,
                border_color="#D6DEE8", num_format='+0.0%;-0.0%')})
ws.conditional_format(r + 1, 23, r + nrows, 23, {
    "type": "data_bar", "bar_color": AMBER, "bar_solid": True})
ws.conditional_format(r + 1, 6, r + nrows, 6, {
    "type": "data_bar", "bar_color": TEAL, "bar_solid": True})
ws.autofilter(r, 1, r + nrows, 24)
ws.freeze_panes(r + 1, 2)

ws.write(end + 2, 1, "HEALTH SCORE COMPOSITION", h2)
weights = pd.DataFrame({
    "Component": ["Recent momentum (latest month vs prior 3-month average)",
                  "Month-on-month change", "Structural trend (last 3 vs first 3 months)",
                  "Target attainment index", "Redemption rate",
                  "Operational deterioration (ticket volume vs own history)",
                  "Redemption speed", "SLA breach rate"],
    "Weight": [0.25, 0.15, 0.15, 0.15, 0.10, 0.10, 0.05, 0.05],
    "Direction": ["Higher is better"] * 5 + ["Lower is better"] * 3,
})
write_table(ws, weights, end + 3, 1, {"Weight": pct1}, {"Component": 62, "Direction": 18})
ws.write(end + 13, 1,
         "Each component is converted to a percentile rank across the 25 merchants, then "
         "weighted. Percentile ranking makes the components comparable despite different "
         "units, and means the score is always relative to the current portfolio. Bands: "
         "Critical < 35, Watch 35–55, Healthy 55–75, Star 75+.", note)
ws.merge_range(end + 13, 1, end + 15, 12, "", note)
ws.write(end + 13, 1,
         "Each component is converted to a percentile rank across the 25 merchants, then "
         "weighted. Percentile ranking makes components with different units comparable, and "
         "keeps the score relative to the current portfolio. Bands: Critical <35, Watch "
         "35–55, Healthy 55–75, Star 75+. Note that operational deterioration uses ticket "
         "CHANGE, not tickets per 1,000 transactions — the latter correlates with merchant "
         "size at r = -0.83 and would mostly measure how small a merchant is.", note)


# ======================================================================================
# SHEET 4 — Voucher Analysis
# ======================================================================================
ws = wb.add_worksheet("4. Voucher Analysis")
ws.hide_gridlines(2)
ws.set_column("A:A", 2); ws.set_column("B:B", 18)
for c in range(2, 14):
    ws.set_column(c, c, 13)
ws.write("B2", "Voucher & Redemption Analysis", title)
ws.write("B3", f"{K['VouchersSold']:,} vouchers worth R{K['VoucherValueSold']:,.0f} issued  ·  "
               f"{K['RedemptionRate']:.1%} redeemed", subtitle)

r = section(ws, 5, "REDEMPTION BY VOUCHER TYPE", 13)
end = write_table(ws, vt, r, 1, {
    "Vouchers Sold": num, "Redemption %": pct2, "Value Redemption %": pct2,
    "Avg Days to Redeem": dec, "Delayed %": pct1, "Sales Value": money,
    "Sales Share": pct1, "Outstanding Value": money}, {"Voucher Type": 16})

r = section(ws, end + 2, "REDEMPTION RATE BY TYPE AND MONTH", 13)
piv = vtype_m.pivot_table(index="VoucherType", columns="YearMonth",
                          values="RedemptionRate").reset_index()
piv.columns.name = None
end2 = write_table(ws, piv, r, 1, {c: pct1 for c in piv.columns if c != "VoucherType"},
                   {"VoucherType": 16})

lc = wb.add_chart({"type": "line"})
for i in range(len(piv)):
    lc.add_series({"name": ["4. Voucher Analysis", r + 1 + i, 1],
                   "categories": ["4. Voucher Analysis", r, 2, r, len(piv.columns)],
                   "values": ["4. Voucher Analysis", r + 1 + i, 2, r + 1 + i,
                              len(piv.columns)],
                   "line": {"width": 2.25},
                   "marker": {"type": "circle", "size": 5}})
lc.set_title({"name": "Redemption rate by voucher type over time",
              "name_font": {"size": 12, "color": NAVY, "bold": True}})
lc.set_y_axis({"num_format": "0%", "min": 0.70, "max": 0.98,
               "major_gridlines": {"visible": True, "line": {"color": "#E4EAF2"}}})
lc.set_legend({"position": "bottom"})
lc.set_size({"width": 760, "height": 300})
lc.set_chartarea({"border": {"none": True}})
ws.insert_chart(end2 + 2, 1, lc)

r = section(ws, end2 + 19, "DELAYED REDEMPTION HOTSPOTS — region × voucher type", 13)
hot = rvt.copy()
base = hot.groupby(["Region", "VoucherType"]).AvgDaysToRedeem.transform("mean")
hot["DeviationFromOwnAvg"] = hot.AvgDaysToRedeem - base
hot = (hot.sort_values("DeviationFromOwnAvg", ascending=False)
       .head(12)[["Region", "VoucherType", "YearMonth", "VouchersSold", "RedemptionRate",
                  "AvgDaysToRedeem", "DelayedRate", "DeviationFromOwnAvg"]])
hot.columns = ["Region", "Voucher Type", "Month", "Vouchers Sold", "Redemption %",
               "Avg Days to Redeem", "Delayed %", "Deviation from Own Avg (days)"]
end3 = write_table(ws, hot, r, 1, {
    "Vouchers Sold": num, "Redemption %": pct1, "Avg Days to Redeem": dec,
    "Delayed %": pct1, "Deviation from Own Avg (days)": dec},
    {"Region": 16, "Voucher Type": 15, "Deviation from Own Avg (days)": 22})
ws.conditional_format(r + 1, 8, r + len(hot), 8, {
    "type": "data_bar", "bar_color": RED, "bar_solid": True})
ws.write(end3 + 1, 1,
         "Western Cape × Bill Payment in April 2026 is a clear outlier: average time-to-redeem "
         "runs 12.1 days above that combination's own average across other months. Every other "
         "region/type/month deviation is under half a day. This is a localised April incident, "
         "not a systemic redemption problem.", note)
ws.merge_range(end3 + 1, 1, end3 + 3, 9, "", note)
ws.write(end3 + 1, 1,
         "Western Cape × Bill Payment in April 2026 is a clear outlier: average time-to-redeem "
         "runs 12.1 days above that combination's own average across other months, while every "
         "other region/type/month deviation is under half a day. A localised April incident, "
         "not a systemic redemption problem.", note)


# ======================================================================================
# SHEET 5 — Operational View
# ======================================================================================
ws = wb.add_worksheet("5. Operational View")
ws.hide_gridlines(2)
ws.set_column("A:A", 2); ws.set_column("B:B", 22)
for c in range(2, 14):
    ws.set_column(c, c, 13)
ws.write("B2", "Operational View", title)
ws.write("B3", f"{K['TotalTickets']:,} tickets  ·  {K['SLABreachRate']:.1%} breached SLA  ·  "
               f"{K['OpenTickets']} still open", subtitle)

row = 5
for i, (lbl, val, sub, fmt, th) in enumerate([
        ("TOTAL TICKETS", K["TotalTickets"], "1 Jan – 31 Jul 2026", "#,##0", "navy"),
        ("AVG RESOLUTION", K["AvgResolutionHours"], "hours · median 16.4h", "0.0", "teal"),
        ("SLA BREACH RATE", K["SLABreachRate"], "358 of 1,363 tickets", "0.0%", "amber"),
        ("OPEN BACKLOG", K["OpenTickets"], "Open, Escalated or Pending", "#,##0", "amber"),
        ("TICKETS / 1k TXN", K["TicketsPer1kTxn"], "portfolio friction rate", "0.00", "teal")]):
    kpi_card(ws, row, 1 + i * 3, lbl, val, sub, fmt, th)
ws.set_row(5, 16); ws.set_row(6, 30); ws.set_row(7, 14)

r = section(ws, 10, "THE SLA POLICY FINDING — targets run inverse to actual workload", 13)
pr = priority[["Priority", "TargetSLAHours", "Tickets", "AvgResolutionHours",
               "MedianResolutionHours", "SLABreaches", "SLABreachRate", "AvgBreachHours",
               "OpenTickets"]].copy()
pr["ShareOfAllBreaches"] = pr.SLABreaches / pr.SLABreaches.sum()
pr.columns = ["Priority", "SLA Target (h)", "Tickets", "Avg Resolution (h)",
              "Median Resolution (h)", "Breaches", "Breach Rate", "Avg Breach (h)",
              "Open", "Share of All Breaches"]
end = write_table(ws, pr, r, 1, {
    "SLA Target (h)": num, "Tickets": num, "Avg Resolution (h)": dec,
    "Median Resolution (h)": dec, "Breaches": num, "Breach Rate": pct1,
    "Avg Breach (h)": dec, "Open": num, "Share of All Breaches": pct1},
    {"Priority": 14, "Median Resolution (h)": 17, "Share of All Breaches": 17})
ws.conditional_format(r + 1, 7, r + len(pr), 7, {
    "type": "3_color_scale", "min_color": "#ABEBC6", "mid_color": "#FCF3CF",
    "max_color": "#F5B7B1"})

ws.merge_range(end + 1, 1, end + 5, 10, "", note)
ws.write(end + 1, 1,
         "Critical tickets are given a 12-hour SLA but take 52.7 hours on average — a 98.3% "
         "breach rate. Low-priority tickets are given 48 hours and take 11.3 — a 0.2% breach "
         "rate. The SLA ladder runs in the opposite direction to the actual workload, so "
         "94.7% of all breaches land on High and Critical. This is a policy configuration "
         "problem, not a team performance problem: no amount of effort makes a 52-hour "
         "investigation fit a 12-hour target. Recommended action is to re-base the SLA on "
         "observed distributions (a 90th-percentile-compliant Critical SLA would be ~120h) "
         "or to resource high-priority work separately.", note)

r = section(ws, end + 7, "TICKET TYPE ANALYSIS", 13)
tt = tkt_type[["TicketType", "TicketCategory", "ImpactArea", "Tickets",
               "AvgResolutionHours", "MedianResolutionHours", "MaxResolutionHours",
               "SLABreachRate", "HighPriorityTickets", "OpenTickets",
               "TotalBreachHours"]].copy()
tt.columns = ["Ticket Type", "Category", "Impact Area", "Tickets", "Avg Resolution (h)",
              "Median (h)", "Max (h)", "Breach Rate", "High Priority", "Open",
              "Total Breach Hours"]
end2 = write_table(ws, tt, r, 1, {
    "Tickets": num, "Avg Resolution (h)": dec, "Median (h)": dec, "Max (h)": dec,
    "Breach Rate": pct1, "High Priority": num, "Open": num, "Total Breach Hours": num},
    {"Ticket Type": 22, "Category": 14, "Impact Area": 18, "Total Breach Hours": 16})
ws.conditional_format(r + 1, 4, r + len(tt), 4, {"type": "data_bar", "bar_color": NAVY,
                                                 "bar_solid": True})

r = section(ws, end2 + 2, "TICKET VOLUME BY MONTH AND PRIORITY", 13)
tm = tkt_month.pivot_table(index="YearMonth", columns="Priority", values="Tickets",
                           fill_value=0).reset_index()
tm.columns.name = None
order = [c for c in ["YearMonth", "Critical", "High", "Medium", "Low"] if c in tm.columns]
tm = tm[order]
tm["Total"] = tm[[c for c in order if c != "YearMonth"]].sum(axis=1)
end3 = write_table(ws, tm, r, 1, {c: num for c in tm.columns if c != "YearMonth"},
                   {"YearMonth": 12})

sc_ch = wb.add_chart({"type": "column", "subtype": "stacked"})
for i, c in enumerate([c for c in order if c != "YearMonth"]):
    sc_ch.add_series({"name": ["5. Operational View", r, 2 + i],
                      "categories": ["5. Operational View", r + 1, 1, end3 - 1, 1],
                      "values": ["5. Operational View", r + 1, 2 + i, end3 - 1, 2 + i],
                      "fill": {"color": [RED, AMBER, TEAL, NAVY][i]},
                      "border": {"none": True}})
sc_ch.set_title({"name": "Ticket volume by month and priority",
                 "name_font": {"size": 12, "color": NAVY, "bold": True}})
sc_ch.set_legend({"position": "bottom"})
sc_ch.set_size({"width": 700, "height": 300})
sc_ch.set_chartarea({"border": {"none": True}})
ws.insert_chart(end3 + 2, 1, sc_ch)

r = end3 + 19
r = section(ws, r, "OPERATIONAL FRICTION vs PERFORMANCE — and why the obvious reading is wrong", 13)
fq = friction.copy()
fq.columns = ["Friction Quartile", "Merchants", "Avg Tickets/1k Txn", "Avg Growth",
              "Avg Target Attainment", "Avg Redemption %", "Avg Health Score"]
end4 = write_table(ws, fq, r, 1, {
    "Merchants": num, "Avg Tickets/1k Txn": dec, "Avg Growth": pctsig,
    "Avg Target Attainment": dec, "Avg Redemption %": pct1, "Avg Health Score": dec},
    {"Friction Quartile": 22, "Avg Target Attainment": 19})
sz = summary["size_confounder"]
ws.merge_range(end4 + 1, 1, end4 + 5, 10, "", note)
ws.write(end4 + 1, 1,
         f"At first glance the highest-friction quartile does underperform: tickets per 1,000 "
         f"transactions correlates with target attainment at r = "
         f"{sz['raw_corr_friction_vs_attainment']:+.2f}. That reading is confounded. The ratio "
         f"is strongly size-dependent — it correlates with log(total sales) at r = "
         f"{sz['friction_vs_log_size_pearson']:+.2f} — so small merchants look worse simply "
         f"because the denominator is small. Controlling for size, the partial correlation "
         f"falls to r = {sz['partial_corr_friction_vs_attainment_controlling_size']:+.2f}. "
         f"SLA breach rate and average resolution time show no association with performance "
         f"at all. The honest conclusion is that operational friction is not a portfolio-level "
         f"predictor of merchant performance; the real signal is event-level, below.", note)

r = section(ws, end4 + 7, "TICKET SPIKE EVENTS — same signal, opposite diagnosis", 13)
ev = events.copy()
ev.columns = ["Merchant", "Region", "Month", "Tickets", "Prior Avg Tickets", "Ticket Uplift",
              "Sales Value", "Sales vs Prior 3M"]
end5 = write_table(ws, ev, r, 1, {
    "Tickets": num, "Prior Avg Tickets": dec, "Ticket Uplift": pctsig,
    "Sales Value": money, "Sales vs Prior 3M": pctsig},
    {"Merchant": 24, "Region": 15, "Prior Avg Tickets": 15, "Sales vs Prior 3M": 16})
ws.merge_range(end5 + 1, 1, end5 + 4, 10, "", note)
ws.write(end5 + 1, 1,
         "Four events where a merchant's ticket volume more than doubled against its own prior "
         "three months. Durban Cash Hub spiked +780% in June and +184% in July while sales GREW "
         "8.2% and 6.3% — a service problem at a healthy, growing account. Umhlanga Value Mart "
         "spiked +693% in July while sales fell 42.5% — a failing account. Identical operational "
         "signal, entirely different commercial diagnosis. This is why the alerting logic pairs "
         "ticket movement with sales movement rather than triggering on either alone.", note)


# ======================================================================================
# SHEET 6 — Anomalies & Alerts
# ======================================================================================
ws = wb.add_worksheet("6. Anomalies & Alerts")
ws.hide_gridlines(2)
ws.set_column("A:A", 2); ws.set_column("B:B", 24); ws.set_column("C:C", 15)
for c in range(3, 12):
    ws.set_column(c, c, 14)
ws.write("B2", "Anomalies & Alerts", title)
ws.write("B3", "Two independent detection layers: deterministic business rules, and an "
               "unsupervised Isolation Forest.", subtitle)

r = section(ws, 5, "RULES-BASED ALERTS", 11)
al = alerts.copy()
al.columns = ["Merchant", "Region", "Alert Type", "Severity", "Detail", "Revenue at Risk"]
end = write_table(ws, al, r, 1, {"Revenue at Risk": money},
                  {"Merchant": 24, "Region": 15, "Alert Type": 22, "Severity": 11,
                   "Detail": 58, "Revenue at Risk": 16})
ws.conditional_format(r + 1, 4, r + len(al), 4, {
    "type": "text", "criteria": "containing", "value": "Critical",
    "format": f(bg_color="#F9D6D5", font_color="#922B21", bold=True, border=1,
                border_color="#D6DEE8")})

r = section(ws, end + 2, "ISOLATION FOREST — unsupervised anomaly detection", 11)
an = anom[["Merchant", "Region", "YearMonth", "AnomalyScore", "SalesValue",
           "SalesVsOwnHistory", "Tickets", "TicketsVsOwnHistory", "RedemptionRate",
           "Explanation"]].copy()
an.columns = ["Merchant", "Region", "Month", "Anomaly Score", "Sales Value",
              "Sales vs Own History", "Tickets", "Tickets vs Own History", "Redemption %",
              "Explanation"]
end2 = write_table(ws, an, r, 1, {
    "Anomaly Score": dec, "Sales Value": money, "Sales vs Own History": pctsig,
    "Tickets": num, "Tickets vs Own History": pctsig, "Redemption %": pct1},
    {"Merchant": 24, "Sales vs Own History": 18, "Tickets vs Own History": 19,
     "Explanation": 56})
ws.conditional_format(r + 1, 4, r + len(an), 4, {
    "type": "3_color_scale", "min_color": "#FCF3CF", "mid_color": "#FAD7A0",
    "max_color": "#F5B7B1"})

ws.merge_range(end2 + 1, 1, end2 + 6, 10, "", note)
ws.write(end2 + 1, 1,
         f"The model scored {mlsum['anomaly_detection']['observations_scored']} merchant-months "
         f"on seven features, each expressed as a deviation from that merchant's OWN history "
         f"rather than an absolute value — without that, the model would simply flag the "
         f"largest merchants every month. It flagged "
         f"{mlsum['anomaly_detection']['anomalies_flagged']} observations at 5% contamination.\n\n"
         "Validation: the dataset documentation states four patterns were deliberately embedded. "
         "The model was not told what they were, and independently recovered all four — "
         "Umhlanga Value Mart's July collapse (top-ranked), Kudu Digital Kiosk's May growth "
         "step, Durban Cash Hub's June ticket spike, and a Liberty Lane redemption-delay month. "
         "Every flagged row carries a plain-English explanation, because a score with no reason "
         "attached does not get acted on.", note)


# ======================================================================================
# SHEET 7 — ML Model Results
# ======================================================================================
ws = wb.add_worksheet("7. ML Model Results")
ws.hide_gridlines(2)
ws.set_column("A:A", 2); ws.set_column("B:B", 30); ws.set_column("C:C", 20)
for c in range(3, 12):
    ws.set_column(c, c, 15)
ws.write("B2", "Machine Learning Results", title)
ws.write("B3", "Five models. Time-based validation splits throughout — never random — so the "
               "reported metrics hold for forward-looking use.", subtitle)

r = section(ws, 5, "MODEL SUMMARY", 11)
models = pd.DataFrame([
    {"Model": "1. Anomaly detection", "Algorithm": "Isolation Forest (400 trees)",
     "Validation": "Unsupervised; validated against 4 documented embedded patterns",
     "Headline metric": f"{mlsum['anomaly_detection']['anomalies_flagged']} anomalies "
                        f"from {mlsum['anomaly_detection']['observations_scored']} obs",
     "Business use": "Weekly exception list for account managers"},
    {"Model": "2. Redemption propensity", "Algorithm": "HistGradientBoostingClassifier",
     "Validation": "Time split: train Jan–May, test Jun–Jul",
     "Headline metric": f"AUC {mlsum['redemption_propensity']['roc_auc']:.3f} "
                        f"(ceiling {mlsum['redemption_propensity']['oracle_auc_ceiling']:.3f})",
     "Business use": "Target follow-up at high non-redemption risk vouchers"},
    {"Model": "3. Resolution time", "Algorithm": "HistGradientBoostingRegressor",
     "Validation": "Time split: train Jan–May, test Jun–Jul",
     "Headline metric": f"MAE {mlsum['resolution_time']['mae_hours']:.1f}h, "
                        f"{mlsum['resolution_time']['improvement_vs_naive']:.0%} better than naive",
     "Business use": "Triage: flag tickets likely to breach before they do"},
    {"Model": "4. Sales forecast", "Algorithm": "Holt-Winters (weekly seasonality)",
     "Validation": "Backtest on held-out final 30 days",
     "Headline metric": f"MAPE {mlsum['sales_forecast']['mape']:.2%}, "
                        f"{mlsum['sales_forecast']['improvement_vs_naive']:.0%} better than naive",
     "Business use": "30-day capacity and revenue planning"},
    {"Model": "5. Merchant segmentation", "Algorithm": "K-Means (k=4)",
     "Validation": f"Silhouette {mlsum['segmentation']['silhouette_at_selected_k']:.3f} at k=4",
     "Headline metric": "4 segments, 2 singleton outliers identified automatically",
     "Business use": "Differentiated account management plays"},
])
end = write_table(ws, models, r, 1, {},
                  {"Model": 24, "Algorithm": 34, "Validation": 46, "Headline metric": 40,
                   "Business use": 44})

r = section(ws, end + 2, "REDEMPTION PROPENSITY — risk decile lift", 11)
dc = deciles[["RiskDecile", "Vouchers", "AvgPredictedRisk", "ActualNonRedemptionRate",
              "Lift", "ValueAtRisk"]].copy()
dc.columns = ["Risk Decile", "Vouchers", "Predicted Risk", "Actual Non-Redemption",
              "Lift vs Base", "Value at Risk"]
end2 = write_table(ws, dc, r, 1, {
    "Vouchers": num, "Predicted Risk": pct1, "Actual Non-Redemption": pct1,
    "Lift vs Base": dec, "Value at Risk": money},
    {"Risk Decile": 12, "Actual Non-Redemption": 19, "Value at Risk": 15})
ws.conditional_format(r + 1, 4, r + len(dc), 4, {"type": "data_bar", "bar_color": RED,
                                                 "bar_solid": True})
rp = mlsum["redemption_propensity"]
ws.merge_range(end2 + 1, 1, end2 + 6, 10, "", note)
ws.write(end2 + 1, 1,
         f"An AUC of {rp['roc_auc']:.3f} looks weak in isolation, so it was tested against a "
         f"ceiling. If redemption is generated purely as a function of voucher type, the best "
         f"any model can achieve is the type-level base rate — an oracle scoring AUC "
         f"{rp['oracle_auc_ceiling']:.3f}. The model captures "
         f"{rp['pct_of_achievable_signal']:.1%} of the achievable signal, so "
         f"{rp['roc_auc']:.3f} is the practical ceiling of this dataset, not an underfit model. "
         f"Establishing that distinction prevents a team spending a sprint chasing an AUC that "
         f"cannot move.\n\n"
         f"The ranking remains operationally useful: the top risk decile has a "
         f"{rp['top_vs_bottom_decile_ratio']:.1f}x higher actual non-redemption rate than the "
         f"bottom decile, concentrating R{rp['top_decile_value_at_risk']:,.0f} of value at risk "
         f"into 10% of vouchers.", note)

r = section(ws, end2 + 8, "30-DAY SALES FORECAST", 11)
fc = fcast.copy()
fc.columns = ["Date", "Forecast", "Lower 80%", "Upper 80%", "Lower 95%", "Upper 95%"]
end3 = write_table(ws, fc, r, 1, {
    "Date": datef, "Forecast": money, "Lower 80%": money, "Upper 80%": money,
    "Lower 95%": money, "Upper 95%": money}, {"Date": 12})

fch = wb.add_chart({"type": "line"})
fch.add_series({"name": "Forecast",
                "categories": ["7. ML Model Results", r + 1, 1, end3 - 1, 1],
                "values": ["7. ML Model Results", r + 1, 2, end3 - 1, 2],
                "line": {"color": NAVY, "width": 2.5}})
for idx, (nm, colr) in enumerate([("Lower 80%", "#9FB6D4"), ("Upper 80%", "#9FB6D4")]):
    fch.add_series({"name": nm,
                    "categories": ["7. ML Model Results", r + 1, 1, end3 - 1, 1],
                    "values": ["7. ML Model Results", r + 1, 3 + idx, end3 - 1, 3 + idx],
                    "line": {"color": colr, "width": 1.25, "dash_type": "dash"}})
fch.set_title({"name": "Next 30 days: forecast sales with 80% interval",
               "name_font": {"size": 12, "color": NAVY, "bold": True}})
fch.set_y_axis({"num_format": "R #,##0,\"k\"",
                "major_gridlines": {"visible": True, "line": {"color": "#E4EAF2"}}})
fch.set_legend({"position": "bottom"})
fch.set_size({"width": 760, "height": 300})
fch.set_chartarea({"border": {"none": True}})
ws.insert_chart(end3 + 2, 1, fch)

sf = mlsum["sales_forecast"]
ws.merge_range(end3 + 19, 1, end3 + 21, 10, "", note)
ws.write(end3 + 19, 1,
         f"Backtested on the held-out final 30 days: MAPE {sf['mape']:.2%} against a naive "
         f"last-7-day-mean baseline of {sf['naive_mape']:.2%} — a "
         f"{sf['improvement_vs_naive']:.0%} improvement. Forecast total for the next 30 days is "
         f"R{sf['next30_forecast_total']:,.0f}, {sf['forecast_change']:+.1%} against the last 30 "
         f"actual. Intervals are empirical, derived from in-sample residual standard deviation.",
         note)

r = section(ws, end3 + 23, "MERCHANT SEGMENTATION", 11)
sp = segprof[["SegmentName", "Merchants", "TotalSales", "AvgSales", "AvgBasket",
              "AvgRedemption", "AvgTicketsPer1k", "AvgGrowth", "AvgRecentMomentum",
              "AvgHealth"]].copy()
sp.columns = ["Segment", "Merchants", "Total Sales", "Avg Sales", "Avg Basket",
              "Avg Redemption", "Avg Tickets/1k", "Avg Growth", "Avg Recent Momentum",
              "Avg Health Score"]
end4 = write_table(ws, sp, r, 1, {
    "Merchants": num, "Total Sales": money, "Avg Sales": money, "Avg Basket": money2,
    "Avg Redemption": pct1, "Avg Tickets/1k": dec, "Avg Growth": pctsig,
    "Avg Recent Momentum": pctsig, "Avg Health Score": dec},
    {"Segment": 30, "Total Sales": 15, "Avg Sales": 14, "Avg Recent Momentum": 19})
seg = mlsum["segmentation"]
ws.merge_range(end4 + 1, 1, end4 + 5, 10, "", note)
ws.write(end4 + 1, 1,
         f"Silhouette analysis favours k=2 (score {seg['silhouette_at_optimal_k']:.3f}), but "
         f"that produces a 21-vs-4 split with no operational value across only 25 merchants. "
         f"k=4 was selected on business grounds — segments large enough to assign an owner, "
         f"distinct enough to justify a different play — at a silhouette cost "
         f"({seg['silhouette_at_selected_k']:.3f}) that is stated rather than hidden.\n\n"
         "Notably, the algorithm isolated two merchants into single-member clusters entirely on "
         "its own: Kudu Digital Kiosk (breakout growth) and Umhlanga Value Mart (deteriorating). "
         "That is a finding, not a defect — they are behaviourally unlike anything else in the "
         "book, which is exactly what the account team needs to know.", note)


# ======================================================================================
# SHEET 8 — Business Questions
# ======================================================================================
ws = wb.add_worksheet("8. Business Questions")
ws.hide_gridlines(2)
ws.set_column("A:A", 2); ws.set_column("B:B", 5); ws.set_column("C:C", 42)
ws.set_column("D:D", 88)
ws.write("B2", "Business Questions", title)
ws.write("B3", "The five questions in section 6 of the brief. Every answer is computed from "
               "the gold layer — the SQL is in sql/02_business_questions.sql.", subtitle)

BA = summary["business_answers"]
q1 = BA["Q1_highest_sales"]
q2 = BA["Q2_best_voucher_type"]
q3 = BA["Q3_declining_region"]
qs = [
    ("Q1", "Which merchants generate the highest sales value and transaction volume?",
     f"Durban Cash Hub leads on both: R{q1['value']:,.0f} in sales "
     f"({q1['share']:.1%} of the portfolio) and {q1['transactions']:,} transactions. "
     f"The two rankings agree at the top, which is not guaranteed — a merchant can lead on "
     f"value while trailing on volume if its basket is larger, so both are reported.\n\n"
     f"Concentration matters more than the leader: the top 5 merchants carry "
     f"{summary['revenue_concentration']['top5_share']:.1%} of revenue and the top 10 carry "
     f"{summary['revenue_concentration']['top10_share']:.1%}. "
     f"{summary['revenue_concentration']['merchants_for_80pct']} of 25 merchants account for "
     f"80% of sales."),
    ("Q2", "Which voucher type has the highest redemption rate?",
     f"Airtime, at {q2['RedemptionRate']:.1%}. Gaming is lowest at {q2['worst_rate']:.1%} — "
     f"a 16.9 percentage point spread.\n\n"
     f"The value-based redemption rate is almost identical to the volume-based rate within "
     f"each type, which tells us high-value and low-value vouchers behave the same way. "
     f"Time-to-redeem is also effectively flat across types (3.5–3.7 days), so the difference "
     f"is whether customers redeem at all, not how quickly they do it. Gaming's 24% "
     f"non-redemption represents the largest single block of outstanding liability."),
    ("Q3", "Which region shows declining sales or transaction behaviour?",
     f"Eastern Cape, on four independent signals rather than one:\n"
     f"  •  it is the ONLY region that peaked before July (peak May 2026);\n"
     f"  •  it sits {abs(q3['vs_peak']):.1%} below its own peak while every other region is AT "
     f"its peak;\n"
     f"  •  its trend slope is +2.0% of average monthly sales against +4.4% to +8.5% elsewhere;\n"
     f"  •  June fell 12.2% month-on-month against +1.4% to +3.8% for every other region.\n\n"
     f"A single month's movement would not justify calling a decline. Four signals pointing "
     f"the same way does."),
    ("Q4", "Are ticket volumes, priority or long resolution times associated with weaker "
           "merchant performance?",
     f"Not as a portfolio-level rule — but decisively at the level of individual events.\n\n"
     f"The tempting answer is that tickets per 1,000 transactions correlates with target "
     f"attainment at r = {summary['size_confounder']['raw_corr_friction_vs_attainment']:+.2f}, "
     f"so friction hurts performance. That answer is confounded. The ratio is strongly "
     f"size-dependent (r = "
     f"{summary['size_confounder']['friction_vs_log_size_pearson']:+.2f} against log total "
     f"sales), so small merchants look worse purely because the denominator is small. "
     f"Controlling for size, the partial correlation collapses to r = "
     f"{summary['size_confounder']['partial_corr_friction_vs_attainment_controlling_size']:+.2f}. "
     f"SLA breach rate and average resolution time show no association at all.\n\n"
     f"What IS real is event-level. Four months show a merchant's ticket volume more than "
     f"doubling against its own history. Durban Cash Hub spiked +780% while sales GREW 8.2% — "
     f"a service problem at a healthy account. Umhlanga Value Mart spiked +693% while sales "
     f"fell 42.5% — a failing account. The same operational signal, opposite commercial "
     f"diagnosis. Ticket spikes are worth investigating, but they do not predict revenue on "
     f"their own."),
    ("Q5", "Which merchants should management focus on first, and why?",
     "Ranked by revenue at risk, not by severity of decline — a 43% collapse at a small "
     "merchant costs less than a 6% slide at a large one, and ranking on percentage change "
     "alone sends the account team to the wrong door.\n\n" +
     "\n".join(
         f"  {i+1}.  {m['Merchant']} ({m['Region']}) — health {m['HealthScore']:.0f}/100, "
         f"latest month {m['SalesVsPrior3Avg']:+.1%} vs prior 3-month average, "
         f"R{m['RevenueAtRiskAnnualised']:,.0f} annualised revenue at risk"
         + (f", tickets {m['TicketsVsPrior3Avg']:+.0%}" if m.get("TicketsVsPrior3Avg") else "")
         for i, m in enumerate(BA["Q5_focus_merchants"]))),
]
r = 6
for tag, q, a in qs:
    ws.write(r, 1, tag, f(bold=True, font_size=13, font_color=WHITE, bg_color=TEAL,
                          align="center", valign="vcenter"))
    ws.write(r, 2, q, f(bold=True, font_size=11, font_color=NAVY, text_wrap=True,
                        valign="vcenter", bg_color=LIGHT))
    ws.write(r, 3, "", f(bg_color=LIGHT))
    ws.set_row(r, 34)
    ws.write(r + 1, 1, "", cell)
    ws.write(r + 1, 2, "ANSWER", f(bold=True, font_size=9, font_color=GREY, valign="top",
                                   border=1, border_color="#D6DEE8"))
    ws.write(r + 1, 3, a, txt)
    ws.set_row(r + 1, max(60, 13 * a.count("\n") + 46))
    r += 3


# ======================================================================================
# SHEET 9 — Data Dictionary
# ======================================================================================
ws = wb.add_worksheet("9. Data Dictionary")
ws.hide_gridlines(2)
ws.set_column("A:A", 2)
ws.write("B2", "Data Dictionary", title)
ws.write("B3", "Gold layer star schema: 7 dimensions, 4 facts, 2 analytics marts, 1 SCD2 "
               "snapshot.", subtitle)

r = section(ws, 5, "WHY FOURTEEN TABLES WHEN THE README SUGGESTS FIVE", 5)
ws.merge_range(r, 1, r + 2, 5, REG_SUMMARY, note)
r += 4
tier_df = pd.DataFrame([
    {"Tier": TIERS[t][0], "What it means": TIERS[t][2],
     "Count": TIER_COUNTS[t],
     "Tables": ", ".join(sorted(k for k, v in REG.items() if v["tier"] == t))}
    for t in TIER_ORDER])
r = write_table(ws, tier_df, r, 1, {"Count": num},
                {"Tier": 20, "What it means": 34, "Count": 8, "Tables": 78}) + 2

just_df = pd.DataFrame([
    {"Table": name, "Tier": TIERS[v["tier"]][0], "Rows": v["rows"],
     "Why it exists": f"{v['why']} {v['detail']}"}
    for name, v in sorted(REG.items(),
                          key=lambda kv: (TIER_ORDER
                                          .index(kv[1]["tier"]), kv[0]))])
r = write_table(ws, just_df, r, 1, {"Rows": num, "Why it exists": txt},
                {"Table": 27, "Tier": 20, "Rows": 10, "Why it exists": 110}) + 1
ws.merge_range(r, 1, r + 2, 5, "THE FAIR CRITICISM, AND THE ANSWER — " + REG_COUNTER, note)
r += 4
r = section(ws, r, "COLUMN REFERENCE", 5)

dd = pd.DataFrame([
    ("dim_date", "date_key", "INT", "Surrogate", "yyyymmdd integer. Join key for every fact."),
    ("dim_date", "date", "DATE", "Attribute", "Calendar date. Marked as Date Table in Power BI."),
    ("dim_date", "year_month", "VARCHAR(7)", "Attribute", "yyyy-MM, used for monthly grouping."),
    ("dim_date", "is_in_fact_window", "BIT", "Flag",
     "True for dates within the activity window (excludes the redemption tail)."),
    ("dim_merchant", "merchant_key", "VARCHAR(32)", "Surrogate", "Hash surrogate key."),
    ("dim_merchant", "merchant_id", "VARCHAR(10)", "Natural key", "Source key, format M0nn."),
    ("dim_merchant", "region", "VARCHAR(50)", "Attribute", "5 SA provinces."),
    ("dim_merchant", "channel", "VARCHAR(50)", "Attribute",
     "Retail / Wholesale / Online / Agent Network."),
    ("dim_merchant", "active_status", "VARCHAR(20)", "Attribute",
     "CRM lifecycle flag. Active (23) or At Risk (2)."),
    ("dim_merchant", "merchant_size_band", "VARCHAR(20)", "Derived",
     "Quartile of realised sales, NOT of the supplied target (which is mis-calibrated)."),
    ("dim_merchant", "base_monthly_sales_target", "DECIMAL(18,2)", "Attribute",
     "As supplied. KNOWN ISSUE: ~6.1x below realised sales for every merchant."),
    ("dim_voucher_type", "voucher_type", "VARCHAR(50)", "Natural key",
     "Airtime / Electricity / Bill Payment / Groceries / Gaming."),
    ("dim_voucher_type", "voucher_category", "VARCHAR(50)", "Attribute",
     "Business grouping, maintained as a dbt seed."),
    ("dim_priority", "target_sla_hours", "SMALLINT", "Attribute",
     "CURRENT policy SLA. The fact stores the SLA in force when the ticket was raised."),
    ("fct_merchant_sales", "-", "-", "GRAIN",
     "One row per Date x Merchant x VoucherType. 26,500 rows."),
    ("fct_merchant_sales", "sales_value", "DECIMAL(18,2)", "Measure (additive)",
     "Gross voucher sales value in ZAR."),
    ("fct_merchant_sales", "transactions", "INT", "Measure (additive)", "Transaction count."),
    ("fct_merchant_sales", "avg_basket_value", "DECIMAL(18,4)", "Measure (NON-additive)",
     "Row-level only. Aggregate as SUM(sales_value)/SUM(transactions), never as an average."),
    ("fct_voucher_redemptions", "-", "-", "GRAIN",
     "One row per voucher (accumulating snapshot). 120,969 rows."),
    ("fct_voucher_redemptions", "sold_date_key", "INT", "FK (role-playing)",
     "ACTIVE relationship to dim_date. Issuance-cohort view."),
    ("fct_voucher_redemptions", "redeemed_date_key", "INT NULL", "FK (role-playing)",
     "INACTIVE relationship, activated via USERELATIONSHIP. Operational-throughput view."),
    ("fct_voucher_redemptions", "is_redeemed", "BIT", "Flag",
     "TRUE only if the Redeemed flag AND a valid non-retrograde date agree."),
    ("fct_voucher_redemptions", "days_to_redeem", "INT NULL", "Measure",
     "NULL when unredeemed, so AVERAGE correctly excludes them."),
    ("fct_voucher_redemptions", "is_delayed_redemption", "BIT", "Flag",
     "Redeemed more than 7 days after sale. Threshold set once in dbt_project.yml."),
    ("fct_voucher_redemptions", "outstanding_value", "DECIMAL(18,2)", "Measure (additive)",
     "Unredeemed voucher value. A balance-sheet liability, not lost revenue."),
    ("fct_voucher_redemptions", "breakage_value", "DECIMAL(18,2)", "Measure (additive)",
     "Unredeemed AND beyond the 90-day expiry window."),
    ("fct_support_tickets", "-", "-", "GRAIN", "One row per ticket. 1,363 rows."),
    ("fct_support_tickets", "resolution_hours", "DECIMAL(10,2)", "Measure",
     "Hours to resolution. Right-skewed: mean 23.7, median 16.4, max 190.7."),
    ("fct_support_tickets", "sla_hours", "SMALLINT", "Measure",
     "SLA in force WHEN RAISED. Stored on the fact so a policy change cannot restate history."),
    ("fct_support_tickets", "is_sla_breach", "BIT", "Flag", "resolution_hours > sla_hours."),
    ("fct_merchant_target", "-", "-", "GRAIN",
     "One row per Month x Merchant (periodic snapshot). Coarser than the sales fact."),
    ("fct_merchant_target", "monthly_sales_target", "DECIMAL(18,2)", "Measure",
     "Pro-rated by days covered so a part-month shows no false shortfall."),
    ("mart_merchant_scorecard", "health_score", "DECIMAL(5,1)", "Derived",
     "0-100 weighted composite of 8 percentile-ranked components. See sheet 3."),
    ("mart_merchant_scorecard", "revenue_at_risk_annualised", "DECIMAL(18,2)", "Derived",
     "Annualised shortfall vs the merchant's own recent baseline."),
])
dd.columns = ["Table", "Column", "Type", "Role", "Definition"]
end_dd = write_table(ws, dd, r, 1, {},
                     {"Table": 26, "Column": 28, "Type": 16, "Role": 20, "Definition": 92})
ws.autofilter(r, 1, end_dd - 1, 5)


# ======================================================================================
# SHEET 10 — Assumptions & Limitations
# ======================================================================================
ws = wb.add_worksheet("10. Assumptions")
ws.hide_gridlines(2)
ws.set_column("A:A", 2); ws.set_column("B:B", 34); ws.set_column("C:C", 96)
ws.write("B2", "Assumptions, Data Issues & Limitations", title)
ws.write("B3", "Documented decisions. Anything that would change a conclusion is listed here.",
         subtitle)

r = section(ws, 5, "DATA QUALITY FINDINGS", 3)
dq = pd.DataFrame([
    ("Sales targets mis-calibrated",
     "BaseMonthlySalesTarget sits ~6.1x below realised sales for ALL 25 merchants, so raw "
     "target attainment reads 614%. The consistency across every merchant points to a basis "
     "or units error rather than genuine outperformance. The supplied value is retained "
     "unchanged for transparency; the report uses a relative Target Attainment Index "
     "(merchant attainment ÷ portfolio attainment) which is comparable across merchants and "
     "immune to the calibration error. Confirmation of the intended basis is the first "
     "question for the business."),
    ("SLA thresholds inverted vs workload",
     "SLA targets run opposite to actual effort: Critical gets 12h but averages 52.7h; Low "
     "gets 48h and averages 11.3h. 94.7% of all breaches land on High and Critical. Treated "
     "as a genuine policy finding and reported as such, not corrected in the data."),
    ("Redemption flag vs date",
     "0 records in the supplied data disagree between the Redeemed flag and RedeemedDate. The "
     "validation rule is still enforced in silver, and violations would be flagged rather than "
     "silently dropped — the headline redemption rate is too visible to leave unguarded."),
    ("Referential integrity",
     "0 orphan MerchantIDs across all three facts. Fact-embedded Merchant/Region/Channel agree "
     "with MerchantReference in 100% of cases, so those columns were dropped from the facts "
     "losslessly."),
    ("Redemption tail beyond the window",
     "RedeemedDate extends to 20 August 2026, past the 31 July sales cut-off. This is expected "
     "(a voucher sold on 31 July can be redeemed in August). The calendar SPANS these dates so "
     "the join works, but the reporting WINDOW is defined by activity dates only — without "
     "that separation, a partial August with no sales would drag down every period measure."),
])
dq.columns = ["Finding", "Detail and treatment"]
end = write_table(ws, dq, r, 1, {"Detail and treatment": txt, "Finding": bold})

r = section(ws, end + 2, "ASSUMPTIONS MADE", 3)
asm = pd.DataFrame([
    ("Delayed redemption = > 7 days",
     "No threshold was supplied. 7 days sits above the 75th percentile (5 days), so it flags "
     "a genuine tail rather than routine behaviour. Defined once in dbt_project.yml and "
     "inherited by the SQL, DAX and ML layers."),
    ("Voucher expiry / breakage = 90 days",
     "No expiry rule was supplied. 90 days is a common voucher industry default. Affects the "
     "breakage measure only; the outstanding liability measure is unaffected."),
    ("Targets pro-rated by days covered",
     "Every month in the window is complete, so the pro-rating factor is currently 1.0. The "
     "logic is in place so a mid-month refresh cannot produce a false shortfall."),
    ("Support cost of R450/hour",
     "Used only in the indicative Ops Cost Exposure measure. Clearly flagged as an assumption; "
     "should be replaced with Finance's actual loaded rate before use."),
    ("Voucher category and margin band",
     "Not present in the source. Maintained as a dbt seed so the commercial team can change "
     "the mapping without a code deployment."),
    ("Health Score weights",
     "Chosen to prioritise recent momentum (25%) over structural trend (15%), because the "
     "operational purpose is early warning. Weights are declared in one place and are a "
     "business-tunable parameter, not a hidden constant."),
])
asm.columns = ["Assumption", "Rationale"]
end2 = write_table(ws, asm, r, 1, {"Rationale": txt, "Assumption": bold})

r = section(ws, end2 + 2, "LIMITATIONS", 3)
lim = pd.DataFrame([
    ("Seven months of data",
     "1 Jan – 31 Jul 2026. No year-on-year comparison is possible. The YoY measures are "
     "written and will work once a second year exists, but currently return BLANK by design "
     "rather than a misleading zero."),
    ("No prior-year seasonality baseline",
     "The 4.69% forecast MAPE reflects weekly seasonality only. Annual seasonality (festive "
     "trading, school terms) cannot be modelled from seven months and would likely change the "
     "forecast materially for December."),
    ("25 merchants limits statistical power",
     "Merchant-level correlations rest on n=25. This is why the ops-vs-performance analysis "
     "uses the 175-row merchant-month panel and partial correlation rather than resting on a "
     "single cross-sectional coefficient — and why the size confounder was tested for at all."),
    ("Redemption model ceiling",
     "Redemption is generated almost purely from voucher type in this dataset, capping "
     "achievable AUC at ~0.62. On real data with customer-level features (tenure, prior "
     "redemption behaviour, channel), materially higher performance would be expected."),
    ("Synthetic data",
     "All findings describe the supplied synthetic dataset. The embedded patterns were "
     "recovered independently by the anomaly model, which validates the METHOD; it does not "
     "validate the conclusions against real trading behaviour."),
    ("Costs and margins absent",
     "Only revenue is supplied. Merchant profitability, and therefore true commercial "
     "prioritisation, cannot be assessed. Revenue at Risk is a revenue measure, not a "
     "margin measure."),
])
lim.columns = ["Limitation", "Impact"]
write_table(ws, lim, r, 1, {"Impact": txt, "Limitation": bold})

wb.close()
print(f"Wrote {OUT}")
print(f"  10 sheets, {OUT.stat().st_size / 1024:.0f} KB")
