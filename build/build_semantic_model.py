"""
build_semantic_model.py
=======================
Emits the Power BI project (PBIP) and its TMDL semantic model from the actual
gold layer, so the column list, data types and the model can never drift apart
from the tables they describe.

TMDL is tab-indented - spaces are a parse error - so generating it beats hand
typing it.

The partitions read the gold CSVs through a `GoldFolder` M parameter, which
means the PBIP opens and loads on any machine with a copy of this repo. Point
that parameter at a Lakehouse or Warehouse instead and nothing else in the
model changes; see the note written into expressions.tmdl.

Run:  python build/build_semantic_model.py
"""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
GOLD = ROOT / "data" / "gold"
PBI = ROOT / "powerbi"
NAME = "MerchantVoucherIntelligence"
SM = PBI / f"{NAME}.SemanticModel"
T = "\t"


def guid(*parts: str) -> str:
    """Deterministic lineage tags: re-running the build must not churn the diff."""
    h = hashlib.sha1("|".join(parts).encode()).hexdigest()
    return f"{h[:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:32]}"


# Column data types, summarisation and formatting, declared rather than guessed.
# summarizeBy "none" everywhere except the genuine additive measures: an
# implicit sum on a key or a rate is always wrong, and letting Power BI decide
# is how "Sum of Year" ends up on someone's chart.
TYPES = {
    "int64": ("int64", "0"),
    "double": ("double", "0.00"),
    # Text inside double quotes in a .NET format string is ALREADY literal, so
    # a backslash in front of the R is not an escape - it prints a backslash.
    # "R"#,0 renders as \R10M on a card. Quote the R and leave it alone.
    "money": ("double", '"R"#,0.00'),
    "string": ("string", None),
    "dateTime": ("dateTime", "yyyy-mm-dd"),
    "boolean": ("int64", "0"),
}

