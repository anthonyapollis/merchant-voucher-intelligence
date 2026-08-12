"""
01_profile.py — Source data profiling for the Merchant Sales & Voucher Intelligence solution.

Purpose: establish grain, keys, cardinality, null/quality issues and date coverage for each
source file BEFORE any modelling decisions are made. Output feeds the Data Quality section of
the submission report and the dbt test suite.
"""
from pathlib import Path
import pandas as pd
import numpy as np
import json

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
OUT = ROOT / "docs"
OUT.mkdir(parents=True, exist_ok=True)

pd.set_option("display.width", 200)
pd.set_option("display.max_columns", 50)

FILES = {
    "MerchantReference": "MerchantReference.csv",
    "MerchantSales": "MerchantSales.csv",
    "SupportTickets": "SupportTickets.csv",
    "VoucherRedemptions": "VoucherRedemptions.csv",
}

report = {}
frames = {}

print("=" * 100)
print("SOURCE PROFILE")
print("=" * 100)

for name, fn in FILES.items():
    df = pd.read_csv(RAW / fn)
    frames[name] = df
    prof = {
        "rows": int(len(df)),
        "columns": list(df.columns),
        "dtypes": {c: str(t) for c, t in df.dtypes.items()},
        "nulls": {c: int(df[c].isna().sum()) for c in df.columns},
        "distinct": {c: int(df[c].nunique(dropna=True)) for c in df.columns},
        "duplicate_rows": int(df.duplicated().sum()),
    }
    report[name] = prof
    print(f"\n### {name}  ({fn})  rows={len(df):,}")
    print(df.dtypes.to_string())
    print("nulls:", {k: v for k, v in prof["nulls"].items() if v})
    print("distinct:", prof["distinct"])
    print("dup rows:", prof["duplicate_rows"])

# ---------------------------------------------------------------- date coverage
print("\n" + "=" * 100)
print("DATE COVERAGE")
print("=" * 100)
for name, col in [("MerchantSales", "Date"), ("SupportTickets", "Date"),
                  ("VoucherRedemptions", "SoldDate"), ("VoucherRedemptions", "RedeemedDate")]:
    s = pd.to_datetime(frames[name][col], errors="coerce")
    print(f"{name}.{col:14s} min={s.min()}  max={s.max()}  nulls={s.isna().sum():,}")
    report.setdefault("date_coverage", {})[f"{name}.{col}"] = {
        "min": str(s.min()), "max": str(s.max()), "nulls": int(s.isna().sum())
    }

# ---------------------------------------------------------------- grain checks
print("\n" + "=" * 100)
print("GRAIN / KEY CHECKS")
print("=" * 100)
ms = frames["MerchantSales"]
g = ms.groupby(["Date", "MerchantID", "VoucherType"]).size()
print(f"MerchantSales grain Date+MerchantID+VoucherType unique: {(g == 1).all()}  max_dupes={g.max()}")
report["grain_MerchantSales"] = {"unique": bool((g == 1).all()), "max": int(g.max())}

vr = frames["VoucherRedemptions"]
print(f"VoucherRedemptions VoucherID unique: {vr.VoucherID.is_unique}")
st = frames["SupportTickets"]
print(f"SupportTickets TicketID unique: {st.TicketID.is_unique}")
dm = frames["MerchantReference"]
print(f"MerchantReference MerchantID unique: {dm.MerchantID.is_unique}  merchants={len(dm)}")

# ---------------------------------------------------------------- referential integrity
print("\n" + "=" * 100)
print("REFERENTIAL INTEGRITY vs DimMerchant")
print("=" * 100)
dim_ids = set(dm.MerchantID)
for name in ["MerchantSales", "SupportTickets", "VoucherRedemptions"]:
    orphans = set(frames[name].MerchantID) - dim_ids
    print(f"{name:20s} orphan MerchantIDs: {len(orphans)} {sorted(orphans)[:5]}")
    report[f"orphans_{name}"] = sorted(orphans)

# ---------------------------------------------------------------- conformance: does the dim agree with the facts?
print("\n" + "=" * 100)
print("ATTRIBUTE CONFORMANCE (fact-embedded attributes vs DimMerchant)")
print("=" * 100)
chk = (ms[["MerchantID", "Merchant", "Region", "Channel"]].drop_duplicates()
       .merge(dm[["MerchantID", "Merchant", "Region", "Channel"]], on="MerchantID",
              suffixes=("_fact", "_dim")))
for c in ["Merchant", "Region", "Channel"]:
    mism = chk[chk[f"{c}_fact"] != chk[f"{c}_dim"]]
    print(f"  {c:10s} mismatches: {len(mism)}")
    if len(mism):
        print(mism[["MerchantID", f"{c}_fact", f"{c}_dim"]].head(20).to_string(index=False))
    report[f"conformance_{c}"] = len(mism)

st_chk = (st[["MerchantID", "Merchant", "Region"]].drop_duplicates()
          .merge(dm[["MerchantID", "Merchant", "Region"]], on="MerchantID", suffixes=("_fact", "_dim")))
mism = st_chk[st_chk["Region_fact"] != st_chk["Region_dim"]]
print(f"  SupportTickets.Region mismatches vs dim: {len(mism)}")
report["conformance_Region_tickets"] = len(mism)

# ---------------------------------------------------------------- categorical inventory
print("\n" + "=" * 100)
print("CATEGORICAL VALUES")
print("=" * 100)
for name, cols in [("MerchantSales", ["Region", "Channel", "VoucherType"]),
                   ("SupportTickets", ["TicketType", "Priority", "Status"]),
                   ("VoucherRedemptions", ["VoucherType", "Redeemed"]),
                   ("MerchantReference", ["Region", "Channel", "ActiveStatus", "AccountManager"])]:
    for c in cols:
        vals = frames[name][c].value_counts(dropna=False)
        print(f"{name}.{c}: {dict(vals)}")
        report.setdefault("categoricals", {})[f"{name}.{c}"] = {str(k): int(v) for k, v in vals.items()}

