"""
17_fabric_connect.py — discover the Fabric workspace, create the Warehouse if missing,
and write the exact dbt connection settings.

Uses the existing `az login` token rather than a service principal. dbt-fabric supports
CLI authentication, which means no app registration, no client secret, and nothing sensitive
written to disk — the token is fetched from the Azure CLI at connect time.

    python scripts/17_fabric_connect.py            discover and report
    python scripts/17_fabric_connect.py --create   also create WH_MerchantVoucher if absent
"""
import argparse
import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = "WS_MerchantVoucher"
WAREHOUSE = "WH_MerchantVoucher"
LAKEHOUSE = "LH_MerchantVoucher"
API = "https://api.fabric.microsoft.com/v1"


def token():
    r = subprocess.run(["az", "account", "get-access-token", "--resource",
                        "https://api.fabric.microsoft.com", "-o", "json"],
                       capture_output=True, text=True, shell=True)
    if r.returncode:
        print("  Could not get a token. Run: az login")
        print(r.stderr[-400:])
        sys.exit(1)
    return json.loads(r.stdout)


def call(method, url, tok, body=None):
    req = urllib.request.Request(
        url, method=method,
        headers={"Authorization": f"Bearer {tok}", "Content-Type": "application/json"},
        data=json.dumps(body).encode() if body else None)
    try:
        with urllib.request.urlopen(req) as r:
            raw = r.read().decode()
            return json.loads(raw) if raw else {}, r.status
    except urllib.error.HTTPError as e:
        return {"_error": e.read().decode()[:500]}, e.code
    except Exception as e:
        return {"_error": str(e)}, 0


ap = argparse.ArgumentParser()
ap.add_argument("--create", action="store_true", help="create the Warehouse if missing")
args = ap.parse_args()

print("=" * 88)
print("FABRIC CONNECTION")
print("=" * 88)

t = token()
tok = t["accessToken"]
print(f"  tenant   : {t.get('tenant')}")
print(f"  account  : {t.get('subscription', '(n/a)')}")

# ---------------------------------------------------------------- workspace
ws, code = call("GET", f"{API}/workspaces", tok)
if "_error" in ws:
    print(f"\n  Fabric API returned {code}.")
    print("  The Fabric API needs the signed-in user to have workspace access, and the")
    print("  tenant setting 'Service principals / users can use Fabric APIs' enabled.")
    print(f"  detail: {ws['_error'][:300]}")
    sys.exit(1)

target = next((w for w in ws.get("value", []) if w.get("displayName") == WORKSPACE), None)
if not target:
    print(f"\n  Workspace '{WORKSPACE}' not visible to this account.")
    print("  Workspaces found: " +
          ", ".join(w.get("displayName", "?") for w in ws.get("value", [])) or "(none)")
    sys.exit(1)

wid = target["id"]
print(f"\n  workspace : {WORKSPACE}")
print(f"  id        : {wid}")
print(f"  capacity  : {target.get('capacityId') or '(none attached)'}")

# ---------------------------------------------------------------- items
items, _ = call("GET", f"{API}/workspaces/{wid}/items", tok)
by_type = {}
for it in items.get("value", []):
    by_type.setdefault(it["type"], []).append(it)
print(f"\n  items ({len(items.get('value', []))}):")
for ty, lst in sorted(by_type.items()):
    for it in lst:
        print(f"    {ty:<22} {it['displayName']}")

# ---------------------------------------------------------------- warehouse
wh = next((i for i in by_type.get("Warehouse", []) if i["displayName"] == WAREHOUSE), None)

if not wh and args.create:
    print(f"\n  creating Warehouse '{WAREHOUSE}' ...")
    r, code = call("POST", f"{API}/workspaces/{wid}/warehouses", tok,
                   {"displayName": WAREHOUSE,
                    "description": "Gold layer for the Merchant Sales & Voucher "
                                   "Intelligence dbt project"})
    if code in (200, 201):
        wh = r
        print("  created")
    elif code == 202:
        print("  accepted, waiting for provisioning ...")
        for _ in range(30):
            time.sleep(5)
            items, _ = call("GET", f"{API}/workspaces/{wid}/items", tok)
            wh = next((i for i in items.get("value", [])
                       if i.get("displayName") == WAREHOUSE and i["type"] == "Warehouse"), None)
            if wh:
                print("  provisioned")
                break
    else:
        print(f"  FAILED ({code}): {r.get('_error', '')[:300]}")

if not wh:
    print(f"\n  No Warehouse named '{WAREHOUSE}'.")
    print("  Either re-run with --create, or in the portal:")
    print(f"    {WORKSPACE} -> + New item -> Warehouse -> {WAREHOUSE}")
    sys.exit(0)

# ---------------------------------------------------------------- connection string
whid = wh["id"]
detail, _ = call("GET", f"{API}/workspaces/{wid}/warehouses/{whid}", tok)
endpoint = ((detail.get("properties") or {}).get("connectionString")
            or (detail.get("properties") or {}).get("connectionInfo") or "")

print(f"\n  warehouse : {WAREHOUSE}")
print(f"  id        : {whid}")
print(f"  endpoint  : {endpoint or '(not returned — copy from Settings -> SQL endpoint)'}")

# ---------------------------------------------------------------- emit env + profile hint
if endpoint:
    env = ROOT / "dbt" / ".env.fabric.ps1"
    env.write_text(
        "# Generated by scripts/17_fabric_connect.py — dot-source before running dbt:\n"
        "#   . .\\dbt\\.env.fabric.ps1\n"
        "# CLI auth is used, so there is no secret in this file and nothing to rotate.\n"
        f'$env:FABRIC_SQL_ENDPOINT = "{endpoint}"\n'
        f'$env:FABRIC_WAREHOUSE    = "{WAREHOUSE}"\n'
        f'$env:FABRIC_WORKSPACE_ID = "{wid}"\n'
        f'$env:FABRIC_WAREHOUSE_ID = "{whid}"\n', encoding="utf-8")
    print(f"\n  wrote {env.relative_to(ROOT)}")
    print("\n  Next:")
    print("    . .\\dbt\\.env.fabric.ps1")
    print("    cd dbt")
    print("    dbt debug --target fabric")
    print("    dbt build --target fabric")
