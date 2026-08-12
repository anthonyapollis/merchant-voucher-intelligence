"""
19_pbit_add_pages.py — add three pages to the Power BI template.

  Business Answers          the five questions from section 6 of the brief, answered on
                            the page rather than in an appendix
  Reconciliation & Controls the financial control checks, including the population control
                            that explains the R43.5m variance rather than hiding it
  Merchant Value & Risk     merchant lifetime value, attrition risk, fraud-adjacent signals

Two new tables are added to the model to support them (RecControls, MerchantValueRisk),
loaded from the gold CSVs through the existing GoldFolder parameter, plus the measures the
new visuals need.

Everything is written into the .pbit — the file that actually opens without the PBIR
preview flag.
"""
import json
import shutil
import zipfile
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
PBIT = ROOT / "powerbi" / "MerchantVoucherIntelligence.pbit"
GOLD = ROOT / "data" / "gold"

NAVY, TEAL, AMBER, RED, PURPLE, GREY = ("#12305B", "#0E8B8B", "#E8A317", "#C0392B",
                                        "#7B4B94", "#5A6672")

# ---------------------------------------------------------------- 1. export the new marts
con = duckdb.connect(str(ROOT / "data" / "mvi.duckdb"))
for tbl, out in [("mart_reconciliation", "RecControls"),
                 ("mart_merchant_value_risk", "MerchantValueRisk")]:
    con.execute(f"COPY main_marts.{tbl} TO '{(GOLD / (out + '.csv')).as_posix()}' "
                f"(HEADER, DELIMITER ',')")
    n = con.execute(f"select count(*) from main_marts.{tbl}").fetchone()[0]
    print(f"  exported {out}.csv  ({n} rows)")
ans = con.execute("""
    select control_family, control_name, expected_value, actual_value, variance,
           control_status from main_marts.mart_reconciliation order by control_order
""").df()
vr = con.execute("""
    select merchant_name, region, round(annualised_run_rate,0) rr,
           attrition_risk_score, attrition_risk_band, risk_signal_score, risk_signal_band
    from main_marts.mart_merchant_value_risk order by annualised_run_rate desc limit 5
""").df()
con.close()

# ---------------------------------------------------------------- 2. open the template
z = zipfile.ZipFile(PBIT)
members = {n: z.read(n) for n in z.namelist()}
z.close()

model = json.loads(members["DataModelSchema"].decode("utf-16"))
mdl = model["model"]
existing = {t["name"] for t in mdl["tables"]}


def m_partition(csv_name, cols):
    """Build the M expression, matching the style already used in this model."""
    typed = ", ".join(
        f'{{"{c}", {"Int64.Type" if t == "int" else "type number" if t == "num" else "type text"}}}'
        for c, t in cols)
    return [
        "let",
        f'    Source = Csv.Document(File.Contents(GoldFolder & "\\{csv_name}.csv"), '
        f'[Delimiter=",", Encoding=65001, QuoteStyle=QuoteStyle.Csv]),',
        "    Promoted = Table.PromoteHeaders(Source, [PromoteAllScalars=true]),",
        f"    Typed = Table.TransformColumnTypes(Promoted, {{{typed}}}, \"en-US\")",
        "in",
        "    Typed",
    ]


def add_table(name, cols):
    if name in existing:
        return
    mdl["tables"].append({
        "name": name,
        "columns": [{"name": c,
                     "dataType": {"int": "int64", "num": "double"}.get(t, "string"),
                     "sourceColumn": c} for c, t in cols],
        "partitions": [{"name": name, "mode": "import",
                        "source": {"type": "m", "expression": m_partition(name, cols)}}],
    })
    print(f"  added table {name}")


add_table("RecControls", [
    ("control_order", "int"), ("control_family", "str"), ("control_name", "str"),
    ("expected_value", "num"), ("actual_value", "num"), ("variance", "num"),
    ("variance_pct", "num"), ("control_status", "str"), ("txn_per_voucher", "num"),
    ("rationale", "str")])

add_table("MerchantValueRisk", [
    ("merchant_key", "str"), ("merchant_name", "str"), ("region", "str"),
    ("channel", "str"), ("account_manager", "str"), ("health_score", "num"),
    ("health_band", "str"), ("total_sales", "num"), ("tenure_months", "int"),
    ("avg_monthly_revenue", "num"), ("annualised_run_rate", "num"),
    ("implied_lifetime_value", "num"), ("reversal_tickets", "int"),
    ("reversal_per_1k_txn", "num"), ("same_day_redemption_rate", "num"),
    ("value_outlier_vouchers", "int"), ("retention_score", "num"),
    ("risk_signal_score", "num"), ("attrition_risk_score", "num"),
    ("attrition_risk_band", "str"), ("risk_signal_band", "str"),
    ("value_at_stake_if_lost", "num")])

