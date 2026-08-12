"""
22_pbit_fonts.py — force font sizes and data colours into every visual.

A theme's textClasses are only a DEFAULT. Any property a visual sets explicitly wins, and
the supplied report set most of them — which is why the theme swap changed very little and
everything still rendered at 8-9pt. The reliable fix is to write the properties onto each
visualContainer, which is what this does.

Sizes chosen for a projector at the back of a room, not for a developer's monitor:
    card value        32pt      the number is the point of the visual
    card label        13pt
    visual title      14pt
    axis / legend     12pt
    data labels       12pt
    table values      12pt, headers 12pt on navy
    slicer items      13pt      also the control that was being clipped
    textbox           left as authored — those carry deliberate hierarchy
"""
import json
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PBIT = ROOT / "powerbi" / "MerchantVoucherIntelligence.pbit"

NAVY, TEAL, AMBER, RED, PURPLE = "#12305B", "#0E8B8B", "#E8A317", "#C0392B", "#7B4B94"
GREEN, PINK, SLATE = "#1E8449", "#D6336C", "#5A6672"
SERIES = [NAVY, TEAL, AMBER, PURPLE, RED, GREEN, PINK]


def lit(v):
    return {"expr": {"Literal": {"Value": v}}}


def num(n):
    return lit(f"{n}D")


def colour(hexv):
    return {"solid": {"color": lit(f"'{hexv}'")}}


def put(objs, key, props):
    """Merge properties into objects[key][0].properties without dropping what is there."""
    lst = objs.setdefault(key, [{}])
    if not lst:
        lst.append({})
    entry = lst[0]
    entry.setdefault("properties", {}).update(props)


# KPI tile colours, cycled across each page — the same sequence the HTML report uses.
KPI_FILLS = [NAVY, TEAL, "1B4079", AMBER, RED, PURPLE]
card_seq = {}

z = zipfile.ZipFile(PBIT)
members = {n: z.read(n) for n in z.namelist()}
order = z.namelist()
z.close()

layout = json.loads(members["Report/Layout"].decode("utf-16-le"))

touched = 0
for sec in layout.get("sections", []):
    for vc in sec.get("visualContainers", []):
        try:
            cfg = json.loads(vc["config"])
        except Exception:
            continue
        sv = cfg.get("singleVisual")
        if not sv:
            continue
        vt = sv.get("visualType", "")
        objs = sv.setdefault("objects", {})
        vobjs = sv.setdefault("vcObjects", {})

        # Title on every visual that has one
        if vt != "textbox":
            put(vobjs, "title", {"fontSize": num(18), "fontColor": colour(NAVY),
                                 "fontFamily": lit("'Segoe UI Semibold'")})

        if vt in ("card", "kpi", "multiRowCard"):
            # WHITE tile, coloured accent border, dark text.
            #
            # A previous version filled the tile with colour and reversed the text out in
            # white. It failed: some cards already carried their own background or category
            # label colour in the supplied definition, so the row rendered as a mix of
            # coloured and white tiles WITH dark labels on dark fills — unreadable, and
            # inconsistent across the same row.
            #
            # Colour is carried by the border instead. It never collides with text, it works
            # regardless of what a card already had set, and the row stays uniform.
            idx = card_seq.get(sec.get("name"), 0)
            accent = KPI_FILLS[idx % len(KPI_FILLS)]
            card_seq[sec.get("name")] = idx + 1
            put(objs, "labels", {"fontSize": num(43), "color": colour(accent),
                                 "fontFamily": lit("'Segoe UI Bold'")})
            put(objs, "categoryLabels", {"fontSize": num(17), "color": colour(SLATE),
                                         "fontFamily": lit("'Segoe UI'")})
            put(objs, "wordWrap", {"show": lit("true")})
            put(vobjs, "background", {"show": lit("true"), "color": colour("FFFFFF"),
                                      "transparency": num(0)})
            put(vobjs, "border", {"show": lit("true"), "color": colour(accent),
                                  "radius": num(6)})
            put(vobjs, "title", {"show": lit("false")})

        elif vt == "slicer":
            put(objs, "items", {"fontSize": num(17), "fontColor": colour("#12203A")})
            put(objs, "header", {"fontSize": num(17), "fontColor": colour(NAVY),
                                 "fontFamily": lit("'Segoe UI Semibold'")})

        elif vt in ("tableEx", "pivotTable", "matrix"):
            put(objs, "values", {"fontSize": num(16),
                                 "fontColorPrimary": colour("#12203A"),
                                 "fontColorSecondary": colour("#12203A")})
            put(objs, "columnHeaders", {"fontSize": num(16), "fontColor": colour("#FFFFFF"),
                                        "backColor": colour(NAVY),
                                        "fontFamily": lit("'Segoe UI Semibold'")})
            put(objs, "total", {"fontSize": num(16), "fontFamily": lit("'Segoe UI Bold'")})
            put(objs, "grid", {"gridVertical": lit("true"),
                               "gridVerticalColor": colour("#E4EAF2"),
                               "rowPadding": num(4)})

        else:
            # every chart type
            put(objs, "categoryAxis", {"fontSize": num(17), "labelColor": colour(SLATE),
                                       "titleFontSize": num(14),
                                       "titleColor": colour(SLATE)})
            put(objs, "valueAxis", {"fontSize": num(17), "labelColor": colour(SLATE),
                                    "titleFontSize": num(14),
                                    "gridlineColor": colour("#E4EAF2")})
            put(objs, "legend", {"fontSize": num(17), "labelColor": colour(SLATE),
                                 "position": lit("'Bottom'")})
            put(objs, "labels", {"fontSize": num(16), "color": colour("#12203A")})

            # DO NOT set a defaultColor here. An earlier version forced NAVY onto every
            # chart, which rendered the whole report monochrome — worse than the single blue
            # it replaced. Leaving dataPoint alone lets the theme's ordered palette apply,
            # so series 1 is navy, series 2 teal, series 3 amber, and so on.
            if vt in ("donutChart", "pieChart", "ringChart"):
                # Categorical visuals only: force per-slice colouring rather than one hue
                objs.setdefault("dataPoint", [{}])[0].setdefault("properties", {})[
                    "showAllDataPoints"] = lit("true")

        vc["config"] = json.dumps(cfg, separators=(",", ":"))
        touched += 1

members["Report/Layout"] = json.dumps(layout, separators=(",", ":")).encode("utf-16-le")

# ---------------------------------------------------------------- repack
tmp = PBIT.with_suffix(".tmp")
with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zo:
    for n in order:
        zo.writestr(n, members[n])
tmp.replace(PBIT)

# ---------------------------------------------------------------- verify
zc = zipfile.ZipFile(PBIT)
for part in ("Report/Layout", "DataModelSchema"):
    if zc.read(part)[:2] in (b"\xff\xfe", b"\xfe\xff", b"\xef\xbb"):
        raise SystemExit(f"ENCODING ERROR: {part} has a BOM — template will not open")
chk = json.loads(zc.read("Report/Layout").decode("utf-16-le"))
zc.close()

print(f"  fonts applied to {touched} visuals across {len(chk['sections'])} pages")
print(f"  card values 32pt | titles 14pt | axes & legends 12pt | slicers 13pt | tables 12pt")
print(f"  encoding verified: UTF-16-LE, no BOM")
print(f"  {PBIT.name}  {PBIT.stat().st_size/1024:.0f} KB")

import shutil
shutil.copy2(PBIT, ROOT / "MerchantVoucherIntelligence_PowerBI" /
             "MerchantVoucherIntelligence.pbit")
print(f"  synced to MerchantVoucherIntelligence_PowerBI/")
