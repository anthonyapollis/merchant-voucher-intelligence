"""
30_pbit_more_pages.py — three further report pages.

  Voucher & Redemption   the clearest gap. Redemption is central to the brief and had no
                         page of its own: rate by type, time-to-redeem, delayed redemptions,
                         outstanding liability and breakage were scattered across other pages.
  Fraud & Controls       the prevent / detect / correct framework, with each control's status
                         and the four that cannot be built named alongside the telemetry
                         they would need.
  Data Quality & Model   the reconciliation controls plus ModelGuide, so a reviewer can see
                         where every table came from without leaving the report.
"""
import json
import shutil
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PBIT = ROOT / "powerbi" / "MerchantVoucherIntelligence.pbit"

NAVY, NAVY2, TEAL, AMBER = "#12305B", "#1B4079", "#0E8B8B", "#E8A317"
RED, PURPLE, GREEN, GREY, INK = "#C0392B", "#7B4B94", "#1E8449", "#5A6672", "#12203A"
W, M, G = 1280, 16, 12

z = zipfile.ZipFile(PBIT)
members = {n: z.read(n) for n in z.namelist()}
order = z.namelist()
z.close()
layout = json.loads(members["Report/Layout"].decode("utf-16-le"))


def vc(name, vtype, x, y, w, h, extra=None, z_=0):
    cfg = {"name": name, "layouts": [{"id": 0, "position": {"x": x, "y": y, "z": z_,
                                                            "width": w, "height": h}}],
           "singleVisual": {"visualType": vtype, "drillFilterOtherVisuals": True}}
    if extra:
        cfg["singleVisual"].update(extra)
    return {"x": x, "y": y, "z": z_, "width": w, "height": h,
            "config": json.dumps(cfg, separators=(",", ":")), "filters": "[]"}


def tb(name, x, y, w, h, runs, bg=None):
    paras = [{"horizontalTextAlignment": "left", "textRuns": [
        {"value": t, "textStyle": {"fontSize": f"{s}pt", "color": c,
                                   "fontWeight": "bold" if b else "normal",
                                   "fontFamily": "Segoe UI"}}]} for t, s, c, b in runs]
    objs = {"general": [{"properties": {"paragraphs": paras}}]}
    if bg:
        objs["background"] = [{"properties": {
            "show": {"expr": {"Literal": {"Value": "true"}}},
            "color": {"solid": {"color": {"expr": {"Literal": {"Value": f"'{bg}'"}}}}}}}]
    return vc(name, "textbox", x, y, w, h, {"objects": objs})


def card(name, measure, x, y, w, h, label, fill):
    L = lambda v: {"expr": {"Literal": {"Value": v}}}
    col = lambda c: {"solid": {"color": L(f"'{c}'")}}
    return vc(name, "card", x, y, w, h, {
        "projections": {"Values": [{"queryRef": f"_Measures.{measure}"}]},
        "prototypeQuery": {"Version": 2,
                           "From": [{"Name": "m", "Entity": "_Measures", "Type": 0}],
                           "Select": [{"Measure": {"Expression": {"SourceRef": {"Source": "m"}},
                                                   "Property": measure},
                                       "Name": f"_Measures.{measure}"}]},
        # White tile, coloured accent border, dark text — see the note in 22_pbit_fonts.py.
        # Dark text on a dark fill is the failure this avoids.
        "objects": {"labels": [{"properties": {"fontSize": L("30D"), "color": col(fill),
                                               "fontFamily": L("'Segoe UI Bold'")}}],
                    "categoryLabels": [{"properties": {"fontSize": L("12D"),
                                                       "color": col("#5A6672")}}]},
        "vcObjects": {"background": [{"properties": {"show": L("true"),
                                                     "color": col("#FFFFFF"),
                                                     "transparency": L("0D")}}],
                      "border": [{"properties": {"show": L("true"), "color": col(fill),
                                                 "radius": L("6D")}}],
                      "title": [{"properties": {"show": L("false")}}]}})


