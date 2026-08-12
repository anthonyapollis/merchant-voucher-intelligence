"""
29_pbit_mark_origins.py — mark every table in the semantic model with its origin.

A reviewer opening the Data pane sees 15 tables and has no way to tell which five came from
the supplied README and which were added. This makes that visible IN THE MODEL, three ways:

  1. Table descriptions  — Power BI shows these on hover in the Data pane and in Model view
  2. A prefix in the description, e.g. [README] / [BRIEF] / [ML] / [ADDED]
  3. A _Model Guide table — a small reference table listed alongside the data, so the
     justification is one click away rather than in a separate document

Renaming the tables themselves was the obvious alternative and was rejected: every visual,
measure and relationship binds to the table NAME, so a prefix would silently break the
report. Descriptions carry the same information at zero risk.
"""
import csv
import json
import shutil
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PBIT = ROOT / "powerbi" / "MerchantVoucherIntelligence.pbit"
GOLD = ROOT / "data" / "gold"

# tier -> (badge, one-line meaning)
TIER = {
    "readme": ("CSV", "Named in the README AND supplied as a CSV file"),
    "built": ("BUILT", "Named in the README but NOT supplied — the README requires it to "
                       "be created"),
    "brief": ("BRIEF", "Not in the README, but required by a stated report requirement"),
    "ml": ("ML", "Output of the optional AI extension the brief invites"),
    "added": ("ADDED", "Beyond the brief — added on judgement and labelled as such"),
    "system": ("SYSTEM", "Container only, holds no data"),
}

ORIGIN = {
    # ---- the five the README actually names
    "DimDate": ("built", "README: 'DimDate: candidate should create a proper date table'. "
                         "NO SOURCE CSV EXISTS — the drop supplies four files and the "
                         "README's model lists five tables; this is the fifth. Generated to "
                         "full calendar boundaries, contiguous 365 days: time intelligence "
                         "returns wrong answers, not errors, on a gapped date table."),
    "DimMerchant": ("readme", "README: DimMerchant from MerchantReference.csv. The single "
                              "filter path for every fact."),
    "FactMerchantSales": ("readme", "README: FactMerchantSales from MerchantSales.csv. Grain "
                                    "Date x Merchant x VoucherType, 26,500 rows."),
    "FactVoucherRedemptions": ("readme", "README: FactVoucherRedemptions from "
                                         "VoucherRedemptions.csv. One row per voucher, "
                                         "120,969 rows, with role-playing sold/redeemed "
                                         "dates."),
    "FactSupportTickets": ("readme", "README: FactSupportTickets from SupportTickets.csv. "
                                     "One row per ticket, 1,363 rows."),
    # ---- required by the brief's own report requirements
    "DimVoucherType": ("brief", "Brief section 5 requires voucher type performance. Shared by "
                                "BOTH the sales and redemption facts - a conformed dimension."),
    "DimPriority": ("brief", "Brief sections 4-5 require ticket priority and an SLA breach "
                             "indicator. Carries the SLA target alongside observed "
                             "resolution times."),
    "DimTicketType": ("brief", "Brief section 5 requires ticket analysis. Adds category and "
                               "impact area, which do not exist in the source."),
    # ---- optional AI extension
    "DimMerchantSegment": ("ml", "K-Means merchant segmentation output. Supports the brief's "
                                 "optional AI extension."),
    "FactAnomaly": ("ml", "Isolation Forest anomaly detections, written back to gold so "
                          "Power BI reads predictions as ordinary columns."),
    "FactSalesForecast": ("ml", "Holt-Winters 30-day forecast with confidence intervals. "
                                "Backtest MAPE 4.69%."),
    "InsightNarrative": ("ml", "Generated plain-English merchant narratives for the "
                               "Insights page."),
    # ---- container
    "_Measures": ("system", "Empty table holding all 70 DAX measures. Keeps measures out of "
                            "any fact table's lifecycle and at the top of the field list."),
    # ---- added on judgement
    "MerchantValueRisk": ("added", "NOT REQUESTED. Merchant lifetime value, attrition risk "
                                   "and fraud-adjacent signals. Modelled at MERCHANT level "
                                   "because no customer identifier exists anywhere in the "
                                   "four source files."),
    "RecControls": ("added", "NOT REQUESTED. Reconciliation control results, including the "
                             "R43.5m population variance recorded as EXPECTED so nobody "
                             "escalates it as a break."),
}

