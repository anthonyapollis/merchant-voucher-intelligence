# Fabric notebook source
# ---------------------------------------------------------------------------
# nb_03_gold_star_schema
# ---------------------------------------------------------------------------
# Silver -> Gold. Builds the star schema the semantic model imports: five
# dimensions and three fact tables, all keyed on integer/short surrogate keys.
#
# Design rules applied here:
#   * Facts carry keys and measures only. Every descriptive attribute lives in
#     a dimension, once.
#   * DimDate is generated, not derived from the facts, so it is contiguous and
#     covers dates no fact has reached yet (a voucher sold in July can be
#     redeemed in August).
#   * SLAHours moves from the ticket to DimPriority, because it is a property
#     of the priority tier, not of the ticket.
#
# Attach to: lh_merchant_gold  (reads lh_merchant_silver via shortcut)
# ---------------------------------------------------------------------------

# CELL ********************

from pyspark.sql import functions as F
from pyspark.sql.types import IntegerType

SILVER, GOLD = "lh_merchant_silver", "lh_merchant_gold"

sales = spark.table(f"{SILVER}.slv_merchant_sales")
redemptions = spark.table(f"{SILVER}.slv_voucher_redemptions")
tickets = spark.table(f"{SILVER}.slv_support_tickets")
merchant = spark.table(f"{SILVER}.slv_merchant")

# MARKDOWN ******************************

# ## DimDate
#
# Generated across whole months so year-to-date and month-over-month behave at
# the boundaries, and extended to the latest date any fact points at - which is
# a redemption date, not a sales date.

# CELL ********************

bounds = (sales.select(F.min("Date").alias("lo"), F.max("Date").alias("hi"))
          .union(redemptions.select(F.min("SoldDate"), F.max("RedeemedDate")))
          .union(tickets.select(F.min("Date"), F.max("Date")))
          .agg(F.min("lo").alias("lo"), F.max("hi").alias("hi")).collect()[0])

start = F.trunc(F.lit(bounds["lo"]), "month")
end = F.last_day(F.lit(bounds["hi"]))

dim_date = (spark.sql("SELECT 1")
            .select(F.explode(F.sequence(start, end, F.expr("interval 1 day")))
                    .alias("Date"))
            .withColumn("DateKey", F.date_format("Date", "yyyyMMdd").cast(IntegerType()))
            .withColumn("Year", F.year("Date"))
            .withColumn("QuarterNumber", F.quarter("Date"))
            .withColumn("Quarter", F.concat(F.lit("Q"), F.quarter("Date")))
            .withColumn("MonthNumber", F.month("Date"))
            .withColumn("MonthName", F.date_format("Date", "MMMM"))
            .withColumn("MonthShort", F.date_format("Date", "MMM"))
            .withColumn("MonthYear", F.date_format("Date", "MMM yyyy"))
            # Sort column: without it "Apr 2026" sorts before "Jan 2026"
            # alphabetically on every axis and legend in the report.
            .withColumn("MonthYearSort", F.year("Date") * 100 + F.month("Date"))
            .withColumn("Day", F.dayofmonth("Date"))
            .withColumn("DayName", F.date_format("Date", "EEEE"))
            .withColumn("DayOfWeek", F.dayofweek("Date"))
            .withColumn("IsWeekend",
                        F.when(F.dayofweek("Date").isin(1, 7), 1).otherwise(0))
            .withColumn("WeekOfYear", F.weekofyear("Date"))
            .withColumn("WeekStartDate", F.date_sub(
                F.col("Date"), F.dayofweek("Date") - 2))
            .withColumn("MonthStartDate", F.trunc("Date", "month"))
            .withColumn("MonthEndDate", F.last_day("Date")))

dim_date.write.format("delta").mode("overwrite").option(
    "overwriteSchema", "true").saveAsTable(f"{GOLD}.DimDate")

# MARKDOWN ******************************

# ## DimMerchant

# CELL ********************

as_of = sales.agg(F.max("Date")).collect()[0][0]

dim_merchant = (merchant
                .withColumn("TenureMonths",
                            F.months_between(F.lit(as_of), F.col("OnboardedDate"))
                            .cast("int"))
                .withColumn("TenureBand",
                            F.when(F.col("TenureMonths") <= 12, "0-12 months")
                             .when(F.col("TenureMonths") <= 24, "13-24 months")
                             .when(F.col("TenureMonths") <= 36, "25-36 months")
                             .otherwise("36+ months")))

dim_merchant.write.format("delta").mode("overwrite").option(
    "overwriteSchema", "true").saveAsTable(f"{GOLD}.DimMerchant")

