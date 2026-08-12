"""
run_all.py
==========
Runs the whole build in dependency order, from the raw CSVs to the finished
report and dashboard. Stops at the first failure rather than carrying on with a
half-built gold layer.

Run:  python build/run_all.py
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

STEPS = [
    ("build_geo.py", "Prepare province geometry"),
    ("build_gold.py", "Bronze to gold star schema, with the 20-check DQ gate"),
    ("build_insights.py", "Anomaly detection, narratives, computed findings"),
    ("build_ml.py", "Segmentation, propensity, SLA, forecast"),
    ("build_semantic_model.py", "TMDL semantic model and PBIP"),
    ("build_report.py", "PBIR report definition"),
    ("validate_report.py", "Static validation of the report against the model"),
    ("build_pbit.py", "Power BI template (.pbit) that opens in Desktop"),
    ("validate_pbit.py", "Static validation of the .pbit package and model"),
    ("build_dashboard.py", "Offline HTML dashboard"),
    ("package_delivery.py", "Zip the openable deliverable"),
]


def main() -> None:
    started = time.time()
    for i, (script, description) in enumerate(STEPS, 1):
        print(f"\n{'=' * 72}")
        print(f"[{i}/{len(STEPS)}] {script} - {description}")
        print("=" * 72)
        result = subprocess.run([sys.executable, str(ROOT / "build" / script)],
                                cwd=ROOT)
        if result.returncode != 0:
            print(f"\nFAILED at step {i} ({script}). Build stopped.")
            sys.exit(result.returncode)

    print(f"\n{'=' * 72}")
    print(f"Build complete in {time.time() - started:.0f}s.")
    print("  powerbi/MerchantVoucherIntelligence.pbip   open in Power BI Desktop")
    print("  dashboard/index.html                       open in any browser")
    print("=" * 72)


if __name__ == "__main__":
    main()
