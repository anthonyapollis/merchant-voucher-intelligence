"""
31_pbit_fix_visuals.py — repair the faults visible when the template is actually opened.

Four defects, all found by opening the report rather than by reading the JSON:

  1. Three visuals on 'Voucher & Redemption' render "Something's wrong with one or more
     fields". The page builder fell through to a placeholder query that selects
     DimVoucherType[VoucherTypeSort] — a column that does not exist in this model. A
     field-reference check passes on the OTHER visuals, which is why this was not caught
     statically: the entity resolves, the column does not. They are rebuilt here against
     real measures.

  2. 'Merchants To Review' shows (Blank). COUNTROWS(FILTER(...)) returns BLANK, not 0, when
     nothing matches — and nothing does match, because no merchant currently lands in the
     'Review' band. Blank on a KPI tile reads as a broken measure. Wrapped in COALESCE so a
     true zero displays as 0.

  3. Textbox body copy renders faint and small — light grey at 9pt. Every run is lifted to a
     minimum size and forced to a dark ink colour.

  4. Bar and column charts render in Power BI's default light blue because no dataPoint fill
     is set and the theme's ordered palette only applies to multi-series visuals. A single
     series gets an explicit fill from the report palette.
"""
import json
import shutil
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PBIT = ROOT / "powerbi" / "MerchantVoucherIntelligence.pbit"

NAVY, TEAL, AMBER, RED, PURPLE = "#12305B", "#0E8B8B", "#E8A317", "#C0392B", "#7B4B94"
GREEN, INK = "#1E8449", "#12203A"
BAR_SEQ = [NAVY, TEAL, AMBER, PURPLE, GREEN, RED]

MIN_BODY_PT = 15          # nothing below this is legible on a projector
SUBTLE = "#3E5C86"        # for secondary text on white — dark enough to read, still recessive


def luminance(hexv):
    """Relative luminance 0..1. Used to tell 'light text sitting on a dark banner' (keep)
    apart from 'grey body copy on white' (darken). A first-nibble test was tried first and
    was wrong: #5A6672 slate starts with '5' but still renders faint at small sizes."""
    h = hexv.lstrip("#")
    if len(h) != 6:
        return 0.0
    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def L(v):
    return {"expr": {"Literal": {"Value": v}}}


def col(h):
    return {"solid": {"color": L(f"'{h}'")}}


def put(o, k, props):
    o.setdefault(k, [{}])[0].setdefault("properties", {}).update(props)


def measure(entity, name, alias):
    return {"Measure": {"Expression": {"SourceRef": {"Source": "m"}}, "Property": name},
            "Name": alias}


def column(src, entity, prop, alias):
    return {"Column": {"Expression": {"SourceRef": {"Source": src}}, "Property": prop},
            "Name": alias}


# ---------------------------------------------------------------- replacement visuals
def q_by_type(meas_name, alias, vtype):
    """Categorical breakdown: voucher type on the axis, one measure on values."""
    return {
        "visualType": vtype,
        "projections": {"Category": [{"queryRef": "DimVoucherType.VoucherType"}],
                        "Y": [{"queryRef": alias}]},
        "prototypeQuery": {
            "Version": 2,
            "From": [{"Name": "t", "Entity": "DimVoucherType", "Type": 0},
                     {"Name": "m", "Entity": "_Measures", "Type": 0}],
            "Select": [column("t", "DimVoucherType", "VoucherType",
                              "DimVoucherType.VoucherType"),
                       measure("_Measures", meas_name, alias)],
            "OrderBy": [{"Direction": 2,
                         "Expression": {"Measure": {
                             "Expression": {"SourceRef": {"Source": "m"}},
                             "Property": meas_name}}}],
        },
    }


def q_table():
    """Redemption summary table — the numbers behind the two charts above it."""
    cols = ["Vouchers Sold", "Vouchers Redeemed", "Redemption Rate %",
            "Average Days To Redeem", "Delayed Redemption %", "Unredeemed Voucher Value"]
    return {
        "visualType": "tableEx",
        "projections": {"Values": ([{"queryRef": "DimVoucherType.VoucherType"}] +
                                   [{"queryRef": c} for c in cols])},
        "prototypeQuery": {
            "Version": 2,
            "From": [{"Name": "t", "Entity": "DimVoucherType", "Type": 0},
                     {"Name": "m", "Entity": "_Measures", "Type": 0}],
            "Select": ([column("t", "DimVoucherType", "VoucherType",
                               "DimVoucherType.VoucherType")] +
                       [measure("_Measures", c, c) for c in cols]),
        },
    }


