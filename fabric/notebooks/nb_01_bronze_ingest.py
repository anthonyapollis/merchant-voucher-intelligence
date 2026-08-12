# Fabric notebook source
# ---------------------------------------------------------------------------
# nb_01_bronze_ingest
# ---------------------------------------------------------------------------
# Lands the four source files into the Bronze layer of lh_merchant_bronze
# exactly as received, with lineage columns added and nothing else changed.
#
# Bronze rule: no cleaning, no typing beyond what the reader infers, no
# filtering, no de-duplication. If the source is wrong, Bronze stays wrong -
# that is what makes it replayable and what makes a Silver bug provable.
#
# Attach to: lh_merchant_bronze
# Schedule:  daily 02:00 SAST via pl_merchant_daily_refresh
# ---------------------------------------------------------------------------

# MARKDOWN ******************************

# ## Parameters

# PARAMETERS CELL ********************

# Overridden by the pipeline at run time.
source_folder = "Files/landing"
run_date = None          # ISO date; None means "today"
full_reload = False      # True re-lands every file, ignoring the watermark

# CELL ********************

from datetime import datetime, timezone

from pyspark.sql import functions as F
from pyspark.sql.types import (DateType, DecimalType, IntegerType, StringType,
                               StructField, StructType)

BRONZE = "lh_merchant_bronze"
run_ts = datetime.now(timezone.utc)
run_id = run_ts.strftime("%Y%m%d%H%M%S")
run_date = run_date or run_ts.date().isoformat()

print(f"run_id={run_id}  run_date={run_date}  full_reload={full_reload}")

# MARKDOWN ******************************

# ## Explicit schemas
#
# Schema inference is convenient and wrong. It samples, so a column that is
# numeric in the sample and alphanumeric later silently changes type between
# runs and breaks the Silver merge. Every source below is declared.
#
# Note `RedeemedDate` is nullable by design: a voucher that has not been
# redeemed has no redemption date, and that null is information, not a defect.

# CELL ********************

SCHEMAS = {
    "MerchantSales": StructType([
        StructField("Date", DateType(), False),
        StructField("MerchantID", StringType(), False),
        StructField("Merchant", StringType(), True),
        StructField("Region", StringType(), True),
        StructField("Channel", StringType(), True),
        StructField("VoucherType", StringType(), False),
        StructField("SalesValue", DecimalType(18, 2), False),
        StructField("Transactions", IntegerType(), False),
    ]),
    "VoucherRedemptions": StructType([
        StructField("VoucherID", StringType(), False),
        StructField("MerchantID", StringType(), False),
        StructField("Merchant", StringType(), True),
        StructField("SoldDate", DateType(), False),
        StructField("VoucherType", StringType(), False),
        StructField("VoucherValue", DecimalType(18, 2), False),
        StructField("Redeemed", StringType(), False),
        StructField("RedeemedDate", DateType(), True),
    ]),
    "SupportTickets": StructType([
        StructField("TicketID", StringType(), False),
        StructField("Date", DateType(), False),
        StructField("MerchantID", StringType(), False),
        StructField("Merchant", StringType(), True),
        StructField("Region", StringType(), True),
        StructField("TicketType", StringType(), False),
        StructField("Priority", StringType(), False),
        StructField("ResolutionHours", DecimalType(10, 2), True),
        StructField("SLAHours", IntegerType(), False),
        StructField("Status", StringType(), False),
    ]),
    "MerchantReference": StructType([
        StructField("MerchantID", StringType(), False),
        StructField("Merchant", StringType(), False),
        StructField("Region", StringType(), False),
        StructField("Channel", StringType(), False),
        StructField("ActiveStatus", StringType(), False),
        StructField("OnboardedDate", DateType(), True),
        StructField("AccountManager", StringType(), True),
        StructField("BaseMonthlySalesTarget", DecimalType(18, 2), True),
    ]),
}

# The three transactional sources append; the reference file is a full snapshot
# of the merchant book each day and is therefore overwritten.
WRITE_MODE = {
    "MerchantSales": "append",
    "VoucherRedemptions": "append",
    "SupportTickets": "append",
    "MerchantReference": "overwrite",
}

# CELL ********************

def land(name: str) -> int:
    """Read one source file and write it to Bronze with lineage columns."""
    path = f"{source_folder}/{name}.csv"

    df = (spark.read
          .schema(SCHEMAS[name])
          .option("header", True)
          .option("mode", "PERMISSIVE")
          .option("columnNameOfCorruptRecord", "_corrupt_record")
          .csv(path))

    df = (df
          .withColumn("_ingested_at_utc", F.lit(run_ts).cast("timestamp"))
          .withColumn("_run_id", F.lit(run_id))
          .withColumn("_source_file", F.input_file_name()))

    mode = "overwrite" if full_reload else WRITE_MODE[name]
    target = f"{BRONZE}.br_{to_snake(name)}"

    writer = df.write.format("delta").mode(mode)
    if mode == "overwrite":
        # Source columns can legitimately be added upstream; a schema
        # overwrite on a full reload is intended, on an append it is not.
        writer = writer.option("overwriteSchema", "true")
    writer.saveAsTable(target)

    n = df.count()
    print(f"  {target:<45} {n:>9,} rows  ({mode})")
    return n


def to_snake(name: str) -> str:
    out = []
    for i, ch in enumerate(name):
        if ch.isupper() and i > 0:
            out.append("_")
        out.append(ch.lower())
    return "".join(out)

# CELL ********************

results = {name: land(name) for name in SCHEMAS}

# MARKDOWN ******************************

# ## Ingestion audit
#
# One row per source per run. This is the table that answers "did last night's
# load actually run, and did it land the volume we expected" without anyone
# opening a notebook.

# CELL ********************

audit = spark.createDataFrame(
    [(run_id, run_date, name, int(rows), WRITE_MODE[name], run_ts)
     for name, rows in results.items()],
    "run_id string, run_date string, source_name string, row_count long, "
    "write_mode string, ingested_at_utc timestamp",
)
audit.write.format("delta").mode("append").saveAsTable(f"{BRONZE}.br_ingest_audit")

display(audit)

# CELL ********************

# Fail the pipeline loudly rather than let an empty load flow to Silver and
# silently blank the report.
empty = [name for name, rows in results.items() if rows == 0]
if empty:
    raise ValueError(f"Bronze ingest landed 0 rows for: {', '.join(empty)}")

print(f"Bronze ingest complete. {sum(results.values()):,} rows across "
      f"{len(results)} sources.")