MODEL = {
    "DimDate": {
        "dataCategory": "Time",
        "key": "DateKey",
        "sortBy": {"MonthYear": "MonthYearSort", "MonthShort": "MonthNumber",
                   "MonthName": "MonthNumber", "DayName": "DayOfWeek"},
        "hidden": ["DateKey", "MonthYearSort", "MonthNumber", "DayOfWeek",
                   "QuarterNumber"],
        "markAsDate": "Date",
        "cols": {
            "DateKey": "int64", "Date": "dateTime", "Year": "int64",
            "QuarterNumber": "int64", "Quarter": "string", "MonthNumber": "int64",
            "MonthName": "string", "MonthShort": "string", "MonthYear": "string",
            "MonthYearSort": "int64", "Day": "int64", "DayName": "string",
            "DayOfWeek": "int64", "IsWeekend": "int64", "WeekOfYear": "int64",
            "WeekStartDate": "dateTime", "MonthStartDate": "dateTime",
            "MonthEndDate": "dateTime",
        },
    },
    "DimMerchant": {
        "key": "MerchantKey",
        "hidden": ["MerchantKey", "RegionGeo"],
        # Country is constant, but a filled map given only "Free State" has to
        # guess which country it is in and renders the whole world. With a
        # Country column categorised as Country, Bing resolves the provinces.
        # Country pins the geocoder to South Africa. RegionGeo is what the
        # filled map actually binds to: a two-field Country/Region hierarchy
        # renders at the COUNTRY level by default, giving one filled blob for
        # the whole of South Africa, so the province name is pre-qualified into
        # a single unambiguous field instead.
        "extraColumns": {
            "Country": ('"South Africa"', "type text"),
            "RegionGeo": ('[Region] & ", South Africa"', "type text"),
        },
        "cols": {
            "MerchantKey": "string", "Merchant": "string", "Region": "string",
            "Country": "string", "RegionGeo": "string",
            "Channel": "string", "ActiveStatus": "string",
            "AccountManager": "string", "OnboardedDate": "dateTime",
            "TenureMonths": "int64", "TenureBand": "string",
            "BaseMonthlySalesTarget": "money",
        },
    },
    "DimVoucherType": {
        "key": "VoucherTypeKey", "hidden": ["VoucherTypeKey"],
        "cols": {"VoucherTypeKey": "string", "VoucherType": "string",
                 "SettlementModel": "string"},
    },
    "DimTicketType": {
        "key": "TicketTypeKey", "hidden": ["TicketTypeKey"],
        "cols": {"TicketTypeKey": "string", "TicketType": "string",
                 "TicketCategory": "string"},
    },
    "DimPriority": {
        "key": "PriorityKey", "hidden": ["PriorityKey", "PrioritySort"],
        "sortBy": {"Priority": "PrioritySort"},
        "cols": {"PriorityKey": "string", "Priority": "string",
                 "PrioritySort": "int64", "SLATargetHours": "int64"},
    },
    "FactMerchantSales": {
        "hidden": ["DateKey", "MerchantKey", "VoucherTypeKey"],
        "sum": ["SalesValue", "Transactions"],
        "cols": {"DateKey": "int64", "MerchantKey": "string",
                 "VoucherTypeKey": "string", "SalesValue": "money",
                 "Transactions": "int64"},
    },
    "FactVoucherRedemptions": {
        "hidden": ["SoldDateKey", "RedeemedDateKey", "MerchantKey",
                   "VoucherTypeKey", "VoucherID"],
        "sum": ["VoucherValue", "IsRedeemed", "IsDelayedRedemption"],
        "cols": {"VoucherID": "string", "SoldDateKey": "int64",
                 "RedeemedDateKey": "int64", "MerchantKey": "string",
                 "VoucherTypeKey": "string", "VoucherValue": "money",
                 "IsRedeemed": "int64", "DaysToRedeem": "int64",
                 "IsDelayedRedemption": "int64"},
    },
    "FactSupportTickets": {
        "hidden": ["DateKey", "MerchantKey", "TicketTypeKey", "PriorityKey",
                   "TicketID"],
        "sum": ["IsSLABreach", "IsOpen"],
        "cols": {"TicketID": "string", "DateKey": "int64",
                 "MerchantKey": "string", "TicketTypeKey": "string",
                 "PriorityKey": "string", "ResolutionHours": "double",
                 "SLAHours": "int64", "Status": "string",
                 "IsSLABreach": "int64", "IsOpen": "int64"},
    },
    "DimMerchantSegment": {
        "key": "MerchantKey",
        # Merchant, Region, Channel, ActiveStatus and AccountManager are
        # repeated here from DimMerchant. Hidden rather than dropped: the CSV is
        # a standalone ML output that has to make sense on its own, but a user
        # picking DimMerchantSegment[Merchant] instead of DimMerchant[Merchant]
        # would silently build a table off the wrong side of the relationship.
        "hidden": ["MerchantKey", "SegmentID", "Merchant", "Region", "Channel",
                   "ActiveStatus", "AccountManager", "BaseMonthlySalesTarget"],
        # Scatter plots need an aggregation over these, not a raw column.
        "avg": ["PCA1", "PCA2", "HealthScore", "GrowthSlopePct",
                "TargetAttainmentPct", "TicketsPer1kTx", "RedemptionRate"],
        "cols": {"MerchantKey": "string", "Merchant": "string",
                 "Region": "string", "Channel": "string", "ActiveStatus": "string",
                 "AccountManager": "string", "Segment": "string",
                 "SegmentID": "int64", "SegmentProfile": "string",
                 "PCA1": "double", "PCA2": "double", "HealthScore": "double",
                 "RiskTier": "string", "TotalSales": "money",
                 "TotalTransactions": "int64", "AvgBasket": "money",
                 "GrowthSlopePct": "double", "Volatility": "double",
                 "RedemptionRate": "double", "AvgDaysToRedeem": "double",
                 "DelayedRate": "double", "Tickets": "int64",
                 "TicketsPer1kTx": "double", "AvgResolutionHours": "double",
                 "SLABreachRate": "double", "BaseMonthlySalesTarget": "money",
                 "TargetAttainmentPct": "double"},
    },
    "FactAnomaly": {
        "hidden": ["AnomalyID", "MerchantKey"],
        "cols": {"AnomalyID": "string", "Date": "dateTime",
                 "MerchantKey": "string", "Merchant": "string",
                 "Region": "string", "Measure": "string",
                 "ActualValue": "double", "ExpectedValue": "double",
                 "Score": "double", "Direction": "string",
                 "ScoreType": "string", "Severity": "string",
                 "DeviationPct": "double"},
    },
    "InsightNarrative": {
        "key": "MerchantKey",
        "hidden": ["MerchantKey", "Region", "Channel"],
        "cols": {"MerchantKey": "string", "Merchant": "string",
                 "Region": "string", "Channel": "string", "Headline": "string",
                 "ActionFlag": "string", "SalesMoMPct": "double",
                 "TransactionsMoMPct": "double", "AvgBasketMoMPct": "double",
                 "TicketsThisMonth": "int64", "TicketsPrevMonth": "int64",
                 "Narrative": "string"},
    },
    "FactSalesForecast": {
        "hidden": [],
        "sum": ["ForecastSalesValue", "LowerBound", "UpperBound"],
        "cols": {"Date": "dateTime", "ForecastSalesValue": "money",
                 "LowerBound": "money", "UpperBound": "money",
                 "Scope": "string"},
    },
}