# ---------------------------------------------------------------- 3. new measures
meas_tbl = next(t for t in mdl["tables"] if t["name"] == "_Measures")
have = {m["name"] for m in meas_tbl["measures"]}
NEW = [
    ("Controls Passing", "COUNTROWS(FILTER(RecControls, RecControls[control_status] IN "
                         "{\"PASS\",\"EXPECTED\"}))", "#,##0"),
    ("Controls Total", "COUNTROWS(RecControls)", "#,##0"),
    ("Control Pass Rate", "DIVIDE([Controls Passing],[Controls Total])", "0.0%"),
    ("Population Variance", "CALCULATE(SUM(RecControls[variance]), "
                            "RecControls[control_family]=\"Population control\")", "R #,##0"),
    ("Transactions per Voucher", "MAX(RecControls[txn_per_voucher])", "0.00"),
    ("Total Lifetime Value", "SUM(MerchantValueRisk[implied_lifetime_value])", "R #,##0"),
    ("Avg Annualised Run Rate", "AVERAGE(MerchantValueRisk[annualised_run_rate])", "R #,##0"),
    ("Value at Stake", "SUM(MerchantValueRisk[value_at_stake_if_lost])", "R #,##0"),
    ("High Attrition Risk Merchants", "COUNTROWS(FILTER(MerchantValueRisk, "
                                      "MerchantValueRisk[attrition_risk_band]=\"High\"))", "#,##0"),
    ("Merchants To Review", "COUNTROWS(FILTER(MerchantValueRisk, "
                            "MerchantValueRisk[risk_signal_band]=\"Review\"))", "#,##0"),
    ("Avg Attrition Risk", "AVERAGE(MerchantValueRisk[attrition_risk_score])", "0.0"),
    ("Reversal Rate per 1k", "AVERAGE(MerchantValueRisk[reversal_per_1k_txn])", "0.00"),
]
for n, expr, fmt in NEW:
    if n not in have:
        meas_tbl["measures"].append({"name": n, "expression": expr, "formatString": fmt})
print(f"  added {sum(1 for n,_,_ in NEW if n not in have)} measures")

# relationship so the new risk table filters with the merchant dimension
rels = mdl.setdefault("relationships", [])
if not any(r.get("fromTable") == "MerchantValueRisk" for r in rels):
    rels.append({"name": "MerchantValueRisk_DimMerchant",
                 "fromTable": "MerchantValueRisk", "fromColumn": "merchant_key",
                 "toTable": "DimMerchant", "toColumn": "MerchantKey",
                 "crossFilteringBehavior": "oneDirection"})
    print("  added relationship MerchantValueRisk -> DimMerchant")

members["DataModelSchema"] = json.dumps(model, ensure_ascii=False).encode("utf-16-le")   # NO BOM — see note at bottom of file

# ---------------------------------------------------------------- 4. page builders
layout = json.loads(members["Report/Layout"].decode("utf-16"))
W, M, G = 1280, 16, 12


def vc(name, vtype, x, y, w, h, cfg_extra=None, z=0):
    cfg = {"name": name, "layouts": [{"id": 0, "position": {"x": x, "y": y, "z": z,
                                                            "width": w, "height": h}}],
           "singleVisual": {"visualType": vtype, "drillFilterOtherVisuals": True}}
    if cfg_extra:
        cfg["singleVisual"].update(cfg_extra)
    return {"x": x, "y": y, "z": z, "width": w, "height": h,
            "config": json.dumps(cfg, separators=(",", ":")), "filters": "[]"}


def textbox(name, x, y, w, h, runs, bg=None):
    paras = []
    for text, size, colour, bold in runs:
        paras.append({"horizontalTextAlignment": "left", "textRuns": [
            {"value": text, "textStyle": {"fontSize": f"{size}pt", "color": colour,
                                          "fontWeight": "bold" if bold else "normal",
                                          "fontFamily": "Segoe UI"}}]})
    objs = {"general": [{"properties": {"paragraphs": paras}}]}
    if bg:
        objs["background"] = [{"properties": {"show": {"expr": {"Literal": {"Value": "true"}}},
                                              "color": {"solid": {"color": {"expr": {"Literal": {
                                                  "Value": f"'{bg}'"}}}}}}}]
    return vc(name, "textbox", x, y, w, h, {"objects": objs})