# ---------------------------------------------------------------- redemption logic checks
print("\n" + "=" * 100)
print("REDEMPTION LOGIC")
print("=" * 100)
vr["SoldDate"] = pd.to_datetime(vr["SoldDate"])
vr["RedeemedDate"] = pd.to_datetime(vr["RedeemedDate"], errors="coerce")
vr["is_redeemed"] = vr["Redeemed"].str.strip().str.lower().eq("yes")
print("Redeemed=Yes but RedeemedDate null :", int((vr.is_redeemed & vr.RedeemedDate.isna()).sum()))
print("Redeemed=No  but RedeemedDate set  :", int((~vr.is_redeemed & vr.RedeemedDate.notna()).sum()))
vr["days_to_redeem"] = (vr.RedeemedDate - vr.SoldDate).dt.days
print("Negative days_to_redeem            :", int((vr.days_to_redeem < 0).sum()))
print("days_to_redeem describe:\n", vr.days_to_redeem.describe().to_string())
print("Overall redemption rate            : {:.2%}".format(vr.is_redeemed.mean()))
report["redemption"] = {
    "yes_no_date": int((vr.is_redeemed & vr.RedeemedDate.isna()).sum()),
    "no_with_date": int((~vr.is_redeemed & vr.RedeemedDate.notna()).sum()),
    "negative_lag": int((vr.days_to_redeem < 0).sum()),
    "overall_rate": float(vr.is_redeemed.mean()),
    "mean_days": float(vr.days_to_redeem.mean()),
}

# ---------------------------------------------------------------- ticket / SLA checks
print("\n" + "=" * 100)
print("TICKETS / SLA")
print("=" * 100)
print("ResolutionHours describe:\n", st.ResolutionHours.describe().to_string())
print("SLAHours values:", dict(st.SLAHours.value_counts()))
st["breach"] = st.ResolutionHours > st.SLAHours
print("SLA breach rate: {:.2%}".format(st.breach.mean()))
print("Breach rate by Priority:\n", st.groupby("Priority").breach.mean().to_string())
report["tickets"] = {"breach_rate": float(st.breach.mean()),
                     "mean_res_hours": float(st.ResolutionHours.mean())}

# ---------------------------------------------------------------- the four embedded patterns
print("\n" + "=" * 100)
print("EMBEDDED PATTERN DETECTION (README claims)")
print("=" * 100)
ms["Date"] = pd.to_datetime(ms["Date"])
ms["Month"] = ms["Date"].dt.to_period("M").astype(str)
mm = ms.pivot_table(index="Merchant", columns="Month", values="SalesValue", aggfunc="sum").fillna(0)
print("\n-- Monthly sales by merchant (R) --")
print(mm.round(0).to_string())

# July decline
if "2026-07" in mm.columns and "2026-06" in mm.columns:
    d = ((mm["2026-07"] - mm["2026-06"]) / mm["2026-06"]).sort_values()
    print("\nJuly vs June % change (worst 5):\n", (d.head(5) * 100).round(1).to_string())
    report["july_decline_merchant"] = d.index[0]

# May growth
if "2026-05" in mm.columns:
    base = mm[[c for c in mm.columns if c < "2026-05"]].mean(axis=1)
    post = mm[[c for c in mm.columns if c >= "2026-05"]].mean(axis=1)
    g2 = ((post - base) / base).sort_values(ascending=False)
    print("\nPost-May vs Pre-May uplift (top 5):\n", (g2.head(5) * 100).round(1).to_string())
    report["may_growth_merchant"] = g2.index[0]

# June ticket spike
st["Date"] = pd.to_datetime(st["Date"])
st["Month"] = st["Date"].dt.to_period("M").astype(str)
tm = st.pivot_table(index="Merchant", columns="Month", values="TicketID", aggfunc="count").fillna(0)
print("\n-- Monthly tickets by merchant --")
print(tm.astype(int).to_string())
pre = tm[[c for c in tm.columns if c < "2026-06"]].mean(axis=1)
pos = tm[[c for c in tm.columns if c >= "2026-06"]].mean(axis=1)
sp = ((pos - pre) / pre.replace(0, np.nan)).sort_values(ascending=False)
print("\nPost-June ticket uplift (top 5):\n", (sp.head(5) * 100).round(1).to_string())
report["june_ticket_spike_merchant"] = sp.index[0]

# April delayed redemptions by region+vouchertype
vr2 = vr.merge(dm[["MerchantID", "Region"]], on="MerchantID", how="left")
vr2["SoldMonth"] = vr2["SoldDate"].dt.to_period("M").astype(str)
lag = vr2.pivot_table(index=["Region", "VoucherType"], columns="SoldMonth",
                      values="days_to_redeem", aggfunc="mean")
if "2026-04" in lag.columns:
    others = [c for c in lag.columns if c != "2026-04"]
    delta = (lag["2026-04"] - lag[others].mean(axis=1)).sort_values(ascending=False)
    print("\nApril avg-days-to-redeem vs other months (top 5 region+type):\n",
          delta.head(5).round(2).to_string())
    report["april_delay_combo"] = list(delta.index[0])

with open(OUT / "profile_report.json", "w") as f:
    json.dump(report, f, indent=2, default=str)
print("\n\nWrote", OUT / "profile_report.json")
