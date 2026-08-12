"""
rebuild_pbit.py — the one supported way to rebuild the Power BI template.

The .pbit is built by a CHAIN of scripts applied in order to a pristine copy. Each one assumes
the previous has run. Until now that order lived only in shell history, which meant a rebuild
could silently drop a step — the role-playing date relationship (43) existed in the shipped
file but in no build script, so rebuilding from the original would have quietly removed it
while the Word report continued to describe it.

Order matters, and not arbitrarily:

    16  theme + layout            base styling
    19  extra pages + measures    adds tables the later scripts style
    22  fonts + card accents      must run after pages exist
    29  table origin badges       reads the model 19 produced
    30  three more pages          the last script to CREATE visuals
    31  repair broken bindings    validates every visual against the model — needs them all
    35  fill the Insights page    replaces its own previous output
    38  canvas tint + tile depth  styles visuals only; never touches textboxes
    32  phone layout              must be last of the layout steps, sees every visual
    39  unify the health score    model + data
    43  role-playing date         model only
    44  align the calendar        data only

32 sits after 38 deliberately: it reads final positions, so any script that moves or adds a
visual has to run before it.

    python scripts/rebuild_pbit.py            rebuild from the pristine original
    python scripts/rebuild_pbit.py --check    list the chain and verify each script exists
"""
import argparse
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
PBIT = ROOT / "powerbi" / "MerchantVoucherIntelligence.pbit"
ORIGINAL = ROOT / "powerbi" / "_MerchantVoucherIntelligence.original.pbit"

CHAIN = [
    (16, "theme and layout"),
    (19, "extra pages, tables and measures"),
    (22, "fonts and card accents"),
    (29, "table origin badges and ModelGuide"),
    (30, "Voucher, Fraud and Data Quality pages"),
    (31, "repair broken field bindings"),
    (35, "fill Insights and Notes"),
    (38, "canvas tint and tile depth"),
    (32, "phone layout"),
    (39, "unify health score and banding"),
    (43, "role-playing redeemed date"),
    (44, "align the Power BI calendar to dbt"),
]


def resolve(num):
    hits = sorted(SCRIPTS.glob(f"{num}_*.py"))
    if not hits:
        raise SystemExit(f"chain is broken: no script numbered {num} in scripts/")
    if len(hits) > 1:
        raise SystemExit(f"ambiguous: {num} matches {[h.name for h in hits]}")
    return hits[0]


ap = argparse.ArgumentParser()
ap.add_argument("--check", action="store_true", help="list the chain without running it")
args = ap.parse_args()

resolved = [(n, d, resolve(n)) for n, d in CHAIN]

if args.check:
    print(f"  {len(resolved)} steps, all present:")
    for n, d, p in resolved:
        print(f"    {n:>3}  {p.name:<34} {d}")
    raise SystemExit(0)

if not ORIGINAL.exists():
    raise SystemExit(f"pristine original missing: {ORIGINAL}")
shutil.copy2(ORIGINAL, PBIT)
print(f"  restored pristine template ({ORIGINAL.stat().st_size / 1024:.0f} KB)")

failed = []
for n, desc, path in resolved:
    r = subprocess.run([sys.executable, str(path)], capture_output=True, text=True, cwd=ROOT)
    tail = (r.stdout or r.stderr).strip().splitlines()
    note = tail[-1].strip() if tail else ""
    if r.returncode:
        failed.append(path.name)
        print(f"    FAILED  {n:>3} {path.name}")
        for ln in (r.stdout + r.stderr).strip().splitlines()[-4:]:
            print(f"            {ln}")
    else:
        print(f"    ok      {n:>3} {path.name:<34} {note[:60]}")

if failed:
    raise SystemExit(f"\n  {len(failed)} step(s) failed: {', '.join(failed)}")

# A rebuild that produces a template Power BI refuses to open is worse than no rebuild.
import json
import zipfile

z = zipfile.ZipFile(PBIT)
for part in ("Report/Layout", "DataModelSchema"):
    if z.read(part)[:2] in (b"\xff\xfe", b"\xfe\xff", b"\xef\xbb"):
        raise SystemExit(f"ENCODING ERROR: {part} has a BOM — template will not open")
lay = json.loads(z.read("Report/Layout").decode("utf-16-le"))
mdl = json.loads(z.read("DataModelSchema").decode("utf-16-le"))["model"]
z.close()

pages = len(lay["sections"])
meas = sum(len(t.get("measures", [])) for t in mdl["tables"])
rels = len(mdl.get("relationships", []))
inactive = [r for r in mdl["relationships"] if r.get("isActive") is False]

print(f"\n  {pages} pages · {len(mdl['tables'])} tables · {meas} measures · {rels} relationships")
print(f"  inactive (role-playing) relationships: {len(inactive)}")
if not inactive:
    raise SystemExit("the role-playing date relationship is missing — step 43 did not take")
print(f"  {PBIT.name}  {PBIT.stat().st_size / 1024:.0f} KB")
