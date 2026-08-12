"""
02_build_warehouse.py
=====================
Local, runnable implementation of the Microsoft Fabric medallion architecture used in this
solution. It is the *reference implementation* — the Fabric notebooks in /notebooks and the
dbt models in /dbt express exactly the same logic against a Lakehouse/Warehouse, and this
script proves the transformations produce correct output before anything is deployed.

    RAW  (CSV landing / OneLake Files)
      -> BRONZE  Delta/Parquet, schema-on-write, lineage columns, no business logic
      -> SILVER  cleaned, typed, conformed, deduplicated, business rules applied
      -> GOLD    Kimball star schema consumed by Power BI Direct Lake

Naming convention (documented in the report):
    bronze_<source>          silver_<entity>          dim_* / fact_*
Surrogate keys are integer, generated in the gold layer, never exposed to users.
"""
from __future__ import annotations

from pathlib import Path
import hashlib
import numpy as np
import pandas as pd
import duckdb

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
BRONZE = ROOT / "data" / "bronze"
SILVER = ROOT / "data" / "silver"
GOLD = ROOT / "data" / "gold"
for p in (BRONZE, SILVER, GOLD):
    p.mkdir(parents=True, exist_ok=True)

LOAD_TS = pd.Timestamp("2026-08-11 06:00:00")
BATCH_ID = "20260811T060000Z"

# Business rules that must match the DAX / dbt definitions exactly.
DELAYED_REDEMPTION_DAYS = 7          # a redemption taking > 7 days is "delayed"
EXPIRY_DAYS = 90                     # unredeemed after 90 days -> assumed breakage
HIGH_PRIORITIES = ("High", "Critical")

log = lambda m: print(f"[{pd.Timestamp.now():%H:%M:%S}] {m}")


def write(df: pd.DataFrame, layer: Path, name: str) -> pd.DataFrame:
    """Persist a layer table as parquet (the Delta stand-in) and CSV (for inspection)."""
    df.to_parquet(layer / f"{name}.parquet", index=False)
    df.to_csv(layer / f"{name}.csv", index=False)
    log(f"  wrote {layer.name}/{name}  rows={len(df):,}  cols={df.shape[1]}")
    return df


def surrogate(series: pd.Series) -> pd.Series:
    """Deterministic integer surrogate key from a natural key (stable across reloads)."""
    return series.map(lambda v: int(hashlib.md5(str(v).encode()).hexdigest()[:8], 16) % 2_000_000_000)


# =============================================================================
# BRONZE — land raw exactly as received, add audit columns only
# =============================================================================
log("BRONZE  ingesting raw landing files")

bronze = {}
for name, fn in [
    ("bronze_merchant_reference", "MerchantReference.csv"),
    ("bronze_merchant_sales", "MerchantSales.csv"),
    ("bronze_support_tickets", "SupportTickets.csv"),
    ("bronze_voucher_redemptions", "VoucherRedemptions.csv"),
]:
    df = pd.read_csv(RAW / fn, dtype=str)          # schema-on-read as string: no silent coercion
    df["_source_file"] = fn
    df["_ingested_at"] = LOAD_TS
    df["_batch_id"] = BATCH_ID
    bronze[name] = write(df, BRONZE, name)


# =============================================================================
# SILVER — type, clean, conform, deduplicate, apply business rules
# =============================================================================
log("SILVER  cleansing and conforming")

# ---- silver_merchant -------------------------------------------------------
m = bronze["bronze_merchant_reference"].copy()
m["MerchantID"] = m.MerchantID.str.strip().str.upper()
m["Merchant"] = m.Merchant.str.strip()
for c in ("Region", "Channel", "ActiveStatus", "AccountManager"):
    m[c] = m[c].str.strip()
m["OnboardedDate"] = pd.to_datetime(m.OnboardedDate)
m["BaseMonthlySalesTarget"] = m.BaseMonthlySalesTarget.astype(float)
m = m.drop_duplicates(subset=["MerchantID"], keep="last")
silver_merchant = write(m.drop(columns=["_source_file"]), SILVER, "silver_merchant")

