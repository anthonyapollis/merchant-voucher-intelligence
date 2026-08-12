"""
_test_scd2.py — prove the Type 2 snapshot actually captures change.

A snapshot that has only ever seen one version of each row is indistinguishable from a
snapshot that is silently broken. Declaring "this is SCD2" is not evidence. This script
simulates a real merchant change, re-runs the snapshot, and asserts that history was
captured correctly — then restores the original state so nothing is left mutated.

Simulated change: Umhlanga Value Mart moves from ActiveStatus 'Active' to 'At Risk' and is
reassigned to a different account manager — exactly what should happen given its July
collapse, and exactly the kind of change the source system would overwrite without trace.
"""
import shutil
import subprocess
import sys
from pathlib import Path

import duckdb
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "mvi.duckdb"
RAW = ROOT / "data" / "raw" / "MerchantReference.csv"

# NOTE: this harness deliberately touches NOTHING on disk. An earlier version backed up and
# rewrote data/bronze/bronze_merchant_reference.parquet; when an assertion raised mid-run the
# restore left a zero-byte file behind and broke the next pipeline run. A test that can
# corrupt the thing it is testing is worse than no test. Everything now happens inside the
# DuckDB bronze TABLE, which is rebuilt from the raw CSV at the end — the CSV is read-only
# input, so the restore cannot fail the same way.

TARGET = "M002"          # Umhlanga Value Mart
rule = lambda t: print("\n" + "=" * 84 + f"\n{t}\n" + "=" * 84)


def dbt(cmd):
    return subprocess.run(["dbt", cmd, "--profiles-dir", "."], cwd=ROOT / "dbt",
                          capture_output=True, text=True, shell=True)


rule("SCD TYPE 2 VALIDATION")

con = duckdb.connect(str(DB))
before = con.execute("""
    select merchant_id, merchant_name, active_status, account_manager, version_number,
           is_current
    from main_marts.dim_merchant_history where merchant_id = ? order by version_number
""", [TARGET]).df()
print("BEFORE — versions held for", TARGET)
print(before.to_string(index=False))
n_before = len(before)

con.execute("CREATE OR REPLACE TABLE _scd2_snap_backup AS SELECT * FROM snapshots.snap_merchant")
con.close()

try:
    # ---- simulate the source-system change, in the DB only ----------------------------
    con = duckdb.connect(str(DB))
    con.execute("UPDATE bronze_merchant_reference SET ActiveStatus = 'At Risk', "
                "AccountManager = 'T. Mokoena' WHERE MerchantID = ?", [TARGET])
    con.close()
    print(f"\nSimulated source change: {TARGET} ActiveStatus -> 'At Risk', "
          f"AccountManager -> 'T. Mokoena'")

    # ---- re-run the snapshot, then rebuild the Type 2 dimension ----------------------
    r = dbt("snapshot")
    print("dbt snapshot:", "OK" if r.returncode == 0 else "FAILED")
    if r.returncode:
        print(r.stdout[-1200:])
        sys.exit(1)
    r = subprocess.run(["dbt", "run", "--select", "dim_merchant_history",
                        "--profiles-dir", "."], cwd=ROOT / "dbt",
                       capture_output=True, text=True, shell=True)
    print("dbt run dim_merchant_history:", "OK" if r.returncode == 0 else "FAILED")
    if r.returncode:
        print((r.stdout or r.stderr)[-2000:])

    con = duckdb.connect(str(DB))
    after = con.execute("""
        select merchant_id, merchant_name, active_status, account_manager, version_number,
               is_current, cast(valid_from as date) valid_from, cast(valid_to as date) valid_to
        from main_marts.dim_merchant_history where merchant_id = ? order by version_number
    """, [TARGET]).df()
    others = con.execute("""
        select count(*) from main_marts.dim_merchant_history where merchant_id <> ?
    """, [TARGET]).fetchone()[0]
    con.close()

    print("\nAFTER — versions held for", TARGET)
    print(after.to_string(index=False))

    # ---- assertions -------------------------------------------------------------------
    checks = [
        ("A new version row was created", len(after) == n_before + 1),
        ("Exactly one version is current", int(after.is_current.sum()) == 1),
        ("The current version carries the NEW value",
         after[after.is_current].active_status.iloc[0] == "At Risk"),
        ("The superseded version retains the OLD value",
         after[~after.is_current].active_status.iloc[0] == "Active"),
        ("The superseded version was closed off (valid_to set)",
         str(after[~after.is_current].valid_to.iloc[0]) != "9999-12-31"),
        ("Version numbering is contiguous",
         list(after.version_number) == list(range(1, len(after) + 1))),
        ("Unchanged merchants did NOT gain a version", others == 24),
    ]
    print()
    failed = 0
    for label, ok in checks:
        failed += not ok
        print(f"  {'PASS' if ok else 'FAIL'}  {label}")
    print(f"\n  {len(checks)-failed}/{len(checks)} SCD2 assertions passed")

finally:
    # ---- restore, from the read-only raw CSV so the restore itself cannot corrupt -------
    con = duckdb.connect(str(DB))
    con.execute(f"UPDATE bronze_merchant_reference SET ActiveStatus = r.ActiveStatus, "
                f"AccountManager = r.AccountManager "
                f"FROM read_csv_auto('{RAW.as_posix()}') r "
                f"WHERE bronze_merchant_reference.MerchantID = r.MerchantID")
    con.execute("CREATE OR REPLACE TABLE snapshots.snap_merchant AS "
                "SELECT * FROM _scd2_snap_backup")
    con.execute("DROP TABLE IF EXISTS _scd2_snap_backup")
    con.close()
    subprocess.run(["dbt", "run", "--select", "dim_merchant_history", "--profiles-dir", "."],
                   cwd=ROOT / "dbt", capture_output=True, text=True, shell=True)

    con = duckdb.connect(str(DB))
    n = con.execute("select count(*) from main_marts.dim_merchant_history").fetchone()[0]
    st = con.execute("select active_status from main_marts.dim_merchant_history "
                     "where merchant_id = ?", [TARGET]).fetchone()[0]
    con.close()
    print(f"\nRestored: dim_merchant_history back to {n} rows, {TARGET} status = '{st}'")
