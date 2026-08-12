# Fabric notebook — 01_bronze_to_silver
# ======================================================================================
# Runs on a Fabric Spark pool against the Lakehouse. Reads bronze Delta tables written by
# the Data Factory copy activity, applies typing / cleansing / conformance / business rules,
# and writes silver Delta tables.
#
# This is the PySpark expression of the logic proven locally in scripts/02_build_warehouse.py.
# Keeping a runnable local reference means transformation defects are found on a laptop in
# seconds rather than in a Spark job in minutes.
#
# PARAMETERS (set by the pipeline via the parameter cell below)
# ======================================================================================

# PARAMETERS CELL — Fabric injects pipeline values over these defaults
batch_id = "20260811T060000Z"
run_id = "local-dev"
fail_on_error = True

# --------------------------------------------------------------------------------------
from pyspark.sql import functions as F, Window
from pyspark.sql.types import (StructType, StructField, StringType, DoubleType,
                               IntegerType, DateType)
from delta.tables import DeltaTable
from datetime import datetime

# Business rules — kept identical to dbt_project.yml vars and the DAX library
DELAYED_REDEMPTION_DAYS = 7
VOUCHER_EXPIRY_DAYS = 90
HIGH_PRIORITIES = ["High", "Critical"]

LAKEHOUSE = "LH_MerchantVoucher"
ingested_at = F.lit(datetime.utcnow())

print(f"Bronze -> Silver | batch {batch_id} | run {run_id}")


def audit(df, name):
    """Attach lineage columns to every silver table. Without a batch id on the row it is
    impossible to answer 'which load produced this number?' during an incident."""
    return (df
            .withColumn("_batch_id", F.lit(batch_id))
            .withColumn("_ingested_at", ingested_at))


def write_silver(df, name, partition_by=None):
    w = (df.write.format("delta").mode("overwrite")
         .option("overwriteSchema", "true"))
    if partition_by:
        w = w.partitionBy(partition_by)
    w.saveAsTable(f"{LAKEHOUSE}.{name}")
    n = spark.table(f"{LAKEHOUSE}.{name}").count()
    print(f"  wrote {name:34s} rows={n:>9,}")
    return n


# ======================================================================================
# silver_merchant
# ======================================================================================
bronze_m = spark.table(f"{LAKEHOUSE}.bronze_merchant_reference")

silver_merchant = (bronze_m
    .withColumn("merchant_id", F.upper(F.trim("MerchantID")))
    .withColumn("merchant_name", F.trim("Merchant"))
    .withColumn("region", F.trim("Region"))
    .withColumn("channel", F.trim("Channel"))
    .withColumn("active_status", F.trim("ActiveStatus"))
    .withColumn("account_manager", F.trim("AccountManager"))
    .withColumn("onboarded_date", F.to_date("OnboardedDate"))
    .withColumn("base_monthly_sales_target", F.col("BaseMonthlySalesTarget").cast("decimal(18,2)"))
    # Deduplicate on the natural key, keeping the most recently ingested record.
    .withColumn("_rn", F.row_number().over(
        Window.partitionBy(F.upper(F.trim("MerchantID"))).orderBy(F.col("_ingested_at").desc())))
    .filter("_rn = 1").drop("_rn")
    .withColumn("is_at_risk", F.col("active_status") == "At Risk")
    .select("merchant_id", "merchant_name", "region", "channel", "active_status",
            "is_at_risk", "account_manager", "onboarded_date", "base_monthly_sales_target"))
write_silver(audit(silver_merchant, "silver_merchant"), "silver_merchant")


# ======================================================================================
# silver_merchant_sales
# ======================================================================================
bronze_s = spark.table(f"{LAKEHOUSE}.bronze_merchant_sales")

silver_sales = (bronze_s
    .withColumn("sales_date", F.to_date("Date"))
    .withColumn("merchant_id", F.upper(F.trim("MerchantID")))
    .withColumn("voucher_type", F.trim("VoucherType"))
    .withColumn("sales_value", F.col("SalesValue").cast("decimal(18,2)"))
    .withColumn("transactions", F.col("Transactions").cast("int"))
    .filter(F.col("sales_date").isNotNull() & F.col("merchant_id").isNotNull())
    .filter(F.col("sales_value") >= 0)
    # Descriptive attributes (Merchant, Region, Channel) are DROPPED here — they belong to
    # the dimension. Profiling confirmed zero disagreement with MerchantReference, so this
    # is lossless and prevents two competing versions of "Region" existing in the model.
    .groupBy("sales_date", "merchant_id", "voucher_type")
    .agg(F.sum("sales_value").alias("sales_value"),
         F.sum("transactions").alias("transactions"))
    .withColumn("avg_basket_value",
                F.when(F.col("transactions") > 0,
                       F.col("sales_value") / F.col("transactions"))))
# Partitioned by month: the report filters by period constantly, and partition pruning on a
# 26,500-row table is negligible now but the pattern must be right before volume arrives.
write_silver(audit(silver_sales, "silver_merchant_sales")
             .withColumn("year_month", F.date_format("sales_date", "yyyy-MM")),
             "silver_merchant_sales", partition_by="year_month")


# ======================================================================================
# silver_voucher_redemptions
# ======================================================================================
bronze_v = spark.table(f"{LAKEHOUSE}.bronze_voucher_redemptions")

max_sold = bronze_v.select(F.max(F.to_date("SoldDate"))).collect()[0][0]

