"""
build_pbit.py
=============
Produces powerbi/MerchantVoucherIntelligence.pbit - a Power BI Template that
opens directly in Power BI Desktop, loads the gold layer, and becomes the full
report on first save.

Why a .pbit and not a .pbix
--------------------------
A .pbix stores its model in a `DataModel` part: an XPress9-compressed Analysis
Services backup that only Power BI Desktop (or an AS engine) can write. There is
no way to author that byte stream from outside those tools, and neither is
installed on this machine - the supplied Demo.pbix contains an empty 8 KB model
and a blank page, so there was nothing in it to extend either.

A .pbit stores the same model as `DataModelSchema`: plain TMSL JSON. That is
fully authorable here. Opening the template in Desktop makes Desktop build the
binary model itself, which is exactly the step that cannot be faked.

The template is assembled on the part formats read out of Demo.pbix, so the
Version (1.28), layout schema version (5.55) and base theme (CY24SU06) match the
user's own Power BI build rather than being guessed.

Run:  python build/build_pbit.py   (after build_gold.py)
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import build_semantic_model as sm

ROOT = Path(__file__).resolve().parents[1]
GOLD = ROOT / "data" / "gold"
OUT = ROOT / "powerbi" / "MerchantVoucherIntelligence.pbit"
DEMO = Path(r"C:\Users\Anthony.DESKTOP-ES5HL78\Downloads\Demo.pbix")

PBIX_VERSION = "1.28"
LAYOUT_VERSION = "5.55"
BASE_THEME = "CY24SU06"
CUSTOM_THEME = "MerchantVoucherIntelligence"

# --------------------------------------------------------------- design system
# Categorical slots are the validated data-viz palette, used in its documented
# order. Chrome colours are the same ones the offline dashboard uses, so a
# screenshot from either surface reads as one product.
INK = "#0B0B0B"
INK_2 = "#52514E"
INK_MUTED = "#898781"
SURFACE = "#FFFFFF"
PAGE_BG = "#F2F1ED"
GRID = "#E6E4DE"
BRAND = "#1C5CAB"        # header band
BRAND_LIGHT = "#E8F0FB"  # tinted KPI background
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4",
          "#008300", "#4a3aa7", "#e34948"]
GOOD, WARN, BAD = "#0ca30c", "#fab219", "#d03b3b"
TINT_BAD, TINT_WARN, TINT_GOOD = "#FCEFEE", "#FEF6E7", "#EAF7EA"

FONT = "Segoe UI"
FONT_SEMI = "Segoe UI Semibold"


def _c(hex_colour):
    return {"solid": {"color": hex_colour}}


THEME = {
    "name": CUSTOM_THEME,
    "dataColors": SERIES,
    "good": GOOD, "neutral": WARN, "bad": BAD,
    "maximum": "#0d366b", "center": "#86b6ef", "minimum": "#cde2fb",
    "null": GRID,
    "background": SURFACE, "secondaryBackground": PAGE_BG,
    "foreground": INK, "tableAccent": SERIES[0],
    "textClasses": {
        "callout": {"fontSize": 28, "fontFace": FONT_SEMI, "color": INK},
        "title": {"fontSize": 12, "fontFace": FONT_SEMI, "color": INK},
        "header": {"fontSize": 11, "fontFace": FONT_SEMI, "color": INK_2},
        "label": {"fontSize": 9, "fontFace": FONT, "color": INK_2},
    },
    "visualStyles": {
        "*": {
            "*": {
                "background": [{"show": True, "color": _c(SURFACE),
                                "transparency": 0}],
                # Rounded corners and a hairline, rather than the default
                # hard-edged grey box.
                "border": [{"show": True, "color": _c(GRID), "radius": 10}],
                "dropShadow": [{"show": True, "color": _c("#000000"),
                                "position": "Outer", "preset": "BottomRight",
                                "shadowSpread": 3, "transparency": 92}],
                "visualHeader": [{"show": False}],
                "title": [{"show": True, "fontColor": _c(INK), "fontSize": 11,
                           "fontFamily": FONT_SEMI, "alignment": "left",
                           "background": _c(SURFACE)}],
                "labels": [{"color": _c(INK_2), "fontSize": 9,
                            "fontFamily": FONT}],
                "legend": [{"show": True, "position": "Top", "showTitle": False,
                            "labelColor": _c(INK_2), "fontSize": 9,
                            "fontFamily": FONT}],
                # Recessive axes: no vertical gridlines, hairline horizontals.
                "categoryAxis": [{"show": True, "showAxisTitle": False,
                                  "labelColor": _c(INK_MUTED), "fontSize": 9,
                                  "gridlineShow": False,
                                  "axisColor": _c(GRID)}],
                "valueAxis": [{"show": True, "showAxisTitle": False,
                               "labelColor": _c(INK_MUTED), "fontSize": 9,
                               "gridlineShow": True, "gridlineColor": _c(GRID),
                               "gridlineThickness": 1, "gridlineStyle": "solid"}],
            }
        },
        "card": {
            "*": {
                "labels": [{"color": _c(BRAND), "fontSize": 26,
                            "fontFamily": FONT_SEMI, "labelDisplayUnits": 0}],
                "categoryLabels": [{"show": True, "color": _c(INK_MUTED),
                                    "fontSize": 9, "fontFamily": FONT}],
                "title": [{"show": False}],
                "wordWrap": [{"show": True}],
            }
        },
        "tableEx": {
            "*": {
                "grid": [{"gridVertical": False, "gridHorizontal": True,
                          "gridHorizontalColor": _c(GRID), "rowPadding": 4,
                          "outlineColor": _c(GRID), "outlineWeight": 1,
                          "textSize": 9}],
                "columnHeaders": [{"fontColor": _c(INK_MUTED),
                                   "backColor": _c(SURFACE), "fontSize": 9,
                                   "bold": True, "fontFamily": FONT_SEMI,
                                   "alignment": "Left", "wordWrap": True,
                                   "outline": "BottomOnly"}],
                "values": [{"fontColor": _c(INK), "backColor": _c(SURFACE),
                            "fontSize": 9, "fontFamily": FONT,
                            # Zebra striping - the single biggest readability
                            # win on a wide table.
                            "backColorSecondary": _c("#FAFAF8"),
                            "urlIcon": False, "wordWrap": False}],
                "total": [{"fontColor": _c(INK), "backColor": _c("#F2F1ED"),
                           "bold": True, "fontSize": 9,
                           "outline": "TopOnly"}],
            }
        },
        "slicer": {
            "*": {
                "background": [{"show": True, "color": _c(SURFACE),
                                "transparency": 0}],
                "border": [{"show": True, "color": _c(GRID), "radius": 8}],
                "dropShadow": [{"show": False}],
                "header": [{"show": True, "fontColor": _c(INK_MUTED),
                            "fontSize": 9, "fontFamily": FONT_SEMI,
                            "background": _c(SURFACE), "outline": "None"}],
                "items": [{"fontColor": _c(INK_2), "fontSize": 9,
                           "background": _c(SURFACE)}],
                "title": [{"show": False}],
            }
        },
        "lineChart": {
            "*": {
                "lineStyles": [{"strokeWidth": 3, "lineStyle": "solid",
                                "showMarker": False, "strokeLineJoin": "round"}],
            }
        },
        "barChart": {"*": {"labels": [{"show": True, "color": _c(INK_2),
                                       "fontSize": 9}]}},
        "columnChart": {"*": {"labels": [{"show": True, "color": _c(INK_2),
                                          "fontSize": 9}]}},
        "clusteredColumnChart": {"*": {"labels": [{"show": True,
                                                   "color": _c(INK_2),
                                                   "fontSize": 9}]}},
        "donutChart": {
            "*": {
                "slices": [{"innerRadiusRatio": 60}],
                "labels": [{"show": True, "color": _c(INK_2), "fontSize": 9,
                            "labelStyle": "Category, percent of total"}],
            }
        },
        # No textbox entry in the theme. A theme-level "background: show
        # false" beat the per-visual background and the brand header band
        # rendered as white text on a near-white page - invisible. Textbox
        # backgrounds are now set per visual, where they belong.
        "page": {
            "*": {
                "background": [{"color": _c(PAGE_BG), "transparency": 0}],
                "outspace": [{"color": _c(PAGE_BG), "transparency": 0}],
            }
        },
    },
}

# Absolute, so the template loads without the user editing anything. It is still
# a parameter, so it can be repointed at a Lakehouse or another folder from
# Transform data > Manage parameters.
DEFAULT_GOLD_FOLDER = str(GOLD)


# ===========================================================  DataModelSchema
def tmsl_columns(table: str) -> list[dict]:
    spec = sm.MODEL[table]
    hidden = set(spec.get("hidden", []))
    sort_by = spec.get("sortBy", {})
    cols = []
    for col, kind in spec["cols"].items():
        dtype, fmt = sm.TYPES[kind]
        c = {
            "name": col,
            "dataType": dtype,
            "sourceColumn": col,
            "summarizeBy": sm.summarize_for(spec, col),
        }
        if col in hidden:
            c["isHidden"] = True
        if col == spec.get("key"):
            c["isKey"] = True
        if fmt:
            c["formatString"] = fmt
        if col in sort_by:
            c["sortByColumn"] = sort_by[col]
        # Geocoding hints. Without them a filled map has to guess what "Free
        # State" is, finds candidates on three continents, and zooms out to the
        # whole world. Country plus StateOrProvince pins it to South Africa.
        if table == "DimMerchant" and col == "Region":
            c["dataCategory"] = "StateOrProvince"
        if table == "DimMerchant" and col == "Country":
            c["dataCategory"] = "Country"
        c["annotations"] = [{"name": "SummarizationSetBy", "value": "User"}]
        cols.append(c)
    return cols


def tmsl_measures() -> list[dict]:
    dax = (ROOT / "powerbi" / "dax" / "measures.dax").read_text(encoding="utf8")
    out = []
    for name, expr, fmt, folder, _desc in sm.parse_dax(dax):
        mea = {
            "name": name,
            "expression": expr.splitlines(),
            "lineageTag": sm.guid("measure", name),
        }
        if fmt:
            mea["formatString"] = fmt
        if folder:
            mea["displayFolder"] = folder
        out.append(mea)
    return out


def data_model_schema() -> dict:
    tables = []
    for name in sm.MODEL:
        spec = sm.MODEL[name]
        t = {
            "name": name,
            "lineageTag": sm.guid("table", name),
            "columns": tmsl_columns(name),
            "partitions": [{
                "name": name,
                "mode": "import",
                "source": {"type": "m", "expression": sm.m_partition(name)},
            }],
            "annotations": [{"name": "PBI_ResultType", "value": "Table"}],
        }
        if spec.get("dataCategory"):
            t["dataCategory"] = spec["dataCategory"]
        tables.append(t)

    # The measure table. A single hidden placeholder column gives it a
    # partition; nothing ever reads it.
    tables.append({
        "name": "_Measures",
        "lineageTag": sm.guid("table", "_Measures"),
        "columns": [{
            "name": "_placeholder", "dataType": "string",
            "sourceColumn": "_placeholder", "summarizeBy": "none",
            "isHidden": True,
            "annotations": [{"name": "SummarizationSetBy", "value": "Automatic"}],
        }],
        "partitions": [{
            "name": "_Measures", "mode": "import",
            "source": {"type": "m", "expression": [
                "let", '    Source = #table({"_placeholder"}, {{""}})',
                "in", "    Source"]},
        }],
        "measures": tmsl_measures(),
        "annotations": [{"name": "PBI_ResultType", "value": "Table"}],
    })

    relationships = []
    for f_tab, f_col, t_tab, t_col, active, _cross in sm.RELATIONSHIPS:
        rel = {
            "name": sm.guid("rel", f_tab, f_col, t_tab, t_col),
            "fromTable": f_tab, "fromColumn": f_col,
            "toTable": t_tab, "toColumn": t_col,
        }
        if not active:
            rel["isActive"] = False
        relationships.append(rel)

    return {
        "name": "MerchantVoucherIntelligence",
        "compatibilityLevel": 1567,
        "model": {
            "culture": "en-ZA",
            "defaultPowerBIDataSourceVersion": "powerBI_V3",
            "sourceQueryCulture": "en-ZA",
            # Stops a user dragging a raw column onto a chart and getting a
            # silent, unformatted, undocumented SUM.
            "discourageImplicitMeasures": True,
            "dataAccessOptions": {
                "legacyRedirects": True,
                "returnErrorValuesAsNull": True,
            },
            "tables": tables,
            "relationships": relationships,
            "expressions": [{
                "name": "GoldFolder",
                "kind": "m",
                "expression": f'"{DEFAULT_GOLD_FOLDER}" meta [IsParameterQuery=true, '
                              f'Type="Text", IsParameterQueryRequired=true]',
                "lineageTag": sm.guid("expr", "GoldFolder"),
                "annotations": [{"name": "PBI_NavigationStepName", "value": "Navigation"},
                                {"name": "PBI_ResultType", "value": "Text"}],
            }],
            "annotations": [
                {"name": "PBI_QueryOrder",
                 "value": json.dumps(list(sm.MODEL) + ["_Measures"])},
                {"name": "__PBI_TimeIntelligenceEnabled", "value": "0"},
                {"name": "PBIDesktopVersion", "value": PBIX_VERSION},
            ],
        },
    }


# =================================================================  Report
def entity_of(ref: dict) -> tuple[str, str]:
    if "Measure" in ref:
        return "_Measures", ref["Measure"]["Property"]
    return (ref["Column"]["Expression"]["SourceRef"]["Entity"],
            ref["Column"]["Property"])


def build_query(roles: dict) -> tuple[dict, dict]:
    """Turn {role: [field, ...]} into a prototypeQuery plus projections.

    Classic layout wants every entity aliased in `From`, and every projection
    referenced by a `queryRef` of the form Entity.Property. Getting the aliases
    wrong is the usual reason a restored visual comes back empty.
    """
    aliases, from_list = {}, []
    selects, projections = [], {}

    for role, fields in roles.items():
        if not fields:
            continue
        projections[role] = []
        for ref in fields:
            entity, prop = entity_of(ref)
            if entity not in aliases:
                alias = entity[0].lower() + str(len(aliases))
                aliases[entity] = alias
                from_list.append({"Name": alias, "Entity": entity, "Type": 0})
            alias = aliases[entity]
            qref = f"{entity}.{prop}"
            kind = "Measure" if "Measure" in ref else "Column"
            selects.append({
                kind: {"Expression": {"SourceRef": {"Source": alias}},
                       "Property": prop},
                "Name": qref,
            })
            projections[role].append({"queryRef": qref})

    return {"Version": 2, "From": from_list, "Select": selects}, projections


# Visual-CONTAINER properties. These live in `vcObjects`, not `objects`.
#
# This distinction is invisible until it bites: put `title` in `objects` and
# Power BI silently ignores it and auto-generates "Total Sales by Region"
# instead. Put `background` there and a coloured header band renders as a plain
# white card. Data-role formatting (labels, legend, axes, slicer header) stays
# in `objects` and works from there - which is exactly why the KPI card styling
# applied while every custom chart title did not.
VC_PROPERTIES = {"title", "subTitle", "background", "border", "dropShadow",
                 "visualHeader", "padding", "divider", "outspace",
                 "visualTooltip", "stylePreset"}


def split_objects(objects: dict) -> tuple[dict, dict]:
    data_objects, vc_objects = {}, {}
    for key, value in (objects or {}).items():
        (vc_objects if key in VC_PROPERTIES else data_objects)[key] = value
    return data_objects, vc_objects


def container(name, vtype, x, y, w, h, roles=None, *, objects=None, z=0,
              sort=None, title=None):
    single = {"visualType": vtype, "drillFilterOtherVisuals": True}
    if roles:
        query, projections = build_query(roles)
        single["projections"] = projections
        single["prototypeQuery"] = query
        if sort:
            entity, prop, direction = sort
            single["prototypeQuery"]["OrderBy"] = [{
                "Direction": 2 if direction == "desc" else 1,
                "Expression": ({"Measure": {"Expression": {"SourceRef": {
                    "Source": next(f["Name"] for f in query["From"]
                                   if f["Entity"] == entity)}}, "Property": prop}}
                    if entity == "_Measures" else
                    {"Column": {"Expression": {"SourceRef": {
                        "Source": next(f["Name"] for f in query["From"]
                                       if f["Entity"] == entity)}}, "Property": prop}}),
            }]
    obj = dict(objects or {})
    if title:
        obj.setdefault("title", [{"properties": {
            "show": {"expr": {"Literal": {"Value": "true"}}},
            "text": {"expr": {"Literal": {"Value": f"'{title}'"}}},
            "titleWrap": {"expr": {"Literal": {"Value": "true"}}},
        }}])
    data_objects, vc_objects = split_objects(obj)
    if data_objects:
        single["objects"] = data_objects
    if vc_objects:
        single["vcObjects"] = vc_objects

    cfg = {
        "name": name,
        "layouts": [{"id": 0, "position": {"x": x, "y": y, "z": z,
                                           "width": w, "height": h,
                                           "tabOrder": z * 100}}],
        "singleVisual": single,
    }
    return {"x": x, "y": y, "z": z, "width": w, "height": h,
            "config": json.dumps(cfg, separators=(",", ":")), "filters": "[]"}


def lit(value):
    return {"expr": {"Literal": {"Value": value}}}


def bg(colour, transparency=0):
    return [{"properties": {
        "show": lit("true"),
        "color": {"solid": {"color": lit(f"'{colour}'")}},
        "transparency": lit(f"{transparency}D"),
    }}]


def text_container(name, x, y, w, h, runs, z=0, background=None,
                   align="left", padding=None):
    paragraphs = [{
        "horizontalTextAlignment": align,
        "textRuns": [{
            "value": r["text"],
            "textStyle": {
                "fontSize": f"{r.get('size', 10)}pt",
                "fontWeight": r.get("weight", "normal"),
                "color": r.get("color", INK),
                "fontFamily": r.get("font", FONT),
            },
        }],
    } for r in runs]
    objects = {"general": [{"properties": {"paragraphs": paragraphs}}]}
    if background == "TRANSPARENT":
        # Sits directly on the page: no card, no border, no shadow.
        objects["background"] = [{"properties": {"show": lit("false")}}]
        objects["border"] = [{"properties": {"show": lit("false")}}]
        objects["dropShadow"] = [{"properties": {"show": lit("false")}}]
    elif background:
        objects["background"] = bg(background)
        objects["border"] = [{"properties": {"show": lit("false")}}]
        objects["dropShadow"] = [{"properties": {"show": lit("false")}}]
    data_objects, vc_objects = split_objects(objects)
    single = {
        "visualType": "textbox",
        "drillFilterOtherVisuals": True,
        "objects": data_objects,
    }
    if vc_objects:
        single["vcObjects"] = vc_objects
    cfg = {
        "name": name,
        "layouts": [{"id": 0, "position": {"x": x, "y": y, "z": z,
                                           "width": w, "height": h}}],
        "singleVisual": single,
    }
    return {"x": x, "y": y, "z": z, "width": w, "height": h,
            "config": json.dumps(cfg, separators=(",", ":")), "filters": "[]"}


def header(prefix, title, subtitle):
    """The coloured band across the top of every page.

    Two overlapping textboxes rather than one: the band carries the fill and
    the title, the subtitle sits beside it in a lighter tint. Giving every page
    the same band is what makes six pages read as one report rather than six.
    """
    return [
        text_container(f"{prefix}Band", 0, 0, 1280, 56, [
            {"text": " " + title, "size": 16, "weight": "bold",
             "color": "#FFFFFF", "font": FONT_SEMI}],
            z=0, background=BRAND),
        text_container(f"{prefix}Sub", 660, 18, 604, 28, [
            {"text": subtitle + " ", "size": 9, "color": "#C3D7F0"}],
            z=1, align="right", background="TRANSPARENT"),
    ]


M = sm  # shorthand for the field helpers below


def meas(name):
    return {"Measure": {"Expression": {"SourceRef": {"Entity": "_Measures"}},
                        "Property": name}}


def col(entity, prop):
    return {"Column": {"Expression": {"SourceRef": {"Entity": entity}},
                       "Property": prop}}


def kpi_card(name, x, y, w, h, measure_name, label, z=0, accent=None):
    """A KPI tile. `accent` tints the card and its number for status metrics,
    so a breach rate does not look like a sales figure."""
    tint = {"bad": TINT_BAD, "warn": TINT_WARN, "good": TINT_GOOD}.get(accent)
    ink = {"bad": BAD, "warn": "#8A5B00", "good": "#0A7A0A"}.get(accent, BRAND)
    objects = {
        "labels": [{"properties": {
            "fontSize": lit("26D"),
            "color": {"solid": {"color": lit(f"'{ink}'")}},
            "labelDisplayUnits": lit("0D"),
            "labelPrecision": lit("1D"),
        }}],
        "categoryLabels": [{"properties": {
            "show": lit("true"), "fontSize": lit("9D"),
            "color": {"solid": {"color": lit(f"'{INK_MUTED}'")}},
        }}],
    }
    if tint:
        objects["background"] = bg(tint)
    return container(name, "card", x, y, w, h, {"Values": [meas(measure_name)]},
                     z=z, objects=objects)


def slicer_v(name, x, y, w, h, field, title, z=0, mode="Dropdown"):
    return container(name, "slicer", x, y, w, h, {"Values": [field]},
                     z=z, objects={
                         # Slicer style (list vs dropdown) is a `data` property.
                         # Under `general` it is ignored and the slicer stays a
                         # vertical list, which at 56px shows one item and a
                         # scrollbar - exactly what it looked like.
                         "data": [{"properties": {"mode": lit(f"'{mode}'")}}],
                         "header": [{"properties": {
                             "show": lit("true"),
                             "text": lit(f"'{title}'"),
                             "fontSize": lit("9D"),
                         }}],
                     })


def note(name, x, y, w, text, z=90, h=34):
    """Small-print footnote: no card, no border, sits directly on the page."""
    return text_container(name, x, y, w, h,
                          [{"text": text, "size": 8, "color": INK_MUTED}],
                          z=z, background="TRANSPARENT")


def pages() -> list[tuple[str, list]]:
    """Six pages on one 1280x720 grid.

    Layout constants rather than ad-hoc numbers: 16px margin, 12px gutter, a
    56px header band, a 92px KPI row and a 56px slicer row. Everything below
    starts at y=228 and every visual snaps to the same column stops, which is
    what stops a report looking hand-placed.
    """
    P = []
    M0, G = 16, 12                 # margin, gutter
    FULL = 1280 - M0 * 2           # 1248
    HALF = (FULL - G) // 2         # 618
    KPI_Y, SLICER_Y, BODY_Y = 68, 168, 236

    def cols(n):
        """n equal columns across the content width, as (x, width) pairs."""
        w = (FULL - G * (n - 1)) // n
        return [(M0 + i * (w + G), w) for i in range(n)]

    # ------------------------------------------------ 1. Executive Overview
    v = header("ex", "Executive overview",
               "Jan - Jul 2026  |  25 merchants  |  5 provinces")
    kpis = [("Total Sales", None), ("Total Transactions", None),
            ("Redemption Rate %", None), ("Average Resolution Hours", None),
            ("SLA Breach %", "bad")]
    for i, ((mn, accent), (x, w)) in enumerate(zip(kpis, cols(5))):
        v.append(kpi_card(f"exKpi{i}", x, KPI_Y, w, 88, mn, mn, z=2 + i,
                          accent=accent))
    for i, (field, title, (x, w)) in enumerate(zip(
            [col("DimMerchant", "Region"), col("DimVoucherType", "VoucherType"),
             col("DimMerchant", "Channel"), col("DimDate", "MonthYear")],
            ["Region", "Voucher type", "Channel", "Month"], cols(4))):
        v.append(slicer_v(f"exSl{i}", x, SLICER_Y, w, 56, field, title, z=10 + i))

    c3 = cols(3)
    v += [
        container("exTrend", "lineChart", M0, BODY_Y, HALF, 224,
                  {"Category": [col("DimDate", "Date")], "Y": [meas("Total Sales")]},
                  title="Sales trend", z=20),
        container("exRegion", "barChart", c3[2][0] - c3[0][1] - G, BODY_Y,
                  c3[0][1], 224,
                  {"Category": [col("DimMerchant", "Region")],
                   "Y": [meas("Total Sales")]},
                  title="Sales by province", z=21,
                  sort=("_Measures", "Total Sales", "desc")),
        container("exVoucher", "donutChart", c3[2][0], BODY_Y, c3[2][1], 224,
                  {"Category": [col("DimVoucherType", "VoucherType")],
                   "Y": [meas("Total Sales")]},
                  title="Sales mix by voucher type", z=22),
        container("exTop", "barChart", M0, BODY_Y + 236, HALF, 220,
                  {"Category": [col("DimMerchant", "Merchant")],
                   "Y": [meas("Total Sales")]},
                  title="Merchants by sales value", z=23,
                  sort=("_Measures", "Total Sales", "desc")),
        container("exRedemption", "lineChart", M0 + HALF + G, BODY_Y + 236,
                  HALF, 220,
                  {"Category": [col("DimDate", "MonthYear")],
                   "Y": [meas("Redemption Rate %")]},
                  title="Redemption rate by month", z=24),
    ]
    P.append(("Executive Overview", v))

    # -------------------------------------------------- 2. Merchant Analysis
    v = header("mr", "Merchant analysis",
               "Right-click any merchant row to drill through")
    for i, (field, title, (x, w)) in enumerate(zip(
            [col("DimMerchant", "Region"), col("DimMerchantSegment", "Segment"),
             col("DimMerchantSegment", "RiskTier"), col("DimMerchant", "Channel")],
            ["Region", "ML segment", "Risk tier", "Channel"], cols(4))):
        v.append(slicer_v(f"mrSl{i}", x, 68, w, 56, field, title, z=1 + i))
    v += [
        container("mrScatter", "scatterChart", M0, 136, HALF, 268,
                  {"Category": [col("DimMerchant", "Merchant")],
                   "X": [meas("Total Sales")], "Y": [meas("Sales MoM %")],
                   "Size": [meas("Total Tickets")]},
                  title="Growth against scale  -  bubble size is ticket volume",
                  z=10),
        container("mrContribution", "barChart", M0 + HALF + G, 136, HALF, 268,
                  {"Category": [col("DimMerchant", "Merchant")],
                   "Y": [meas("Total Sales")],
                   "Tooltips": [meas("Sales Share of Total %")]},
                  title="Merchant contribution", z=11,
                  sort=("_Measures", "Total Sales", "desc")),
        container("mrTable", "tableEx", M0, 416, FULL, 268,
                  {"Values": [
                      col("DimMerchant", "Merchant"), col("DimMerchant", "Region"),
                      col("DimMerchantSegment", "Segment"), meas("Merchant Rank"),
                      meas("Total Sales"), meas("Sales Share of Total %"),
                      meas("Total Transactions"), meas("Average Basket Value"),
                      meas("Sales MoM %"), meas("Redemption Rate %"),
                      meas("Tickets per 1k Transactions"), meas("SLA Breach %"),
                      col("DimMerchantSegment", "RiskTier")]},
                  title="Merchant league table", z=12,
                  sort=("_Measures", "Total Sales", "desc")),
        note("mrNote", M0, 688, FULL,
             "Merchant Rank, share and month-on-month all respond to the "
             "slicers above - share is of the current selection, not of the "
             "national total.", h=30),
    ]
    P.append(("Merchant Analysis", v))

    # ------------------------------------------------- 3. Operational View
    v = header("op", "Operational view",
               "1,363 tickets  |  26.3% breach a target that is set backwards")
    kpis = [("Total Tickets", None), ("Average Resolution Hours", None),
            ("SLA Breach %", "bad"), ("Open Tickets", "warn"),
            ("Tickets per 1k Transactions", None)]
    for i, ((mn, accent), (x, w)) in enumerate(zip(kpis, cols(5))):
        v.append(kpi_card(f"opKpi{i}", x, KPI_Y, w, 88, mn, mn, z=2 + i,
                          accent=accent))
    for i, (field, title, (x, w)) in enumerate(zip(
            [col("DimPriority", "Priority"), col("DimTicketType", "TicketType"),
             col("DimMerchant", "Region"), col("FactSupportTickets", "Status")],
            ["Priority", "Ticket type", "Region", "Status"], cols(4))):
        v.append(slicer_v(f"opSl{i}", x, SLICER_Y, w, 56, field, title, z=10 + i))
    v += [
        # The headline visual on the whole report. Two bars per tier, read
        # against each other.
        container("opSla", "clusteredColumnChart", M0, BODY_Y, HALF, 232,
                  {"Category": [col("DimPriority", "Priority")],
                   "Y": [meas("Average Resolution Hours"),
                         meas("SLA Target Hours")]},
                  title="Resolution time against SLA target, by priority  -  "
                        "the queue runs backwards", z=20),
        container("opTrend", "lineChart", M0 + HALF + G, BODY_Y, HALF, 232,
                  {"Category": [col("DimDate", "MonthYear")],
                   "Y": [meas("Total Tickets")]},
                  title="Ticket volume by month", z=21),
        container("opTypes", "barChart", M0, BODY_Y + 244, 400, 204,
                  {"Category": [col("DimTicketType", "TicketType")],
                   "Y": [meas("Total Tickets")],
                   "Tooltips": [meas("SLA Breach %")]},
                  title="Ticket types", z=22,
                  sort=("_Measures", "Total Tickets", "desc")),
        container("opMerchants", "tableEx", M0 + 412, BODY_Y + 244,
                  FULL - 412, 204,
                  {"Values": [col("DimMerchant", "Merchant"),
                              col("DimMerchant", "Region"), meas("Total Tickets"),
                              meas("Tickets per 1k Transactions"),
                              meas("Average Resolution Hours"),
                              meas("SLA Breach %"), meas("Sales MoM %")]},
                  title="Merchant operational league table", z=23,
                  sort=("_Measures", "Tickets per 1k Transactions", "desc")),
        note("opNote", M0, 688, FULL,
             "Still-open tickets report elapsed hours, not time to resolution, "
             "so Average Resolution Hours blends two definitions - use Average "
             "Resolution Hours (Closed) where that matters.", h=30),
    ]
    P.append(("Operational View", v))

    # ------------------------------------------- 4. Geographic Intelligence
    v = header("ge", "Geographic intelligence",
               "5 of 9 provinces served  |  56% of land area uncovered")
    for i, (field, title, (x, w)) in enumerate(zip(
            [col("DimVoucherType", "VoucherType"), col("DimMerchant", "Channel"),
             col("DimDate", "MonthYear")],
            ["Voucher type", "Channel", "Month"], cols(3))):
        v.append(slicer_v(f"geSl{i}", x, 68, w, 56, field, title, z=1 + i))
    v += [
        # Country sits above Region in the Location well. Without it Bing finds
        # a "Free State" on three continents and zooms out to the whole world.
        container("geMap", "filledMap", M0, 136, HALF, 470,
                  {"Category": [col("DimMerchant", "RegionGeo")],
                   "Y": [meas("Total Sales")],
                   "Tooltips": [meas("Total Transactions"),
                                meas("Redemption Rate %"),
                                meas("Tickets per 1k Transactions"),
                                meas("Sales Momentum %")]},
                  title="Sales by province", z=10),
        container("geMomentum", "barChart", M0 + HALF + G, 136, HALF, 226,
                  {"Category": [col("DimMerchant", "Region")],
                   "Y": [meas("Sales Momentum %")]},
                  title="Provincial momentum  -  latest month vs prior three",
                  z=11, sort=("_Measures", "Sales Momentum %", "asc")),
        container("geTable", "tableEx", M0 + HALF + G, 374, HALF, 232,
                  {"Values": [col("DimMerchant", "Region"), meas("Total Sales"),
                              meas("Sales Share of Total %"),
                              meas("Redemption Rate %"),
                              meas("Tickets per 1k Transactions"),
                              meas("SLA Breach %"), meas("Sales Momentum %")]},
                  title="Province league table", z=12,
                  sort=("_Measures", "Total Sales", "desc")),
        note("geNote", M0, 614, FULL,
             "Only 5 of South Africa's 9 provinces carry merchants; the "
             "unserved four are 56% of the country's land area. That is a "
             "footprint observation, not a market opportunity - no population "
             "or GDP feed was supplied, and land area is a poor proxy for "
             "demand. The offline HTML report carries a true province "
             "choropleth built on Natural Earth boundaries.", h=64),
    ]
    P.append(("Geographic Intelligence", v))

    # ------------------------------------------------ 5. Intelligence & ML
    v = header("ai", "Intelligence and machine learning",
               "Every metric measured on data the model never saw")
    kpis = [("Forecast Next 30 Days", None), ("Merchants At Risk", "warn"),
            ("High Severity Anomalies", "bad"), ("Average Health Score", None)]
    for i, ((mn, accent), (x, w)) in enumerate(zip(kpis, cols(4))):
        v.append(kpi_card(f"aiKpi{i}", x, KPI_Y, w, 88, mn, mn, z=2 + i,
                          accent=accent))
    v += [
        container("aiActual", "lineChart", M0, 168, HALF, 244,
                  {"Category": [col("DimDate", "Date")],
                   "Y": [meas("Total Sales")]},
                  title="Daily sales, actual", z=10),
        # FactSalesForecast is deliberately unrelated to DimDate - its rows sit
        # beyond the last actual date - so it gets its own axis rather than a
        # blank series on a shared one.
        container("aiForecast", "lineChart", M0 + HALF + G, 168, HALF, 244,
                  {"Category": [col("FactSalesForecast", "Date")],
                   "Y": [meas("Forecast Sales Value"),
                         meas("Forecast Lower Bound"),
                         meas("Forecast Upper Bound")]},
                  title="Forecast, next 30 days, with 95% interval", z=11),
        container("aiSegments", "scatterChart", M0, 424, HALF, 216,
                  {"Category": [col("DimMerchant", "Merchant")],
                   "X": [meas("Avg PCA 1")],
                   "Y": [meas("Avg PCA 2")],
                   "Size": [meas("Average Health Score")],
                   "Series": [col("DimMerchantSegment", "Segment")]},
                  title="Merchant segments  -  K-Means, PCA projection", z=12),
        container("aiAnomalies", "tableEx", M0 + HALF + G, 424, HALF, 216,
                  {"Values": [col("FactAnomaly", "Date"),
                              col("FactAnomaly", "Merchant"),
                              col("FactAnomaly", "Measure"),
                              col("FactAnomaly", "DeviationPct"),
                              col("FactAnomaly", "Severity")]},
                  title="Detected anomalies  -  unsupervised", z=13),
        note("aiNote", M0, 648, FULL,
             "Redemption propensity AUC 0.621  |  SLA breach AUC 0.966 "
             "(5-fold CV)  |  segmentation silhouette 0.350 at k=3  |  forecast "
             "MAPE 2.47% against a 2.65% seasonal-naive benchmark. The "
             "delayed-redemption model scores at chance, which is the finding: "
             "the April lag spike had no predictable structural cause.", h=56),
    ]
    P.append(("Intelligence & ML", v))

    # --------------------------------------------------- 6. Insights & Notes
    v = header("no", "Insights, assumptions and next steps",
               "Every figure reproducible from build/ or fabric/sql/")
    findings = [
        ("1.  The support queue runs in reverse priority order.",
         "Critical tickets: 12h target, 52.7h actual, 98.3% breach. Low "
         "tickets: 48h target, 11.3h actual, 0.2% breach. The tightest target "
         "gets the slowest service. Cheapest fix on this page and it needs no "
         "new data. It is also why the SLA breach model scores 0.966 - breach "
         "is near-deterministic given the tier."),
        ("2.  Umhlanga Value Mart fell 44.7% - operational, not market.",
         "The fall came from transaction volume (-48.1%), not basket size "
         "(+6.4%), in the same month its tickets went from 3 to 37. Customers "
         "could not transact; they did not choose to spend less."),
        ("3.  Ticket volume leads sales. Resolution speed does not.",
         "Ticket intensity correlates with growth at r = -0.49; resolution "
         "hours at +0.19. Months after a ticket surge averaged -12.9% growth "
         "against +4.4% otherwise - on 3 surge months, so a strong signal on "
         "thin evidence. Durban Cash Hub has had an 8-fold ticket rise since "
         "June with sales not yet hit. That is the call to make this week."),
    ]
    y = 68
    for i, (title, body) in enumerate(findings):
        v.append(text_container(f"noF{i}", M0, y, FULL, 92, [
            {"text": title + "\n", "size": 11, "weight": "bold",
             "color": BRAND, "font": FONT_SEMI},
            {"text": body, "size": 9, "color": INK_2}],
            z=10 + i, background=SURFACE))
        y += 100

    col_w = (FULL - G) // 2
    v += [
        text_container("noAssume", M0, y, col_w, 336, [
            {"text": "Assumptions\n", "size": 11, "weight": "bold",
             "color": BRAND, "font": FONT_SEMI},
            {"text": "Delayed redemption means more than 7 days from sale, "
                     "against an observed median of about 3 days.\n"
                     "Unredeemed vouchers are excluded from the delay rate, "
                     "not counted as on-time - they have no outcome yet.\n"
                     "Merchant region and channel come from the reference file "
                     "only, verified identical on every fact row.\n"
                     "SLAHours is a property of the priority tier, not the "
                     "ticket, so it lives on DimPriority.\n"
                     "Sales targets are the monthly figure times months in the "
                     "period; no phasing was supplied.\n"
                     "FactAnomaly is deliberately unrelated to DimMerchant: 10 "
                     "of its rows are region-scope with a null merchant key, "
                     "and a nullable key adds a blank member to every merchant "
                     "slicer.", "size": 9, "color": INK_2}],
            z=40, background=SURFACE),
        text_container("noLimits", M0 + col_w + G, y, col_w, 336, [
            {"text": "Limitations\n", "size": 11, "weight": "bold",
             "color": BRAND, "font": FONT_SEMI},
            {"text": "Seven months of one year: no year-on-year comparison, and "
                     "seasonality cannot be separated from trend.\n"
                     "25 merchants is too few to validate a churn classifier, "
                     "so the health score is a transparent weighted percentile "
                     "index - which by construction always puts a quarter of "
                     "merchants in the bottom tier.\n"
                     "The delayed-redemption model scores at chance. Reported "
                     "rather than dropped: it is evidence the April incident "
                     "had no standing cause.\n"
                     "The forecast beats a seasonal-naive benchmark by 0.18pp "
                     "of MAPE on 28 held-out days - real, but slim.\n"
                     "The ticket-surge result rests on 3 merchant-months.\n"
                     "No causality is established anywhere in this analysis.",
             "size": 9, "color": INK_2}],
            z=41, background=SURFACE),
    ]
    P.append(("Insights & Notes", v))

    return P


def report_layout() -> dict:
    sections = []
    for i, (display, visuals) in enumerate(pages()):
        sections.append({
            "id": i,
            "name": f"page{i:02d}{abs(hash(display)) % 10**12:012d}",
            "displayName": display,
            "filters": "[]",
            "ordinal": i,
            "visualContainers": visuals,
            "config": "{}",
            "displayOption": 1,
            "width": 1280,
            "height": 720,
        })

    config = {
        "version": LAYOUT_VERSION,
        # type 2 = a shipped base theme, type 1 = a theme registered in this
        # report's own resources. The custom theme layers on top of the base.
        "themeCollection": {
            "baseTheme": {"name": BASE_THEME, "version": LAYOUT_VERSION,
                          "type": 2},
            "customTheme": {"name": CUSTOM_THEME, "version": LAYOUT_VERSION,
                            "type": 1},
        },
        "activeSectionIndex": 0,
        "defaultDrillFilterOtherVisuals": True,
        "settings": {
            "useNewFilterPaneExperience": True,
            "allowChangeFilterTypes": True,
            "useStylableVisualContainerHeader": True,
            "queryLimitOption": 6,
            "exportDataMode": 1,
            "useDefaultAggregateDisplayName": True,
        },
        "objects": {"section": [{"properties": {"verticalAlignment": {
            "expr": {"Literal": {"Value": "'Top'"}}}}}]},
    }

    return {
        "id": 0,
        "resourcePackages": [
            {"resourcePackage": {
                "name": "SharedResources", "type": 2,
                "items": [{"type": 202, "path": f"BaseThemes/{BASE_THEME}.json",
                           "name": BASE_THEME}],
                "disabled": False,
            }},
            {"resourcePackage": {
                "name": "RegisteredResources", "type": 1,
                "items": [{"type": 202, "path": f"{CUSTOM_THEME}.json",
                           "name": CUSTOM_THEME}],
                "disabled": False,
            }},
        ],
        "sections": sections,
        "config": json.dumps(config, separators=(",", ":")),
        "layoutOptimization": 0,
    }


# ====================================================================  pack
CONTENT_TYPES = (
    '<?xml version="1.0" encoding="utf-8"?>'
    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
    '<Default Extension="json" ContentType="" />'
    '<Override PartName="/Version" ContentType="" />'
    '<Override PartName="/DataModelSchema" ContentType="" />'
    '<Override PartName="/DiagramLayout" ContentType="" />'
    '<Override PartName="/Report/Layout" ContentType="" />'
    '<Override PartName="/Settings" ContentType="application/json" />'
    '<Override PartName="/Metadata" ContentType="application/json" />'
    "</Types>"
)


def u16(obj) -> bytes:
    """Every text part in a pbix/pbit is UTF-16LE with no BOM."""
    text = obj if isinstance(obj, str) else json.dumps(obj, separators=(",", ":"))
    return text.encode("utf-16-le")


def main() -> None:
    if not GOLD.exists():
        raise SystemExit("Gold layer missing - run build_gold.py first")

    schema = data_model_schema()
    layout = report_layout()

    # Reuse the base theme shipped inside the user's own Demo.pbix rather than
    # inventing one, so the template matches their Desktop build.
    theme = None
    if DEMO.exists():
        with zipfile.ZipFile(DEMO) as z:
            name = f"Report/StaticResources/SharedResources/BaseThemes/{BASE_THEME}.json"
            if name in z.namelist():
                theme = z.read(name)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("Version", u16(PBIX_VERSION))
        z.writestr("DataModelSchema", u16(schema))
        z.writestr("DiagramLayout", u16({
            "version": "1.1.0",
            "diagrams": [{"ordinal": 0, "scrollPosition": {"x": 0, "y": 0},
                          "nodes": [], "name": "All tables", "zoomValue": 100,
                          "pinKeyFieldsToTop": False,
                          "showExtraHeaderInfo": False,
                          "hideKeyFieldsWhenCollapsed": False,
                          "tablesLocked": False}],
            "selectedDiagram": "All tables", "defaultDiagram": "All tables",
        }))
        z.writestr("Report/Layout", u16(layout))
        z.writestr("Settings", u16({
            "Version": 4, "ReportSettings": {},
            "QueriesSettings": {"TypeDetectionEnabled": False,
                                "RelationshipImportEnabled": False,
                                "Version": "2.130.528.0"},
        }))
        # Type detection and relationship auto-import are switched OFF above on
        # purpose: the model already declares every type and relationship, and
        # letting Desktop guess would add duplicates on top of them.
        z.writestr("Metadata", u16({
            "Version": 5, "AutoCreatedRelationships": [],
            "CreatedFrom": "Desktop", "CreatedFromRelease": "2026.08",
        }))
        z.writestr("[Content_Types].xml", CONTENT_TYPES.encode("utf-8"))
        if theme:
            z.writestr(
                f"Report/StaticResources/SharedResources/BaseThemes/{BASE_THEME}.json",
                theme)
        # The custom theme is UTF-8, unlike the UTF-16 report parts.
        z.writestr(
            f"Report/StaticResources/RegisteredResources/{CUSTOM_THEME}.json",
            json.dumps(THEME, indent=1).encode("utf-8"))

    n_tables = len(schema["model"]["tables"])
    n_measures = len(schema["model"]["tables"][-1]["measures"])
    n_rel = len(schema["model"]["relationships"])
    n_visuals = sum(len(s["visualContainers"]) for s in layout["sections"])
    print(f"Wrote {OUT.relative_to(ROOT)}  ({OUT.stat().st_size / 1024:,.0f} KB)")
    print(f"  model : {n_tables} tables, {n_rel} relationships, {n_measures} measures")
    print(f"  report: {len(layout['sections'])} pages, {n_visuals} visuals")
    print(f"  data  : GoldFolder defaults to {DEFAULT_GOLD_FOLDER}")


if __name__ == "__main__":
    main()