# ---- silver_merchant_sales -------------------------------------------------
s = bronze["bronze_merchant_sales"].copy()
s["Date"] = pd.to_datetime(s.Date)
s["MerchantID"] = s.MerchantID.str.strip().str.upper()
s["VoucherType"] = s.VoucherType.str.strip()
s["SalesValue"] = s.SalesValue.astype(float)
s["Transactions"] = s.Transactions.astype(int)
# Fact tables keep only keys + measures; descriptive attributes come from the dimension.
s = s[["Date", "MerchantID", "VoucherType", "SalesValue", "Transactions", "_batch_id", "_ingested_at"]]
# Defensive de-dup at the declared grain (profiling shows none, the rule still belongs here).
s = s.groupby(["Date", "MerchantID", "VoucherType"], as_index=False).agg(
    SalesValue=("SalesValue", "sum"),
    Transactions=("Transactions", "sum"),
    _batch_id=("_batch_id", "first"),
    _ingested_at=("_ingested_at", "first"),
)
s["AvgBasketValue"] = np.where(s.Transactions > 0, s.SalesValue / s.Transactions, np.nan)
silver_sales = write(s, SILVER, "silver_merchant_sales")

# ---- silver_voucher_redemptions -------------------------------------------
v = bronze["bronze_voucher_redemptions"].copy()
v["MerchantID"] = v.MerchantID.str.strip().str.upper()
v["VoucherType"] = v.VoucherType.str.strip()
v["SoldDate"] = pd.to_datetime(v.SoldDate)
v["RedeemedDate"] = pd.to_datetime(v.RedeemedDate, errors="coerce")
v["VoucherValue"] = v.VoucherValue.astype(float)
v["IsRedeemed"] = v.Redeemed.str.strip().str.lower().eq("yes")
# Integrity rule: a voucher is only redeemed if it carries a valid, non-retrograde redeem date.
bad = v.IsRedeemed & (v.RedeemedDate.isna() | (v.RedeemedDate < v.SoldDate))
v["_quality_flag"] = np.where(bad, "REDEEM_DATE_INVALID", "OK")
v.loc[bad, "IsRedeemed"] = False
v["DaysToRedeem"] = (v.RedeemedDate - v.SoldDate).dt.days
v.loc[~v.IsRedeemed, "DaysToRedeem"] = np.nan
v["IsDelayedRedemption"] = v.IsRedeemed & (v.DaysToRedeem > DELAYED_REDEMPTION_DAYS)
v["RedeemedValue"] = np.where(v.IsRedeemed, v.VoucherValue, 0.0)
v["OutstandingValue"] = np.where(v.IsRedeemed, 0.0, v.VoucherValue)
# Breakage: sold > EXPIRY_DAYS ago and still unredeemed -> treat as expired liability release.
asof = v.SoldDate.max()
v["IsExpired"] = (~v.IsRedeemed) & ((asof - v.SoldDate).dt.days > EXPIRY_DAYS)
v["BreakageValue"] = np.where(v.IsExpired, v.VoucherValue, 0.0)
v = v[["VoucherID", "MerchantID", "VoucherType", "SoldDate", "RedeemedDate", "VoucherValue",
       "IsRedeemed", "DaysToRedeem", "IsDelayedRedemption", "RedeemedValue", "OutstandingValue",
       "IsExpired", "BreakageValue", "_quality_flag", "_batch_id", "_ingested_at"]]
silver_vouchers = write(v, SILVER, "silver_voucher_redemptions")

# ---- silver_support_tickets ------------------------------------------------
t = bronze["bronze_support_tickets"].copy()
t["Date"] = pd.to_datetime(t.Date)
t["MerchantID"] = t.MerchantID.str.strip().str.upper()
for c in ("TicketType", "Priority", "Status"):
    t[c] = t[c].str.strip()
