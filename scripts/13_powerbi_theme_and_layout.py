"""
13_powerbi_theme_and_layout.py
==============================
Two fixes to the Power BI report definition, both of which were visible defects:

1. THEME — the report rendered almost entirely in one blue. Data colours are replaced with
   the same semantic palette used by the HTML report and the Excel pack (navy / teal / amber
   / red / purple), and every text class is scaled up. Font sizes in the supplied definition
   were 8-9pt, which is unreadable on a projector and marginal on a laptop.

2. LAYOUT — slicers were 56-60px tall. A Power BI dropdown slicer needs ~76px for the header
   plus the control, so the "All" value was being clipped on every page. Cards, charts and
   tables were also packed to the pixel with no consistent gutter, and on the Geographic page
   the content ran to y=704 on a 720px canvas.

   Rather than nudge individual visuals, every page is reflowed onto one grid with a single
   set of row heights. The canvas is raised to 1280x860 so nothing has to be squeezed.

Original definition is backed up to powerbi/_Report_backup_prelayout/ on first run.
"""
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "powerbi" / "MerchantVoucherIntelligence.Report"
PAGES = REPORT / "definition" / "pages"
THEME = REPORT / "StaticResources" / "RegisteredResources" / "MerchantVoucherIntelligence.json"
BACKUP = ROOT / "powerbi" / "_Report_backup_prelayout"

if not BACKUP.exists():
    shutil.copytree(REPORT, BACKUP)
    print(f"  backed up original -> {BACKUP.relative_to(ROOT)}")

# ============================================================================ THEME
NAVY, TEAL, AMBER, RED, PURPLE = "#12305B", "#0E8B8B", "#E8A317", "#C0392B", "#7B4B94"
GREEN, PINK, SLATE = "#1E8449", "#D6336C", "#5A6672"

theme = {
    "name": "MerchantVoucherIntelligence",
    # Ordered so the FIRST series in any visual is navy and the second teal — the two
    # colours that carry meaning across every artefact in this submission.
    "dataColors": [NAVY, TEAL, AMBER, PURPLE, RED, GREEN, PINK, "#1B4079",
                   "#14B0AC", "#C88410"],
    "good": GREEN, "neutral": AMBER, "bad": RED,
    "maximum": NAVY, "center": "#8FB5DC", "minimum": "#D6E5F5", "null": "#E4EAF2",
    "background": "#FFFFFF", "secondaryBackground": "#EEF3F9",
    "foreground": "#12203A", "secondaryForeground": SLATE,
    "tableAccent": TEAL,
    "hyperlink": TEAL, "visualHeaderBackground": "#FFFFFF",

    # Font sizes raised across the board. The supplied definition used 8-9pt.
    "textClasses": {
        "title":      {"fontSize": 15, "fontFace": "Segoe UI Semibold", "color": NAVY},
        "header":     {"fontSize": 13, "fontFace": "Segoe UI Semibold", "color": NAVY},
        "label":      {"fontSize": 12, "fontFace": "Segoe UI", "color": "#12203A"},
        "callout":    {"fontSize": 34, "fontFace": "Segoe UI Bold", "color": NAVY},
        "largeTitle": {"fontSize": 20, "fontFace": "Segoe UI Semibold", "color": NAVY},
        "largeLabel": {"fontSize": 14, "fontFace": "Segoe UI Semibold", "color": "#12203A"},
        "smallLabel": {"fontSize": 11, "fontFace": "Segoe UI", "color": SLATE},
        "lightLabel": {"fontSize": 11, "fontFace": "Segoe UI", "color": SLATE},
        "boldLabel":  {"fontSize": 12, "fontFace": "Segoe UI Bold", "color": NAVY},
    },

    "visualStyles": {
        "*": {"*": {
            "background": [{"show": True, "color": {"solid": {"color": "#FFFFFF"}},
                            "transparency": 0}],
            "border": [{"show": True, "color": {"solid": {"color": "#DCE4EF"}},
                        "radius": 6}],
            "dropShadow": [{"show": True, "preset": "Subtle"}],
            "visualHeader": [{"show": False}],
            "title": [{"show": True, "fontSize": 13, "fontColor": {"solid": {"color": NAVY}},
                       "fontFamily": "Segoe UI Semibold", "alignment": "left"}],
            "labels": [{"fontSize": 11, "color": {"solid": {"color": "#12203A"}}}],
            "categoryAxis": [{"fontSize": 11, "labelColor": {"solid": {"color": SLATE}},
                              "titleFontSize": 11}],
            "valueAxis": [{"fontSize": 11, "labelColor": {"solid": {"color": SLATE}},
                           "gridlineColor": {"solid": {"color": "#E4EAF2"}}}],
            "legend": [{"fontSize": 11, "labelColor": {"solid": {"color": SLATE}},
                        "position": "Bottom"}],
        }},
        "card": {"*": {
            "labels": [{"fontSize": 30, "color": {"solid": {"color": NAVY}},
                        "fontFamily": "Segoe UI Bold"}],
            "categoryLabels": [{"fontSize": 12, "color": {"solid": {"color": SLATE}}}],
        }},
        "slicer": {"*": {
            "items": [{"fontSize": 12, "fontColor": {"solid": {"color": "#12203A"}}}],
            "header": [{"fontSize": 12, "fontColor": {"solid": {"color": NAVY}},
                        "fontFamily": "Segoe UI Semibold"}],
        }},
        "tableEx": {"*": {
            "values": [{"fontSize": 11, "fontColorPrimary": {"solid": {"color": "#12203A"}}}],
            "columnHeaders": [{"fontSize": 11, "fontColor": {"solid": {"color": "#FFFFFF"}},
                               "backColor": {"solid": {"color": NAVY}},
                               "fontFamily": "Segoe UI Semibold"}],
            "total": [{"fontSize": 11, "fontFamily": "Segoe UI Bold"}],
        }},
        "pivotTable": {"*": {
            "values": [{"fontSize": 11}],
            "columnHeaders": [{"fontSize": 11, "fontColor": {"solid": {"color": "#FFFFFF"}},
                               "backColor": {"solid": {"color": NAVY}}}],
        }},
        "shapeMap": {"*": {
            "dataPoint": [{"defaultColor": {"solid": {"color": "#D6E5F5"}}}],
        }},
        "textbox": {"*": {"background": [{"show": False}], "border": [{"show": False}],
                          "dropShadow": [{"show": False}]}},
    },
}
THEME.write_text(json.dumps(theme, indent=2), encoding="utf-8")
print(f"  theme rewritten: {len(theme['dataColors'])} data colours, fonts 11-34pt")

