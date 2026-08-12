"""
25_load_bronze_to_fabric.py — load the four bronze tables into the Fabric Warehouse.

dbt transforms what is already there; it does not ingest. In production the Data Factory
pipeline lands bronze (see datafactory/PL_MerchantVoucher_Master.json). This script does the
same job once so `dbt run --target fabric` has something to read.

    python scripts/25_load_bronze_to_fabric.py            load all four
    python scripts/25_load_bronze_to_fabric.py --sample   1,000 rows each

PERFORMANCE WARNING — MEASURED, NOT ASSUMED
Row-by-row INSERT over ODBC into a Fabric Warehouse is unusably slow. A 1,000-row sample of
four tables did not finish in ten minutes over a normal connection, and the full set is
149,498 rows. Fabric Warehouse is a distributed analytics engine: it is built for bulk
ingest, and every single-row INSERT pays full distributed-transaction overhead.

Do not use this for the real load. Use one of:

  1. The ADF pipeline (the intended path)  — Copy activity into the Lakehouse, then dbt
     reads the Delta tables. This is what datafactory/PL_MerchantVoucher_Master.json does
     and why the architecture puts bronze in the Lakehouse rather than the Warehouse.
  2. COPY INTO from staged parquet         — the fastest warehouse-native option, but it
     needs the files in ADLS/OneLake first.
  3. Lakehouse upload + shortcut           — drop fabric_upload/gold into Files, Load to
     Tables, and query it from the Warehouse.

This script is kept because it is the shortest way to prove write access end to end
(4 seed tables were created this way in seconds), not because it is the right loader.
"""
import argparse
import json
import os
import struct
import subprocess
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"

TABLES = [
    ("bronze_merchant_reference", "MerchantReference.csv"),
    ("bronze_merchant_sales", "MerchantSales.csv"),
    ("bronze_support_tickets", "SupportTickets.csv"),
    ("bronze_voucher_redemptions", "VoucherRedemptions.csv"),
]

ap = argparse.ArgumentParser()
ap.add_argument("--sample", action="store_true", help="load only 1,000 rows per table")
ap.add_argument("--batch", type=int, default=1000)
args = ap.parse_args()

try:
    import pyodbc
except ImportError:
    sys.exit("pyodbc is required:  pip install pyodbc")

server = os.environ.get("FABRIC_SQL_ENDPOINT")
database = os.environ.get("FABRIC_WAREHOUSE", "WH_MerchantVoucher")
if not server:
    sys.exit("FABRIC_SQL_ENDPOINT is not set. Run:  . .\\dbt\\.env.fabric.ps1")

# Access token, passed to ODBC via SQL_COPT_SS_ACCESS_TOKEN (1256) in the widechar-prefixed
# form the driver expects.
tok = json.loads(subprocess.run(
    ["az", "account", "get-access-token", "--resource",
     "https://database.windows.net/", "-o", "json"],
    capture_output=True, text=True, shell=True).stdout)["accessToken"]
raw = tok.encode("utf-16-le")
token_struct = struct.pack(f"<I{len(raw)}s", len(raw), raw)

conn = pyodbc.connect(
    f"Driver={{ODBC Driver 17 for SQL Server}};Server={server};Database={database};"
    f"Encrypt=yes;TrustServerCertificate=no",
    attrs_before={1256: token_struct}, autocommit=True)
cur = conn.cursor()
print(f"  connected to {database}\n")

BATCH_ID, INGESTED = "fabric-initial-load", pd.Timestamp.utcnow().strftime("%Y-%m-%d %H:%M:%S")

for table, csv in TABLES:
    df = pd.read_csv(RAW / csv, dtype=str).fillna("")
    if args.sample:
        df = df.head(1000)
    df["_source_file"] = csv
    df["_ingested_at"] = INGESTED
    df["_batch_id"] = BATCH_ID

    # Everything lands as text, exactly as bronze should: typing is silver's job, and a cast
    # applied at ingest is a transformation nobody can see or test.
    cols = ", ".join(f"[{c}] VARCHAR(4000)" for c in df.columns)
    cur.execute(f"DROP TABLE IF EXISTS dbo.{table}")
    cur.execute(f"CREATE TABLE dbo.{table} ({cols})")

    placeholders = ", ".join("?" * len(df.columns))
    insert = (f"INSERT INTO dbo.{table} "
              f"({', '.join('[' + c + ']' for c in df.columns)}) VALUES ({placeholders})")
    cur.fast_executemany = True
    rows = df.values.tolist()
    for i in range(0, len(rows), args.batch):
        cur.executemany(insert, rows[i:i + args.batch])
        if len(rows) > 20000 and i and i % 20000 == 0:
            print(f"      {i:,}/{len(rows):,}")
    n = cur.execute(f"SELECT COUNT(*) FROM dbo.{table}").fetchone()[0]
    print(f"  {table:<32} {n:>9,} rows")

cur.close(); conn.close()
print("\n  Now run:  cd dbt && dbt build --target fabric")
