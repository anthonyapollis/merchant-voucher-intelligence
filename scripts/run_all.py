"""
run_all.py — full pipeline, end to end, from the raw CSVs to every deliverable.

Exists so the whole solution is reproducible in one command, and so a reviewer can confirm
that nothing in this repository was hand-edited after generation.
"""
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

STEPS = [
    ("Profile source data", [sys.executable, "scripts/01_profile.py"]),
    ("Build medallion warehouse", [sys.executable, "scripts/02_build_warehouse.py"]),
    ("Build analytics / KPI layer", [sys.executable, "scripts/03_analytics.py"]),
    ("Train ML models", [sys.executable, "scripts/04_ml_models.py"]),
    ("Register bronze for dbt", [sys.executable, "scripts/_load_bronze_duckdb.py"]),
    # dbt steps run from inside dbt/ — profiles.yml resolves the DuckDB path relative to the
    # profiles directory (../data/mvi.duckdb), so the working directory must be dbt/.
    # `dbt build` runs seeds, snapshots, models and tests in a single DAG-ordered pass.
    # Running `dbt snapshot` separately beforehand fails on a clean database: snap_merchant
    # selects from stg_merchants, which does not exist until the staging models are built.
    # Letting dbt resolve the order is both simpler and correct.
    ("dbt build (seeds + snapshot + models + tests)",
     ["dbt", "build", "--profiles-dir", "."]),
    ("Validate SCD Type 2 behaviour", [sys.executable, "scripts/_test_scd2.py"]),
    ("Reconcile Python vs dbt", [sys.executable, "scripts/05_reconcile.py"]),
    ("Validate DAX measures", [sys.executable, "scripts/06_validate_dax.py"]),
    ("Build Excel pack", [sys.executable, "scripts/07_build_excel.py"]),
    ("Build interactive dashboard", [sys.executable, "scripts/08_build_dashboard.py"]),
    ("Validate dashboard", [sys.executable, "scripts/_check_dashboard.py"]),
    ("Build Word submission", [sys.executable, "scripts/09_build_report_docx.py"]),
]

print("=" * 92)
print("MERCHANT SALES & VOUCHER INTELLIGENCE — full pipeline")
print("=" * 92)

t0 = time.time()
failures = []
for i, (label, cmd) in enumerate(STEPS, 1):
    t = time.time()
    cwd = ROOT / "dbt" if cmd[0] == "dbt" else ROOT
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, shell=(cmd[0] == "dbt"))
    ok = r.returncode == 0
    if not ok:
        failures.append((label, r.stdout[-1500:], r.stderr[-800:]))
    print(f"  [{i:>2}/{len(STEPS)}]  {'OK  ' if ok else 'FAIL'}  {label:<34} "
          f"{time.time()-t:>6.1f}s")

print("=" * 92)
if failures:
    print(f"{len(failures)} step(s) FAILED\n")
    for label, out, err in failures:
        print(f"--- {label} ---")
        print(out or err)
    sys.exit(1)
print(f"All {len(STEPS)} steps completed in {time.time()-t0:.1f}s")
print("""
Deliverables:
  report/dashboard.html                                  interactive 6-page report
  report/Merchant_Voucher_Intelligence_Submission.docx   written submission
  excel/Merchant_Voucher_Intelligence_Report.xlsx        10-sheet Excel pack
  docs/dax_validation.csv                                measure acceptance test
""")
print("=" * 92)