def card(name, measure, x, y, w, h, label):
    return vc(name, "card", x, y, w, h, {
        "projections": {"Values": [{"queryRef": f"_Measures.{measure}"}]},
        "prototypeQuery": {"Version": 2,
                           "From": [{"Name": "m", "Entity": "_Measures", "Type": 0}],
                           "Select": [{"Measure": {"Expression": {"SourceRef": {"Source": "m"}},
                                                   "Property": measure},
                                       "Name": f"_Measures.{measure}"}]},
        "objects": {"labels": [{"properties": {"fontSize": {"expr": {"Literal": {"Value": "28D"}}}}}],
                    "categoryLabels": [{"properties": {"show": {"expr": {"Literal": {"Value": "true"}}}}}]},
        "vcObjects": {"title": [{"properties": {
            "show": {"expr": {"Literal": {"Value": "true"}}},
            "text": {"expr": {"Literal": {"Value": f"'{label}'"}}},
            "fontSize": {"expr": {"Literal": {"Value": "11D"}}}}}]}})


def table_vis(name, entity, cols, x, y, w, h, title):
    sel, proj = [], []
    for c in cols:
        sel.append({"Column": {"Expression": {"SourceRef": {"Source": "t"}}, "Property": c},
                    "Name": f"{entity}.{c}"})
        proj.append({"queryRef": f"{entity}.{c}"})
    return vc(name, "tableEx", x, y, w, h, {
        "projections": {"Values": proj},
        "prototypeQuery": {"Version": 2,
                           "From": [{"Name": "t", "Entity": entity, "Type": 0}],
                           "Select": sel},
        "vcObjects": {"title": [{"properties": {
            "show": {"expr": {"Literal": {"Value": "true"}}},
            "text": {"expr": {"Literal": {"Value": f"'{title}'"}}},
            "fontSize": {"expr": {"Literal": {"Value": "12D"}}}}}]}})


def bar_vis(name, entity, cat, val, x, y, w, h, title):
    return vc(name, "barChart", x, y, w, h, {
        "projections": {"Category": [{"queryRef": f"{entity}.{cat}"}],
                        "Y": [{"queryRef": f"{entity}.{val}"}]},
        "prototypeQuery": {"Version": 2,
                           "From": [{"Name": "t", "Entity": entity, "Type": 0}],
                           "Select": [
                               {"Column": {"Expression": {"SourceRef": {"Source": "t"}},
                                           "Property": cat}, "Name": f"{entity}.{cat}"},
                               {"Aggregation": {"Expression": {"Column": {
                                   "Expression": {"SourceRef": {"Source": "t"}},
                                   "Property": val}}, "Function": 0},
                                "Name": f"{entity}.{val}"}]},
        "vcObjects": {"title": [{"properties": {
            "show": {"expr": {"Literal": {"Value": "true"}}},
            "text": {"expr": {"Literal": {"Value": f"'{title}'"}}},
            "fontSize": {"expr": {"Literal": {"Value": "12D"}}}}}]}})


def banner(page, title, subtitle):
    return [textbox(f"{page}Band", 0, 0, W, 56,
                    [(f"  {title}", 18, "#FFFFFF", True)], NAVY),
            textbox(f"{page}Sub", W - 640, 16, 620, 30,
                    [(subtitle + "  ", 10, "#D6E5F5", False)])]


sections = layout["sections"]
base_ord = max(s.get("ordinal", 0) for s in sections) + 1
new_pages = []

