"""
43_pbit_role_playing_date.py — wire the redeemed-date role-playing relationship.

THE GAP
The registry, the ModelGuide and the Word report all describe the voucher fact as carrying
two date foreign keys — sold_date_key active, redeemed_date_key inactive, activated with
USERELATIONSHIP. The column is present, dbt enforces a relationships test on it, and the
calendar spans far enough for it to resolve. But the SEMANTIC MODEL never had the second
relationship: three date relationships existed, all active, and no measure used
USERELATIONSHIP. The documented design was real; one wiring step was missing.

The practical consequence is not cosmetic. Every redemption measure filtered through
SoldDateKey, so "redemption rate by month" actually meant "redemption rate by month OF SALE".
A voucher sold in July and redeemed in August was reported against July — which is exactly
the attribution error the two-key design exists to prevent, and it makes a redemption backlog
invisible.

WHY THE SECOND RELATIONSHIP IS INACTIVE
Only one relationship between two tables can be active. Sold date is the right default: it is
the date the voucher exists from, and every voucher has one. Redeemed date is null for
unredeemed vouchers, so making it active would silently drop unredeemed vouchers out of any
date-filtered total. The measures below opt into it explicitly where the question is about
redemption timing.
"""
import json
import shutil
import uuid
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PBIT = ROOT / "powerbi" / "MerchantVoucherIntelligence.pbit"

REL = {
    "name": str(uuid.uuid5(uuid.NAMESPACE_DNS, "mvi.redeemeddate.dimdate")),
    "fromTable": "FactVoucherRedemptions",
    "fromColumn": "RedeemedDateKey",
    "toTable": "DimDate",
    "toColumn": "DateKey",
    "isActive": False,
}

# Measures that answer "when was it REDEEMED", as opposed to the existing measures which all
# answer "when was it SOLD". Both are legitimate questions; the model previously could only
# answer one of them.
MEASURES = {
    "Vouchers Redeemed (by redeem date)":
        'CALCULATE ( [Vouchers Redeemed], '
        'USERELATIONSHIP ( FactVoucherRedemptions[RedeemedDateKey], DimDate[DateKey] ) )',
    "Value Redeemed (by redeem date)":
        'CALCULATE ( SUM ( FactVoucherRedemptions[VoucherValue] ), '
        'FactVoucherRedemptions[IsRedeemed] = 1, '
        'USERELATIONSHIP ( FactVoucherRedemptions[RedeemedDateKey], DimDate[DateKey] ) )',
    "Redemption Timing Gap":
        'VAR SoldBasis = [Vouchers Redeemed] '
        'VAR RedeemBasis = [Vouchers Redeemed (by redeem date)] '
        'RETURN RedeemBasis - SoldBasis',
}
FORMAT = {"Vouchers Redeemed (by redeem date)": "#,0",
          "Value Redeemed (by redeem date)": '"R"#,0',
          "Redemption Timing Gap": "#,0"}

z = zipfile.ZipFile(PBIT)
members = {n: z.read(n) for n in z.namelist()}
names = z.namelist()
z.close()

model = json.loads(members["DataModelSchema"].decode("utf-16-le"))
mdl = model["model"]

# ---------------------------------------------------------------- sanity before writing
tables = {t["name"]: t for t in mdl["tables"]}
if "FactVoucherRedemptions" not in tables or "DimDate" not in tables:
    raise SystemExit("expected tables are missing from the model")
cols = {c["name"] for c in tables["FactVoucherRedemptions"].get("columns", [])}
if "RedeemedDateKey" not in cols:
    raise SystemExit("FactVoucherRedemptions has no RedeemedDateKey — nothing to wire")

rels = mdl.setdefault("relationships", [])
existing = [r for r in rels
            if r.get("fromTable") == REL["fromTable"]
            and r.get("fromColumn") == REL["fromColumn"]
            and r.get("toTable") == REL["toTable"]]
if existing:
    for r in existing:
        r["isActive"] = False
    added_rel = False
else:
    rels.append(REL)
    added_rel = True

# Exactly one active relationship may exist between two tables. If a previous run or an edit
# left the sold-date relationship inactive, the model silently loses its default date path.
active_dates = [r for r in rels
                if r.get("fromTable") == "FactVoucherRedemptions"
                and r.get("toTable") == "DimDate"
                and r.get("isActive", True)]
if len(active_dates) != 1 or active_dates[0]["fromColumn"] != "SoldDateKey":
    raise SystemExit("sold date must remain the single ACTIVE date path on the voucher fact")

# ---------------------------------------------------------------- measures
added_m = []
for t in mdl["tables"]:
    ms = t.get("measures")
    if ms is None:
        continue
    have = {x["name"] for x in ms}
    for nm, expr in MEASURES.items():
        if nm in have:
            for x in ms:
                if x["name"] == nm:
                    x["expression"] = expr
                    x["formatString"] = FORMAT[nm]
        elif t["name"] == "_Measures":
            ms.append({"name": nm, "expression": expr, "formatString": FORMAT[nm]})
            added_m.append(nm)

members["DataModelSchema"] = json.dumps(model, ensure_ascii=False).encode("utf-16-le")

tmp = PBIT.with_suffix(".tmp")
with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zo:
    for n in names:
        zo.writestr(n, members[n])
tmp.replace(PBIT)

# ---------------------------------------------------------------- verify
zc = zipfile.ZipFile(PBIT)
for part in ("Report/Layout", "DataModelSchema"):
    if zc.read(part)[:2] in (b"\xff\xfe", b"\xfe\xff", b"\xef\xbb"):
        raise SystemExit(f"ENCODING ERROR: {part} has a BOM — template will not open")
chk = json.loads(zc.read("DataModelSchema").decode("utf-16-le"))["model"]
zc.close()

date_rels = [r for r in chk["relationships"] if r.get("toTable") == "DimDate"]
ur = [x["name"] for t in chk["tables"] for x in t.get("measures", [])
      if "USERELATIONSHIP" in (x["expression"] if isinstance(x["expression"], str)
                               else " ".join(x["expression"])).upper()]
if not ur:
    raise SystemExit("no measure activates the inactive relationship — it would be inert")

shutil.copy2(PBIT, ROOT / "MerchantVoucherIntelligence_PowerBI" /
             "MerchantVoucherIntelligence.pbit")

print(f"  relationship {'added' if added_rel else 'already present, set inactive'}: "
      f"FactVoucherRedemptions[RedeemedDateKey] -> DimDate[DateKey]  (inactive)")
print(f"  date relationships now: {len(date_rels)}")
for r in date_rels:
    print(f"    {r['fromTable']}[{r['fromColumn']}]  active={r.get('isActive', True)}")
print(f"  measures added: {', '.join(added_m) if added_m else '(already present, refreshed)'}")
print(f"  measures using USERELATIONSHIP: {len(ur)}")
print(f"  encoding verified · {PBIT.stat().st_size/1024:.0f} KB")
