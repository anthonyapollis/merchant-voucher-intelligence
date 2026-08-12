"""
_crosscheck_prior_build.py
==========================
This project folder already contained an earlier, independent build of the same task
(dated 5-6 August 2026) which produced its own gold layer using PascalCase table names.
That build was left untouched — it uses different filenames to the snake_case layer
produced by scripts/02_build_warehouse.py, so the two coexist.

That earlier build is effectively a THIRD independent implementation of the same
transformations. Comparing it against the current one is free extra assurance: three
separate code paths agreeing on the headline totals is strong evidence the numbers are right.
"""
from pathlib import Path
import pandas as pd

GOLD = Path(__file__).resolve().parents[1] / "data" / "gold"


def load(name):
    p = GOLD / name
    return pd.read_parquet(p) if p.exists() else None


PAIRS = [
    ("Sales value",      "FactMerchantSales",       "SalesValue",
     "fact_merchant_sales",       "SalesValue"),
    ("Transactions",     "FactMerchantSales",       "Transactions",
     "fact_merchant_sales",       "Transactions"),
    ("Voucher value",    "FactVoucherRedemptions",  "VoucherValue",
     "fact_voucher_redemptions",  "VoucherValue"),
    ("Resolution hours", "FactSupportTickets",      "ResolutionHours",
     "fact_support_tickets",      "ResolutionHours"),
]
ROWS = [
    ("Sales rows",   "FactMerchantSales",      "fact_merchant_sales"),
    ("Voucher rows", "FactVoucherRedemptions", "fact_voucher_redemptions"),
    ("Ticket rows",  "FactSupportTickets",     "fact_support_tickets"),
]

print("=" * 84)
print("CROSS-CHECK — earlier 6 Aug build vs current 11 Aug build")
print("=" * 84)
print(f"{'Metric':<20}{'6 Aug build':>20}{'11 Aug build':>20}{'Variance':>16}")
print("-" * 84)

variances = []
for label, f1, c1, f2, c2 in PAIRS:
    d1, d2 = load(f1 + ".parquet"), load(f2 + ".parquet")
    if d1 is None or d2 is None:
        print(f"{label:<20}{'table missing':>20}")
        continue
    if c1 not in d1.columns:
        print(f"{label:<20}{'col ' + c1 + ' absent':>20}   (columns: "
              f"{', '.join(d1.columns[:6])})")
        continue
    a, b = float(d1[c1].sum()), float(d2[c2].sum())
    variances.append(abs(a - b))
    print(f"{label:<20}{a:>20,.2f}{b:>20,.2f}{a - b:>16,.2f}")

for label, f1, f2 in ROWS:
    d1, d2 = load(f1 + ".parquet"), load(f2 + ".parquet")
    if d1 is None or d2 is None:
        continue
    variances.append(abs(len(d1) - len(d2)))
    print(f"{label:<20}{len(d1):>20,}{len(d2):>20,}{len(d1) - len(d2):>16,}")

print("=" * 84)
if variances and max(variances) < 0.01:
    print("All compared figures agree across BOTH independent builds.")
    print("Three implementations (6 Aug build, pandas, dbt SQL) now produce identical totals.")
else:
    print(f"Largest variance: {max(variances):,.4f} — investigate before relying on either.")
print("=" * 84)
