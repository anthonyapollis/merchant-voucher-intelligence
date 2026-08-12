"""
build_report.py
===============
Emits the PBIR report definition for MerchantVoucherIntelligence.Report from a
compact page/visual spec.

PBIR (the folder-per-visual report format) is deliberately verbose - one JSON
file per visual, each carrying a full query projection. Generating it from a
spec keeps the field references consistent with the semantic model and makes a
layout change a one-line edit rather than a hand-merge across 30 files.

IMPORTANT - what has and has not been verified. The semantic model was checked
against the gold CSVs programmatically, and every number in the report also
appears in dashboard/index.html, which was verified end to end in a browser.
The report definition below is written to the published PBIR schemas, but no
Power BI Desktop was available on the build machine, so it has NOT been opened
and rendered. Treat it as reviewed-not-run: open it in Desktop with the PBIP
and PBIR preview features enabled before presenting from it.

Run:  python build/build_report.py   (after build_semantic_model.py)
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PBI = ROOT / "powerbi"
NAME = "MerchantVoucherIntelligence"
REPORT = PBI / f"{NAME}.Report"
DEF = REPORT / "definition"

SCHEMA = "https://developer.microsoft.com/json-schemas/fabric/item/report/definition"
W, H = 1280, 720

# The dataviz palette, same slots and order as the offline dashboard, so a
# screenshot from either surface reads as the same product.
THEME = {
    "name": "MerchantVoucherIntelligence",
    "dataColors": ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4",
                   "#008300", "#4a3aa7", "#e34948"],
    "good": "#0ca30c", "neutral": "#fab219", "bad": "#d03b3b",
    "background": "#fcfcfb", "foreground": "#0b0b0b", "tableAccent": "#2a78d6",
    "textClasses": {
        "title": {"fontFace": "Segoe UI Semibold", "fontSize": 13, "color": "#0b0b0b"},
        "label": {"fontFace": "Segoe UI", "fontSize": 10, "color": "#52514e"},
        "callout": {"fontFace": "Segoe UI Semibold", "fontSize": 28, "color": "#0b0b0b"},
    },
    "visualStyles": {
        "*": {
            "*": {
                "background": [{"show": True, "color": {"solid": {"color": "#fcfcfb"}},
                                "transparency": 0}],
                "border": [{"show": True, "color": {"solid": {"color": "#e1e0d9"}},
                            "radius": 8}],
                "title": [{"show": True, "fontColor": {"solid": {"color": "#0b0b0b"}},
                           "fontSize": 12, "fontFamily": "Segoe UI Semibold"}],
                # Recessive grid, per the chart chrome spec.
                "categoryAxis": [{"gridlineColor": {"solid": {"color": "#e1e0d9"}},
                                  "gridlineStyle": "solid", "gridlineThickness": 1,
                                  "labelColor": {"solid": {"color": "#898781"}}}],
                "valueAxis": [{"gridlineColor": {"solid": {"color": "#e1e0d9"}},
                               "labelColor": {"solid": {"color": "#898781"}}}],
            }
        }
    },
}


# ------------------------------------------------------------ field helpers
def measure(name: str) -> dict:
    return {"Measure": {"Expression": {"SourceRef": {"Entity": "_Measures"}},
                        "Property": name}}


def column(entity: str, prop: str) -> dict:
    return {"Column": {"Expression": {"SourceRef": {"Entity": entity}},
                       "Property": prop}}


def proj(field: dict) -> dict:
    if "Measure" in field:
        entity, prop = "_Measures", field["Measure"]["Property"]
    else:
        entity = field["Column"]["Expression"]["SourceRef"]["Entity"]
        prop = field["Column"]["Property"]
    return {"field": field, "queryRef": f"{entity}.{prop}", "nativeQueryRef": prop}


def m(name: str) -> dict:
    return proj(measure(name))


def c(entity: str, prop: str) -> dict:
    return proj(column(entity, prop))


# ------------------------------------------------------------ visual builder
def visual(name, vtype, x, y, w, h, roles, *, title=None, order=0,
           sort=None, objects=None, filters=None, hidden=False):
    """One visual container. roles maps a visual data role to its projections."""
    v = {
        "$schema": f"{SCHEMA}/visualContainer/1.0.0/schema.json",
        "name": name,
        "position": {"x": x, "y": y, "z": order, "width": w, "height": h,
                     "tabOrder": order * 100},
        "visual": {
            "visualType": vtype,
            "query": {"queryState": {
                role: {"projections": projections}
                for role, projections in roles.items() if projections
            }},
            # Cross-highlighting on by default: clicking a bar should filter the
            # rest of the page, which is the whole reason the pages are on one
            # canvas rather than in four separate reports.
            "drillFilterOtherVisuals": True,
        },
    }
    if sort:
        v["visual"]["query"]["sortDefinition"] = {
            "sort": [{"field": sort[0], "direction": sort[1]}],
            "isDefaultSort": True,
        }
    obj = {"title": [{"properties": {
        "text": {"expr": {"Literal": {"Value": f"'{title}'"}}},
        "show": {"expr": {"Literal": {"Value": "true"}}},
    }}]} if title else {}
    if objects:
        obj.update(objects)
    if obj:
        v["visual"]["objects"] = obj
    if filters:
        v["filterConfig"] = {"filters": filters}
    if hidden:
        v["isHidden"] = True
    return v


def textbox(name, x, y, w, h, runs, order=0):
    """A text box. Used for page titles and the written insights page."""
    paragraphs = []
    for run in runs:
        paragraphs.append({
            "textRuns": [{
                "value": run["text"],
                "textStyle": {
                    "fontSize": f"{run.get('size', 11)}pt",
                    "fontWeight": run.get("weight", "normal"),
                    "color": run.get("color", "#0b0b0b"),
                    "fontFamily": "Segoe UI",
                },
            }],
        })
    return {
        "$schema": f"{SCHEMA}/visualContainer/1.0.0/schema.json",
        "name": name,
        "position": {"x": x, "y": y, "z": order, "width": w, "height": h,
                     "tabOrder": order * 100},
        "visual": {
            "visualType": "textbox",
            "objects": {"general": [{"properties": {
                "paragraphs": paragraphs,
            }}]},
            "drillFilterOtherVisuals": True,
        },
    }


def slicer(name, x, y, w, h, field, title, mode="Basic", order=0):
    return visual(name, "slicer", x, y, w, h,
                  {"Values": [field]}, title=title, order=order,
                  objects={"general": [{"properties": {
                      "mode": {"expr": {"Literal": {"Value": f"'{mode}'"}}}}}]})


def card(name, x, y, w, h, measure_name, label, order=0):
    return visual(name, "card", x, y, w, h, {"Values": [m(measure_name)]},
                  title=label, order=order,
                  objects={"labels": [{"properties": {
                      "fontSize": {"expr": {"Literal": {"Value": "26D"}}},
                      "color": {"solid": {"color": {"expr": {"Literal": {
                          "Value": "'#0b0b0b'"}}}}}}}]})


# ------------------------------------------------------------------- pages
def page_executive() -> tuple[str, str, list]:
    kpis = [("Total Sales", "Total sales"), ("Total Transactions", "Transactions"),
            ("Redemption Rate %", "Redemption rate"),
            ("Average Resolution Hours", "Avg resolution"),
            ("SLA Breach %", "SLA breach rate")]
    v = [textbox("exTitle", 16, 12, 610, 40, [
        {"text": "Executive overview", "size": 18, "weight": "bold"}])]
    v.append(visual("exNarr", "card", 640, 12, 624, 40,
                    {"Values": [m("Sales Trend Narrative")]},
                    objects={"labels": [{"properties": {
                        "fontSize": {"expr": {"Literal": {"Value": "10D"}}}}}]},
                    order=1))
    for i, (mea, lab) in enumerate(kpis):
        v.append(card(f"exKpi{i}", 16 + i * 250, 60, 238, 92, mea, lab, order=2 + i))
    v += [
        slicer("exSlRegion", 16, 164, 300, 60, c("DimMerchant", "Region"),
               "Region", "Dropdown", order=10),
        slicer("exSlVoucher", 328, 164, 300, 60, c("DimVoucherType", "VoucherType"),
               "Voucher type", "Dropdown", order=11),
        slicer("exSlDate", 640, 164, 624, 60, c("DimDate", "Date"),
               "Period", "Between", order=12),
        visual("exTrend", "lineChart", 16, 236, 620, 232,
               {"Category": [c("DimDate", "Date")],
                "Y": [m("Total Sales")]},
               title="Sales trend", order=20),
        visual("exRegion", "barChart", 648, 236, 300, 232,
               {"Category": [c("DimMerchant", "Region")], "Y": [m("Total Sales")]},
               title="Sales by region", order=21,
               sort=(measure("Total Sales"), "Descending")),
        visual("exVoucher", "donutChart", 960, 236, 304, 232,
               {"Category": [c("DimVoucherType", "VoucherType")],
                "Y": [m("Total Sales")]},
               title="Sales mix by voucher type", order=22),
        visual("exTop", "barChart", 16, 480, 620, 224,
               {"Category": [c("DimMerchant", "Merchant")],
                "Y": [m("Total Sales")]},
               title="Top merchants by sales value", order=23,
               sort=(measure("Total Sales"), "Descending"),
               filters=[{
                   "name": "exTopN", "field": column("DimMerchant", "Merchant"),
                   "type": "TopN",
                   "filter": {"Version": 2, "From": [{"Name": "d", "Entity": "DimMerchant",
                                                      "Type": 0}],
                              "Where": []},
                   "howCreated": "Auto",
                   # Top 10 by sales, so the bar chart stays readable at 25
                   # merchants instead of turning into a scroll bar.
                   "topN": {"itemCount": 10,
                            "orderBy": [{"direction": "Descending",
                                         "expression": measure("Total Sales")}]},
               }]),
        visual("exRedemption", "lineChart", 648, 480, 616, 224,
               {"Category": [c("DimDate", "MonthYear")],
                "Y": [m("Redemption Rate %")]},
               title="Redemption rate by month", order=24),
    ]
    return "exec", "Executive Overview", v


def page_merchant() -> tuple[str, str, list]:
    v = [
        textbox("mrTitle", 16, 12, 900, 40, [
            {"text": "Merchant analysis", "size": 18, "weight": "bold"}]),
        slicer("mrSlRegion", 16, 60, 300, 56, c("DimMerchant", "Region"),
               "Region", "Dropdown", order=1),
        slicer("mrSlSegment", 328, 60, 300, 56,
               c("DimMerchantSegment", "Segment"), "ML segment", "Dropdown", order=2),
        slicer("mrSlChannel", 640, 60, 300, 56, c("DimMerchant", "Channel"),
               "Channel", "Dropdown", order=3),
        slicer("mrSlTier", 952, 60, 312, 56, c("DimMerchantSegment", "RiskTier"),
               "Risk tier", "Dropdown", order=4),
        visual("mrScatter", "scatterChart", 16, 128, 620, 280,
               {"Category": [c("DimMerchant", "Merchant")],
                "X": [m("Total Sales")],
                "Y": [m("Sales MoM %")],
                "Size": [m("Total Tickets")],
                "Details": [c("DimMerchantSegment", "Segment")]},
               title="Growth against scale (bubble is ticket volume)", order=10),
        visual("mrTop", "barChart", 648, 128, 616, 280,
               {"Category": [c("DimMerchant", "Merchant")],
                "Y": [m("Total Sales")], "Tooltips": [m("Sales Share of Total %")]},
               title="Merchant contribution", order=11,
               sort=(measure("Total Sales"), "Descending")),
        visual("mrTable", "tableEx", 16, 420, 1248, 284,
               {"Values": [
                   c("DimMerchant", "Merchant"), c("DimMerchant", "Region"),
                   c("DimMerchantSegment", "Segment"),
                   m("Merchant Rank"), m("Total Sales"), m("Sales Share of Total %"),
                   m("Total Transactions"), m("Average Basket Value"),
                   m("Sales MoM %"), m("Redemption Rate %"),
                   m("Tickets per 1k Transactions"), m("SLA Breach %"),
                   c("DimMerchantSegment", "RiskTier"),
               ]},
               title="Merchant league table - right-click a row to drill through",
               order=12, sort=(measure("Total Sales"), "Descending")),
    ]
    return "merchant", "Merchant Analysis", v


def page_operational() -> tuple[str, str, list]:
    kpis = [("Total Tickets", "Tickets raised"),
            ("Average Resolution Hours", "Avg resolution"),
            ("SLA Breach %", "SLA breach rate"),
            ("Open Tickets", "Still open"),
            ("Tickets per 1k Transactions", "Tickets per 1k tx")]
    v = [textbox("opTitle", 16, 12, 900, 40, [
        {"text": "Operational view", "size": 18, "weight": "bold"}])]
    for i, (mea, lab) in enumerate(kpis):
        v.append(card(f"opKpi{i}", 16 + i * 250, 60, 238, 84, mea, lab, order=i))
    v += [
        slicer("opSlPriority", 16, 156, 300, 56, c("DimPriority", "Priority"),
               "Priority", "Dropdown", order=10),
        slicer("opSlType", 328, 156, 300, 56, c("DimTicketType", "TicketType"),
               "Ticket type", "Dropdown", order=11),
        slicer("opSlRegion", 640, 156, 300, 56, c("DimMerchant", "Region"),
               "Region", "Dropdown", order=12),
        slicer("opSlStatus", 952, 156, 312, 56, c("FactSupportTickets", "Status"),
               "Status", "Dropdown", order=13),
        # The headline operational visual: resolution against target, per tier.
        visual("opSla", "clusteredColumnChart", 16, 224, 620, 244,
               {"Category": [c("DimPriority", "Priority")],
                "Y": [m("Average Resolution Hours"), m("SLA Target Hours")]},
               title="Average resolution hours against SLA target, by priority",
               order=20),
        visual("opTrend", "lineChart", 648, 224, 616, 244,
               {"Category": [c("DimDate", "MonthYear")],
                "Y": [m("Total Tickets")]},
               title="Ticket volume by month", order=21),
        visual("opTypes", "barChart", 16, 480, 400, 224,
               {"Category": [c("DimTicketType", "TicketType")],
                "Y": [m("Total Tickets")], "Tooltips": [m("SLA Breach %")]},
               title="Ticket types", order=22,
               sort=(measure("Total Tickets"), "Descending")),
        visual("opMerchants", "tableEx", 428, 480, 836, 224,
               {"Values": [c("DimMerchant", "Merchant"), c("DimMerchant", "Region"),
                           m("Total Tickets"), m("Tickets per 1k Transactions"),
                           m("Average Resolution Hours"), m("SLA Breach %"),
                           m("Sales MoM %")]},
               title="Merchant operational league table", order=23,
               sort=(measure("Tickets per 1k Transactions"), "Descending")),
    ]
    return "ops", "Operational View", v


def page_geo() -> tuple[str, str, list]:
    """Geographic page.

    shapeMap renders province polygons from a custom TopoJSON, which is the
    right visual for admin-1 choropleth and needs no map service. The
    filledMap alternative requires geocoding against Bing and would resolve
    'Free State' by name rather than by boundary, so it is not used here.
    """
    v = [
        textbox("geTitle", 16, 12, 900, 40, [
            {"text": "Geographic intelligence", "size": 18, "weight": "bold"}]),
        textbox("geNote", 16, 640, 1248, 64, [
            {"text": "Provinces with no merchant presence are excluded from the "
                     "colour scale rather than shaded as zero - absent is not the "
                     "same as low. Land area is computed from the boundary "
                     "geometry; no population or GDP reference feed was supplied, "
                     "so sales per square kilometre is a coverage indicator, not a "
                     "demand measure.", "size": 9, "color": "#898781"}]),
        slicer("geSlVoucher", 16, 60, 300, 56, c("DimVoucherType", "VoucherType"),
               "Voucher type", "Dropdown", order=1),
        slicer("geSlChannel", 328, 60, 300, 56, c("DimMerchant", "Channel"),
               "Channel", "Dropdown", order=2),
        slicer("geSlDate", 640, 60, 624, 56, c("DimDate", "Date"),
               "Period", "Between", order=3),
        visual("geMap", "shapeMap", 16, 128, 620, 500,
               {"Category": [c("DimMerchant", "Region")],
                "Series": [m("Total Sales")],
                "Tooltips": [m("Total Transactions"), m("Redemption Rate %"),
                             m("Tickets per 1k Transactions"),
                             m("Sales Momentum %")]},
               title="Sales by province", order=10,
               objects={"shape": [{"properties": {
                   # The custom map is registered in StaticResources; see
                   # report.json resourcePackages.
                   "map": {"expr": {"Literal": {"Value": "'za_provinces'"}}},
                   "projectionEnum": {"expr": {"Literal": {"Value": "'equirectangular'"}}},
               }}]}),
        visual("geMomentum", "barChart", 648, 128, 616, 244,
               {"Category": [c("DimMerchant", "Region")],
                "Y": [m("Sales Momentum %")]},
               title="Provincial momentum (latest month vs prior three)", order=11,
               sort=(measure("Sales Momentum %"), "Ascending")),
        visual("geTable", "tableEx", 648, 384, 616, 244,
               {"Values": [c("DimMerchant", "Region"), m("Total Sales"),
                           m("Sales Share of Total %"), m("Redemption Rate %"),
                           m("Tickets per 1k Transactions"), m("SLA Breach %"),
                           m("Sales Momentum %")]},
               title="Province league table", order=12,
               sort=(measure("Total Sales"), "Descending")),
    ]
    return "geo", "Geographic Intelligence", v


def page_intelligence() -> tuple[str, str, list]:
    v = [
        textbox("aiTitle", 16, 12, 900, 40, [
            {"text": "Intelligence and machine learning", "size": 18, "weight": "bold"}]),
        card("aiKpi0", 16, 60, 300, 84, "Forecast Next 30 Days", "Forecast, next 30 days"),
        card("aiKpi1", 328, 60, 300, 84, "Merchants At Risk", "Merchants at risk"),
        card("aiKpi2", 640, 60, 300, 84, "High Severity Anomalies", "High-severity anomalies"),
        card("aiKpi3", 952, 60, 312, 84, "Average Health Score", "Average health score"),
        visual("aiForecast", "lineChart", 16, 156, 800, 260,
               {"Category": [c("DimDate", "Date")],
                "Y": [m("Total Sales"), m("Forecast Sales Value")]},
               title="Actual sales and 30-day forecast", order=10),
        visual("aiSegments", "scatterChart", 828, 156, 436, 260,
               {"Category": [c("DimMerchantSegment", "Merchant")],
                "X": [m("Avg PCA 1")],
                "Y": [m("Avg PCA 2")],
                "Size": [m("Average Health Score")],
                "Details": [c("DimMerchantSegment", "Segment")]},
               title="Merchant segments (K-Means, PCA projection)", order=11),
        visual("aiAnomalies", "tableEx", 16, 428, 800, 276,
               {"Values": [proj(column("FactAnomaly", "Date")),
                           c("FactAnomaly", "Merchant"),
                           c("FactAnomaly", "Measure"),
                           proj(column("FactAnomaly", "ActualValue")),
                           proj(column("FactAnomaly", "ExpectedValue")),
                           proj(column("FactAnomaly", "DeviationPct")),
                           c("FactAnomaly", "Severity")]},
               title="Detected anomalies", order=12),
        visual("aiNarrative", "tableEx", 828, 428, 436, 276,
               {"Values": [c("InsightNarrative", "Merchant"),
                           c("InsightNarrative", "ActionFlag"),
                           c("InsightNarrative", "Narrative")]},
               title="Auto-generated merchant narrative", order=13),
    ]
    return "intelligence", "Intelligence & ML", v


def page_notes() -> tuple[str, str, list]:
    body = [
        {"text": "Insights, assumptions and next steps\n", "size": 18, "weight": "bold"},
        {"text": "\nKey findings\n", "size": 13, "weight": "bold"},
        {"text": "1. The support queue is being worked in the wrong order. "
                 "Critical tickets average 52.7 hours against a 12-hour SLA and "
                 "breach 98% of the time; Low tickets close in 11.3 hours against "
                 "a 48-hour SLA and breach 0.2%. Priority is not driving effort.\n",
         "size": 10},
        {"text": "2. Umhlanga Value Mart fell 44.7% month on month, on transaction "
                 "volume rather than basket size, in the same month its ticket count "
                 "went from 3 to 37. Operational, not market.\n", "size": 10},
        {"text": "3. Kudu Digital Kiosk stepped up to a new sales level in May and "
                 "has held it for three months. Worth understanding before assuming "
                 "it repeats.\n", "size": 10},
        {"text": "4. Western Cape Bill Payment vouchers ran at roughly four times "
                 "normal redemption lag through April, then returned to baseline. "
                 "An incident, not a trend.\n", "size": 10},
        {"text": "5. The network serves 5 of 9 provinces; 56% of the country's land "
                 "area has no merchant presence at all.\n", "size": 10},
        {"text": "\nAssumptions\n", "size": 13, "weight": "bold"},
        {"text": "Delayed redemption means more than 7 days from sale, against an "
                 "observed median of about 3 days. Unredeemed vouchers are excluded "
                 "from the delay rate rather than counted as on-time. Merchant "
                 "region and channel come from the reference file only, having been "
                 "verified to agree with all three fact files on every row. "
                 "SLAHours is a property of the priority tier, not the ticket. "
                 "Sales targets are the monthly figure times the months in the "
                 "selected period; no phasing was supplied.\n", "size": 10},
        {"text": "\nData quality\n", "size": 13, "weight": "bold"},
        {"text": "All 20 referential integrity, grain and validity checks pass. "
                 "One caveat carried from the source: tickets that are still open "
                 "report elapsed hours rather than time to resolution, so average "
                 "resolution mixes two definitions. Use Average Resolution Hours "
                 "(Closed) where the distinction matters. Support tickets carry no "
                 "voucher type, so the voucher slicer does not filter ticket "
                 "visuals.\n", "size": 10},
        {"text": "\nLimitations\n", "size": 13, "weight": "bold"},
        {"text": "Seven months of one year: no year-on-year comparison, and annual "
                 "seasonality cannot be separated from trend. 25 merchants is too "
                 "few to fit and validate a churn classifier honestly, so the health "
                 "score is a transparent weighted percentile index instead - which "
                 "also means a quarter of merchants always sit in the bottom tier by "
                 "construction. The delayed-redemption model scores near chance, "
                 "which is itself the finding. The forecast beats a seasonal-naive "
                 "benchmark by only 0.18 percentage points of MAPE on 28 held-out "
                 "days; re-backtest as history accumulates.\n", "size": 10},
        {"text": "\nRecommended next steps\n", "size": 13, "weight": "bold"},
        {"text": "Re-triage the support queue by priority this week. Put Umhlanga "
                 "Value Mart on a recovery plan and clear its ticket backlog. Run a "
                 "root-cause review on the April Western Cape redemption incident. "
                 "Book the modelled non-redemption exposure as a breakage estimate. "
                 "Add a population or GDP reference feed so provincial coverage can "
                 "be assessed against demand rather than land area.\n", "size": 10},
    ]
    return "notes", "Insights & Notes", [textbox("noBody", 16, 12, 1248, 692, body)]


def page_drillthrough() -> tuple[str, str, list]:
    v = [
        textbox("dtTitle", 16, 12, 900, 40, [
            {"text": "Merchant detail", "size": 18, "weight": "bold"}]),
        card("dtKpi0", 16, 60, 246, 84, "Total Sales", "Sales"),
        card("dtKpi1", 274, 60, 246, 84, "Total Transactions", "Transactions"),
        card("dtKpi2", 532, 60, 246, 84, "Average Basket Value", "Avg basket"),
        card("dtKpi3", 790, 60, 246, 84, "Redemption Rate %", "Redemption rate"),
        card("dtKpi4", 1048, 60, 216, 84, "Sales MoM %", "Month on month"),
        visual("dtNarrative", "card", 16, 156, 1248, 72,
               {"Values": [c("InsightNarrative", "Narrative")]},
               title="What changed and why", order=5,
               objects={"labels": [{"properties": {
                   "fontSize": {"expr": {"Literal": {"Value": "10D"}}}}}]}),
        visual("dtTrend", "columnChart", 16, 240, 620, 230,
               {"Category": [c("DimDate", "MonthYear")], "Y": [m("Total Sales")]},
               title="Monthly sales", order=10),
        visual("dtVoucher", "barChart", 648, 240, 616, 230,
               {"Category": [c("DimVoucherType", "VoucherType")],
                "Y": [m("Total Sales")], "Tooltips": [m("Redemption Rate %")]},
               title="Sales by voucher type", order=11),
        visual("dtTickets", "tableEx", 16, 482, 620, 222,
               {"Values": [c("DimTicketType", "TicketType"),
                           c("DimPriority", "Priority"), m("Total Tickets"),
                           m("Average Resolution Hours"), m("SLA Breach %")]},
               title="Support tickets", order=12),
        visual("dtAnomalies", "tableEx", 648, 482, 616, 222,
               {"Values": [proj(column("FactAnomaly", "Date")),
                           c("FactAnomaly", "Measure"),
                           proj(column("FactAnomaly", "ActualValue")),
                           proj(column("FactAnomaly", "ExpectedValue")),
                           c("FactAnomaly", "Severity")]},
               title="Anomalies detected for this merchant", order=13),
    ]
    return "drillMerchant", "Merchant Detail (drill-through)", v


def page_tooltip() -> tuple[str, str, list]:
    v = [
        card("ttKpi0", 8, 8, 156, 60, "Total Sales", "Sales"),
        card("ttKpi1", 172, 8, 148, 60, "Sales MoM %", "MoM"),
        visual("ttTrend", "lineChart", 8, 76, 312, 120,
               {"Category": [c("DimDate", "MonthYear")], "Y": [m("Total Sales")]},
               title="Trend", order=5),
        visual("ttOps", "card", 8, 204, 312, 44,
               {"Values": [m("Tickets per 1k Transactions")]},
               title="Tickets per 1k transactions", order=6),
    ]
    return "tooltipMerchant", "Merchant tooltip", v


def main() -> None:
    if DEF.exists():
        shutil.rmtree(DEF)

    pages = [page_executive(), page_merchant(), page_operational(), page_geo(),
             page_intelligence(), page_notes(), page_drillthrough(), page_tooltip()]

    (REPORT).mkdir(parents=True, exist_ok=True)
    (REPORT / "definition.pbir").write_text(json.dumps({
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/"
                   "definitionProperties/1.0.0/schema.json",
        "version": "4.0",
        "datasetReference": {"byPath": {"path": f"../{NAME}.SemanticModel"}},
    }, indent=2), encoding="utf8")

    (DEF).mkdir(parents=True, exist_ok=True)
    (DEF / "report.json").write_text(json.dumps({
        "$schema": f"{SCHEMA}/report/2.0.0/schema.json",
        "themeCollection": {"customTheme": {
            "name": THEME["name"], "type": "RegisteredResources",
            "path": "MerchantVoucherIntelligence.json"}},
        "layoutOptimization": "None",
        "resourcePackages": [{
            "name": "SharedResources", "type": "SharedResources",
            "items": [{"name": "BaseThemes/CY24SU10.json", "path": "BaseThemes/CY24SU10.json",
                       "type": "BaseTheme"}],
        }, {
            "name": "RegisteredResources", "type": "RegisteredResources",
            "items": [
                {"name": "MerchantVoucherIntelligence.json",
                 "path": "MerchantVoucherIntelligence.json", "type": "CustomTheme"},
                # The province TopoJSON the shapeMap on the geo page binds to.
                {"name": "za_provinces", "path": "za_provinces.json",
                 "type": "ShapeMap"},
            ],
        }],
        "settings": {
            "useStylableVisualContainerHeader": True,
            "defaultDrillFilterOtherVisuals": True,
            "useNewFilterPaneExperience": True,
        },
    }, indent=2), encoding="utf8")

    (DEF / "version.json").write_text(json.dumps({
        "$schema": f"{SCHEMA}/versionMetadata/1.0.0/schema.json",
        "version": "2.0.0",
    }, indent=2), encoding="utf8")

    visible = [p[0] for p in pages if p[0] not in ("drillMerchant", "tooltipMerchant")]
    (DEF / "pages").mkdir(parents=True, exist_ok=True)
    (DEF / "pages" / "pages.json").write_text(json.dumps({
        "$schema": f"{SCHEMA}/pagesMetadata/1.0.0/schema.json",
        "pageOrder": [p[0] for p in pages],
        "activePageName": "exec",
    }, indent=2), encoding="utf8")

    for pname, display, visuals in pages:
        pdir = DEF / "pages" / pname
        pdir.mkdir(parents=True, exist_ok=True)
        page = {
            "$schema": f"{SCHEMA}/page/1.0.0/schema.json",
            "name": pname,
            "displayName": display,
            "displayOption": "FitToPage",
            "height": 260 if pname == "tooltipMerchant" else H,
            "width": 330 if pname == "tooltipMerchant" else W,
        }
        if pname == "drillMerchant":
            page["visibility"] = "HiddenInViewMode"
            page["pageBinding"] = {"name": "drillMerchantBinding", "type": "Drillthrough"}
            # The drill-through key. Right-clicking a merchant anywhere in the
            # report lands here filtered to that merchant.
            page["filterConfig"] = {"filters": [{
                "name": "dtMerchant",
                "field": column("DimMerchant", "Merchant"),
                "type": "Categorical",
                "howCreated": "Drillthrough",
                "isLockedInViewMode": False,
                "isHiddenInViewMode": False,
            }]}
        elif pname == "tooltipMerchant":
            page["visibility"] = "HiddenInViewMode"
            page["pageBinding"] = {"name": "tooltipMerchantBinding", "type": "Tooltip"}
        page["objects"] = {"background": [{"properties": {
            "color": {"solid": {"color": {"expr": {"Literal": {"Value": "'#f9f9f7'"}}}}},
            "transparency": {"expr": {"Literal": {"Value": "0D"}}},
        }}]}
        (pdir / "page.json").write_text(json.dumps(page, indent=2), encoding="utf8")

        for vis in visuals:
            vdir = pdir / "visuals" / vis["name"]
            vdir.mkdir(parents=True, exist_ok=True)
            (vdir / "visual.json").write_text(json.dumps(vis, indent=2), encoding="utf8")

    res = REPORT / "StaticResources" / "RegisteredResources"
    res.mkdir(parents=True, exist_ok=True)
    (res / "MerchantVoucherIntelligence.json").write_text(
        json.dumps(THEME, indent=2), encoding="utf8")

    # The shapeMap resource. Power BI expects TopoJSON, so the simplified
    # province rings are converted from the GeoJSON-style arrays produced by
    # build_geo.py.
    geo = json.loads((ROOT / "data" / "reference" /
                      "za_provinces_simplified.json").read_text(encoding="utf8"))
    arcs, geometries = [], []
    for prov in geo["provinces"]:
        prov_arcs = []
        for ring in prov["rings"]:
            arcs.append([[round(x, 4), round(y, 4)] for x, y in ring])
            prov_arcs.append([len(arcs) - 1])
        # TopoJSON nesting: a Polygon's arcs are an array of RINGS (each ring an
        # array of arc indices); a MultiPolygon's are an array of polygons, each
        # itself an array of rings. Flattening one level too far here is the
        # classic way a shape map renders nothing at all.
        geometries.append({
            "type": "Polygon" if len(prov_arcs) == 1 else "MultiPolygon",
            "arcs": prov_arcs if len(prov_arcs) == 1 else [[a] for a in prov_arcs],
            "properties": {"name": prov["name"], "code": prov["code"]},
        })
    (res / "za_provinces.json").write_text(json.dumps({
        "type": "Topology",
        "objects": {"provinces": {"type": "GeometryCollection",
                                  "geometries": geometries}},
        "arcs": arcs,
        "bbox": geo["bbox"],
    }, separators=(",", ":")), encoding="utf8")

    n_visuals = sum(len(p[2]) for p in pages)
    print(f"Report written to powerbi/{NAME}.Report")
    print(f"  {len(pages)} pages ({len(visible)} visible, "
          f"1 drill-through, 1 tooltip), {n_visuals} visuals")
    print(f"  shapeMap resource: {len(geometries)} provinces, {len(arcs)} arcs")
    print("  NOTE: written to the PBIR schemas but NOT opened in Power BI Desktop "
          "(not installed on this machine). Verify before presenting.")


if __name__ == "__main__":
    main()