t["ResolutionHours"] = t.ResolutionHours.astype(float)
t["SLAHours"] = t.SLAHours.astype(int)
t["IsSLABreach"] = t.ResolutionHours > t.SLAHours
t["SLABreachHours"] = np.where(t.IsSLABreach, t.ResolutionHours - t.SLAHours, 0.0)
t["IsHighPriority"] = t.Priority.isin(HIGH_PRIORITIES)
t["IsOpen"] = ~t.Status.eq("Closed")            # Open / Escalated / Pending Merchant = backlog
t["IsEscalated"] = t.Status.eq("Escalated")
t = t[["TicketID", "Date", "MerchantID", "TicketType", "Priority", "Status", "ResolutionHours",
       "SLAHours", "IsSLABreach", "SLABreachHours", "IsHighPriority", "IsOpen", "IsEscalated",
       "_batch_id", "_ingested_at"]]
silver_tickets = write(t, SILVER, "silver_support_tickets")


# =============================================================================
# GOLD — Kimball star schema
# =============================================================================
log("GOLD  building star schema")

# ---- dim_date --------------------------------------------------------------
dmin = min(silver_sales.Date.min(), silver_tickets.Date.min(), silver_vouchers.SoldDate.min())
dmax = max(silver_sales.Date.max(), silver_tickets.Date.max(),
           silver_vouchers.RedeemedDate.max())
# Pad to full calendar years so DAX time-intelligence functions behave.
cal = pd.DataFrame({"Date": pd.date_range(f"{dmin.year}-01-01", f"{dmax.year}-12-31", freq="D")})
cal["DateKey"] = cal.Date.dt.strftime("%Y%m%d").astype(int)
cal["Year"] = cal.Date.dt.year
cal["Quarter"] = cal.Date.dt.quarter
cal["QuarterName"] = "Q" + cal.Quarter.astype(str)
cal["YearQuarter"] = cal.Year.astype(str) + "-Q" + cal.Quarter.astype(str)
cal["MonthNumber"] = cal.Date.dt.month
cal["MonthName"] = cal.Date.dt.strftime("%B")
cal["MonthShort"] = cal.Date.dt.strftime("%b")
cal["YearMonth"] = cal.Date.dt.strftime("%Y-%m")
cal["MonthYearLabel"] = cal.Date.dt.strftime("%b %Y")
cal["MonthYearSort"] = cal.Year * 100 + cal.MonthNumber
cal["MonthStartDate"] = cal.Date.values.astype("datetime64[M]")
cal["MonthEndDate"] = cal.MonthStartDate + pd.offsets.MonthEnd(0)
cal["DayOfMonth"] = cal.Date.dt.day
cal["DayOfWeek"] = cal.Date.dt.dayofweek + 1
cal["DayName"] = cal.Date.dt.strftime("%A")
cal["DayShort"] = cal.Date.dt.strftime("%a")
cal["WeekOfYear"] = cal.Date.dt.isocalendar().week.astype(int)
cal["YearWeek"] = cal.Year.astype(str) + "-W" + cal.WeekOfYear.astype(str).str.zfill(2)
cal["IsWeekend"] = cal.DayOfWeek.isin([6, 7])
maxfact = silver_sales.Date.max()
cal["IsInFactWindow"] = (cal.Date >= dmin) & (cal.Date <= maxfact)
cal["RelativeMonthOffset"] = ((cal.Year - maxfact.year) * 12 + (cal.MonthNumber - maxfact.month))
cal["IsCurrentMonth"] = cal.RelativeMonthOffset.eq(0)
cal["IsPriorMonth"] = cal.RelativeMonthOffset.eq(-1)
dim_date = write(cal, GOLD, "dim_date")

# ---- dim_merchant ----------------------------------------------------------
dm = silver_merchant.copy()
dm["MerchantKey"] = surrogate(dm.MerchantID)
dm["TenureMonths"] = ((maxfact - dm.OnboardedDate).dt.days / 30.44).round(0).astype(int)
dm["TenureBand"] = pd.cut(dm.TenureMonths, [-1, 12, 24, 36, 10_000],
                          labels=["< 1 year", "1-2 years", "2-3 years", "3+ years"])
_tot = silver_sales.groupby("MerchantID").SalesValue.sum()
dm["_TotalSales"] = dm.MerchantID.map(_tot)
dm["MerchantSizeBand"] = pd.qcut(dm._TotalSales, [0, .25, .60, .85, 1.0],
                                 labels=["Small", "Mid", "Large", "Strategic"])