def tbl(name, entity, cols, x, y, w, h, title):
    sel = [{"Column": {"Expression": {"SourceRef": {"Source": "t"}}, "Property": c},
            "Name": f"{entity}.{c}"} for c in cols]
    return vc(name, "tableEx", x, y, w, h, {
        "projections": {"Values": [{"queryRef": f"{entity}.{c}"} for c in cols]},
        "prototypeQuery": {"Version": 2,
                           "From": [{"Name": "t", "Entity": entity, "Type": 0}],
                           "Select": sel},
        "vcObjects": {"title": [{"properties": {
            "show": {"expr": {"Literal": {"Value": "true"}}},
            "text": {"expr": {"Literal": {"Value": f"'{title}'"}}},
            "fontSize": {"expr": {"Literal": {"Value": "14D"}}}}}]}})


def chart(name, vtype, entity, cat, val, x, y, w, h, title, agg=0):
    return vc(name, vtype, x, y, w, h, {
        "projections": {"Category": [{"queryRef": f"{entity}.{cat}"}],
                        "Y": [{"queryRef": f"{entity}.{val}"}]},
        "prototypeQuery": {"Version": 2,
                           "From": [{"Name": "t", "Entity": entity, "Type": 0}],
                           "Select": [
                               {"Column": {"Expression": {"SourceRef": {"Source": "t"}},
                                           "Property": cat}, "Name": f"{entity}.{cat}"},
                               {"Aggregation": {"Expression": {"Column": {
                                   "Expression": {"SourceRef": {"Source": "t"}},
                                   "Property": val}}, "Function": agg},
                                "Name": f"{entity}.{val}"}]},
        "vcObjects": {"title": [{"properties": {
            "show": {"expr": {"Literal": {"Value": "true"}}},
            "text": {"expr": {"Literal": {"Value": f"'{title}'"}}},
            "fontSize": {"expr": {"Literal": {"Value": "14D"}}}}}]}})


def banner(p, title, sub):
    return [tb(f"{p}Band", 0, 0, W, 56, [(f"  {title}", 18, "#FFFFFF", True)], NAVY),
            tb(f"{p}Sub", W - 660, 16, 640, 30, [(sub + "  ", 10, "#9FB6D4", False)])]


pages = []
cw = (W - 2 * M - 4 * G) // 5

# ---------------------------------------------------------------- VOUCHER & REDEMPTION
v = banner("vc", "Voucher & redemption",
           "Where issued value goes, how fast, and what remains outstanding")
y = 68
for i, (meas, lbl, fill) in enumerate([
        ("Vouchers Sold", "Vouchers issued", NAVY),
        ("Redemption Rate %", "Redemption rate", TEAL),
        ("Average Days To Redeem", "Avg days to redeem", NAVY2),
        ("Delayed Redemption %", "Delayed (>7 days)", AMBER),
        ("Unredeemed Voucher Value", "Outstanding liability", RED)]):
    v.append(card(f"vcK{i}", meas, M + i * (cw + G), y, cw, 104, lbl, fill))
y += 104 + G
half = (W - 2 * M - G) // 2
v.append(chart("vcRate", "barChart", "DimVoucherType", "VoucherType", "VoucherTypeSort",
               M, y, half, 250, "Redemption rate by voucher type"))
v.append(chart("vcDays", "columnChart", "DimVoucherType", "VoucherType", "VoucherTypeSort",
               M + half + G, y, W - M - (M + half + G), 250,
               "Average days to redeem by type"))
y += 250 + G
v.append(tbl("vcTable", "DimVoucherType",
             ["VoucherType", "VoucherCategory", "MarginBand"], M, y, W - 2 * M, 220,
             "Voucher type reference"))
y += 220 + G
v.append(tb("vcNote", M, y, W - 2 * M, 128, [
    ("Airtime redeems at 92.8%; Gaming at 76.0% — a 16.9 percentage point spread.  ",
     13, NAVY, True),
    ("Time-to-redeem is effectively identical across every type (3.5–3.7 days), so the "
     "difference is WHETHER customers redeem, not how quickly. Gaming's 24% non-redemption "
     "is the single largest block of the R3.5m outstanding liability.\n\n"
     "Outstanding value is a balance-sheet liability, not lost revenue. Breakage — unredeemed "
     "beyond the 90-day expiry window — is the portion that can reasonably be released to "
     "income, and is modelled separately for that reason.", 11, INK, False)], "#FFFFFF"))
