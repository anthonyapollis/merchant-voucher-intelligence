"""
39_unify_health_score.py — one health score, one banding, across the whole model.

THE DEFECT
Two gold tables carried a merchant health score and they disagreed on all 25 merchants:

    DimMerchantSegment.HealthScore / RiskTier   written by build/build_ml.py
    MerchantValueRisk.health_score / health_band written by scripts/03_analytics.py

Same bin edges [-1, 35, 55, 75, 101], but the LABELS are offset by one position:

    build/     Critical | At risk | Watch   | Healthy
    scripts/   Critical | Watch   | Healthy | Star

So the 55-75 band reads "Watch" in one table and "Healthy" in the other. Intelligence & ML
reported 15 merchants at risk while Merchant Value & Risk showed the same merchants as
healthy. Both statements came from the same model, which makes every other number in the pack
harder to trust.

WHICH ONE WINS, AND WHY
scripts/03_analytics.py is authoritative on three grounds:

  1. It uses pct_rank(), which reproduces SQL PERCENT_RANK() — (rank-1)/(n-1). The other
     uses pandas rank(pct=True), which is rank/n, a DIFFERENT statistic. That discrepancy was
     already found and fixed once in this project; the stale table predates the fix.
  2. It does not depend on TargetAttainmentPct. The supplied targets are miscalibrated —
     attainment runs 381% to 916% — so the 20% weight the other score gives it is 20% of the
     score resting on a broken denominator.
  3. It is reconciled against the dbt implementation. The other is not.

The K-Means outputs on DimMerchantSegment (Segment, SegmentID, SegmentProfile, PCA1, PCA2)
are genuine and are KEPT — only the health score and its band are replaced.
"""
import json
import shutil
import zipfile
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
GOLD = ROOT / "data" / "gold"
PBIT = ROOT / "powerbi" / "MerchantVoucherIntelligence.pbit"

seg = pd.read_csv(GOLD / "DimMerchantSegment.csv")
vr = pd.read_csv(GOLD / "MerchantValueRisk.csv")

auth = vr[["merchant_name", "health_score", "health_band"]].rename(
    columns={"merchant_name": "Merchant"})

before = seg[["Merchant", "HealthScore", "RiskTier"]].copy()
seg = seg.drop(columns=["HealthScore", "RiskTier"]).merge(auth, on="Merchant", how="left")

missing = seg.health_score.isna().sum()
if missing:
    raise SystemExit(f"{missing} merchant(s) have no authoritative score — refusing to write "
                     f"a table with holes in it")

seg = seg.rename(columns={"health_score": "HealthScore", "health_band": "RiskTier"})

# Put the columns back where they were so nothing downstream depends on column order.
cols = list(before.columns)
order = [c for c in pd.read_csv(GOLD / "DimMerchantSegment.csv", nrows=0).columns]
seg = seg[[c for c in order if c in seg.columns]]
seg.to_csv(GOLD / "DimMerchantSegment.csv", index=False, encoding="utf-8")

comp = before.merge(seg[["Merchant", "HealthScore", "RiskTier"]], on="Merchant",
                    suffixes=("_old", "_new"))
changed = int((comp.RiskTier_old != comp.RiskTier_new).sum())
maxdelta = float((comp.HealthScore_new - comp.HealthScore_old).abs().max())

print(f"  DimMerchantSegment: {len(seg)} rows re-pointed at the authoritative score")
print(f"    band changed for {changed} of {len(comp)} merchants; "
      f"largest score move {maxdelta:.1f} points")
print(f"    band distribution now: "
      + ", ".join(f"{k} {v}" for k, v in seg.RiskTier.value_counts().items()))

# ---------------------------------------------------------------- measures
z = zipfile.ZipFile(PBIT)
members = {n: z.read(n) for n in z.namelist()}
names = z.namelist()
z.close()

model = json.loads(members["DataModelSchema"].decode("utf-16-le"))

# "At risk" now means Critical or Watch under the single banding. Star and Healthy are the
# healthy half, which the previous scheme had no way to express at all.
NEW = {
    "Merchants At Risk":
        'COALESCE ( CALCULATE ( COUNTROWS ( DimMerchantSegment ), '
        'DimMerchantSegment[RiskTier] IN { "Critical", "Watch" } ), 0 )',
    "Merchants Healthy":
        'COALESCE ( CALCULATE ( COUNTROWS ( DimMerchantSegment ), '
        'DimMerchantSegment[RiskTier] IN { "Healthy", "Star" } ), 0 )',
}
patched = []
for t in model["model"]["tables"]:
    ms = t.get("measures")
    if ms is None:
        continue
    have = {x["name"] for x in ms}
    for nm, expr in NEW.items():
        if nm in have:
            for x in ms:
                if x["name"] == nm:
                    x["expression"] = expr
                    patched.append(nm)
        elif t["name"] == "_Measures":
            ms.append({"name": nm, "expression": expr, "formatString": "0"})
            patched.append(nm + " (new)")