REPLACE = [q_by_type("Redemption Rate %", "Redemption Rate %", "barChart"),
           q_by_type("Unredeemed Voucher Value", "Unredeemed Voucher Value", "columnChart"),
           q_table()]
TITLES = ["Redemption rate by voucher type",
          "Outstanding liability by voucher type",
          "Redemption summary by voucher type"]

# ---------------------------------------------------------------- load
z = zipfile.ZipFile(PBIT)
members = {n: z.read(n) for n in z.namelist()}
names = z.namelist()
z.close()

layout = json.loads(members["Report/Layout"].decode("utf-16-le"))

# ---------------------------------------------------------------- reference validator
# Detecting the broken visuals by looking for one known-bad column name was not enough: the
# table on that page referenced DimVoucherType[VoucherCategory] and [MarginBand], which are
# equally absent but have different names. Every reference is resolved against the model
# instead, so any visual bound to a field that does not exist is caught.
_model = json.loads(members["DataModelSchema"].decode("utf-16-le"))["model"]
COLS = {t["name"]: {c["name"] for c in t.get("columns", [])} for t in _model["tables"]}
MEAS = {x["name"] for t in _model["tables"] for x in t.get("measures", [])}


def unresolved(sv):
    """Names referenced by this visual that exist in neither the columns nor the measures."""
    pq = sv.get("prototypeQuery") or {}
    ents = {f["Name"]: f["Entity"] for f in pq.get("From", [])}
    missing = []

    def walk(node):
        if isinstance(node, dict):
            for kind in ("Column", "Measure"):
                ref = node.get(kind)
                if isinstance(ref, dict) and "Property" in ref:
                    src = (ref.get("Expression", {}).get("SourceRef", {}) or {}).get("Source")
                    ent = ents.get(src, "")
                    prop = ref["Property"]
                    if prop not in COLS.get(ent, set()) and prop not in MEAS:
                        missing.append(f"{ent}[{prop}]")
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(pq)
    return missing

fixed_visuals = 0
bars = 0
runs = 0
broken = []

def bg_colour(sv):
    """The visual's own background colour, or None."""
    try:
        p = sv["vcObjects"]["background"][0]["properties"]["color"]["solid"]["color"]
        return str(p["expr"]["Literal"]["Value"]).strip("'")
    except Exception:
        return None


for sec in layout.get("sections", []):
    page = sec.get("displayName", "")
    slot = 0
    bar_i = 0

    # Rectangles of every DARK-backgrounded visual on this page. Light text is legitimate
    # only where it sits inside one of these. Judging by the text colour alone was wrong:
    # the Executive Overview subtitle is #C3D7F0, which looks like banner text but is
    # positioned to the RIGHT of the banner, on plain white — invisible in practice.
    dark_rects = []
    for vc in sec.get("visualContainers", []):
        try:
            s = json.loads(vc["config"]).get("singleVisual") or {}
        except Exception:
            continue
        c = bg_colour(s)
        if c and luminance(c) < 0.5:
            dark_rects.append((vc.get("x", 0), vc.get("y", 0),
                               vc.get("x", 0) + vc.get("width", 0),
                               vc.get("y", 0) + vc.get("height", 0)))

    def on_dark(vc):
        cx = vc.get("x", 0) + vc.get("width", 0) / 2
        cy = vc.get("y", 0) + vc.get("height", 0) / 2
        return any(x0 <= cx <= x1 and y0 <= cy <= y1 for x0, y0, x1, y1 in dark_rects)

    for vc in sec.get("visualContainers", []):
        try:
            cfg = json.loads(vc["config"])
        except Exception:
            continue
        sv = cfg.get("singleVisual")
        if not sv:
            continue
        vt = sv.get("visualType", "")

        # ---- 1. the three broken placeholders -------------------------------------
        miss = unresolved(sv)
        if miss:
            broken.append(f"{page}: {vt} -> {', '.join(sorted(set(miss)))}")
        if page == "Voucher & Redemption" and miss:
            if slot < len(REPLACE):
                new = REPLACE[slot]
                sv["visualType"] = new["visualType"]
                sv["projections"] = new["projections"]
                sv["prototypeQuery"] = new["prototypeQuery"]
                put(sv.setdefault("vcObjects", {}), "title",
                    {"show": L("true"), "text": L(f"'{TITLES[slot]}'"),
                     "fontSize": L("14D"), "fontColor": col(NAVY),
                     "fontFamily": L("'Segoe UI Semibold'")})
                vt = new["visualType"]
                fixed_visuals += 1
                slot += 1

        objs = sv.setdefault("objects", {})

        # ---- 4. single-series charts get a real colour ----------------------------
        if vt in ("barChart", "columnChart", "clusteredBarChart", "clusteredColumnChart",
                  "areaChart", "lineChart", "scatterChart"):
            ys = (sv.get("projections") or {}).get("Y") or []
            if len(ys) <= 1:                      # multi-series keeps the theme palette
                put(objs, "dataPoint", {"fill": col(BAR_SEQ[bar_i % len(BAR_SEQ)])})
                bar_i += 1
                bars += 1

        # ---- 3. faint body copy ---------------------------------------------------
        if vt == "textbox":
            for para in objs.get("general", [{}])[0].get(
                    "properties", {}).get("paragraphs", []):
                for run in para.get("textRuns", []):
                    ts = run.setdefault("textStyle", {})
                    try:
                        size = float(str(ts.get("fontSize", "9")).replace("pt", ""))
                    except ValueError:
                        size = 9.0
                    if size < MIN_BODY_PT:
                        ts["fontSize"] = f"{MIN_BODY_PT}pt"
                    c = str(ts.get("color", "")).lower()

                    # Already-corrected colours are terminal. Without this the script is not
                    # idempotent: a second run reads SUBTLE as "too dark to be banner text"
                    # and pushes it to INK, so the styling drifts every time the chain runs.
                    if c in (INK.lower(), SUBTLE.lower(), "#ffffff"):
                        continue

                    # Light text is kept ONLY where the textbox actually sits on a dark
                    # background. Anywhere else — including text that merely looks like
                    # banner text — it goes to full ink.
                    if on_dark(vc):
                        if c and luminance(c) < 0.5:
                            ts["color"] = "#FFFFFF"     # dark ink on a dark band
                            runs += 1
                    elif not c or luminance(c) < 0.62:
                        ts["color"] = INK
                        runs += 1
                    elif luminance(c) >= 0.62:
                        ts["color"] = SUBTLE            # light text stranded on white
                        runs += 1

        vc["config"] = json.dumps(cfg, separators=(",", ":"))

