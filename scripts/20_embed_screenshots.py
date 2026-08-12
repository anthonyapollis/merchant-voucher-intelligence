"""
20_embed_screenshots.py — embed Fabric screenshots and the before/after ERDs into the
Word submission and the runbook PDF.

Screenshots are matched by FILENAME PREFIX (`04_warehouse*.png`), so the shot list can be
followed loosely — `04_warehouse.png`, `04_warehouse_v2.png` and `04_warehouse-final.jpg`
all resolve. Missing shots are skipped without breaking the build, which matters because
this runs before the full set exists.

The ERD SVGs are converted to PNG for embedding. If no SVG converter is available the ERDs
are referenced rather than inlined, and the report says so instead of showing a blank frame.
"""
import re
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SHOTS = ROOT / "docs" / "screenshots"
SHOTS.mkdir(parents=True, exist_ok=True)

# (prefix, section, caption)
CATALOGUE = [
    ("01_workspace", "Part 1 — Fabric workspace",
     "WS_MerchantVoucher on trial capacity."),
    ("02_capacity", "Part 1 — Fabric workspace",
     "License mode showing Fabric capacity. A Free account cannot create a Lakehouse."),
    ("03_lakehouse", "Part 1 — Fabric workspace",
     "LH_MerchantVoucher — the bronze and silver landing target."),
    ("04_warehouse", "Part 1 — Fabric workspace",
     "WH_MerchantVoucher, created through the Fabric REST API rather than by hand."),
    ("05_sql_endpoint", "Part 1 — Fabric workspace",
     "The SQL endpoint dbt connects to."),
    ("06_dbt_debug", "Part 2 — dbt connected",
     "dbt debug --target fabric: All checks passed. Connection and credentials proven."),
    ("07_dbt_seed", "Part 2 — dbt connected",
     "dbt seed --target fabric: PASS=4. WRITE access proven, not just connection."),
    ("08_warehouse_tables", "Part 2 — dbt connected",
     "The same four tables seen from the Fabric side."),
    ("09_dbt_docs_lineage", "Part 2 — dbt connected",
     "dbt docs lineage — the build DAG."),
    ("10_erd", "Part 2 — dbt connected",
     "The gold ERD, generated from the manifest's relationships tests."),
    ("11_pipeline", "Part 3 — orchestration",
     "PL_MerchantVoucher_Master on the pipeline canvas."),
    ("12_trigger_disabled", "Part 3 — orchestration",
     "The daily trigger shipped disabled — the cost control, evidenced."),
    ("13_notebook", "Part 3 — orchestration",
     "00_autoload_landing — detects csv, zip, xlsx, parquet and json, and loads to Delta."),
    ("14_monitor", "Part 3 — orchestration", "Fabric Monitor run history."),
    ("15_pbi_exec", "Part 4 — Power BI", "Executive Overview."),
    ("16_pbi_business_answers", "Part 4 — Power BI",
     "Business Answers — the five brief questions answered on the page."),
    ("17_pbi_reconciliation", "Part 4 — Power BI",
     "Reconciliation & Controls, including the explained R43.5m population variance."),
    ("18_pbi_value_risk", "Part 4 — Power BI",
     "Merchant Value & Risk — lifetime value, attrition, fraud-adjacent signals."),
    ("19_pbi_mobile", "Part 4 — Power BI", "Phone layout."),
    ("20_cost_guard", "Part 5 — cost control",
     "fabric_cost_guard.py --check: the kill switch."),
    ("21_trial_days", "Part 5 — cost control", "Trial days remaining against the 2026-10-10 expiry."),
]

EXT = (".png", ".jpg", ".jpeg", ".gif", ".bmp")


def find(prefix):
    hits = [p for p in SHOTS.iterdir()
            if p.is_file() and p.suffix.lower() in EXT and p.stem.lower().startswith(prefix)]
    return sorted(hits)[0] if hits else None


found = [(p, s, c, find(p)) for p, s, c in CATALOGUE]
have = [f for f in found if f[3]]
print(f"  {len(have)} of {len(CATALOGUE)} screenshots present")
for pre, sec, cap, path in found:
    print(f"    {'OK ' if path else '-- '} {pre:<26} {path.name if path else '(not supplied)'}")


# ---------------------------------------------------------------- ERD SVG -> PNG
def svg_to_png(svg, png):
    for tool, args in [("cairosvg", None), ("inkscape", ["-o"]), ("magick", None)]:
        if tool == "cairosvg":
            try:
                import cairosvg
                cairosvg.svg2png(url=str(svg), write_to=str(png), output_width=1600)
                return True
            except Exception:
                continue
        exe = shutil.which(tool)
        if not exe:
            continue
        try:
            cmd = ([exe, str(svg), "-o", str(png)] if tool == "inkscape"
                   else [exe, "-density", "150", str(svg), str(png)])
            if subprocess.run(cmd, capture_output=True).returncode == 0 and png.exists():
                return True
        except Exception:
            continue
    return False


erd_png = {}
for name in ("erd_before", "erd_after"):
    svg = ROOT / "docs" / f"{name}.svg"
    png = ROOT / "docs" / f"{name}.png"
    if svg.exists() and (png.exists() or svg_to_png(svg, png)):
        erd_png[name] = png
print(f"\n  ERD images ready: {len(erd_png)}/2"
      + ("" if len(erd_png) == 2 else "  (no SVG converter — reports will reference the "
                                       "HTML version instead of inlining)"))

# ---------------------------------------------------------------- write the manifest
man = ROOT / "docs" / "screenshot_manifest.json"
import json
man.write_text(json.dumps({
    "screenshots": [{"prefix": p, "section": s, "caption": c,
                     "file": str(f.relative_to(ROOT)) if f else None}
                    for p, s, c, f in found],
    "erd": {k: str(v.relative_to(ROOT)) for k, v in erd_png.items()},
    "present": len(have), "total": len(CATALOGUE),
}, indent=2), encoding="utf-8")
print(f"  wrote docs/screenshot_manifest.json")

# ---------------------------------------------------------------- rebuild the reports
print("\n  rebuilding reports with whatever is present ...")
for script in ("10_build_runbook_pdf.py", "09_build_report_docx.py"):
    r = subprocess.run([__import__("sys").executable, f"scripts/{script}"],
                       cwd=ROOT, capture_output=True, text=True)
    tail = (r.stdout or r.stderr).strip().splitlines()
    print(f"    {script:<28} {'OK' if r.returncode == 0 else 'FAILED'}"
          f"  {tail[-1] if tail else ''}")

if len(have) == 0:
    print("\n  No screenshots yet. Follow docs/screenshots/SHOTLIST.md, then re-run this.")
    print("  The five that carry the argument: 04_warehouse, 06_dbt_debug, 07_dbt_seed,")
    print("  16_pbi_business_answers, 12_trigger_disabled.")