members["DataModelSchema"] = json.dumps(model, ensure_ascii=False).encode("utf-16-le")

tmp = PBIT.with_suffix(".tmp")
with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zo:
    for n in names:
        zo.writestr(n, members[n])
tmp.replace(PBIT)

zc = zipfile.ZipFile(PBIT)
for part in ("Report/Layout", "DataModelSchema"):
    if zc.read(part)[:2] in (b"\xff\xfe", b"\xfe\xff", b"\xef\xbb"):
        raise SystemExit(f"ENCODING ERROR: {part} has a BOM — template will not open")
zc.close()
shutil.copy2(PBIT, ROOT / "MerchantVoucherIntelligence_PowerBI" /
             "MerchantVoucherIntelligence.pbit")
print(f"  measures: {', '.join(patched)}")

# ---------------------------------------------------------------- standing control
# The reconciliation compares the Python pipeline against dbt for the SAME table. It had no
# check that two DIFFERENT gold tables agree about the same business concept, which is
# exactly the gap this defect fell through. Recorded as a control so it cannot recur quietly.
chk = seg[["Merchant", "HealthScore", "RiskTier"]].merge(
    vr[["merchant_name", "health_score", "health_band"]],
    left_on="Merchant", right_on="merchant_name")
score_mismatch = int((chk.HealthScore.round(1) != chk.health_score.round(1)).sum())
band_mismatch = int((chk.RiskTier != chk.health_band).sum())

rc_path = GOLD / "RecControls.csv"
rc = pd.read_csv(rc_path)

# Columns are written explicitly. An earlier version guessed the name column as columns[0],
# which is control_order — an INTEGER column — so the control name was written into a numeric
# field and every other value came out NaN. Power Query types expected_value/actual_value as
# Decimal Number, so that row failed to load and took the whole refresh down with it.
row = {
    "control_order": 40,
    "control_family": "Cross-table control",
    "control_name": "Health score agrees across DimMerchantSegment and MerchantValueRisk",
    "expected_value": 0.0,
    "actual_value": float(score_mismatch + band_mismatch),
    "variance": float(score_mismatch + band_mismatch),
    "variance_pct": 0.0,
    "control_status": "PASS" if (score_mismatch == 0 and band_mismatch == 0) else "FAIL",
    "txn_per_voucher": float(rc["txn_per_voucher"].dropna().iloc[0])
                       if rc["txn_per_voucher"].notna().any() else 0.0,
    "rationale": (f"Two gold tables carried a merchant health score and disagreed on all 25 "
                  f"merchants: same bin edges, but band labels offset by one position. "
                  f"MerchantValueRisk is authoritative — it reproduces SQL PERCENT_RANK, does "
                  f"not depend on the miscalibrated target attainment, and is reconciled "
                  f"against dbt. Now {score_mismatch} score and {band_mismatch} band "
                  f"mismatches across {len(chk)} merchants. The other controls compare one "
                  f"table against its own dbt build; this one compares two DIFFERENT tables "
                  f"about the same concept, which is the gap the defect fell through."),
}
missing_cols = set(row) - set(rc.columns)
if missing_cols:
    raise SystemExit(f"RecControls schema changed — unknown columns {missing_cols}")

rc = rc[rc["control_name"] != row["control_name"]]
rc = pd.concat([rc, pd.DataFrame([row])[rc.columns]], ignore_index=True)

# Numeric columns must contain numbers, not blanks — a blank in a Decimal column is a load
# error in Power Query, not a null.
for c in ("control_order", "expected_value", "actual_value", "variance", "variance_pct",
          "txn_per_voucher"):
    bad = rc[c].isna().sum()
    if bad:
        raise SystemExit(f"{bad} blank value(s) in numeric column {c} — Power Query will "
                         f"fail to load RecControls")
rc.to_csv(rc_path, index=False, encoding="utf-8")

print(f"  control added to RecControls: {score_mismatch} score / {band_mismatch} band "
      f"mismatches (0 / 0 expected)")
if score_mismatch or band_mismatch:
    raise SystemExit("tables still disagree after unification")
print("  the two tables now agree on every merchant")