silver_vouchers = (bronze_v
    .withColumn("voucher_id", F.trim("VoucherID"))
    .withColumn("merchant_id", F.upper(F.trim("MerchantID")))
    .withColumn("voucher_type", F.trim("VoucherType"))
    .withColumn("sold_date", F.to_date("SoldDate"))
    .withColumn("redeemed_date", F.to_date("RedeemedDate"))
    .withColumn("voucher_value", F.col("VoucherValue").cast("decimal(18,2)"))
    .withColumn("redeemed_flag", F.lower(F.trim("Redeemed")) == "yes")

    # INTEGRITY RULE — the single most important line in this notebook.
    # A voucher counts as redeemed only if the flag AND a valid, non-retrograde date agree.
    # Trusting the flag alone would let a corrupt feed inflate the headline redemption rate,
    # which is the most scrutinised number in the report.
    .withColumn("is_redeemed",
                F.col("redeemed_flag")
                & F.col("redeemed_date").isNotNull()
                & (F.col("redeemed_date") >= F.col("sold_date")))

    .withColumn("quality_flag",
                F.when(F.col("redeemed_flag") & F.col("redeemed_date").isNull(),
                       "REDEEM_DATE_MISSING")
                 .when(F.col("redeemed_flag") & (F.col("redeemed_date") < F.col("sold_date")),
                       "REDEEM_DATE_BEFORE_SALE")
                 .when(~F.col("redeemed_flag") & F.col("redeemed_date").isNotNull(),
                       "UNREDEEMED_WITH_DATE")
                 .otherwise("OK"))

    .withColumn("days_to_redeem",
                F.when(F.col("is_redeemed"),
                       F.datediff("redeemed_date", "sold_date")))
    .withColumn("is_delayed_redemption",
                F.coalesce(F.col("is_redeemed")
                           & (F.col("days_to_redeem") > DELAYED_REDEMPTION_DAYS),
                           F.lit(False)))
    .withColumn("redeemed_value",
                F.when(F.col("is_redeemed"), F.col("voucher_value")).otherwise(F.lit(0)))
    .withColumn("outstanding_value",
                F.when(F.col("is_redeemed"), F.lit(0)).otherwise(F.col("voucher_value")))
    .withColumn("is_expired",
                (~F.col("is_redeemed"))
                & (F.datediff(F.lit(max_sold), F.col("sold_date")) > VOUCHER_EXPIRY_DAYS))
    .withColumn("breakage_value",
                F.when(F.col("is_expired"), F.col("voucher_value")).otherwise(F.lit(0)))
    .select("voucher_id", "merchant_id", "voucher_type", "sold_date", "redeemed_date",
            "voucher_value", "is_redeemed", "days_to_redeem", "is_delayed_redemption",
            "redeemed_value", "outstanding_value", "is_expired", "breakage_value",
            "quality_flag"))

# Surface any integrity violations rather than letting them pass silently.
violations = silver_vouchers.filter(F.col("quality_flag") != "OK").count()
if violations:
    print(f"  WARNING: {violations:,} vouchers failed the redemption integrity rule "
          f"and were reclassified as unredeemed. See quality_flag.")

write_silver(audit(silver_vouchers, "silver_voucher_redemptions")
             .withColumn("year_month", F.date_format("sold_date", "yyyy-MM")),
             "silver_voucher_redemptions", partition_by="year_month")


# ======================================================================================
# silver_support_tickets
# ======================================================================================
bronze_t = spark.table(f"{LAKEHOUSE}.bronze_support_tickets")

silver_tickets = (bronze_t
    .withColumn("ticket_id", F.trim("TicketID"))
    .withColumn("ticket_date", F.to_date("Date"))
    .withColumn("merchant_id", F.upper(F.trim("MerchantID")))
    .withColumn("ticket_type", F.trim("TicketType"))
    .withColumn("priority", F.trim("Priority"))
    .withColumn("status", F.trim("Status"))
    .withColumn("resolution_hours", F.col("ResolutionHours").cast("decimal(10,2)"))
    .withColumn("sla_hours", F.col("SLAHours").cast("int"))
    .filter(F.col("resolution_hours") >= 0)

    .withColumn("is_sla_breach", F.col("resolution_hours") > F.col("sla_hours"))
    .withColumn("sla_breach_hours",
                F.greatest(F.col("resolution_hours") - F.col("sla_hours"), F.lit(0)))
    .withColumn("sla_utilisation", F.col("resolution_hours") / F.col("sla_hours"))
    .withColumn("is_high_priority", F.col("priority").isin(HIGH_PRIORITIES))
    .withColumn("is_open", F.col("status") != "Closed")
    .withColumn("is_escalated", F.col("status") == "Escalated")
    .select("ticket_id", "ticket_date", "merchant_id", "ticket_type", "priority", "status",
            "resolution_hours", "sla_hours", "is_sla_breach", "sla_breach_hours",
            "sla_utilisation", "is_high_priority", "is_open", "is_escalated"))
write_silver(audit(silver_tickets, "silver_support_tickets"), "silver_support_tickets")


# ======================================================================================
# Optimise: Z-ORDER on the columns the semantic model filters by most.
# Direct Lake reads Delta files directly, so file layout is query performance.
# ======================================================================================
for tbl, cols in [("silver_merchant_sales", "merchant_id, sales_date"),
                  ("silver_voucher_redemptions", "merchant_id, sold_date"),
                  ("silver_support_tickets", "merchant_id, ticket_date")]:
    spark.sql(f"OPTIMIZE {LAKEHOUSE}.{tbl} ZORDER BY ({cols})")
    print(f"  optimised {tbl}")

print(f"\nBronze -> Silver complete for batch {batch_id}")
mssparkutils.notebook.exit("PASS")
