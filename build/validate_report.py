"""
validate_report.py
==================
Static checks over the generated PBIP. Power BI Desktop is not installed on the
build machine, so this is the substitute: it will not prove the report renders,
but it does prove that every field the report asks for exists in the semantic
model, that the JSON parses, and that nothing overlaps or falls off the canvas.

The reference check is the one that matters. A visual pointing at a measure
that was renamed is the single most common way a PBIP opens to a wall of
errors, and it is entirely detectable without opening anything.

Run:  python build/validate_report.py
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NAME = "MerchantVoucherIntelligence"
SM = ROOT / "powerbi" / f"{NAME}.SemanticModel" / "definition"
REPORT = ROOT / "powerbi" / f"{NAME}.Report"
DEF = REPORT / "definition"

CANVAS = {"default": (1280, 720), "tooltipMerchant": (330, 260)}

failures: list[str] = []
notes: list[str] = []


def fail(msg: str) -> None:
    failures.append(msg)


def model_fields() -> tuple[dict[str, set[str]], set[str]]:
    """Every column per table, and every measure name, read from the TMDL."""
    columns: dict[str, set[str]] = {}
    for f in (SM / "tables").glob("*.tmdl"):
        text = f.read_text(encoding="utf8")
        table = re.search(r"^table (\S+)", text, re.M).group(1)
        columns[table] = set(re.findall(r"^\tcolumn (\S+)", text, re.M))
    measures = set(re.findall(r"^\tmeasure '([^']+)'",
                              (SM / "tables" / "_Measures.tmdl").read_text(encoding="utf8"),
                              re.M))
    return columns, measures


def walk_fields(node, out):
    """Collect every Measure/Column reference anywhere in a visual's JSON."""
    if isinstance(node, dict):
        if "Measure" in node and isinstance(node["Measure"], dict):
            out.append(("measure", "_Measures", node["Measure"]["Property"]))
        if "Column" in node and isinstance(node["Column"], dict):
            ent = node["Column"].get("Expression", {}).get("SourceRef", {}).get("Entity")
            out.append(("column", ent, node["Column"]["Property"]))
        for v in node.values():
            walk_fields(v, out)
    elif isinstance(node, list):
        for v in node:
            walk_fields(v, out)