members["Report/Layout"] = json.dumps(layout, separators=(",", ":")).encode("utf-16-le")

# ---------------------------------------------------------------- 2. blank measure
model = json.loads(members["DataModelSchema"].decode("utf-16-le"))
patched = []
NEW = {
    "Merchants To Review":
        'COALESCE ( COUNTROWS ( FILTER ( MerchantValueRisk, '
        'MerchantValueRisk[risk_signal_band] = "Review" ) ), 0 )',
    "Merchants To Monitor":
        'COALESCE ( COUNTROWS ( FILTER ( MerchantValueRisk, '
        'MerchantValueRisk[risk_signal_band] = "Monitor" ) ), 0 )',
}
for t in model["model"]["tables"]:
    ms = t.get("measures")
    if ms is None:
        continue
    have = {x["name"] for x in ms}
    for nm, expr in NEW.items():
        if nm in have:
            for x in ms:
                if x["name"] == nm:
                    x["expression"] = expr
                    patched.append(nm)
        elif t["name"] == "_Measures":
            ms.append({"name": nm, "expression": expr, "formatString": "0"})
            patched.append(nm + " (new)")

members["DataModelSchema"] = json.dumps(model, ensure_ascii=False).encode("utf-16-le")

# ---------------------------------------------------------------- repack + verify
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

# Re-validate the repacked file against the model. This is the check that should have
# existed from the start — "Something's wrong with one or more fields" is a binding to a
# field that is not in the model, and it is fully detectable before the file is opened.
still = []
for sec in chk.get("sections", []):
    for vc in sec.get("visualContainers", []):
        sv = json.loads(vc["config"]).get("singleVisual")
        if sv:
            for r in unresolved(sv):
                still.append(f"{sec.get('displayName')}: {sv.get('visualType')} -> {r}")
if still:
    raise SystemExit("UNRESOLVED FIELD BINDINGS — these render as an error in Power BI:\n  "
                     + "\n  ".join(sorted(set(still))))

shutil.copy2(PBIT, ROOT / "MerchantVoucherIntelligence_PowerBI" /
             "MerchantVoucherIntelligence.pbit")

for b in sorted(set(broken)):
    print(f"  BROKEN BINDING FOUND  {b}")
print(f"  rebuilt {fixed_visuals} broken visuals on 'Voucher & Redemption'")
print(f"  measures patched: {', '.join(patched)}")
print(f"  {runs} text runs darkened to {INK} / min {MIN_BODY_PT}pt")
print(f"  {bars} single-series charts given an explicit palette colour")
print(f"  encoding verified · {len(chk['sections'])} pages · {PBIT.stat().st_size/1024:.0f} KB")