pages.append(("VoucherRedemption", "Voucher & Redemption", v, y + 128 + M))

# ---------------------------------------------------------------- FRAUD & CONTROLS
f = banner("fr", "Fraud detection & prevention",
           "Detection is one third of a control framework")
y = 68
third = (W - 2 * M - 2 * G) // 3
COLS = [
    ("PREVENT", "Stops the loss occurring", "#8B2E24", [
        "Voucher expiry enforcement — modelled, not enforced",
        "Value ceilings per type — Gaming carries 24% non-redemption",
        "Velocity limits per merchant — cap redemptions per hour",
        "Onboarding due diligence — 2 CRM 'At Risk' merchants have no linked control",
        "Segregation of duties — issuance and redemption approval",
    ]),
    ("DETECT", "Finds it after the fact — BUILT", TEAL, [
        "Reversal rate per 1k txn — 215 tickets, range 0.00–1.99",
        "Redemption velocity — same-day share, ~23% and uniform",
        "Behavioural anomaly — Isolation Forest on own-history deviation",
        "Liability concentration — R3.5m tracked per merchant",
        "Value outliers — implemented; correctly returns ZERO",
    ]),
    ("CORRECT", "Limits the damage once found", AMBER, [
        "Quarantine on DQ failure — bad loads never reach gold",
        "Change alerting — SCD2 diff raises status changes as Critical",
        "Reversal workflow — financial tickets are 25% of volume",
        "Merchant suspension path — 'Review' should hold, not email",
        "Audit trail — batch_id answers 'which load produced this'",
    ])]
for i, (title, sub, col, items) in enumerate(COLS):
    x = M + i * (third + G)
    f.append(tb(f"frH{i}", x, y, third, 62,
                [(f"  {title}", 15, "#FFFFFF", True), (f"  {sub}", 10, "#E8EFF8", False)],
                col))
    f.append(tb(f"frB{i}", x, y + 62, third, 250,
                [(f"•  {t}", 10.5, INK, False) for t in items], "#FFFFFF"))
y += 62 + 250 + G
f.append(tb("frGap", M, y, W - 2 * M, 150, [
    ("Four controls cannot be built on this dataset — each names what it would need.",
     13, RED, True),
    ("Duplicate redemption — voucher_id is unique BY CONSTRUCTION in the extract, so a "
     "duplicate cannot appear. Needs the raw redemption event log including failed attempts.\n"
     "Geographic anomaly — needs transaction location and timestamp, not a static merchant "
     "province.\n"
     "PIN / invalid voucher use — needs voucher PIN, attempt outcome and failure reason.\n"
     "Customer velocity, CLV and churn — needs a customer or session identifier, which does "
     "not exist in any of the four source files. Merchant-level equivalents are modelled "
     "instead, on the Merchant Value & Risk page.", 11, INK, False)], "#FDF0EE"))
y += 150 + G
f.append(tbl("frTable", "MerchantValueRisk",
             ["merchant_name", "region", "reversal_tickets", "reversal_per_1k_txn",
              "same_day_redemption_rate", "value_outlier_vouchers", "risk_signal_score",
              "risk_signal_band"], M, y, W - 2 * M, 240, "Merchant risk signals"))
pages.append(("FraudControls", "Fraud & Controls", f, y + 240 + M))

# ---------------------------------------------------------------- DATA QUALITY & MODEL
d = banner("dq", "Data quality & model guide",
           "Where every table came from, and whether the numbers reconcile")
y = 68
for i, (meas, lbl, fill) in enumerate([
        ("Controls Total", "Controls run", NAVY),
        ("Control Pass Rate", "Pass rate", TEAL),
        ("Population Variance", "Explained variance", AMBER),
        ("Transactions per Voucher", "Txn per voucher", NAVY2)]):
    q = (W - 2 * M - 3 * G) // 4
    d.append(card(f"dqK{i}", meas, M + i * (q + G), y, q, 104, lbl, fill))