dm["AnnualisedTarget"] = dm.BaseMonthlySalesTarget * 12
dm = dm[["MerchantKey", "MerchantID", "Merchant", "Region", "Channel", "ActiveStatus",
         "AccountManager", "OnboardedDate", "TenureMonths", "TenureBand",
         "BaseMonthlySalesTarget", "AnnualisedTarget", "MerchantSizeBand"]]
dim_merchant = write(dm, GOLD, "dim_merchant")
mkey = dim_merchant.set_index("MerchantID").MerchantKey

# ---- dim_voucher_type ------------------------------------------------------
vt_meta = {
    "Airtime":      ("Prepaid Telco",   "Low",    1),
    "Electricity":  ("Utilities",       "Low",    2),
    "Bill Payment": ("Utilities",       "Medium", 3),
    "Groceries":    ("Retail Goods",    "Medium", 4),
    "Gaming":       ("Digital Content", "High",   5),
}
vt = pd.DataFrame([{"VoucherType": k, "VoucherCategory": a, "MarginBand": b, "VoucherTypeSort": c}
                   for k, (a, b, c) in vt_meta.items()])
vt["VoucherTypeKey"] = surrogate(vt.VoucherType)
dim_voucher_type = write(vt[["VoucherTypeKey", "VoucherType", "VoucherCategory",
                             "MarginBand", "VoucherTypeSort"]], GOLD, "dim_voucher_type")
vkey = dim_voucher_type.set_index("VoucherType").VoucherTypeKey

# ---- dim_ticket_type -------------------------------------------------------
tt_meta = {
    "Voucher Not Received": ("Fulfilment", "Customer Impacting"),
    "Redemption Issue":     ("Fulfilment", "Customer Impacting"),
    "Reversal Query":       ("Financial",  "Customer Impacting"),
    "Settlement Delay":     ("Financial",  "Merchant Impacting"),
    "Pricing Query":        ("Commercial", "Merchant Impacting"),
    "Merchant Support":     ("Commercial", "Merchant Impacting"),
}
tt = pd.DataFrame([{"TicketType": k, "TicketCategory": a, "ImpactArea": b}
                   for k, (a, b) in tt_meta.items()])
tt["TicketTypeKey"] = surrogate(tt.TicketType)
dim_ticket_type = write(tt[["TicketTypeKey", "TicketType", "TicketCategory", "ImpactArea"]],
                        GOLD, "dim_ticket_type")
tkey = dim_ticket_type.set_index("TicketType").TicketTypeKey

# ---- dim_priority ----------------------------------------------------------
pr = pd.DataFrame([
    {"Priority": "Critical", "PrioritySort": 1, "TargetSLAHours": 12, "SeverityWeight": 4.0},
    {"Priority": "High",     "PrioritySort": 2, "TargetSLAHours": 24, "SeverityWeight": 3.0},
    {"Priority": "Medium",   "PrioritySort": 3, "TargetSLAHours": 36, "SeverityWeight": 2.0},
    {"Priority": "Low",      "PrioritySort": 4, "TargetSLAHours": 48, "SeverityWeight": 1.0},
])
pr["PriorityKey"] = surrogate(pr.Priority)
dim_priority = write(pr[["PriorityKey", "Priority", "PrioritySort", "TargetSLAHours",
                         "SeverityWeight"]], GOLD, "dim_priority")
pkey = dim_priority.set_index("Priority").PriorityKey

# ---- dim_ticket_status -----------------------------------------------------
sta = pd.DataFrame([
    {"Status": "Closed",           "StatusSort": 1, "IsOpenStatus": False, "StatusGroup": "Resolved"},
    {"Status": "Pending Merchant", "StatusSort": 2, "IsOpenStatus": True,  "StatusGroup": "Waiting"},
    {"Status": "Open",             "StatusSort": 3, "IsOpenStatus": True,  "StatusGroup": "In Progress"},
    {"Status": "Escalated",        "StatusSort": 4, "IsOpenStatus": True,  "StatusGroup": "Escalated"},
])
sta["StatusKey"] = surrogate(sta.Status)
dim_ticket_status = write(sta[["StatusKey", "Status", "StatusSort", "IsOpenStatus", "StatusGroup"]],
                          GOLD, "dim_ticket_status")