# MARKDOWN ******************************

# ## DimVoucherType, DimTicketType, DimPriority
#
# Small conformed dimensions. The category and settlement-model columns are
# grouping logic the business asked for; they belong in the model rather than
# in a dozen report-level calculated columns.

# CELL ********************

dim_voucher = (sales.select(F.col("VoucherTypeKey"))
               .union(redemptions.select("VoucherTypeKey"))
               .distinct()
               .withColumn("VoucherType", F.col("VoucherTypeKey"))
               .withColumn("SettlementModel",
                           F.when(F.col("VoucherTypeKey")
                                  .isin("Airtime", "Electricity", "Gaming"),
                                  "Prepaid")
                            .otherwise("Third-party settled")))

dim_voucher.write.format("delta").mode("overwrite").option(
    "overwriteSchema", "true").saveAsTable(f"{GOLD}.DimVoucherType")

dim_ticket_type = (tickets.select("TicketTypeKey").distinct()
                   .withColumn("TicketType", F.col("TicketTypeKey"))
                   .withColumn("TicketCategory",
                               F.when(F.col("TicketTypeKey").isin(
                                   "Settlement Delay", "Reversal Query",
                                   "Pricing Query"), "Financial")
                                .when(F.col("TicketTypeKey").isin(
                                    "Voucher Not Received", "Redemption Issue"),
                                    "Fulfilment")
                                .otherwise("Service")))

dim_ticket_type.write.format("delta").mode("overwrite").option(
    "overwriteSchema", "true").saveAsTable(f"{GOLD}.DimTicketType")

dim_priority = (tickets.groupBy(F.col("PriorityKey"))
                .agg(F.max("SLAHours").alias("SLATargetHours"))
                .withColumn("Priority", F.col("PriorityKey"))
                .withColumn("PrioritySort",
                            F.when(F.col("PriorityKey") == "Critical", 1)
                             .when(F.col("PriorityKey") == "High", 2)
                             .when(F.col("PriorityKey") == "Medium", 3)
                             .otherwise(4)))

dim_priority.write.format("delta").mode("overwrite").option(
    "overwriteSchema", "true").saveAsTable(f"{GOLD}.DimPriority")

# MARKDOWN ******************************

# ## Facts

# CELL ********************

def dk(col: str):
    return F.date_format(F.col(col), "yyyyMMdd").cast(IntegerType())


(sales
 .select(dk("Date").alias("DateKey"), "MerchantKey", "VoucherTypeKey",
         "SalesValue", "Transactions")
 .write.format("delta").mode("overwrite").option("overwriteSchema", "true")
 .saveAsTable(f"{GOLD}.FactMerchantSales"))

(redemptions
 .select("VoucherID",
         dk("SoldDate").alias("SoldDateKey"),
         dk("RedeemedDate").alias("RedeemedDateKey"),
         "MerchantKey", "VoucherTypeKey", "VoucherValue", "IsRedeemed",
         "DaysToRedeem", "IsDelayedRedemption")
 .write.format("delta").mode("overwrite").option("overwriteSchema", "true")
 .saveAsTable(f"{GOLD}.FactVoucherRedemptions"))

(tickets
 .select("TicketID", dk("Date").alias("DateKey"), "MerchantKey",
         "TicketTypeKey", "PriorityKey", "ResolutionHours", "SLAHours",
         "Status", "IsSLABreach", "IsOpen")
 .write.format("delta").mode("overwrite").option("overwriteSchema", "true")
 .saveAsTable(f"{GOLD}.FactSupportTickets"))

# MARKDOWN ******************************

# ## Optimise
#
# Z-ordering the two large facts on the columns the report filters hardest
# keeps the DirectLake scan narrow.

# CELL ********************

spark.sql(f"OPTIMIZE {GOLD}.FactMerchantSales ZORDER BY (DateKey, MerchantKey)")
spark.sql(f"OPTIMIZE {GOLD}.FactVoucherRedemptions ZORDER BY (SoldDateKey, MerchantKey)")
spark.sql(f"OPTIMIZE {GOLD}.FactSupportTickets ZORDER BY (DateKey, MerchantKey)")

for t in ("DimDate", "DimMerchant", "DimVoucherType", "DimTicketType",
          "DimPriority", "FactMerchantSales", "FactVoucherRedemptions",
          "FactSupportTickets"):
    print(f"  {t:<26} {spark.table(f'{GOLD}.{t}').count():>9,} rows")

print("Gold star schema built.")