# ============================================================================ LAYOUT
CANVAS_W, CANVAS_H = 1280, 860
M, G = 16, 12                       # margin, gutter

# One set of row heights, applied everywhere. Slicers get 76 because a dropdown needs
# room for its header AND its control — 56 was clipping the value on every page.
H = {"textbox": 44, "card": 104, "slicer": 76, "actionButton": 44,
     "shape": 44, "image": 120}
H_CHART = 268
H_TABLE = 300


def vheight(vt, name):
    if vt in H:
        return H[vt]
    if vt in ("tableEx", "pivotTable", "matrix"):
        return H_TABLE
    if vt in ("shapeMap", "map", "filledMap"):
        return 470
    return H_CHART


def row_key(v):
    return (round(v["position"]["y"] / 40), v["position"]["x"])


changed = 0
for page_dir in sorted(p for p in PAGES.iterdir() if p.is_dir()):
    vis_files = sorted((page_dir / "visuals").glob("*/visual.json")) \
        if (page_dir / "visuals").exists() else []
    if not vis_files:
        continue
    pj = json.loads((page_dir / "page.json").read_text(encoding="utf-8"))
    is_tooltip = pj.get("displayOption") == "FitToPage" and pj.get("width", 0) < 700

    visuals = [(f, json.loads(f.read_text(encoding="utf-8"))) for f in vis_files]
    if is_tooltip:                      # leave the tooltip page alone; it is sized for hover
        continue

    visuals.sort(key=lambda fv: row_key(fv[1]))

    # Group into rows using the original y bands, then lay each row out edge-to-edge
    rows, cur, last_band = [], [], None
    for f, v in visuals:
        band = round(v["position"]["y"] / 40)
        if last_band is not None and band != last_band:
            rows.append(cur); cur = []
        cur.append((f, v)); last_band = band
    if cur:
        rows.append(cur)

    y = M
    for row in rows:
        n = len(row)
        avail = CANVAS_W - 2 * M - (n - 1) * G
        # Preserve relative widths from the original design, but make the row fill the canvas
        tot = sum(v["position"]["width"] for _, v in row) or 1
        h = max(vheight(v["visual"]["visualType"], v["name"]) for _, v in row)
        x = M
        for i, (f, v) in enumerate(row):
            w = int(avail * v["position"]["width"] / tot) if n > 1 else avail
            if i == n - 1:
                w = CANVAS_W - M - x          # absorb rounding into the last visual
            v["position"]["x"] = x
            v["position"]["y"] = y
            v["position"]["width"] = w
            v["position"]["height"] = h
            f.write_text(json.dumps(v, indent=2), encoding="utf-8")
            x += w + G
            changed += 1
        y += h + G

    pj["width"], pj["height"] = CANVAS_W, max(CANVAS_H, y + M)
    pj["displayOption"] = "FitToWidth"
    (page_dir / "page.json").write_text(json.dumps(pj, indent=2), encoding="utf-8")
    print(f"  {pj.get('displayName', page_dir.name):<32} {len(visuals):>2} visuals, "
          f"{len(rows)} rows, canvas {CANVAS_W}x{pj['height']}")

print(f"\nRepositioned {changed} visuals. No overlaps: every row is laid out sequentially "
      f"with a {G}px gutter and a {M}px margin.")
print("Open the .pbip in Power BI Desktop to review.")