# from-table, from-column, to-table, to-column, active, cross-filter
RELATIONSHIPS = [
    ("FactMerchantSales", "DateKey", "DimDate", "DateKey", True, "single"),
    ("FactMerchantSales", "MerchantKey", "DimMerchant", "MerchantKey", True, "single"),
    ("FactMerchantSales", "VoucherTypeKey", "DimVoucherType", "VoucherTypeKey", True, "single"),
    ("FactVoucherRedemptions", "SoldDateKey", "DimDate", "DateKey", True, "single"),
    # The redemption-date role is deliberately NOT a physical relationship.
    #
    # 19,126 of 120,969 vouchers are unredeemed, so RedeemedDateKey is null for
    # them. A physical relationship on a nullable key makes Power BI add a blank
    # member to DimDate, and that blank then appears as "(Blank)" in every date
    # slicer in the report - and it does so even when the relationship is
    # INACTIVE, so USERELATIONSHIP does not avoid it.
    #
    # [Redemptions by Redemption Date] uses TREATAS instead: a virtual
    # relationship applied at query time. Same answer, no blank member, and the
    # nulls stay meaningful rather than being coalesced to a fake date.
    ("FactVoucherRedemptions", "MerchantKey", "DimMerchant", "MerchantKey", True, "single"),
    ("FactVoucherRedemptions", "VoucherTypeKey", "DimVoucherType", "VoucherTypeKey", True, "single"),
    ("FactSupportTickets", "DateKey", "DimDate", "DateKey", True, "single"),
    ("FactSupportTickets", "MerchantKey", "DimMerchant", "MerchantKey", True, "single"),
    ("FactSupportTickets", "TicketTypeKey", "DimTicketType", "TicketTypeKey", True, "single"),
    ("FactSupportTickets", "PriorityKey", "DimPriority", "PriorityKey", True, "single"),
    # One-to-one extensions of DimMerchant. Both filter FROM the dimension, so
    # a merchant slicer drives them; neither is allowed to filter back.
    ("DimMerchantSegment", "MerchantKey", "DimMerchant", "MerchantKey", True, "single"),
    ("InsightNarrative", "MerchantKey", "DimMerchant", "MerchantKey", True, "single"),
    # FactAnomaly is deliberately NOT related to DimMerchant.
    #
    # Ten of its 36 rows are region x voucher-type anomalies with no merchant at
    # all, so MerchantKey is null for them. A nullable foreign key makes Power BI
    # add a blank member to the table on the one side, and that blank member then
    # shows up as "(Blank)" in every DimMerchant slicer on every page - Region,
    # Channel, Merchant. The cost of the relationship is a visible defect on four
    # pages; the benefit is cross-filtering one table that already carries its own
    # Merchant, Region and Severity columns. The relationship loses.
]


def m_partition(table: str) -> list[str]:
    """Power Query for one gold CSV. Types are set explicitly, never inferred.

    The "en-US" culture argument on Table.TransformColumnTypes is load-bearing,
    not decoration. The model culture is en-ZA, which uses a COMMA as the decimal
    separator, while the CSVs are written with a period. Without an explicit
    culture, Power Query parses decimals against the model culture and every
    decimal column silently arrives empty - integers survive, so the failure
    looks like "some measures are blank" rather than like a parsing error, and
    Total Sales, Average Resolution Hours and Average Health Score all come back
    BLANK while Total Transactions and Total Tickets look perfectly fine.
    """
    spec = MODEL[table]
    cols = spec["cols"]
    extra = spec.get("extraColumns", {})
    declared = {c: t for c, t in cols.items() if c not in extra}

    transforms = ", ".join(
        f'{{"{c}", {"Int64.Type" if TYPES[t][0] == "int64" else "type number" if TYPES[t][0] == "double" else "type date" if TYPES[t][0] == "dateTime" else "type text"}}}'
        for c, t in declared.items())
    keep = ", ".join(f'"{c}"' for c in cols)

    steps = [
        "let",
        f'    Source = Csv.Document(File.Contents(GoldFolder & "\\{table}.csv"), '
        "[Delimiter=\",\", Encoding=65001, QuoteStyle=QuoteStyle.Csv]),",
        "    Promoted = Table.PromoteHeaders(Source, [PromoteAllScalars=true]),",
        f'    Typed = Table.TransformColumnTypes(Promoted, {{{transforms}}}, "en-US"),',
    ]
    last = "Typed"
    for i, (name, (expr, m_type)) in enumerate(extra.items()):
        step = f"Added{i}"
        steps.append(f'    {step} = Table.AddColumn({last}, "{name}", '
                     f"each {expr}, {m_type}),")
        last = step
    steps += [
        f"    Selected = Table.SelectColumns({last}, {{{keep}}})",
        "in",
        "    Selected",
    ]
    return steps