skey = dim_ticket_status.set_index("Status").StatusKey

# ---- fact_merchant_sales ---------------------------------------------------
f = silver_sales.copy()
f["DateKey"] = f.Date.dt.strftime("%Y%m%d").astype(int)
f["MerchantKey"] = f.MerchantID.map(mkey)
f["VoucherTypeKey"] = f.VoucherType.map(vkey)
fact_sales = write(
    f[["DateKey", "MerchantKey", "VoucherTypeKey", "SalesValue", "Transactions",
       "AvgBasketValue", "_batch_id"]], GOLD, "fact_merchant_sales")

# ---- fact_voucher_redemptions ---------------------------------------------
f = silver_vouchers.copy()
f["SoldDateKey"] = f.SoldDate.dt.strftime("%Y%m%d").astype(int)
f["RedeemedDateKey"] = f.RedeemedDate.dt.strftime("%Y%m%d").astype("Int64")   # null-safe
f["MerchantKey"] = f.MerchantID.map(mkey)
f["VoucherTypeKey"] = f.VoucherType.map(vkey)
f["VoucherCount"] = 1
fact_redemptions = write(
    f[["VoucherID", "SoldDateKey", "RedeemedDateKey", "MerchantKey", "VoucherTypeKey",
       "VoucherValue", "VoucherCount", "IsRedeemed", "DaysToRedeem", "IsDelayedRedemption",
       "RedeemedValue", "OutstandingValue", "IsExpired", "BreakageValue", "_batch_id"]],
    GOLD, "fact_voucher_redemptions")

# ---- fact_support_tickets --------------------------------------------------
f = silver_tickets.copy()
f["DateKey"] = f.Date.dt.strftime("%Y%m%d").astype(int)
f["MerchantKey"] = f.MerchantID.map(mkey)
f["TicketTypeKey"] = f.TicketType.map(tkey)
f["PriorityKey"] = f.Priority.map(pkey)
f["StatusKey"] = f.Status.map(skey)
f["TicketCount"] = 1
fact_tickets = write(
    f[["TicketID", "DateKey", "MerchantKey", "TicketTypeKey", "PriorityKey", "StatusKey",
       "TicketCount", "ResolutionHours", "SLAHours", "IsSLABreach", "SLABreachHours",
       "IsHighPriority", "IsOpen", "IsEscalated", "_batch_id"]], GOLD, "fact_support_tickets")

# ---- fact_merchant_target (monthly, enables Sales vs Target) ---------------
months = dim_date.loc[dim_date.IsInFactWindow, ["MonthStartDate"]].drop_duplicates()
tgt = months.merge(dim_merchant[["MerchantKey", "BaseMonthlySalesTarget"]], how="cross")
tgt["DateKey"] = pd.to_datetime(tgt.MonthStartDate).dt.strftime("%Y%m%d").astype(int)
# July 2026 is a part-month in the data (31 days present) — targets are pro-rated by days covered
days_in_fact = (dim_date[dim_date.IsInFactWindow]
                .groupby("MonthStartDate").size().rename("DaysCovered"))
days_in_month = dim_date.groupby("MonthStartDate").size().rename("DaysInMonth")
tgt = tgt.merge(days_in_fact, on="MonthStartDate").merge(days_in_month, on="MonthStartDate")
tgt["MonthlySalesTarget"] = (tgt.BaseMonthlySalesTarget * tgt.DaysCovered / tgt.DaysInMonth).round(2)
fact_target = write(tgt[["DateKey", "MerchantKey", "MonthlySalesTarget", "DaysCovered",
                         "DaysInMonth"]], GOLD, "fact_merchant_target")


# =============================================================================
# Load the gold layer into DuckDB so every downstream artefact queries ONE source
# =============================================================================
log("Loading gold layer into DuckDB (mvi.duckdb)")
dbpath = ROOT / "data" / "mvi.duckdb"
if dbpath.exists():
    dbpath.unlink()
