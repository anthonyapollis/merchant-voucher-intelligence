"""
35_pbit_fill_insights.py — fill the two empty blocks on 'Insights & Notes', and stop the
change-alerts table reading as broken.

Two defects, both visible only by opening the report:

  1. 'Insights & Notes' carries an Assumptions heading and a Limitations heading with NOTHING
     underneath either — roughly half the page is blank. The content exists (it is in the
     Excel workbook and the Word report); it was simply never written onto the page.

  2. mart_merchant_change_alerts holds 0 rows. That is CORRECT — no merchant attribute has
     changed since the first snapshot, so there is nothing to alert on. But a reviewer sees a
     table with 0 next to it and reasonably concludes something failed. The number needs its
     explanation attached to it, and evidence that the mechanism works when there IS a change:
     scripts/_test_scd2.py simulates one and asserts 7/7 on the resulting history.

Assumptions and limitations are stated in the same words as the Excel workbook and the Word
report deliberately — three documents disagreeing about what was assumed is worse than any
one of them being terse.
"""
import json
import shutil
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PBIT = ROOT / "powerbi" / "MerchantVoucherIntelligence.pbit"

NAVY, TEAL, AMBER, INK, SLATE = "#12305B", "#0E8B8B", "#B8860B", "#12203A", "#3E5C86"

ASSUMPTIONS = [
    ("Delayed redemption = more than 7 days",
     "No threshold was supplied. 7 days sits above the 75th percentile of 5 days, so it "
     "flags a genuine tail rather than routine behaviour. Defined once in dbt_project.yml "
     "and inherited by the SQL, DAX and ML layers."),
    ("Voucher expiry / breakage = 90 days",
     "No expiry rule was supplied. Affects the breakage measure only — outstanding "
     "liability is unaffected."),
    ("Targets pro-rated by days covered",
     "Every month in the window is complete, so the factor is currently 1.0. The logic is "
     "in place so a mid-month refresh cannot produce a false shortfall."),
    ("Support cost of R450 per hour",
     "Used only in the indicative Ops Cost Exposure measure. Replace with Finance's loaded "
     "rate before any real use."),
    ("Voucher category and margin band",
     "Not present in the source. Held as a dbt seed so the commercial team can change the "
     "mapping without a code deployment."),
    ("Health Score weights",
     "Weighted toward recent momentum (25%) over structural trend (15%) because the purpose "
     "is early warning. A business-tunable parameter, not a hidden constant."),
]

LIMITATIONS = [
    ("Seven months of data",
     "1 Jan to 31 Jul 2026. No year-on-year comparison is possible. The YoY measures are "
     "written and return BLANK by design rather than a misleading zero."),
    ("No annual seasonality baseline",
     "The 4.69% forecast MAPE reflects weekly seasonality only. Festive trading and school "
     "terms cannot be modelled from seven months."),
    ("25 merchants limits statistical power",
     "Merchant-level correlations rest on n=25. This is why the operations analysis uses the "
     "175-row merchant-month panel and partial correlation rather than one coefficient."),
    ("Redemption model ceiling",
     "Redemption is driven almost entirely by voucher type here, capping achievable AUC at "
     "about 0.62. The model reaches 0.620 against a 0.621 oracle — 99.8% of the available "
     "signal."),
    ("No customer identifier exists",
     "None of the four files carries one. CLV, churn and duplicate-redemption fraud are "
     "therefore modelled at MERCHANT level, and per-customer versions cannot be built from "
     "this extract at all."),
    ("Synthetic data",
     "The embedded patterns were recovered independently by the anomaly model, which "
     "validates the METHOD. It does not validate the conclusions against real trading."),
]


def L(v):
    return {"expr": {"Literal": {"Value": v}}}


def run(text, size, colour, bold=False):
    return {"value": text,
            "textStyle": {"fontSize": f"{size}pt", "color": colour,
                          "fontWeight": "bold" if bold else "normal",
                          "fontFamily": "Segoe UI"}}


def textbox(name, x, y, w, h, paragraphs, z=100):
    return {
        "x": x, "y": y, "width": w, "height": h, "z": z,
        "config": json.dumps({
            "name": name,
            "layouts": [{"id": 0, "position": {"x": x, "y": y, "width": w, "height": h,
                                               "z": z}}],
            "singleVisual": {
                "visualType": "textbox",
                "objects": {"general": [{"properties": {"paragraphs": paragraphs}}]},
                "vcObjects": {"background": [{"properties": {
                    "show": L("true"),
                    "color": {"solid": {"color": L("'#FFFFFF'")}},
                    "transparency": L("0D")}}],
                    "border": [{"properties": {
                        "show": L("true"),
                        "color": {"solid": {"color": L("'#D8E2EE'")}},
                        "radius": L("6D")}}]},
            }}, separators=(",", ":")),
        "filters": "[]",
    }


