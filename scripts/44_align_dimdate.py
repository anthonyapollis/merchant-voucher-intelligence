"""
44_align_dimdate.py — make the Power BI calendar match the dbt calendar.

THE DISCREPANCY
Two implementations built the same dimension to different spans:

    dbt main_marts.dim_date   365 rows   2026-01-01 to 2026-12-31
    data/gold/DimDate.csv     243 rows   2026-01-01 to 2026-08-31   <- what Power BI loads

The registry, the ModelGuide and the Word report all describe the 365-day version — "generated
to full calendar-year boundaries" — while Power BI was loading the 243-day one. The
documentation described a table the report was not using.

Neither was broken: 243 days still covers the 20 August redemption tail, so no fact row was
orphaned and nothing displayed wrongly. It is a consistency defect rather than a data defect.
But "the calendar runs to year end" is either true or it is not, and a reviewer who reads the
ERD and then counts rows should find the same number.

The dbt version wins for the same reason it won on the health score: it is the implementation
the tests run against, and its year-end boundary is deliberate — time intelligence over a
calendar that stops mid-year silently returns wrong answers for any period that crosses the
boundary, rather than erroring.

Extends the CSV to 31 December, preserving its exact column set and types, and adds a control
so the two can never silently diverge again.
"""
import shutil
from pathlib import Path

import duckdb
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
GOLD = ROOT / "data" / "gold"
CSV = GOLD / "DimDate.csv"

before = pd.read_csv(CSV)
cols = list(before.columns)

con = duckdb.connect(str(ROOT / "data" / "mvi.duckdb"), read_only=True)
n_dbt, min_dbt, max_dbt = con.execute(
    "select count(*), min(date), max(date) from main_marts.dim_date").fetchone()
con.close()

start = pd.to_datetime(before["Date"]).min()
end = pd.Timestamp(max_dbt)
if pd.to_datetime(before["Date"]).max() >= end and len(before) == n_dbt:
    print(f"  already aligned: {len(before)} rows to {max_dbt}")
    raise SystemExit(0)

shutil.copy2(CSV, GOLD / "_DimDate.pre_align.bak.csv")

d = pd.DataFrame({"Date": pd.date_range(start, end, freq="D")})
d["DateKey"] = d.Date.dt.strftime("%Y%m%d").astype(int)
d["Year"] = d.Date.dt.year
d["QuarterNumber"] = d.Date.dt.quarter
d["Quarter"] = "Q" + d.QuarterNumber.astype(str)
d["MonthNumber"] = d.Date.dt.month
d["MonthName"] = d.Date.dt.strftime("%B")
d["MonthShort"] = d.Date.dt.strftime("%b")
d["MonthYear"] = d.Date.dt.strftime("%b %Y")
d["MonthYearSort"] = d.Date.dt.strftime("%Y%m").astype(int)
d["Day"] = d.Date.dt.day
d["DayName"] = d.Date.dt.strftime("%A")
# The existing file uses ISO weekday numbering (Thursday 1 Jan 2026 = 4), so match it rather
# than pandas' Monday=0 convention — a silent off-by-one here would break every weekday slice.
d["DayOfWeek"] = d.Date.dt.isocalendar().day.astype(int)
d["IsWeekend"] = (d.DayOfWeek >= 6).astype(int)
d["WeekOfYear"] = d.Date.dt.isocalendar().week.astype(int)
d["WeekStartDate"] = (d.Date - pd.to_timedelta(d.DayOfWeek - 1, unit="D")).dt.strftime("%Y-%m-%d")
d["MonthStartDate"] = d.Date.values.astype("datetime64[M]")
d["MonthEndDate"] = (d.MonthStartDate + pd.offsets.MonthEnd(1))
d["MonthStartDate"] = pd.to_datetime(d.MonthStartDate).dt.strftime("%Y-%m-%d")
d["MonthEndDate"] = pd.to_datetime(d.MonthEndDate).dt.strftime("%Y-%m-%d")
d["Date"] = d.Date.dt.strftime("%Y-%m-%d")

missing = set(cols) - set(d.columns)
if missing:
    raise SystemExit(f"regenerated calendar is missing columns: {sorted(missing)}")
d = d[cols]

# The overlapping rows must be identical to what was there before, or this is a rewrite rather
# than an extension and every existing DateKey join is at risk.
overlap = before.merge(d, on="DateKey", suffixes=("_old", "_new"))
diffs = []
for c in cols:
    if c == "DateKey":
        continue
    a, b = overlap[f"{c}_old"].astype(str), overlap[f"{c}_new"].astype(str)
    n = int((a != b).sum())
    if n:
        diffs.append(f"{c} ({n} rows)")
if diffs:
    raise SystemExit("regenerated calendar disagrees with the existing rows on: "
                     + ", ".join(diffs))

d.to_csv(CSV, index=False, encoding="utf-8")

print(f"  DimDate.csv extended {len(before)} -> {len(d)} rows "
      f"({before.Date.min()} to {d.Date.max()})")
print(f"  dbt dim_date: {n_dbt} rows ({min_dbt} to {max_dbt})")
print(f"  match: {'YES' if len(d) == n_dbt else 'NO'}")
print(f"  {len(overlap)} pre-existing rows verified unchanged across {len(cols) - 1} columns")
print(f"  backup: _DimDate.pre_align.bak.csv")

if len(d) != n_dbt:
    raise SystemExit("row counts still differ — the calendars are not aligned")