# ---------------------------------------------------------------- model guide table
guide = GOLD / "ModelGuide.csv"
with open(guide, "w", newline="", encoding="utf-8") as fh:
    w = csv.writer(fh)
    w.writerow(["Sort", "Origin", "Table", "Rows", "Why this table exists"])
    ROWS = {"DimDate": 365, "DimMerchant": 25, "FactMerchantSales": 26500,
            "FactVoucherRedemptions": 120969, "FactSupportTickets": 1363,
            "DimVoucherType": 5, "DimPriority": 4, "DimTicketType": 6,
            "DimMerchantSegment": 25, "FactAnomaly": 8, "FactSalesForecast": 30,
            "InsightNarrative": 25, "_Measures": 0, "MerchantValueRisk": 25,
            "RecControls": 6}
    order = {"readme": 1, "built": 2, "brief": 3, "ml": 4, "added": 5, "system": 6}
    for name, (tier, why) in sorted(ORIGIN.items(),
                                    key=lambda kv: (order[kv[1][0]], kv[0])):
        w.writerow([order[tier], TIER[tier][0], name, ROWS.get(name, 0), why])
print(f"  wrote {guide.name}  ({len(ORIGIN)} rows)")

# ---------------------------------------------------------------- patch the template
z = zipfile.ZipFile(PBIT)
members = {n: z.read(n) for n in z.namelist()}
order_names = z.namelist()
z.close()

model = json.loads(members["DataModelSchema"].decode("utf-16-le"))
mdl = model["model"]

marked = 0
for t in mdl["tables"]:
    nm = t["name"]
    if nm not in ORIGIN:
        continue
    tier, why = ORIGIN[nm]
    badge, meaning = TIER[tier]
    t["description"] = f"[{badge}]  {why}   —   {meaning}."
    marked += 1
print(f"  described {marked} tables")

if not any(t["name"] == "ModelGuide" for t in mdl["tables"]):
    mdl["tables"].append({
        "name": "ModelGuide",
        "description": "[SYSTEM]  Reference: where every table in this model came from and "
                       "why. Five tables are named in the supplied README; the rest are "
                       "justified individually here.",
        "columns": [
            {"name": "Sort", "dataType": "int64", "sourceColumn": "Sort", "isHidden": True},
            {"name": "Origin", "dataType": "string", "sourceColumn": "Origin",
             "sortByColumn": "Sort"},
            {"name": "Table", "dataType": "string", "sourceColumn": "Table"},
            {"name": "Rows", "dataType": "int64", "sourceColumn": "Rows"},
            {"name": "Why this table exists", "dataType": "string",
             "sourceColumn": "Why this table exists"},
        ],
        "partitions": [{"name": "ModelGuide", "mode": "import", "source": {"type": "m",
            "expression": [
                "let",
                '    Source = Csv.Document(File.Contents(GoldFolder & "\\ModelGuide.csv"), '
                '[Delimiter=",", Encoding=65001, QuoteStyle=QuoteStyle.Csv]),',
                "    Promoted = Table.PromoteHeaders(Source, [PromoteAllScalars=true]),",
                '    Typed = Table.TransformColumnTypes(Promoted, {{"Sort", Int64.Type}, '
                '{"Origin", type text}, {"Table", type text}, {"Rows", Int64.Type}, '
                '{"Why this table exists", type text}}, "en-US")',
                "in",
                "    Typed"]}}],
    })
    print("  added ModelGuide table")

members["DataModelSchema"] = json.dumps(model, ensure_ascii=False).encode("utf-16-le")

tmp = PBIT.with_suffix(".tmp")
with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zo:
    for n in order_names:
        zo.writestr(n, members[n])
tmp.replace(PBIT)

zc = zipfile.ZipFile(PBIT)
for part in ("Report/Layout", "DataModelSchema"):
    if zc.read(part)[:2] in (b"\xff\xfe", b"\xfe\xff", b"\xef\xbb"):
        raise SystemExit(f"ENCODING ERROR: {part} has a BOM — template will not open")
chk = json.loads(zc.read("DataModelSchema").decode("utf-16-le"))
zc.close()

shutil.copy2(PBIT, ROOT / "MerchantVoucherIntelligence_PowerBI" /
             "MerchantVoucherIntelligence.pbit")

from collections import Counter
c = Counter(v[0] for v in ORIGIN.values())
print(f"\n  {len(chk['model']['tables'])} tables in the model")
for k in ("readme", "built", "brief", "ml", "added", "system"):
    names = sorted(n for n, v in ORIGIN.items() if v[0] == k)
    print(f"    [{TIER[k][0]:<6}] {c[k]}  {', '.join(names)}")
print(f"\n  encoding verified · {PBIT.stat().st_size/1024:.0f} KB")
print("  Hover any table in the Data pane to see its origin, or open ModelGuide.")