def summarize_for(spec: dict, col: str) -> str:
    if col in set(spec.get("sum", [])):
        return "sum"
    if col in set(spec.get("avg", [])):
        return "average"
    return "none"


def table_tmdl(name: str) -> str:
    spec = MODEL[name]
    hidden = set(spec.get("hidden", []))
    sort_by = spec.get("sortBy", {})
    lines = [f"table {name}", f"{T}lineageTag: {guid('table', name)}"]
    if spec.get("dataCategory"):
        lines.append(f"{T}dataCategory: {spec['dataCategory']}")
    lines.append("")

    for col, kind in spec["cols"].items():
        dtype, fmt = TYPES[kind]
        lines.append(f"{T}column {col}")
        lines.append(f"{T*2}dataType: {dtype}")
        if col == spec.get("key"):
            lines.append(f"{T*2}isKey")
        if col in hidden:
            lines.append(f"{T*2}isHidden")
        if fmt:
            lines.append(f"{T*2}formatString: {fmt}")
        lines.append(f"{T*2}lineageTag: {guid('col', name, col)}")
        lines.append(f"{T*2}summarizeBy: {summarize_for(spec, col)}")
        lines.append(f"{T*2}sourceColumn: {col}")
        if name == "DimMerchant" and col == "Region":
            lines.append(f"{T*2}dataCategory: StateOrProvince")
        if name == "DimMerchant" and col == "Country":
            lines.append(f"{T*2}dataCategory: Country")
        if col in sort_by:
            lines.append(f"{T*2}sortByColumn: {sort_by[col]}")
        lines.append("")
        lines.append(f"{T*2}annotation SummarizationSetBy = User")
        lines.append("")

    lines.append(f"{T}partition {name} = m")
    lines.append(f"{T*2}mode: import")
    lines.append(f"{T*2}source =")
    for ln in m_partition(name):
        lines.append(f"{T*4}{ln}")
    lines.append("")
    lines.append(f"{T}annotation PBI_ResultType = Table")
    lines.append("")
    return "\n".join(lines)


def measures_tmdl() -> str:
    """The measure table: a hidden, single-row table that holds every measure.

    A dedicated measure table keeps measures out of the fact tables, so the
    field list reads as business concepts rather than as storage.
    """
    dax = (ROOT / "powerbi" / "dax" / "measures.dax").read_text(encoding="utf8")
    measures = parse_dax(dax)

    lines = ["table _Measures",
             f"{T}lineageTag: {guid('table', '_Measures')}",
             ""]
    for name, expr, fmt, folder, desc in measures:
        lines.append(f"{T}measure '{name}' =")
        for ln in expr.splitlines():
            lines.append(f"{T*3}{ln}" if ln.strip() else "")
        if fmt:
            lines.append(f"{T*2}formatString: {fmt}")
        lines.append(f"{T*2}lineageTag: {guid('measure', name)}")
        if folder:
            lines.append(f"{T*2}displayFolder: {folder}")
        if desc:
            lines.append(f"{T*2}description: {desc}")
        lines.append("")
        lines.append(f"{T*2}annotation PBI_FormatHint = {{\"isGeneralNumber\":true}}"
                     if not fmt else f"{T*2}annotation PBI_FormatHint = {{}}")
        lines.append("")

    # The single hidden column exists only to give the table a partition;
    # it is never used and never visible.
    lines += [
        f"{T}column _placeholder",
        f"{T*2}isHidden",
        f"{T*2}dataType: string",
        f"{T*2}lineageTag: {guid('col', '_Measures', '_placeholder')}",
        f"{T*2}summarizeBy: none",
        f"{T*2}sourceColumn: _placeholder",
        "",
        f"{T}partition _Measures = m",
        f"{T*2}mode: import",
        f"{T*2}source =",
        f"{T*4}let",
        f'{T*4}    Source = #table({{"_placeholder"}}, {{{{""}}}})',
        f"{T*4}in",
        f"{T*4}    Source",
        "",
        f"{T}annotation PBI_ResultType = Table",
        "",
    ]
    return "\n".join(lines)


