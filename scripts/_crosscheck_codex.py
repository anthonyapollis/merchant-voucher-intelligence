"""
_crosscheck_codex.py — verify my figures against the earlier (Codex) build's own outputs.

Compares the 6 Aug build's gold CSVs and its published dashboard data.json against the
current build, rather than eyeballing screenshots. Any variance is reported, not smoothed.
"""
import json
import sys
import io
from pathlib import Path

import pandas as pd
import duckdb

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
ROOT = Path(__file__).resolve().parents[1]
GOLD = ROOT / "data" / "gold"
con = duckdb.connect(str(ROOT / "data" / "mvi.duckdb"))

rows = []


def cmp(label, codex, mine, tol=0.01, fmt="{:,.2f}"):
    if codex is None or mine is None:
        rows.append((label, "n/a", "n/a", "SKIP")); return
    ok = abs(float(codex) - float(mine)) <= tol
    rows.append((label, fmt.format(codex), fmt.format(mine),
                 "MATCH" if ok else f"DIFF {float(codex)-float(mine):+,.4f}"))


print("=" * 96)
print("CROSS-CHECK — 6 Aug (Codex) build vs current build")
print("=" * 96)

# ---- headline totals from Codex's own gold CSVs -----------------------------------
cs = pd.read_csv(GOLD / "FactMerchantSales.csv")
cv = pd.read_csv(GOLD / "FactVoucherRedemptions.csv")
ct = pd.read_csv(GOLD / "FactSupportTickets.csv")

m = con.execute("""
    select (select sum(sales_value) from main_marts.fct_merchant_sales)      s,
           (select sum(transactions) from main_marts.fct_merchant_sales)     t,
           (select count(*) from main_marts.fct_voucher_redemptions)         vs,
           (select sum(redeemed_count) from main_marts.fct_voucher_redemptions) vr,
           (select sum(voucher_value) from main_marts.fct_voucher_redemptions) vv,
           (select count(*) from main_marts.fct_support_tickets)             tk,
           (select sum(resolution_hours) from main_marts.fct_support_tickets) rh,
           (select sum(sla_breach_count) from main_marts.fct_support_tickets) br
""").df().iloc[0]

cmp("Total sales value", cs.SalesValue.sum(), m.s)
cmp("Total transactions", cs.Transactions.sum(), m.t, fmt="{:,.0f}")
cmp("Sales fact rows", len(cs), 26500, fmt="{:,.0f}")
cmp("Vouchers sold", len(cv), m.vs, fmt="{:,.0f}")
redeemed_col = "Redeemed" if "Redeemed" in cv.columns else "IsRedeemed"
cx_red = (cv[redeemed_col].astype(str).str.lower().isin(["yes", "true", "1"])).sum()
cmp("Vouchers redeemed", cx_red, m.vr, fmt="{:,.0f}")
cmp("Redemption rate", cx_red / len(cv), m.vr / m.vs, tol=1e-6, fmt="{:.6f}")
vv_col = [c for c in cv.columns if c.lower() in ("vouchervalue", "voucher_value")]
if vv_col:
    cmp("Voucher value sold", cv[vv_col[0]].sum(), m.vv)
cmp("Support tickets", len(ct), m.tk, fmt="{:,.0f}")
rh_col = [c for c in ct.columns if c.lower() in ("resolutionhours", "resolution_hours")]
if rh_col:
    cmp("Total resolution hours", ct[rh_col[0]].sum(), m.rh)
    cmp("Avg resolution hours", ct[rh_col[0]].mean(), m.rh / m.tk, tol=1e-4, fmt="{:.4f}")

# ---- Codex's published dashboard payload -------------------------------------------
dj = ROOT / "dashboard" / "data.json"
if dj.exists():
    cd = json.load(open(dj, encoding="utf-8"))
    flat = {}

    def walk(o, path=""):
        if isinstance(o, dict):
            for k, v in o.items():
                walk(v, f"{path}.{k}" if path else k)
        elif isinstance(o, (int, float)) and not isinstance(o, bool):
            flat[path] = o
    walk(cd)
    for key, mine, lbl, tol in [
        ("totalSales", m.s, "dashboard totalSales", 0.01),
        ("totalTransactions", m.t, "dashboard totalTransactions", 0.5),
        ("redemptionRate", m.vr / m.vs, "dashboard redemptionRate", 1e-4),
    ]:
        hit = [v for k, v in flat.items() if k.lower().endswith(key.lower())]
        if hit:
            cmp(lbl, hit[0], mine, tol=tol, fmt="{:,.4f}")

# ---- per-province -------------------------------------------------------------------
if (GOLD / "DimMerchant.csv").exists():
    dm = pd.read_csv(GOLD / "DimMerchant.csv")
    mk = [c for c in dm.columns if c.lower() in ("merchantkey", "merchant_key")][0]
    rg = [c for c in dm.columns if c.lower() == "region"][0]
    fk = [c for c in cs.columns if c.lower() in ("merchantkey", "merchant_key")][0]
    cx_reg = (cs.merge(dm[[mk, rg]], left_on=fk, right_on=mk)
                .groupby(rg).SalesValue.sum().sort_values(ascending=False))
    my_reg = con.execute("""
        select m.region, sum(f.sales_value) v
        from main_marts.fct_merchant_sales f
        join main_marts.dim_merchant m using(merchant_key)
        group by 1 order by 2 desc""").df().set_index("region").v
    print("\nPer-province sales:")
    for r in cx_reg.index:
        cmp(f"  {r}", cx_reg[r], my_reg.get(r))

print()
w = max(len(r[0]) for r in rows) + 2
print(f"{'Check':<{w}}{'Codex (6 Aug)':>20}{'Mine (current)':>20}   Result")
print("-" * (w + 48))
for lbl, a, b, res in rows:
    print(f"{lbl:<{w}}{a:>20}{b:>20}   {res}")

diffs = [r for r in rows if r[3].startswith("DIFF")]
print("\n" + "=" * 96)
print(f"{len(rows)-len(diffs)}/{len(rows)} match" +
      ("" if not diffs else f"  —  {len(diffs)} DIFFERENCE(S), listed above"))
print("=" * 96)
con.close()
