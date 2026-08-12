"""Register the bronze parquet files as tables in the DuckDB dev warehouse so the dbt
project can resolve its `bronze` source and run end-to-end locally."""
import duckdb
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
con = duckdb.connect(str(ROOT / "data" / "mvi.duckdb"))
for n in ["bronze_merchant_reference", "bronze_merchant_sales",
          "bronze_support_tickets", "bronze_voucher_redemptions"]:
    p = (ROOT / "data" / "bronze" / f"{n}.parquet").as_posix()
    con.execute(f"CREATE OR REPLACE TABLE {n} AS SELECT * FROM read_parquet('{p}')")
    print(f"  {n:32s} {con.execute(f'select count(*) from {n}').fetchone()[0]:>8,}")
con.close()
