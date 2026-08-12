# Fabric notebook source
# ---------------------------------------------------------------------------
# nb_02_silver_conform
# ---------------------------------------------------------------------------
# Bronze -> Silver. Cleans, types, de-duplicates and conforms the four sources
# into business entities. Derived flags that the whole business shares a
# definition of (redeemed, delayed, SLA breach) are calculated once here rather
# than repeatedly in DAX.
#
# Attach to: lh_merchant_silver  (reads lh_merchant_bronze via shortcut)
# ---------------------------------------------------------------------------

# PARAMETERS CELL ********************

# A voucher redeemed more than this many days after sale counts as delayed.
# Business-agreed threshold; the observed median lag is ~3 days for every
# voucher type, so 7 days is comfortably outside normal behaviour.
delayed_redemption_threshold_days = 7

# CELL ********************

from pyspark.sql import Window
from pyspark.sql import functions as F

BRONZE, SILVER = "lh_merchant_bronze", "lh_merchant_silver"

# MARKDOWN ******************************

# ## De-duplication
#
# The transactional sources append every day, so a re-run or a re-sent file
# produces duplicates in Bronze by design. Silver keeps the most recently
# ingested version of each business key.

# CELL ********************

def latest_by_key(table: str, keys: list[str]):
    """Keep one row per business key - the one from the newest ingest run."""
    df = spark.table(f"{BRONZE}.{table}")
    w = Window.partitionBy(*keys).orderBy(F.col("_ingested_at_utc").desc(),
                                          F.col("_run_id").desc())
    return (df.withColumn("_rn", F.row_number().over(w))
            .filter(F.col("_rn") == 1)
            .drop("_rn"))

# MARKDOWN ******************************

# ## Merchant
#
# The one place merchant name, region and channel are allowed to live. The
# three fact sources each repeat these attributes; Silver drops them there and
# keeps them here, so a merchant that changes region changes in one place.

# CELL ********************

merchant = (latest_by_key("br_merchant_reference", ["MerchantID"])
            .select(
                F.col("MerchantID").alias("MerchantKey"),
                F.trim("Merchant").alias("Merchant"),
                F.trim("Region").alias("Region"),
                F.trim("Channel").alias("Channel"),
                F.trim("ActiveStatus").alias("ActiveStatus"),
                F.trim("AccountManager").alias("AccountManager"),
                F.col("OnboardedDate"),
                F.col("BaseMonthlySalesTarget"),
            ))

merchant.write.format("delta").mode("overwrite").option(
    "overwriteSchema", "true").saveAsTable(f"{SILVER}.slv_merchant")

# MARKDOWN ******************************

# ## Sales
#
# Grain: one row per merchant per voucher type per day.

# CELL ********************

sales = (latest_by_key("br_merchant_sales", ["Date", "MerchantID", "VoucherType"])
         .select(
             F.col("Date"),
             F.col("MerchantID").alias("MerchantKey"),
             F.trim("VoucherType").alias("VoucherTypeKey"),
             F.col("SalesValue").cast("decimal(18,2)").alias("SalesValue"),
             F.col("Transactions").cast("int").alias("Transactions"),
         )
         # A negative day is a reversal artefact, not a sale. Kept visible in
         # Bronze, excluded from Silver, counted in the DQ table.
         .filter((F.col("SalesValue") >= 0) & (F.col("Transactions") >= 0)))

sales.write.format("delta").mode("overwrite").option(
    "overwriteSchema", "true").partitionBy("Date").saveAsTable(
    f"{SILVER}.slv_merchant_sales")

# MARKDOWN ******************************

# ## Redemptions
#
# Grain: one row per voucher. `IsDelayedRedemption` is null for a voucher that
# has not been redeemed - an unredeemed voucher is not "on time", it simply has
# no answer yet, and averaging it in as a zero would understate the delay rate.

# CELL ********************

redemptions = (latest_by_key("br_voucher_redemptions", ["VoucherID"])
               .select(
                   F.col("VoucherID"),
                   F.col("MerchantID").alias("MerchantKey"),
                   F.trim("VoucherType").alias("VoucherTypeKey"),
                   F.col("SoldDate"),
                   F.col("RedeemedDate"),
                   F.col("VoucherValue").cast("decimal(18,2)").alias("VoucherValue"),
                   F.when(F.upper(F.trim("Redeemed")) == "YES", 1)
                    .otherwise(0).cast("tinyint").alias("IsRedeemed"),
               )
               .withColumn("DaysToRedeem",
                           F.datediff("RedeemedDate", "SoldDate"))
               .withColumn(
                   "IsDelayedRedemption",
                   F.when(F.col("IsRedeemed") == 0, F.lit(None).cast("tinyint"))
                    .when(F.col("DaysToRedeem")
                          > delayed_redemption_threshold_days, F.lit(1))
                    .otherwise(F.lit(0)).cast("tinyint"))
               # A redemption before the sale is impossible; quarantine rather
               # than silently absorb it.
               .withColumn("_is_valid",
                           F.col("DaysToRedeem").isNull()
                           | (F.col("DaysToRedeem") >= 0)))

quarantine = redemptions.filter(~F.col("_is_valid"))
if quarantine.count() > 0:
    quarantine.write.format("delta").mode("append").saveAsTable(
        f"{SILVER}.slv_quarantine_redemptions")

(redemptions.filter(F.col("_is_valid")).drop("_is_valid")
 .write.format("delta").mode("overwrite").option("overwriteSchema", "true")
 .saveAsTable(f"{SILVER}.slv_voucher_redemptions"))

# MARKDOWN ******************************

# ## Support tickets
#
# `SLAHours` is a fixed property of `Priority`, not of the individual ticket -
# it is promoted to the priority dimension in Gold and kept here only so a
# change in SLA policy is visible in history.

# CELL ********************

tickets = (latest_by_key("br_support_tickets", ["TicketID"])
           .select(
               F.col("TicketID"),
               F.col("Date"),
               F.col("MerchantID").alias("MerchantKey"),
               F.trim("TicketType").alias("TicketTypeKey"),
               F.trim("Priority").alias("PriorityKey"),
               F.col("ResolutionHours").cast("decimal(10,2)").alias("ResolutionHours"),
               F.col("SLAHours").cast("int").alias("SLAHours"),
               F.trim("Status").alias("Status"),
           )
           .withColumn("IsSLABreach",
                       (F.col("ResolutionHours") > F.col("SLAHours"))
                       .cast("tinyint"))
           .withColumn("IsOpen", (F.col("Status") != "Closed").cast("tinyint")))

tickets.write.format("delta").mode("overwrite").option(
    "overwriteSchema", "true").saveAsTable(f"{SILVER}.slv_support_tickets")

# MARKDOWN ******************************

# ## Orphan check
#
# Any fact row whose merchant is not in the reference file would silently
# vanish from every merchant-sliced visual. It is caught here, not discovered
# in a meeting.

# CELL ********************

keys = merchant.select("MerchantKey")
orphans = []
for name, df in (("slv_merchant_sales", sales),
                 ("slv_voucher_redemptions", redemptions),
                 ("slv_support_tickets", tickets)):
    n = df.join(F.broadcast(keys), "MerchantKey", "left_anti").count()
    orphans.append((name, n))
    print(f"  {name:<32} {n} orphan merchant keys")

if any(n for _, n in orphans):
    raise ValueError(f"Orphan merchant keys found: {orphans}")

print("Silver conform complete.")