con = duckdb.connect(str(dbpath))
for name in ["dim_date", "dim_merchant", "dim_voucher_type", "dim_ticket_type", "dim_priority",
             "dim_ticket_status", "fact_merchant_sales", "fact_voucher_redemptions",
             "fact_support_tickets", "fact_merchant_target"]:
    con.execute(f"CREATE TABLE {name} AS SELECT * FROM read_parquet('{(GOLD / (name + '.parquet')).as_posix()}')")
for name in ["silver_merchant", "silver_merchant_sales", "silver_voucher_redemptions",
             "silver_support_tickets"]:
    con.execute(f"CREATE TABLE {name} AS SELECT * FROM read_parquet('{(SILVER / (name + '.parquet')).as_posix()}')")

# ---------------------------------------------------------------- integrity gate
log("Running warehouse integrity tests")
tests = [
    ("fact_merchant_sales has no orphan MerchantKey",
     "SELECT COUNT(*) FROM fact_merchant_sales f LEFT JOIN dim_merchant d USING(MerchantKey) WHERE d.MerchantKey IS NULL"),
    ("fact_merchant_sales has no orphan DateKey",
     "SELECT COUNT(*) FROM fact_merchant_sales f LEFT JOIN dim_date d USING(DateKey) WHERE d.DateKey IS NULL"),
    ("fact_merchant_sales has no orphan VoucherTypeKey",
     "SELECT COUNT(*) FROM fact_merchant_sales f LEFT JOIN dim_voucher_type d USING(VoucherTypeKey) WHERE d.VoucherTypeKey IS NULL"),
    ("fact_voucher_redemptions has no orphan MerchantKey",
     "SELECT COUNT(*) FROM fact_voucher_redemptions f LEFT JOIN dim_merchant d USING(MerchantKey) WHERE d.MerchantKey IS NULL"),
    ("fact_support_tickets has no orphan PriorityKey",
     "SELECT COUNT(*) FROM fact_support_tickets f LEFT JOIN dim_priority d USING(PriorityKey) WHERE d.PriorityKey IS NULL"),
    ("dim_merchant MerchantKey is unique",
     "SELECT COUNT(*)-COUNT(DISTINCT MerchantKey) FROM dim_merchant"),
    ("dim_date DateKey is unique",
     "SELECT COUNT(*)-COUNT(DISTINCT DateKey) FROM dim_date"),
    ("fact grain Date+Merchant+VoucherType is unique",
     "SELECT COUNT(*)-COUNT(DISTINCT (DateKey,MerchantKey,VoucherTypeKey)) FROM fact_merchant_sales"),
    ("no negative SalesValue",
     "SELECT COUNT(*) FROM fact_merchant_sales WHERE SalesValue < 0"),
    ("no negative DaysToRedeem",
     "SELECT COUNT(*) FROM fact_voucher_redemptions WHERE DaysToRedeem < 0"),
    ("redeemed vouchers all carry a RedeemedDateKey",
     "SELECT COUNT(*) FROM fact_voucher_redemptions WHERE IsRedeemed AND RedeemedDateKey IS NULL"),
    ("unredeemed vouchers carry no RedeemedDateKey",
     "SELECT COUNT(*) FROM fact_voucher_redemptions WHERE NOT IsRedeemed AND RedeemedDateKey IS NOT NULL"),
    ("silver sales value reconciles to gold",
     "SELECT CAST(ABS((SELECT SUM(SalesValue) FROM silver_merchant_sales)-(SELECT SUM(SalesValue) FROM fact_merchant_sales)) > 0.01 AS INT)"),
    ("ticket count reconciles raw -> gold",
     "SELECT ABS((SELECT COUNT(*) FROM silver_support_tickets)-(SELECT COUNT(*) FROM fact_support_tickets))"),
]
failed = 0
for label, sql in tests:
    got = con.execute(sql).fetchone()[0]
    ok = (got == 0)
    failed += (not ok)
    print(f"   {'PASS' if ok else 'FAIL'}  {label}" + ("" if ok else f"   -> {got}"))
print(f"\n   {len(tests) - failed}/{len(tests)} integrity tests passed")

con.close()
log("Warehouse build complete -> data/mvi.duckdb")