def main() -> None:
    columns, measures = model_fields()
    tables = set(columns)

    # ---------------------------------------------------------- structure --
    for required in (REPORT / ".platform", REPORT / "definition.pbir",
                     DEF / "report.json", DEF / "pages" / "pages.json",
                     ROOT / "powerbi" / f"{NAME}.pbip"):
        if not required.exists():
            fail(f"missing required file: {required.relative_to(ROOT)}")

    pbir = json.loads((REPORT / "definition.pbir").read_text(encoding="utf8"))
    # The path in definition.pbir is relative to the .Report folder itself.
    ds = pbir["datasetReference"]["byPath"]["path"]
    if not (REPORT / ds).resolve().exists():
        fail(f"definition.pbir points at a semantic model that does not exist: {ds}")

    pages_meta = json.loads((DEF / "pages" / "pages.json").read_text(encoding="utf8"))
    page_dirs = {p.name for p in (DEF / "pages").iterdir() if p.is_dir()}
    if set(pages_meta["pageOrder"]) != page_dirs:
        fail(f"pages.json order {sorted(pages_meta['pageOrder'])} does not match "
             f"folders {sorted(page_dirs)}")
    if pages_meta["activePageName"] not in page_dirs:
        fail("activePageName is not a real page")

    # ------------------------------------------------------------ visuals --
    total_visuals = 0
    bad_refs = 0
    for pdir in sorted((DEF / "pages").iterdir()):
        if not pdir.is_dir():
            continue
        page = json.loads((pdir / "page.json").read_text(encoding="utf8"))
        cw, ch = CANVAS.get(page["name"], CANVAS["default"])
        if page.get("width") != cw or page.get("height") != ch:
            fail(f"{page['name']}: canvas {page.get('width')}x{page.get('height')} "
                 f"expected {cw}x{ch}")

        boxes = []
        for vdir in sorted((pdir / "visuals").iterdir()):
            vis = json.loads((vdir / "visual.json").read_text(encoding="utf8"))
            total_visuals += 1
            if vis["name"] != vdir.name:
                fail(f"{page['name']}/{vdir.name}: visual name '{vis['name']}' "
                     f"does not match its folder")

            pos = vis["position"]
            if (pos["x"] < 0 or pos["y"] < 0
                    or pos["x"] + pos["width"] > cw
                    or pos["y"] + pos["height"] > ch):
                fail(f"{page['name']}/{vis['name']}: falls outside the "
                     f"{cw}x{ch} canvas "
                     f"(x{pos['x']} y{pos['y']} w{pos['width']} h{pos['height']})")
            boxes.append((vis["name"], pos))

            refs = []
            walk_fields(vis, refs)
            for kind, entity, prop in refs:
                if kind == "measure":
                    if prop not in measures:
                        fail(f"{page['name']}/{vis['name']}: measure "
                             f"[{prop}] is not in the model")
                        bad_refs += 1
                else:
                    if entity not in tables:
                        fail(f"{page['name']}/{vis['name']}: table "
                             f"'{entity}' is not in the model")
                        bad_refs += 1
                    elif prop not in columns[entity]:
                        fail(f"{page['name']}/{vis['name']}: column "
                             f"{entity}[{prop}] is not in the model")
                        bad_refs += 1

            vt = vis["visual"]["visualType"]
            if vt not in ("textbox", "card", "slicer", "shapeMap") \
                    and not vis["visual"]["query"].get("queryState"):
                fail(f"{page['name']}/{vis['name']}: {vt} has no query projections")

        # Overlap check: two visuals sharing pixels is always a layout mistake.
        for i in range(len(boxes)):
            for j in range(i + 1, len(boxes)):
                (n1, a), (n2, b) = boxes[i], boxes[j]
                if (a["x"] < b["x"] + b["width"] and b["x"] < a["x"] + a["width"]
                        and a["y"] < b["y"] + b["height"]
                        and b["y"] < a["y"] + a["height"]):
                    fail(f"{page['name']}: '{n1}' overlaps '{n2}'")

        # Page-type rules.
        if page["name"] == "drillMerchant":
            if page.get("pageBinding", {}).get("type") != "Drillthrough":
                fail("drillMerchant is not bound as a drill-through page")
            fields = [f["field"] for f in page.get("filterConfig", {}).get("filters", [])]
            if not fields:
                fail("drillMerchant has no drill-through filter field")
        if page["name"] == "tooltipMerchant" \
                and page.get("pageBinding", {}).get("type") != "Tooltip":
            fail("tooltipMerchant is not bound as a tooltip page")

    # ---------------------------------------------------------- shape map --
    topo = json.loads((REPORT / "StaticResources" / "RegisteredResources"
                       / "za_provinces.json").read_text(encoding="utf8"))
    if topo.get("type") != "Topology":
        fail("shape map resource is not a TopoJSON Topology")
    geoms = topo["objects"]["provinces"]["geometries"]
    arcs = topo["arcs"]
    for g in geoms:
        # Polygon.arcs must be [ring, ...]; ring must be [arcIndex, ...].
        if g["type"] == "Polygon":
            if not all(isinstance(r, list) and all(isinstance(i, int) for i in r)
                       for r in g["arcs"]):
                fail(f"{g['properties']['name']}: Polygon arcs are nested wrongly")
        else:
            if not all(isinstance(p, list) and all(isinstance(r, list) for r in p)
                       for p in g["arcs"]):
                fail(f"{g['properties']['name']}: MultiPolygon arcs nested wrongly")
        for ring in (g["arcs"] if g["type"] == "Polygon"
                     else [r for p in g["arcs"] for r in p]):
            for idx in ring:
                if not 0 <= idx < len(arcs):
                    fail(f"{g['properties']['name']}: arc index {idx} out of range")

    # The shape map binds on province NAME, so the values in DimMerchant[Region]
    # must match the topology's name property exactly or the map draws blank.
    import csv
    regions = {r["Region"] for r in
               csv.DictReader((ROOT / "data" / "gold" / "DimMerchant.csv")
                              .open(encoding="utf8"))}
    topo_names = {g["properties"]["name"] for g in geoms}
    unmatched = regions - topo_names
    if unmatched:
        fail(f"regions with no matching province in the shape map: {sorted(unmatched)}")
    notes.append(f"{len(regions)} of {len(topo_names)} provinces carry merchants; "
                 f"unserved: {sorted(topo_names - regions)}")

    # ------------------------------------------------------------- report --
    print(f"Report:  {total_visuals} visuals across {len(page_dirs)} pages")
    print(f"Model:   {len(tables)} tables, {sum(len(c) for c in columns.values())} "
          f"columns, {len(measures)} measures")
    for n in notes:
        print(f"Note:    {n}")
    print()
    if failures:
        for f in failures:
            print(f"  FAIL  {f}")
        print(f"\n{len(failures)} problem(s) found.")
        sys.exit(1)
    print("All static checks passed: every field reference resolves, no visual "
          "overlaps or overflows, shape map topology is well formed.")
    print("Still unverified: actual rendering in Power BI Desktop (not installed).")


if __name__ == "__main__":
    main()
