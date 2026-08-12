"""
build_gold.py
=============
Local, dependency-light reference implementation of the Fabric medallion build.

This is the same logic that fabric/notebooks/nb_02_silver_conform.py and
nb_03_gold_star_schema.py run in PySpark, expressed in pandas so the star
schema can be materialised, tested and reviewed without a Fabric capacity.

Outputs
-------
data/gold/*.csv        star-schema tables (Power BI import source)
data/gold/*.parquet    same tables, columnar (preferred by the semantic model)
data/gold/_manifest.json  row counts + checksums for the DQ gate

Run:  python build/build_gold.py
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
GOLD = ROOT / "data" / "gold"
GOLD.mkdir(parents=True, exist_ok=True)

# Delayed-redemption threshold. Documented assumption: the business treats a
# voucher redeemed more than 7 calendar days after sale as "delayed", because
# the observed median time-to-redeem is ~3 days across every voucher type.
DELAY_THRESHOLD_DAYS = 7


# ---------------------------------------------------------------- bronze ----
def read_bronze() -> dict[str, pd.DataFrame]:
    """Land the source files as-is. No typing beyond dates, no filtering."""
    sales = pd.read_csv(RAW / "MerchantSales.csv", parse_dates=["Date"])
    redemptions = pd.read_csv(
        RAW / "VoucherRedemptions.csv", parse_dates=["SoldDate", "RedeemedDate"]
    )
    tickets = pd.read_csv(RAW / "SupportTickets.csv", parse_dates=["Date"])
    merchants = pd.read_csv(RAW / "MerchantReference.csv", parse_dates=["OnboardedDate"])
    return {
        "sales": sales,
        "redemptions": redemptions,
        "tickets": tickets,
        "merchants": merchants,
    }


# ---------------------------------------------------------------- silver ----
def conform(bronze: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    """Clean, type, de-duplicate and strip redundant descriptive columns.

    MerchantSales, VoucherRedemptions and SupportTickets all repeat merchant
    name / region / channel. Those were verified to agree with
    MerchantReference on every row, so the facts keep only MerchantID and the
    descriptive attributes live once, in DimMerchant.
    """
    sales = bronze["sales"].copy()
    redemptions = bronze["redemptions"].copy()
    tickets = bronze["tickets"].copy()
    merchants = bronze["merchants"].copy()

    for frame, cols in (
        (sales, ["MerchantID", "Merchant", "Region", "Channel", "VoucherType"]),
        (redemptions, ["VoucherID", "MerchantID", "Merchant", "VoucherType"]),
        (tickets, ["TicketID", "MerchantID", "Merchant", "Region", "TicketType",
                   "Priority", "Status"]),
        (merchants, ["MerchantID", "Merchant", "Region", "Channel",
                     "ActiveStatus", "AccountManager"]),
    ):
        for col in cols:
            frame[col] = frame[col].astype("string").str.strip()

    # Grain enforcement (all three arrive clean; the guard stays because a
    # daily incremental load is the intended production pattern).
    sales = sales.drop_duplicates(subset=["Date", "MerchantID", "VoucherType"])
    redemptions = redemptions.drop_duplicates(subset=["VoucherID"])
    tickets = tickets.drop_duplicates(subset=["TicketID"])

    sales = sales[["Date", "MerchantID", "VoucherType", "SalesValue", "Transactions"]]

    redemptions["IsRedeemed"] = (redemptions["Redeemed"] == "Yes").astype("int8")
    redemptions["DaysToRedeem"] = (
        redemptions["RedeemedDate"] - redemptions["SoldDate"]
    ).dt.days
    redemptions["IsDelayedRedemption"] = np.where(
        redemptions["DaysToRedeem"] > DELAY_THRESHOLD_DAYS, 1, 0
    ).astype("int8")
    # An unredeemed voucher is neither delayed nor on-time; it is excluded from
    # the delay ratio rather than counted as zero.
    redemptions.loc[redemptions["IsRedeemed"] == 0, "IsDelayedRedemption"] = np.nan
    redemptions = redemptions[
        ["VoucherID", "MerchantID", "VoucherType", "SoldDate", "RedeemedDate",
         "VoucherValue", "IsRedeemed", "DaysToRedeem", "IsDelayedRedemption"]
    ]

    tickets["IsSLABreach"] = (
        tickets["ResolutionHours"] > tickets["SLAHours"]
    ).astype("int8")
    tickets["IsOpen"] = (tickets["Status"] != "Closed").astype("int8")
    tickets = tickets[
        ["TicketID", "Date", "MerchantID", "TicketType", "Priority",
         "ResolutionHours", "SLAHours", "Status", "IsSLABreach", "IsOpen"]
    ]

    return {
        "sales": sales,
        "redemptions": redemptions,
        "tickets": tickets,
        "merchants": merchants,
    }


# ------------------------------------------------------------------ gold ----
def date_key(series: pd.Series) -> pd.Series:
    """yyyymmdd integer surrogate key; <NA> stays null for open-ended dates."""
    out = series.dt.strftime("%Y%m%d")
    return pd.to_numeric(out, errors="coerce").astype("Int32")


def build_dim_date(start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    days = pd.date_range(start, end, freq="D")
    dim = pd.DataFrame({"Date": days})
    dim["DateKey"] = date_key(dim["Date"])
    dim["Year"] = dim["Date"].dt.year.astype("int16")
    dim["QuarterNumber"] = dim["Date"].dt.quarter.astype("int8")
    dim["Quarter"] = "Q" + dim["QuarterNumber"].astype(str)
    dim["MonthNumber"] = dim["Date"].dt.month.astype("int8")
    dim["MonthName"] = dim["Date"].dt.strftime("%B")
    dim["MonthShort"] = dim["Date"].dt.strftime("%b")
    dim["MonthYear"] = dim["Date"].dt.strftime("%b %Y")
    # Sort column so "Jan 2026" orders before "Feb 2026" on every axis.
    # Cast before multiplying: Year is int16 and Year * 100 overflows it.
    dim["MonthYearSort"] = (dim["Year"].astype("int32") * 100
                            + dim["MonthNumber"].astype("int32")).astype("int32")
    dim["Day"] = dim["Date"].dt.day.astype("int8")
    dim["DayName"] = dim["Date"].dt.strftime("%A")
    dim["DayOfWeek"] = (dim["Date"].dt.dayofweek + 1).astype("int8")  # Mon = 1
    dim["IsWeekend"] = dim["DayOfWeek"].isin([6, 7]).astype("int8")
    dim["WeekOfYear"] = dim["Date"].dt.isocalendar().week.astype("int8")
    dim["WeekStartDate"] = dim["Date"] - pd.to_timedelta(dim["Date"].dt.dayofweek, "D")
    dim["MonthStartDate"] = dim["Date"].values.astype("datetime64[M]")
    dim["MonthEndDate"] = dim["MonthStartDate"] + pd.offsets.MonthEnd(0)
    return dim


def build_gold(silver: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    sales, redemptions = silver["sales"], silver["redemptions"]
    tickets, merchants = silver["tickets"], silver["merchants"]

    # The calendar must cover every date any fact can point at, including
    # RedeemedDate values that fall after the last sales date, and it must be
    # whole months end-to-end for time intelligence to behave.
    min_date = min(sales["Date"].min(), redemptions["SoldDate"].min(),
                   tickets["Date"].min())
    max_date = max(sales["Date"].max(), redemptions["RedeemedDate"].max(),
                   tickets["Date"].max())
    dim_date = build_dim_date(
        pd.Timestamp(min_date).to_period("M").start_time,
        pd.Timestamp(max_date).to_period("M").end_time.normalize(),
    )

    # --- DimMerchant -------------------------------------------------------
    dim_merchant = merchants.rename(columns={"MerchantID": "MerchantKey"}).copy()
    as_of = pd.Timestamp(sales["Date"].max())
    dim_merchant["TenureMonths"] = (
        (as_of.year - dim_merchant["OnboardedDate"].dt.year) * 12
        + (as_of.month - dim_merchant["OnboardedDate"].dt.month)
    ).astype("int16")
    dim_merchant["TenureBand"] = pd.cut(
        dim_merchant["TenureMonths"],
        bins=[-1, 12, 24, 36, 999],
        labels=["0-12 months", "13-24 months", "25-36 months", "36+ months"],
    ).astype("string")
    dim_merchant = dim_merchant[
        ["MerchantKey", "Merchant", "Region", "Channel", "ActiveStatus",
         "AccountManager", "OnboardedDate", "TenureMonths", "TenureBand",
         "BaseMonthlySalesTarget"]
    ]

    # --- DimVoucherType ----------------------------------------------------
    voucher_types = sorted(
        set(sales["VoucherType"].dropna()) | set(redemptions["VoucherType"].dropna())
    )
    # Prepaid types settle instantly at the point of sale; the other two are
    # third-party settled, which is why their redemption behaviour differs.
    prepaid = {"Airtime", "Electricity", "Gaming"}
    dim_voucher = pd.DataFrame({"VoucherTypeKey": voucher_types})
    dim_voucher["VoucherType"] = dim_voucher["VoucherTypeKey"]
    dim_voucher["SettlementModel"] = np.where(
        dim_voucher["VoucherTypeKey"].isin(prepaid), "Prepaid", "Third-party settled"
    )

    # --- DimTicketType / DimPriority --------------------------------------
    dim_ticket_type = pd.DataFrame(
        {"TicketTypeKey": sorted(tickets["TicketType"].dropna().unique())}
    )
    dim_ticket_type["TicketType"] = dim_ticket_type["TicketTypeKey"]
    # Grouping used on the operational page to separate money-movement issues
    # from delivery/service issues.
    category = {
        "Settlement Delay": "Financial",
        "Reversal Query": "Financial",
        "Pricing Query": "Financial",
        "Voucher Not Received": "Fulfilment",
        "Redemption Issue": "Fulfilment",
        "Merchant Support": "Service",
    }
    dim_ticket_type["TicketCategory"] = (
        dim_ticket_type["TicketTypeKey"].map(category).fillna("Other")
    )

    # SLAHours is a fixed attribute of Priority (verified 1:1), so it belongs
    # in the dimension rather than repeated on every ticket row.
    sla = (
        tickets.groupby("Priority", as_index=False)["SLAHours"]
        .max()
        .rename(columns={"Priority": "PriorityKey", "SLAHours": "SLATargetHours"})
    )
    order = {"Critical": 1, "High": 2, "Medium": 3, "Low": 4}
    sla["Priority"] = sla["PriorityKey"]
    sla["PrioritySort"] = sla["PriorityKey"].map(order).astype("int8")
    dim_priority = sla.sort_values("PrioritySort")[
        ["PriorityKey", "Priority", "PrioritySort", "SLATargetHours"]
    ]

    # --- Facts -------------------------------------------------------------
    fact_sales = sales.rename(
        columns={"MerchantID": "MerchantKey", "VoucherType": "VoucherTypeKey"}
    ).copy()
    fact_sales["DateKey"] = date_key(fact_sales["Date"])
    fact_sales = fact_sales[
        ["DateKey", "MerchantKey", "VoucherTypeKey", "SalesValue", "Transactions"]
    ]

    fact_red = redemptions.rename(
        columns={"MerchantID": "MerchantKey", "VoucherType": "VoucherTypeKey"}
    ).copy()
    fact_red["SoldDateKey"] = date_key(fact_red["SoldDate"])
    fact_red["RedeemedDateKey"] = date_key(fact_red["RedeemedDate"])
    fact_red = fact_red[
        ["VoucherID", "SoldDateKey", "RedeemedDateKey", "MerchantKey",
         "VoucherTypeKey", "VoucherValue", "IsRedeemed", "DaysToRedeem",
         "IsDelayedRedemption"]
    ]

    fact_tickets = tickets.rename(
        columns={"MerchantID": "MerchantKey", "TicketType": "TicketTypeKey",
                 "Priority": "PriorityKey"}
    ).copy()
    fact_tickets["DateKey"] = date_key(fact_tickets["Date"])
    fact_tickets = fact_tickets[
        ["TicketID", "DateKey", "MerchantKey", "TicketTypeKey", "PriorityKey",
         "ResolutionHours", "SLAHours", "Status", "IsSLABreach", "IsOpen"]
    ]

    return {
        "DimDate": dim_date,
        "DimMerchant": dim_merchant,
        "DimVoucherType": dim_voucher,
        "DimTicketType": dim_ticket_type,
        "DimPriority": dim_priority,
        "FactMerchantSales": fact_sales,
        "FactVoucherRedemptions": fact_red,
        "FactSupportTickets": fact_tickets,
    }


# -------------------------------------------------------------- dq gate ----
def run_dq_checks(gold: dict[str, pd.DataFrame]) -> list[dict]:
    """Referential integrity + grain + null checks. Mirrors fabric/sql/03_dq_checks.sql."""
    checks: list[dict] = []

    def check(name: str, passed: bool, detail: str = "") -> None:
        checks.append({"check": name, "status": "PASS" if passed else "FAIL",
                       "detail": detail})

    dates = set(gold["DimDate"]["DateKey"].dropna())
    merchants = set(gold["DimMerchant"]["MerchantKey"])
    vtypes = set(gold["DimVoucherType"]["VoucherTypeKey"])

    fs, fr, ft = (gold["FactMerchantSales"], gold["FactVoucherRedemptions"],
                  gold["FactSupportTickets"])

    check("FactMerchantSales.DateKey -> DimDate",
          set(fs["DateKey"].dropna()) <= dates)
    check("FactMerchantSales.MerchantKey -> DimMerchant",
          set(fs["MerchantKey"]) <= merchants)
    check("FactMerchantSales.VoucherTypeKey -> DimVoucherType",
          set(fs["VoucherTypeKey"]) <= vtypes)
    check("FactVoucherRedemptions.SoldDateKey -> DimDate",
          set(fr["SoldDateKey"].dropna()) <= dates)
    check("FactVoucherRedemptions.RedeemedDateKey -> DimDate",
          set(fr["RedeemedDateKey"].dropna()) <= dates)
    check("FactVoucherRedemptions.MerchantKey -> DimMerchant",
          set(fr["MerchantKey"]) <= merchants)
    check("FactSupportTickets.DateKey -> DimDate",
          set(ft["DateKey"].dropna()) <= dates)
    check("FactSupportTickets.MerchantKey -> DimMerchant",
          set(ft["MerchantKey"]) <= merchants)
    check("FactSupportTickets.PriorityKey -> DimPriority",
          set(ft["PriorityKey"]) <= set(gold["DimPriority"]["PriorityKey"]))
    check("FactSupportTickets.TicketTypeKey -> DimTicketType",
          set(ft["TicketTypeKey"]) <= set(gold["DimTicketType"]["TicketTypeKey"]))

    check("FactMerchantSales grain unique (Date, Merchant, VoucherType)",
          not fs.duplicated(["DateKey", "MerchantKey", "VoucherTypeKey"]).any())
    check("FactVoucherRedemptions grain unique (VoucherID)",
          not fr["VoucherID"].duplicated().any())
    check("FactSupportTickets grain unique (TicketID)",
          not ft["TicketID"].duplicated().any())
    check("DimMerchant grain unique (MerchantKey)",
          not gold["DimMerchant"]["MerchantKey"].duplicated().any())

    check("No negative SalesValue", (fs["SalesValue"] >= 0).all())
    check("No negative Transactions", (fs["Transactions"] >= 0).all())
    check("No negative DaysToRedeem",
          (fr["DaysToRedeem"].dropna() >= 0).all())
    check("Redeemed vouchers all carry a RedeemedDate",
          fr.loc[fr["IsRedeemed"] == 1, "RedeemedDateKey"].notna().all())
    check("Unredeemed vouchers carry no RedeemedDate",
          fr.loc[fr["IsRedeemed"] == 0, "RedeemedDateKey"].isna().all())
    check("DimDate is contiguous",
          len(gold["DimDate"]) ==
          (gold["DimDate"]["Date"].max() - gold["DimDate"]["Date"].min()).days + 1)

    return checks


# ----------------------------------------------------------------- write ----
def write_gold(gold: dict[str, pd.DataFrame]) -> dict:
    manifest = {"tables": {}}
    for name, frame in gold.items():
        frame.to_csv(GOLD / f"{name}.csv", index=False)
        try:
            frame.to_parquet(GOLD / f"{name}.parquet", index=False)
            fmt = "csv+parquet"
        except Exception:  # pyarrow not installed; CSV still lands
            fmt = "csv"
        manifest["tables"][name] = {
            "rows": int(len(frame)),
            "columns": list(frame.columns),
            "written": fmt,
        }
    return manifest


def main() -> None:
    bronze = read_bronze()
    silver = conform(bronze)
    gold = build_gold(silver)

    checks = run_dq_checks(gold)
    failed = [c for c in checks if c["status"] == "FAIL"]

    manifest = write_gold(gold)
    manifest["dq_checks"] = checks
    manifest["dq_failed"] = len(failed)
    (GOLD / "_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf8")

    for name, meta in manifest["tables"].items():
        print(f"{name:<24} {meta['rows']:>8,} rows  ({meta['written']})")
    print()
    for c in checks:
        marker = "OK  " if c["status"] == "PASS" else "FAIL"
        print(f"  [{marker}] {c['check']}")
    print()
    if failed:
        raise SystemExit(f"{len(failed)} data quality check(s) failed - gold not certified")
    print(f"All {len(checks)} data quality checks passed. Gold layer certified.")


if __name__ == "__main__":
    main()
