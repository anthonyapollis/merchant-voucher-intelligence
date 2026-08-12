"""
validate_pbit.py
================
Static checks on the generated .pbit. Power BI Desktop is not installed here, so
this substitutes for opening it: it verifies the package structure, the encoding
of every part, that the TMSL model is internally consistent, and that every
field the report asks for exists in that model.

It cannot prove the template renders. It can prove the things that would stop it
rendering for a reason detectable from the file alone.

Run:  python build/validate_pbit.py
"""

from __future__ import annotations

import json
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PBIT = ROOT / "powerbi" / "MerchantVoucherIntelligence.pbit"
GOLD = ROOT / "data" / "gold"

failures: list[str] = []
warnings: list[str] = []


def fail(msg):
    failures.append(msg)


def main() -> None:
    if not PBIT.exists():
        raise SystemExit("pbit not found - run build_pbit.py")

    z = zipfile.ZipFile(PBIT)
    names = set(z.namelist())

    # ------------------------------------------------------------ package --
    required = {"Version", "DataModelSchema", "Report/Layout",
                "[Content_Types].xml", "Settings", "Metadata", "DiagramLayout"}
    missing = required - names
    if missing:
        fail(f"missing parts: {sorted(missing)}")
    if "DataModel" in names:
        fail("a .pbit must not contain a binary DataModel part")

    # Every text part except [Content_Types].xml must be UTF-16LE.
    for part in names - {"[Content_Types].xml"}:
        # Themes are UTF-8: the base one is copied verbatim out of Demo.pbix,
        # and the custom one is written as UTF-8 to match. Only the report and
        # model parts are UTF-16LE.
        if part.endswith(".json") and "StaticResources" in part:
            json.loads(z.read(part).decode("utf-8"))  # must still be valid JSON
            continue
        raw = z.read(part)
        try:
            raw.decode("utf-16-le")
        except UnicodeDecodeError:
            fail(f"{part} is not valid UTF-16LE")
        if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
            fail(f"{part} has a BOM; Power BI expects none")

    ct = z.read("[Content_Types].xml").decode("utf-8")
    for part in ("/Version", "/DataModelSchema", "/Report/Layout"):
        if part not in ct:
            fail(f"[Content_Types].xml does not declare {part}")

    # ------------------------------------------------------------- model --
    schema = json.loads(z.read("DataModelSchema").decode("utf-16-le"))
    model = schema["model"]
    tables = {t["name"]: t for t in model["tables"]}
    columns = {n: {c["name"] for c in t["columns"]} for n, t in tables.items()}
    measures = {m["name"] for t in tables.values() for m in t.get("measures", [])}

    if schema.get("compatibilityLevel", 0) < 1500:
        fail("compatibilityLevel is too low for a modern model")

    for name, t in tables.items():
        if not t.get("columns"):
            fail(f"{name}: no columns")
        if not t.get("partitions"):
            fail(f"{name}: no partition")
        for p in t.get("partitions", []):
            src = p.get("source", {})
            if src.get("type") != "m" or not src.get("expression"):
                fail(f"{name}: partition has no M expression")
                continue
            m_text = "\n".join(src["expression"])
            # REGRESSION GUARD. The model culture is en-ZA, which uses a comma
            # as the decimal separator; the CSVs use a period. Without an
            # explicit culture on TransformColumnTypes every decimal column
            # loads empty, integers load fine, and the report shows a mix of
            # correct and BLANK measures with no error anywhere. This exact bug
            # shipped once. It does not get to ship twice.
            if "Table.TransformColumnTypes" in m_text and '"en-US"' not in m_text:
                fail(f"{name}: TransformColumnTypes has no culture argument - "
                     f"decimal columns will load blank under the en-ZA model "
                     f"culture")
        # sortByColumn must point at a real column in the same table.
        for c_ in t["columns"]:
            sb = c_.get("sortByColumn")
            if sb and sb not in columns[name]:
                fail(f"{name}[{c_['name']}]: sortByColumn '{sb}' does not exist")
            if c_.get("dataType") not in ("string", "int64", "double", "dateTime",
                                          "decimal", "boolean"):
                fail(f"{name}[{c_['name']}]: bad dataType {c_.get('dataType')}")

    # Relationship endpoints must exist, and each pair may have only one active.
    active_pairs = {}
    for r in model["relationships"]:
        for tab, col_ in ((r["fromTable"], r["fromColumn"]),
                          (r["toTable"], r["toColumn"])):
            if tab not in tables:
                fail(f"relationship references missing table {tab}")
            elif col_ not in columns[tab]:
                fail(f"relationship references missing column {tab}[{col_}]")
        if r.get("isActive", True):
            key = (r["fromTable"], r["toTable"])
            active_pairs[key] = active_pairs.get(key, 0) + 1
    for (a, b), n in active_pairs.items():
        if n > 1:
            fail(f"{n} active relationships between {a} and {b} - only one allowed")

    if not model.get("expressions"):
        warnings.append("no M parameter defined")

    # REGRESSION GUARD. A relationship whose "many" side has null keys makes
    # Power BI add a blank member to the table on the "one" side, and that blank
    # then appears as "(Blank)" in every slicer built on that table. Checked
    # against the actual CSV rather than assumed.
    import csv as _csv
    for r in model["relationships"]:
        src = GOLD / f"{r['fromTable']}.csv"
        if not src.exists():
            continue
        with src.open(encoding="utf8") as fh:
            nulls = sum(1 for row in _csv.DictReader(fh)
                        if not (row.get(r["fromColumn"]) or "").strip())
        if nulls:
            fail(f"{r['fromTable']}[{r['fromColumn']}] has {nulls} null keys but "
                 f"is related to {r['toTable']} - this injects a blank member "
                 f"into every {r['toTable']} slicer")

    # Every table must have a gold CSV behind it, or the load fails on open.
    for name in tables:
        if name == "_Measures":
            continue
        if not (GOLD / f"{name}.csv").exists():
            fail(f"{name}: no matching CSV in data/gold")

    # ------------------------------------------------------------ report --
    layout = json.loads(z.read("Report/Layout").decode("utf-16-le"))
    n_visuals = 0
    seen_pages = set()
    for section in layout["sections"]:
        if section["name"] in seen_pages:
            fail(f"duplicate page name {section['name']}")
        seen_pages.add(section["name"])
        cw, ch = section["width"], section["height"]

        for vc in section["visualContainers"]:
            n_visuals += 1
            cfg = json.loads(vc["config"])
            sv = cfg["singleVisual"]
            vname = cfg["name"]

            if (vc["x"] < 0 or vc["y"] < 0 or vc["x"] + vc["width"] > cw
                    or vc["y"] + vc["height"] > ch):
                fail(f"{section['displayName']}/{vname}: outside the canvas")

            # The container position and the config's layout copy must agree;
            # Desktop reads the config one and users see the container one.
            pos = cfg["layouts"][0]["position"]
            if (pos["x"], pos["y"], pos["width"], pos["height"]) != (
                    vc["x"], vc["y"], vc["width"], vc["height"]):
                fail(f"{section['displayName']}/{vname}: layout position "
                     f"disagrees with the container position")

            # REGRESSION GUARD. Visual-CONTAINER properties (title, background,
            # border, drop shadow) belong in `vcObjects`. Placed in `objects`
            # they are silently ignored - no error, no warning. That is how
            # every custom chart title in this report was replaced by an
            # auto-generated "Total Sales by Region", and how a brand-coloured
            # header band rendered as white text on a white card.
            vc_only = {"title", "subTitle", "background", "border", "dropShadow",
                       "visualHeader", "padding", "divider"}
            misplaced = vc_only & set(sv.get("objects", {}))
            if misplaced:
                fail(f"{section['displayName']}/{vname}: {sorted(misplaced)} are "
                     f"visual-container properties and must be in vcObjects, not "
                     f"objects - Power BI ignores them silently there")

            q = sv.get("prototypeQuery")
            if sv["visualType"] == "textbox":
                continue
            if not q:
                fail(f"{section['displayName']}/{vname}: no prototypeQuery")
                continue

            aliases = {f["Name"]: f["Entity"] for f in q["From"]}
            selected = set()
            for s in q["Select"]:
                kind = "Measure" if "Measure" in s else "Column"
                node = s[kind]
                alias = node["Expression"]["SourceRef"]["Source"]
                prop = node["Property"]
                if alias not in aliases:
                    fail(f"{section['displayName']}/{vname}: unknown alias "
                         f"'{alias}'")
                    continue
                entity = aliases[alias]
                if kind == "Measure":
                    if prop not in measures:
                        fail(f"{section['displayName']}/{vname}: measure "
                             f"[{prop}] not in model")
                else:
                    if entity not in tables:
                        fail(f"{section['displayName']}/{vname}: table "
                             f"{entity} not in model")
                    elif prop not in columns[entity]:
                        fail(f"{section['displayName']}/{vname}: column "
                             f"{entity}[{prop}] not in model")
                if s["Name"] != f"{entity}.{prop}":
                    fail(f"{section['displayName']}/{vname}: Select Name "
                         f"'{s['Name']}' does not match {entity}.{prop}")
                selected.add(s["Name"])

            # Projection queryRefs must all be present in Select, or the visual
            # comes back empty with no error message.
            for role, projs in sv.get("projections", {}).items():
                for p in projs:
                    if p["queryRef"] not in selected:
                        fail(f"{section['displayName']}/{vname}: projection "
                             f"{role}.{p['queryRef']} is not in the query Select")

            # REGRESSION GUARD. The model sets discourageImplicitMeasures, so a
            # raw column dropped into a value well has no aggregation. A line
            # chart renders empty; a scatter refuses outright with "set a
            # summarization for x- and y-axis". Every value role needs a
            # measure. Group-by roles (Category, Series, Legend) and table
            # Values are columns by design and are exempt.
            value_roles = {"X", "Y", "Y2", "Size", "Gradient"}
            if sv["visualType"] in ("card", "multiRowCard", "kpi", "gauge"):
                value_roles = value_roles | {"Values"}
            for role, projs in sv.get("projections", {}).items():
                if role not in value_roles:
                    continue
                for p in projs:
                    if not p["queryRef"].startswith("_Measures."):
                        fail(f"{section['displayName']}/{vname}: {role} uses the "
                             f"raw column {p['queryRef']} - with "
                             f"discourageImplicitMeasures set it will not "
                             f"aggregate and the visual will not render")

    cfg = json.loads(layout["config"])
    if "version" not in cfg:
        fail("layout config has no version")

    print(f"Package: {len(names)} parts, {PBIT.stat().st_size / 1024:,.0f} KB")
    print(f"Model:   {len(tables)} tables, {len(model['relationships'])} "
          f"relationships, {len(measures)} measures")
    print(f"Report:  {len(layout['sections'])} pages, {n_visuals} visuals")
    for w in warnings:
        print(f"  warn  {w}")
    print()
    if failures:
        for f in failures:
            print(f"  FAIL  {f}")
        print(f"\n{len(failures)} problem(s).")
        sys.exit(1)
    print("All static checks passed.")
    print("Still unverified: rendering in Power BI Desktop (not installed here).")


if __name__ == "__main__":
    main()