def block(heading, items, accent):
    paras = [{"horizontalTextAlignment": "left",
              "textRuns": [run(heading, 15, accent, True)]}]
    for title, body in items:
        paras.append({"horizontalTextAlignment": "left",
                      "textRuns": [run(f"\n{title}  ", 14, INK, True),
                                   run(body, 14, SLATE)]})
    return paras


z = zipfile.ZipFile(PBIT)
members = {n: z.read(n) for n in z.namelist()}
names = z.namelist()
z.close()

layout = json.loads(members["Report/Layout"].decode("utf-16-le"))

target = None
for sec in layout["sections"]:
    if sec.get("displayName") == "Insights & Notes":
        target = sec
        break
if target is None:
    raise SystemExit("page 'Insights & Notes' not found")

# Remove the two bare headings — they are replaced by blocks that carry their own heading.
# Anything this script previously added is removed too, by name: without that the blocks are
# appended again on every run and the page ends up with duplicates stacked on each other.
OWNED = {"insAssumptions", "insLimitations", "insChangeAlerts"}
before = len(target["visualContainers"])
kept = []
for vc in target["visualContainers"]:
    try:
        cfg = json.loads(vc["config"])
        sv = cfg.get("singleVisual") or {}
        paras = sv.get("objects", {}).get("general", [{}])[0].get(
            "properties", {}).get("paragraphs", [])
        txt = "".join(r.get("value", "") for p in paras for r in p.get("textRuns", []))
    except Exception:
        cfg, sv, txt = {}, {}, ""
    if cfg.get("name") in OWNED:
        continue
    if sv.get("visualType") == "textbox" and txt.strip() in ("Assumptions", "Limitations"):
        continue
    kept.append(vc)
target["visualContainers"] = kept
removed = before - len(kept)

PW = 1280
COL = (PW - 40 - 16) // 2
Y = 400
H = 300

target["visualContainers"].append(
    textbox("insAssumptions", 20, Y, COL, H, block("Assumptions", ASSUMPTIONS, NAVY)))
target["visualContainers"].append(
    textbox("insLimitations", 20 + COL + 16, Y, COL, H,
            block("Limitations", LIMITATIONS, AMBER)))

# The change-alerts explanation. A zero that is not explained looks like a failure.
target["visualContainers"].append(
    textbox("insChangeAlerts", 20, Y + H + 12, PW - 40, 96, [
        {"horizontalTextAlignment": "left",
         "textRuns": [run("Why the change-alert table shows zero rows", 15, TEAL, True)]},
        {"horizontalTextAlignment": "left",
         "textRuns": [
             run("\nmart_merchant_change_alerts", 13, INK, True),
             run("  holds 0 rows, and that is the correct result: the Type 2 snapshot has "
                 "run against a source in which no merchant attribute has yet changed, so "
                 "there is nothing to alert on. A snapshot that has only ever seen one "
                 "version of each row is indistinguishable from one that is silently "
                 "broken, so the mechanism is proven rather than asserted — ", 11, SLATE),
             run("scripts/_test_scd2.py", 13, INK, True),
             run(" simulates a real change (Umhlanga Value Mart moving to At Risk under a "
                 "new account manager), re-runs the snapshot and asserts 7/7 on the "
                 "resulting history: a new version is created, exactly one version is "
                 "current, the superseded row retains the old value and is closed off, "
                 "numbering stays contiguous, and unchanged merchants gain nothing. The "
                 "harness restores the original state, which is why this table reads zero "
                 "again afterwards.", 11, SLATE)]}]))

members["Report/Layout"] = json.dumps(layout, separators=(",", ":")).encode("utf-16-le")

tmp = PBIT.with_suffix(".tmp")
with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zo:
    for n in names:
        zo.writestr(n, members[n])
tmp.replace(PBIT)

zc = zipfile.ZipFile(PBIT)
for part in ("Report/Layout", "DataModelSchema"):
    if zc.read(part)[:2] in (b"\xff\xfe", b"\xfe\xff", b"\xef\xbb"):
        raise SystemExit(f"ENCODING ERROR: {part} has a BOM — template will not open")
chk = json.loads(zc.read("Report/Layout").decode("utf-16-le"))
zc.close()

sec = next(s for s in chk["sections"] if s["displayName"] == "Insights & Notes")
bottom = max(vc["y"] + vc["height"] for vc in sec["visualContainers"])

shutil.copy2(PBIT, ROOT / "MerchantVoucherIntelligence_PowerBI" /
             "MerchantVoucherIntelligence.pbit")

print(f"  removed {removed} empty headings, added 3 populated blocks")
print(f"  {len(ASSUMPTIONS)} assumptions and {len(LIMITATIONS)} limitations written onto the page")
print(f"  page content now extends to {bottom}px · {len(sec['visualContainers'])} visuals")
print(f"  encoding verified · {PBIT.stat().st_size/1024:.0f} KB")