FORMATS = {
    "Total Sales": '"R"#,0;("R"#,0)', "Sales Target": '"R"#,0',
    "Sales Previous Month": '"R"#,0', "Sales Latest Month": '"R"#,0',
    "Last Month With Sales": "yyyy-mm-dd", "Sales MoM Change": '"R"#,0;-"R"#,0',
    "Sales Previous Period": '"R"#,0', "Sales YTD": '"R"#,0',
    "Sales Rolling 3 Months": '"R"#,0',
    "Sales Prior 3 Month Average": '"R"#,0',
    "Voucher Value Sold": '"R"#,0', "Unredeemed Voucher Value": '"R"#,0',
    "Forecast Next 30 Days": '"R"#,0',
    "Average Basket Value": '"R"#,0.00',
    "Total Transactions": "#,0", "Vouchers Sold": "#,0",
    "Vouchers Redeemed": "#,0", "Total Tickets": "#,0", "SLA Breaches": "#,0",
    "Open Tickets": "#,0", "Delayed Redemptions": "#,0",
    "Redemptions by Redemption Date": "#,0", "Merchant Rank": "0",
    "Merchant Rank by Transactions": "0", "Merchants At Risk": "0",
    "Merchants Needing Attention": "0", "High Severity Anomalies": "0",
    "Redemption Rate %": "0.0%", "SLA Breach %": "0.0%",
    "SLA Attainment %": "0.0%", "Delayed Redemption %": "0.0%",
    "Target Attainment %": "0.0%", "Open Ticket %": "0.0%",
    "Sales Share of Total %": "0.0%", "Cumulative Sales Share %": "0.0%",
    "Top 5 Merchant Share %": "0.0%",
    "Redemption Rate Previous Month": "0.0%",
    "Sales MoM %": "+0.0%;-0.0%;0.0%",
    "Sales Momentum %": "+0.0%;-0.0%;0.0%",
    "Redemption Rate MoM Change": "+0.0%;-0.0%;0.0%",
    "Forecast vs Last 30 Days %": "+0.0%;-0.0%;0.0%",
    "Average Resolution Hours": '0.0"h"',
    "Average Resolution Hours (Closed)": '0.0"h"',
    "Resolution vs SLA Target": '+0.0"h";-0.0"h"',
    "Average Days To Redeem": "0.00", "Median Days To Redeem": "0.00",
    "Tickets per 1k Transactions": "0.00",
    "Average Health Score": "0.0", "Avg PCA 1": "0.00", "Avg PCA 2": "0.00",
    "SLA Target Hours": '0"h"',
    "Forecast Sales Value": '"R"#,0', "Forecast Lower Bound": '"R"#,0',
    "Forecast Upper Bound": '"R"#,0',
    "Tickets MoM Change": "+#,0;-#,0;0", "Ticket Surge Flag": "0",
}

FOLDERS = [
    ("Sales", ["Total Sales", "Total Transactions", "Average Basket Value",
               "Sales Target", "Target Attainment %"]),
    ("Sales\\Period comparison", ["Sales Previous Month", "Sales MoM Change",
        "Sales MoM %", "Sales Previous Period", "Sales YTD",
        "Sales Rolling 3 Months", "Sales Prior 3 Month Average",
        "Sales Momentum %"]),
    ("Sales\\Contribution", ["Sales Share of Total %", "Merchant Rank",
        "Merchant Rank by Transactions", "Cumulative Sales Share %",
        "Top 5 Merchant Share %"]),
    ("Redemption", ["Vouchers Sold", "Vouchers Redeemed", "Redemption Rate %",
        "Voucher Value Sold", "Unredeemed Voucher Value",
        "Average Days To Redeem", "Median Days To Redeem",
        "Delayed Redemptions", "Delayed Redemption %",
        "Redemptions by Redemption Date", "Redemption Rate Previous Month",
        "Redemption Rate MoM Change"]),
    ("Operations", ["Total Tickets", "Average Resolution Hours",
        "Average Resolution Hours (Closed)", "SLA Breaches", "SLA Breach %",
        "SLA Attainment %", "Open Tickets", "Open Ticket %",
        "Tickets per 1k Transactions", "SLA Target Hours",
        "Resolution vs SLA Target", "Tickets MoM Change", "Ticket Surge Flag"]),
    ("Intelligence", ["Average Health Score", "Merchants At Risk",
        "Forecast Next 30 Days", "Forecast vs Last 30 Days %",
        "Forecast Sales Value", "Forecast Lower Bound", "Forecast Upper Bound",
        "Avg PCA 1", "Avg PCA 2",
        "High Severity Anomalies", "Merchants Needing Attention"]),
    ("Narrative", ["Selected Period Label", "Sales Trend Narrative"]),
]


