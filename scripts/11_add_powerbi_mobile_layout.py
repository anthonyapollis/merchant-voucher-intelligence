"""
SUPERSEDED — do not run. Use 32_pbit_mobile_layout.py instead.

This wrote the phone layout into the PBIR folder (MerchantVoucherIntelligence.Report), which
was the .pbip-format artifact. That artifact stopped at 8 pages while the delivered .pbit grew
to 12, so this script was reporting "phone layout added to 8 pages" while the template that
actually ships had no phone layout at all — a build log agreeing with itself and with nothing
else.

32_pbit_mobile_layout.py writes the layout directly into the .pbit, covering all 12 pages, and
runs as part of scripts/rebuild_pbit.py. The PBIR folder now lives in _superseded/.
"""
import sys

print(__doc__.strip())
sys.exit(0)

"""
11_add_powerbi_mobile_layout.py
===============================
Adds a phone layout to every page of the PBIR report definition.

Power BI does NOT auto-generate a usable mobile view. Without an explicit phone layout the
app shows the desktop canvas scaled down, which makes a 1280x720 executive page unreadable on
a handset — and the people most likely to open this on a phone (regional managers, account
managers between merchant visits) are exactly the audience the report is for.

Approach: single-column stack on the standard 320x568 phone canvas, ordered by the desktop
reading order (top-to-bottom, then left-to-right). Heights are assigned per visual type, not
copied from desktop — a card that is 92px wide-format needs less vertical space than a table.

Slicers are kept but moved to the end: on a phone, filters below the numbers beat filters
above them, because the first screenful should answer the question rather than ask one.
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PAGES = ROOT / "powerbi" / "MerchantVoucherIntelligence.Report" / "definition" / "pages"

PHONE_W = 320
GUTTER = 8
MARGIN = 8

# Vertical space per visual type on a phone. Tables and maps need room; cards do not.
HEIGHTS = {
    "card": 96, "multiRowCard": 150, "kpi": 110,
    "slicer": 64, "advancedSlicerVisual": 64,
    "textbox": 60, "actionButton": 44, "shape": 40, "image": 90,
    "clusteredBarChart": 240, "clusteredColumnChart": 240, "barChart": 240,
    "columnChart": 240, "lineChart": 220, "lineClusteredColumnComboChart": 240,
    "areaChart": 220, "donutChart": 230, "pieChart": 230, "ringChart": 230,
    "scatterChart": 250, "map": 280, "filledMap": 280, "shapeMap": 280,
    "tableEx": 280, "pivotTable": 280, "matrix": 280,
    "textboxVisual": 60,
}
DEFAULT_H = 220
# Decorative desktop-only furniture: page titles and background shapes just waste a phone
# screen, so they are hidden rather than stacked.
HIDE_TYPES = {"shape"}
HIDE_NAME_PREFIX = ("exTitle", "mrTitle", "opTitle", "geTitle", "aiTitle", "dtTitle")

changed_pages, changed_visuals = 0, 0

for page_dir in sorted(p for p in PAGES.iterdir() if p.is_dir()):
    vis_dir = page_dir / "visuals"
    if not vis_dir.exists():
        continue

    visuals = []
    for vf in sorted(vis_dir.glob("*/visual.json")):
        v = json.loads(vf.read_text(encoding="utf-8"))
        pos = v.get("position", {})
        vtype = (v.get("visual") or {}).get("visualType", "")
        visuals.append({"file": vf, "json": v, "type": vtype,
                        "x": pos.get("x", 0), "y": pos.get("y", 0),
                        "name": v.get("name", vf.parent.name)})
    if not visuals:
        continue

    # Desktop reading order: banded by row (60px tolerance), then left-to-right
    visuals.sort(key=lambda v: (round(v["y"] / 60), v["x"]))

    # Slicers last — on a phone the first screenful should answer, not ask
    body = [v for v in visuals if "slicer" not in v["type"].lower()]
    slicers = [v for v in visuals if "slicer" in v["type"].lower()]
    ordered = body + slicers

    cursor = MARGIN
    for v in ordered:
        hide = v["type"] in HIDE_TYPES or v["name"].startswith(HIDE_NAME_PREFIX)
        h = HEIGHTS.get(v["type"], DEFAULT_H)

        v["json"]["mobileState"] = {
            "position": {
                "x": MARGIN,
                "y": MARGIN if hide else cursor,
                "z": v["json"].get("position", {}).get("z", 0),
                "width": PHONE_W - 2 * MARGIN,
                "height": h,
                "tabOrder": v["json"].get("position", {}).get("tabOrder", 0),
            },
            "isHidden": hide,
        }
        if not hide:
            cursor += h + GUTTER

        v["file"].write_text(json.dumps(v["json"], indent=2), encoding="utf-8")
        changed_visuals += 1

    # Tell the page how tall its phone canvas is, so PBI does not clip the stack
    pf = page_dir / "page.json"
    pj = json.loads(pf.read_text(encoding="utf-8"))
    pj["mobileState"] = {"height": max(cursor + MARGIN, 568), "width": PHONE_W,
                         "displayOption": "FitToWidth"}
    pf.write_text(json.dumps(pj, indent=2), encoding="utf-8")
    changed_pages += 1

    shown = sum(1 for v in ordered if not v["json"]["mobileState"]["isHidden"])
    print(f"  {pj.get('displayName', page_dir.name):<26} {shown:>2} visuals stacked, "
          f"{len(ordered)-shown} hidden, canvas {PHONE_W}x{max(cursor + MARGIN, 568)}")

print(f"\nPhone layout added to {changed_pages} pages / {changed_visuals} visuals.")
print("Open the .pbip in Power BI Desktop -> View -> Mobile layout to review and nudge.")