# ---------------------------------------------------------------- PAGE: Business Answers
vcs = banner("ba", "Business answers", "Section 6 of the brief, answered")
y = 68
QA = [
    ("Q1  Which merchants generate the highest sales value and transaction volume?",
     "Durban Cash Hub leads on BOTH — R5,776,119 (8.8% of portfolio) and 45,371 transactions. "
     "The two rankings agreeing is not guaranteed: a merchant can lead on value while trailing "
     "on volume if its basket is larger, so both are reported. Concentration matters more than "
     "the leader — the top 5 carry 35.4% of revenue and 15 of 25 merchants make up 80%."),
    ("Q2  Which voucher type has the highest redemption rate?",
     "Airtime at 92.8%; Gaming lowest at 76.0% — a 16.9 percentage point spread. The value-based "
     "rate is almost identical to the volume-based rate within each type, and time-to-redeem is "
     "flat across types (3.5-3.7 days). So the difference is WHETHER customers redeem, not how "
     "quickly. Gaming's 24% non-redemption is the largest block of the R3.5m outstanding liability."),
    ("Q3  Which region shows declining sales or transaction behaviour?",
     "Eastern Cape, on four independent signals: the only region that peaked before July (May); "
     "9.8% below its own peak while every other region is AT its peak; the flattest trend slope "
     "(+2.0% of average monthly sales vs +4.4% to +8.5%); and a 12.2% June fall against +1.4% to "
     "+3.8% elsewhere. Three of the five Critical/Watch merchants sit there."),
    ("Q4  Are ticket volumes, priority or resolution times associated with weaker performance?",
     "NOT as a portfolio rule — and the obvious analysis says otherwise. Tickets per 1k transactions "
     "correlates with target attainment at r = -0.56, but that is confounded: the ratio is "
     "size-dependent (r = -0.83 vs log sales). Controlling for size the partial correlation collapses "
     "to -0.20, and SLA breach rate shows no association at all. The real signal is event-level: "
     "Durban Cash Hub +780% tickets while sales GREW 8.2%; Umhlanga +693% while sales FELL 42.5%."),
    ("Q5  Which merchants should management focus on first, and why?",
     "Ranked by revenue at risk, not by severity of decline. 1. Umhlanga Value Mart (-42.5% vs prior "
     "3-month avg, R571,518 at risk, tickets +693%). 2. Table Bay Express (R354,163). 3. Pretoria "
     "PayPoint (R154,045). A 42.5% collapse at a small merchant costs less than a 6% slide at a large "
     "one — ranking on percentage change alone sends the account team to the wrong door."),
]
for i, (q, a) in enumerate(QA):
    vcs.append(textbox(f"baQ{i}", M, y, W - 2 * M, 34, [(q, 12, "#FFFFFF", True)], TEAL))
    vcs.append(textbox(f"baA{i}", M, y + 34, W - 2 * M, 92, [(a, 10.5, "#12203A", False)],
                       "#FFFFFF"))
    y += 134
new_pages.append(("BusinessAnswers", "Business Answers", vcs, y + M))

# ---------------------------------------------------------------- PAGE: Reconciliation
vcs = banner("rc", "Reconciliation & controls",
             "Controls that pass matter as much as controls that fail")
y = 68
cw = (W - 2 * M - 3 * G) // 4
for i, (meas, lbl) in enumerate([("Controls Total", "Controls run"),
                                 ("Control Pass Rate", "Pass rate"),
                                 ("Population Variance", "Explained variance"),
                                 ("Transactions per Voucher", "Txn per voucher")]):
    vcs.append(card(f"rcK{i}", meas, M + i * (cw + G), y, cw, 104, lbl))
y += 104 + G
vcs.append(table_vis("rcTable", "RecControls",
                     ["control_family", "control_name", "expected_value", "actual_value",
                      "variance", "control_status"], M, y, W - 2 * M, 250,
                     "Financial control checks"))
y += 250 + G
vcs.append(textbox("rcNote", M, y, W - 2 * M, 150, [
    ("The population control is the one that matters.  ", 12, NAVY, True),
    ("fct_merchant_sales totals R65,521,299 across 510,127 transactions; "
     "fct_voucher_redemptions totals R22,019,853 across 120,969 vouchers — a R43,501,446 "
     "difference. That is EXPECTED, not a break. MerchantSales is a daily aggregate of ALL "
     "transactions; VoucherRedemptions is a voucher-level extract covering roughly 1 in 4.2 of "
     "them. They describe different populations and must never be forced to tie.\n\n"
     "Recording it as an explained variance is what stops someone escalating a R43.5m "
     "reconciliation break — or dividing one by the other and reporting a value-based redemption "
     "rate against the wrong denominator.", 10.5, "#12203A", False)], "#FEF8EC"))
y += 150
new_pages.append(("Reconciliation", "Reconciliation & Controls", vcs, y + M))

# ---------------------------------------------------------------- PAGE: Value & Risk
vcs = banner("vr", "Merchant value & risk",
             "Lifetime value, attrition risk and fraud-adjacent signals")
y = 68
for i, (meas, lbl) in enumerate([("Total Lifetime Value", "Implied lifetime value"),
                                 ("Value at Stake", "Annualised value at stake"),
                                 ("High Attrition Risk Merchants", "High attrition risk"),
                                 ("Merchants To Review", "Risk signals to review")]):
    vcs.append(card(f"vrK{i}", meas, M + i * (cw + G), y, cw, 104, lbl))
y += 104 + G
half = (W - 2 * M - G) // 2
vcs.append(bar_vis("vrBar", "MerchantValueRisk", "merchant_name", "annualised_run_rate",
                   M, y, half, 260, "Annualised run rate by merchant"))