def folder_for(name: str) -> str:
    for folder, members in FOLDERS:
        if name in members:
            return folder
    return ""


def parse_dax(text: str) -> list[tuple[str, str, str, str, str]]:
    """Read measures.dax into (name, expression, format, folder, description).

    A measure starts at a line matching `Name =` at column 0 and runs until the
    next such line. Comment lines directly above it become the description, so
    the reasoning in the .dax file reaches the model rather than being lost.
    """
    measures, pending_comment = [], []
    current_name, current_body = None, []

    def flush():
        if current_name is None:
            return
        expr = "\n".join(current_body).strip("\n")
        # Trailing comment lines belong to the NEXT measure, not this one.
        body_lines = expr.splitlines()
        while body_lines and body_lines[-1].strip().startswith("//"):
            body_lines.pop()
        while body_lines and not body_lines[-1].strip():
            body_lines.pop()
        measures.append((current_name, "\n".join(body_lines),
                         FORMATS.get(current_name, ""), folder_for(current_name),
                         " ".join(pending_comment).strip()))

    # DAX keywords that also appear at column 0 inside a measure body. Without
    # excluding these, `VAR Prior = ...` reads as the start of a new measure
    # and every multi-statement measure gets chopped in half.
    body_keywords = ("VAR ", "RETURN", "EVALUATE", "DEFINE", "MEASURE ")

    for line in text.splitlines():
        stripped = line.strip()
        head = line.split(" =")[0] if " =" in line else ""
        is_header = (
            line and not line[0].isspace() and " =" in line
            and not stripped.startswith("//")
            and not stripped.startswith(body_keywords)
            and head.replace(" ", "").replace("%", "").replace("(", "")
                    .replace(")", "").isalnum())
        if is_header:
            flush()
            current_name = head.strip()
            rest = line.split(" =", 1)[1]
            current_body = [rest.lstrip()] if rest.strip() else []
            pending_comment = []
        elif current_name is not None:
            if stripped.startswith("//") and not current_body:
                continue
            current_body.append(line)
    flush()
    # Descriptions come from the comment lines inside each body instead - keep
    # it simple and skip empty measures produced by the section banners.
    return [m for m in measures if m[1].strip()]


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf8")