y += 104 + G
d.append(tbl("dqRec", "RecControls",
             ["control_family", "control_name", "expected_value", "actual_value",
              "variance", "control_status"], M, y, W - 2 * M, 230,
             "Reconciliation controls"))
y += 230 + G
d.append(tbl("dqGuide", "ModelGuide", ["Origin", "Table", "Rows", "Why this table exists"],
             M, y, W - 2 * M, 300, "Model guide — origin of every table"))
y += 300 + G
d.append(tb("dqNote", M, y, W - 2 * M, 140, [
    ("Five tables come from the supplied README. The rest are justified individually.",
     13, NAVY, True),
    ("[README] 5 · [BRIEF] 3 required by the brief's own report requirements · [ML] 4 "
     "outputs of the optional AI extension · [ADDED] 2 beyond the brief and labelled as "
     "such · [SYSTEM] 1 measure container holding no data.\n\n"
     "The population control is the one worth reading: the sales fact and the voucher fact "
     "differ by R43.5m and that is EXPECTED, not a break. MerchantSales aggregates all "
     "510,127 transactions; VoucherRedemptions covers 120,969 individual vouchers — a 4.2:1 "
     "ratio between two different populations. Forcing them to tie would be the error.",
     11, INK, False)], "#EEF3F9"))
pages.append(("DataQuality", "Data Quality & Model", d, y + 140 + M))

# ---------------------------------------------------------------- attach
secs = layout["sections"]
base = max(s.get("ordinal", 0) for s in secs) + 1
for i, (name, disp, vcs, h) in enumerate(pages):
    secs = [s for s in secs if s.get("name") != name]
    secs.append({
        "id": 950 + i, "name": name, "displayName": disp, "filters": "[]",
        "ordinal": base + i, "visualContainers": vcs,
        "config": json.dumps({"objects": {"background": [{"properties": {
            "color": {"solid": {"color": {"expr": {"Literal": {"Value": "'#F2F5FA'"}}}}},
            "transparency": {"expr": {"Literal": {"Value": "0D"}}}}}]}},
            separators=(",", ":")),
        "displayOption": 1, "width": W, "height": max(h, 720)})
    print(f"  added '{disp}'  ({len(vcs)} visuals, {max(h,720)}px)")

layout["sections"] = sorted(secs, key=lambda s: s.get("ordinal", 0))
members["Report/Layout"] = json.dumps(layout, separators=(",", ":")).encode("utf-16-le")

tmp = PBIT.with_suffix(".tmp")
with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zo:
    for n in order:
        zo.writestr(n, members[n])
tmp.replace(PBIT)

zc = zipfile.ZipFile(PBIT)
for part in ("Report/Layout", "DataModelSchema"):
    if zc.read(part)[:2] in (b"\xff\xfe", b"\xfe\xff", b"\xef\xbb"):
        raise SystemExit(f"ENCODING ERROR: {part} has a BOM")
chk = json.loads(zc.read("Report/Layout").decode("utf-16-le"))
bad = 0
for s in chk["sections"]:
    vs = s.get("visualContainers", [])
    for i, a in enumerate(vs):
        for b in vs[i + 1:]:
            ox = max(0, min(a["x"] + a["width"], b["x"] + b["width"]) - max(a["x"], b["x"]))
            oy = max(0, min(a["y"] + a["height"], b["y"] + b["height"]) - max(a["y"], b["y"]))
            bad += (ox > 0 and oy > 0)
zc.close()
shutil.copy2(PBIT, ROOT / "MerchantVoucherIntelligence_PowerBI" /
             "MerchantVoucherIntelligence.pbit")
print(f"\n  {len(chk['sections'])} pages · {bad} overlaps · encoding verified · "
      f"{PBIT.stat().st_size/1024:.0f} KB")
print("  " + " · ".join(s.get("displayName", "?") for s in chk["sections"]))