vcs.append(bar_vis("vrRisk", "MerchantValueRisk", "merchant_name", "attrition_risk_score",
                   M + half + G, y, W - M - (M + half + G), 260, "Attrition risk score"))
y += 260 + G
vcs.append(table_vis("vrTable", "MerchantValueRisk",
                     ["merchant_name", "region", "annualised_run_rate", "tenure_months",
                      "implied_lifetime_value", "attrition_risk_score", "attrition_risk_band",
                      "reversal_per_1k_txn", "risk_signal_score", "risk_signal_band"],
                     M, y, W - 2 * M, 250, "Merchant value and risk register"))
y += 250 + G
vcs.append(textbox("vrNote", M, y, W - 2 * M, 120, [
    ("Merchant-level, not customer-level — and that is a data limit, not a choice.  ",
     12, NAVY, True),
    ("Customer lifetime value and customer churn were asked for. There is no customer identifier "
     "anywhere in the four source files, so they cannot be built and it would be dishonest to "
     "present something that looks like them. The merchant is the customer of the voucher business, "
     "so the defensible equivalent is modelled here.\n\n"
     "Fraud controls follow the same rule. Supported: reversal rate, redemption velocity, liability "
     "concentration, behavioural anomaly. Tested and NIL: voucher value outliers (zero beyond 3 SD — "
     "the control runs and correctly returns zero). Not supported: duplicate redemption, geographic "
     "anomaly, PIN misuse — each needs telemetry this dataset does not carry.",
     10.5, "#12203A", False)], "#F0F9F9"))
y += 120
new_pages.append(("ValueRisk", "Merchant Value & Risk", vcs, y + M))

# ---------------------------------------------------------------- 5. attach pages
for i, (name, disp, vcs, height) in enumerate(new_pages):
    sections = [s for s in sections if s.get("name") != name]
    sections.append({
        "id": 900 + i, "name": name, "displayName": disp, "filters": "[]",
        "ordinal": base_ord + i, "visualContainers": vcs,
        "config": json.dumps({"objects": {"background": [{"properties": {
            "color": {"solid": {"color": {"expr": {"Literal": {"Value": "'#F2F5FA'"}}}}},
            "transparency": {"expr": {"Literal": {"Value": "0D"}}}}}]}},
            separators=(",", ":")),
        "displayOption": 1, "width": W, "height": max(height, 720),
    })
    print(f"  added page '{disp}' ({len(vcs)} visuals, {max(height,720)}px)")

layout["sections"] = sorted(sections, key=lambda s: s.get("ordinal", 0))
members["Report/Layout"] = json.dumps(layout, separators=(",", ":")).encode("utf-16-le")   # NO BOM — see note at bottom of file

# ---------------------------------------------------------------- 6. repack
tmp = PBIT.with_suffix(".tmp")
with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zo:
    for n in ["Version"] + [k for k in members if k != "Version"]:
        zo.writestr(n, members[n])
tmp.replace(PBIT)
shutil.copy2(PBIT, ROOT / "MerchantVoucherIntelligence_PowerBI" /
             "MerchantVoucherIntelligence.pbit")

zc = zipfile.ZipFile(PBIT)
chk = json.loads(zc.read("Report/Layout").decode("utf-16"))
mc = json.loads(zc.read("DataModelSchema").decode("utf-16"))
zc.close()
print(f"\n  {PBIT.name}  {PBIT.stat().st_size/1024:.0f} KB")
print(f"  pages  : {len(chk['sections'])}  -> " +
      ", ".join(s.get("displayName", "?") for s in chk["sections"]))
print(f"  tables : {len(mc['model']['tables'])}")
print(f"  measures: {len(next(t for t in mc['model']['tables'] if t['name']=='_Measures')['measures'])}")

# ---------------------------------------------------------------- 7. encoding guard
# The one thing that silently breaks a .pbit. Power BI stores Report/Layout and
# DataModelSchema as UTF-16-LE with NO byte-order mark. Python's "utf-16" codec adds one,
# and Desktop then refuses the entire file with "Either the file is encrypted or corrupted"
# — an error that points nowhere near the actual cause. Asserted here so it can never
# regress unnoticed.
zc = zipfile.ZipFile(PBIT)
bad = []
for part in ("Report/Layout", "DataModelSchema"):
    head = zc.read(part)[:2]
    if head in (b"\xff\xfe", b"\xfe\xff", b"\xef\xbb"):
        bad.append(f"{part} starts with a BOM ({head.hex()})")
zc.close()
if bad:
    raise SystemExit("ENCODING ERROR — template would not open:\n  " + "\n  ".join(bad))
print("  encoding : UTF-16-LE, no BOM (verified)")