def main() -> None:
    if SM.exists():
        shutil.rmtree(SM)
    report_dir = PBI / f"{NAME}.Report"

    # --------------------------------------------------------- .platform ----
    for folder, ftype in ((SM, "SemanticModel"), (report_dir, "Report")):
        write(folder / ".platform", json.dumps({
            "$schema": "https://developer.microsoft.com/json-schemas/fabric/gitIntegration/platformProperties/2.0.0/schema.json",
            "metadata": {"type": ftype, "displayName": NAME},
            "config": {"version": "2.0", "logicalId": guid(ftype, NAME)},
        }, indent=2))

    write(SM / "definition.pbism", json.dumps({
        "version": "4.2",
        "settings": {"qnaEnabled": True},
    }, indent=2))

    # --------------------------------------------------------- database -----
    write(SM / "definition" / "database.tmdl",
          "database\n"
          f"{T}compatibilityLevel: 1567\n")

    # ---------------------------------------------------------- model -------
    tables = list(MODEL) + ["_Measures"]
    model = [
        "model Model",
        f"{T}culture: en-ZA",
        f"{T}defaultPowerBIDataSourceVersion: powerBI_V3",
        f"{T}sourceQueryCulture: en-ZA",
        # Implicit measures let a user drag a raw column onto a chart and get a
        # silent SUM. Every number in this report goes through a named measure.
        f"{T}discourageImplicitMeasures",
        "",
        f"{T}annotation PBI_QueryOrder = {json.dumps(tables)}",
        "",
        f"{T}annotation __PBI_TimeIntelligenceEnabled = 0",
        "",
    ]
    for t in tables:
        model.append(f"ref table {t}")
    model.append("")
    model.append("ref cultureInfo en-ZA")
    model.append("")
    write(SM / "definition" / "model.tmdl", "\n".join(model))

    # ------------------------------------------------------ expressions -----
    write(SM / "definition" / "expressions.tmdl", "\n".join([
        "/// Folder holding the gold-layer CSVs. Point this at the repo's",
        "/// data/gold folder to open the model without a Fabric capacity.",
        "/// To move to Fabric, replace the partitions' Csv.Document source",
        "/// with Lakehouse.Contents(...) - the column names, types and every",
        "/// measure stay exactly as they are.",
        "expression GoldFolder = \"..\\..\\..\\data\\gold\" meta "
        "[IsParameterQuery=true, Type=\"Text\", IsParameterQueryRequired=true]",
        f"{T}lineageTag: {guid('expr', 'GoldFolder')}",
        "",
        f"{T}annotation PBI_NavigationStepName = Navigation",
        "",
        f"{T}annotation PBI_ResultType = Text",
        "",
    ]))

    # ---------------------------------------------------------- tables ------
    for name in MODEL:
        write(SM / "definition" / "tables" / f"{name}.tmdl", table_tmdl(name))
    write(SM / "definition" / "tables" / "_Measures.tmdl", measures_tmdl())

    # --------------------------------------------------- relationships ------
    rel = []
    for f_tab, f_col, t_tab, t_col, active, cross in RELATIONSHIPS:
        rid = guid("rel", f_tab, f_col, t_tab, t_col)
        rel.append(f"relationship {rid}")
        if not active:
            rel.append(f"{T}isActive: false")
        rel.append(f"{T}fromColumn: {f_tab}.{f_col}")
        rel.append(f"{T}toColumn: {t_tab}.{t_col}")
        rel.append("")
    write(SM / "definition" / "relationships.tmdl", "\n".join(rel))

    # --------------------------------------------------------- culture ------
    write(SM / "definition" / "cultures" / "en-ZA.tmdl", "\n".join([
        "cultureInfo en-ZA",
        "",
        f"{T}linguisticMetadata =",
        f"{T*3}" + json.dumps({
            "Version": "1.0.0", "Language": "en-ZA",
            "DynamicImprovement": "HighConfidence",
        }, indent=2).replace("\n", f"\n{T*3}"),
        f"{T*2}contentType: json",
        "",
    ]))

    # ------------------------------------------------------------- pbip -----
    write(PBI / f"{NAME}.pbip", json.dumps({
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/pbip/definitionProperties/1.0.0/schema.json",
        "version": "1.0",
        "artifacts": [{"report": {"path": f"{NAME}.Report"}}],
        "settings": {"enableAutoRecovery": True},
    }, indent=2))

    n_measures = len(parse_dax((ROOT / "powerbi" / "dax" / "measures.dax")
                               .read_text(encoding="utf8")))
    print(f"Semantic model written to powerbi/{NAME}.SemanticModel")
    print(f"  {len(MODEL)} tables, {len(RELATIONSHIPS)} relationships "
          f"({sum(1 for r in RELATIONSHIPS if not r[4])} inactive), "
          f"{n_measures} measures")

    # Every table in MODEL must exist in gold, or the model will not load.
    missing = [t for t in MODEL if not (GOLD / f"{t}.csv").exists()]
    if missing:
        raise SystemExit(f"Gold tables missing for: {', '.join(missing)}")

    # And every declared column must exist in the file.
    for t, spec in MODEL.items():
        actual = set(pd.read_csv(GOLD / f"{t}.csv", nrows=1).columns)
        # Columns added in Power Query are not expected in the CSV.
        declared = set(spec["cols"]) - set(spec.get("extraColumns", {}))
        if declared - actual:
            raise SystemExit(f"{t}: declared columns not in gold CSV: "
                             f"{sorted(declared - actual)}")
        if actual - declared:
            print(f"  note: {t} has un-modelled columns {sorted(actual - declared)}")
    print("  all declared columns verified against the gold CSVs")


if __name__ == "__main__":
    main()
