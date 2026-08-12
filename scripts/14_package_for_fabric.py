"""
14_package_for_fabric.py
========================
Produces fabric_upload/ — everything needed to stand the solution up in a Fabric workspace,
in the order it gets uploaded.

Deliberately packages BOTH:
  landing/   the four raw CSVs, so the Fabric pipeline can be demonstrated running the real
             bronze -> silver -> gold path end to end
  gold/      the finished gold tables as CSV, so the Power BI report can be pointed at real
             data within minutes even before the pipeline is wired up

CSV rather than parquet for the gold copy: Fabric's Lakehouse "upload files" path handles
CSV without a schema definition, and the point of this package is the fastest route to a
working report, not the most efficient storage format.
"""
import shutil
import sys
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "fabric_upload"
if OUT.exists():
    shutil.rmtree(OUT)
(OUT / "landing").mkdir(parents=True)
(OUT / "gold").mkdir(parents=True)

# ---- raw landing files ---------------------------------------------------------------
for f in ["MerchantSales.csv", "VoucherRedemptions.csv", "SupportTickets.csv",
          "MerchantReference.csv"]:
    shutil.copy2(ROOT / "data" / "raw" / f, OUT / "landing" / f)
print(f"  landing/  4 source CSVs")

# ---- gold tables ---------------------------------------------------------------------
con = duckdb.connect(str(ROOT / "data" / "mvi.duckdb"))
tables = [r[0] for r in con.execute("""
    select table_name from information_schema.tables
    where table_schema = 'main_marts'
      and (table_name like 'dim_%' or table_name like 'fct_%' or table_name like 'mart_%')
    order by table_name""").fetchall()]
total = 0
for t in tables:
    p = (OUT / "gold" / f"{t}.csv").as_posix()
    con.execute(f"COPY main_marts.{t} TO '{p}' (HEADER, DELIMITER ',')")
    n = con.execute(f"select count(*) from main_marts.{t}").fetchone()[0]
    total += n
    print(f"  gold/{t + '.csv':<38} {n:>9,} rows")
con.close()

# ---- checklist -----------------------------------------------------------------------
(OUT / "OPEN_ME_FIRST.md").write_text(f"""# Fabric deployment package

{len(tables)} gold tables ({total:,} rows) and the 4 raw source files.

## Step 0 — you need a Fabric capacity first

The account is currently **Free (Power BI trial only)**. Lakehouse, Warehouse, Notebooks and
Data Factory pipelines all require a Fabric capacity, so nothing below works until:

> Profile icon (top right) -> **Start Fabric trial** (60 days, no card required)

The Power BI trial and the Fabric trial are different things. Having the first does not give
you the second.

## Step 1 — workspace

`Workspaces -> New workspace -> WS_MerchantVoucher`
Under **Advanced -> License mode**, select **Fabric capacity** (or Trial). If that option is
greyed out, step 0 has not completed.

## Step 2 — Lakehouse

`+ New -> Lakehouse -> LH_MerchantVoucher`

Then either:

**Fast path (report working in ~10 minutes)**
`Files -> Upload -> Upload folder -> gold/`, then for each CSV use
**... -> Load to Tables -> New table**. Point Power BI at these and the report renders
against real data immediately.

**Full path (demonstrates the pipeline)**
`Files -> New subfolder -> landing`, upload `landing/`, then run the notebooks in
`notebooks/` in order. This exercises bronze -> silver -> gold properly.

## Step 3 — Warehouse (needed for dbt)

`+ New -> Warehouse -> WH_MerchantVoucher`, then run `sql/01_create_warehouse.sql`.

Copy the **SQL connection string** from `Settings -> SQL endpoint`.

## Step 4 — point dbt at Fabric

```powershell
pip install dbt-fabric
$env:FABRIC_SQL_ENDPOINT = "<workspace>.datawarehouse.fabric.microsoft.com"
$env:FABRIC_WAREHOUSE    = "WH_MerchantVoucher"
$env:AZURE_TENANT_ID     = "<tenant id>"
$env:AZURE_CLIENT_ID     = "<service principal app id>"
$env:AZURE_CLIENT_SECRET = "<service principal secret>"

cd dbt
dbt debug --target fabric
dbt build  --target fabric
```

The `fabric` target already exists in `profiles.yml`. The same SQL that produces
156 passing checks on DuckDB runs unchanged against the Warehouse — that is the reason dbt
is in this stack.

**Service principal**: Entra ID -> App registrations -> New registration -> add a client
secret -> then grant that app **Contributor** on the workspace. Fabric will not accept it
otherwise.

## Step 5 — semantic model and report

Open `powerbi/MerchantVoucherIntelligence.pbip` in Power BI Desktop, repoint the source to
the Lakehouse/Warehouse, then **Publish** to `WS_MerchantVoucher`.

## Step 6 — pipeline and schedule

Import `datafactory/PL_MerchantVoucher_Master.json` and `TR_Daily_0200_SAST.json`.
Set the workspace, semantic model and notebook ids as pipeline parameters — they are
parameters rather than literals precisely so the same JSON promotes between environments.

---

## Cost note

The Fabric trial is 60 days on an F64-equivalent capacity. Two things to remember:

- **A trial capacity still runs jobs.** Pause or delete the workspace when you are done
  demonstrating, or a scheduled pipeline will keep firing daily for 60 days.
- **The daily 02:00 trigger is set to Started** in the supplied JSON. Leave it disabled until
  you actually want scheduled refreshes.
""", encoding="utf-8")

size = sum(f.stat().st_size for f in OUT.rglob("*") if f.is_file())
print(f"\n  fabric_upload/  {size/1024/1024:.1f} MB  ->  start with OPEN_ME_FIRST.md")
