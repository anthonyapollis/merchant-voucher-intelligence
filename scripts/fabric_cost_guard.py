"""
fabric_cost_guard.py — Fabric cost kill-switch and audit.

    python scripts/fabric_cost_guard.py --check     what is running / scheduled (read-only)
    python scripts/fabric_cost_guard.py --stop      disable every trigger and schedule
    python scripts/fabric_cost_guard.py --nuke      --stop, plus delete the trial workspace

WHY THIS IS A SCRIPT AND NOT A CHECKLIST
A Fabric trial is 60 days on an F64-equivalent capacity. It does not warn you, and it does
not stop on its own — a scheduled pipeline keeps firing nightly for the whole period, and if
the tenant later attaches a paid capacity the same schedules keep running against it. The
failure mode is not a big bill on day one; it is a small bill every day that nobody looks at.

TRIAL DATES FOR THIS WORKSPACE
    activated   2026-08-11
    expires     2026-10-10  (60 days)
    act by      2026-10-03  (trigger endTime is set to this; one week of margin)

Authentication uses the Azure CLI login already on the machine (`az login`), so no secret is
stored or entered here.
"""
import argparse
import json
import subprocess
import sys
from datetime import date, datetime

WORKSPACE = "WS_MerchantVoucher"
TRIAL_ACTIVATED = date(2026, 8, 11)
TRIAL_EXPIRES = date(2026, 10, 10)
ACT_BY = date(2026, 10, 3)

API = "https://api.fabric.microsoft.com/v1"

# Item types that hold compute UP rather than billing per run. An Eventhouse and its KQL
# database keep a cluster warm from the moment they are created; a Fabric trial burns through
# capacity units against them whether or not anyone runs a query. They are called out
# separately because the usual remedy — disabling schedules — has no effect on them.
ALWAYS_ON = ("Eventhouse", "KQLDatabase", "KQLQueryset", "KQLDashboard",
             "MirroredDatabase", "SQLDatabase")
PBI = "https://api.powerbi.com/v1.0/myorg"


def token(resource="https://api.fabric.microsoft.com"):
    """Reuse the existing az login rather than handling any secret here."""
    try:
        r = subprocess.run(["az", "account", "get-access-token", "--resource", resource,
                            "-o", "json"], capture_output=True, text=True, shell=True)
        if r.returncode:
            return None
        return json.loads(r.stdout)["accessToken"]
    except Exception:
        return None


def call(method, url, tok, body=None):
    import urllib.request
    req = urllib.request.Request(url, method=method,
                                 headers={"Authorization": f"Bearer {tok}",
                                          "Content-Type": "application/json"},
                                 data=json.dumps(body).encode() if body else None)
    try:
        with urllib.request.urlopen(req) as resp:
            raw = resp.read().decode()
            return json.loads(raw) if raw else {}
    except Exception as e:
        return {"_error": str(e)}


def days_left():
    return (TRIAL_EXPIRES - date.today()).days


def banner():
    d = days_left()
    urgency = "OK" if d > 14 else ("ACT SOON" if d > 7 else "ACT NOW")
    print("=" * 78)
    print(f"FABRIC COST GUARD  |  workspace {WORKSPACE}")
    print(f"trial activated {TRIAL_ACTIVATED}  expires {TRIAL_EXPIRES}  "
          f"({d} days left)  [{urgency}]")
    print(f"act by {ACT_BY} — one week of margin before expiry")
    print("=" * 78)


def check(tok):
    """Read-only inventory of everything that can generate cost."""
    ws = call("GET", f"{API}/workspaces", tok)
    target = next((w for w in ws.get("value", []) if w.get("displayName") == WORKSPACE), None)
    if not target:
        print(f"  workspace '{WORKSPACE}' not found (or no API access)")
        return None
    wid = target["id"]
    print(f"  workspace id : {wid}")
    print(f"  capacity id  : {target.get('capacityId', '(none — no capacity attached)')}")

    items = call("GET", f"{API}/workspaces/{wid}/items", tok).get("value", [])
    by_type = {}
    for it in items:
        by_type.setdefault(it["type"], []).append(it["displayName"])
    print(f"\n  {len(items)} item(s):")
    always_on = []
    for t, names in sorted(by_type.items()):
        if t in ALWAYS_ON:
            # These are the dangerous ones. A pipeline or notebook bills for the seconds it
            # runs and is idle the rest of the time; an Eventhouse / KQL database holds a
            # compute cluster UP and bills continuously until it is deleted or its capacity
            # is paused. Disabling schedules does nothing to it.
            cost = "  <-- ALWAYS ON, BILLS CONTINUOUSLY"
            always_on += [(t, n) for n in names]
        elif t in ("DataPipeline", "Notebook", "SparkJobDefinition", "Eventstream", "Reflex"):
            cost = "  <-- can incur cost when it runs"
        else:
            cost = ""
        print(f"    {t:<24} {len(names):>3}{cost}")
        for n in names:
            print(f"        {n}")

    if always_on:
        print(f"\n  WARNING — {len(always_on)} always-on item(s) found:")
        for t, n in always_on:
            print(f"    {t}: {n}")
        print("    These consume capacity units continuously, not per run. Deleting the item "
              "or pausing the capacity are the only things that stop the charge; disabling "
              "schedules does NOT.")

    # Scheduled jobs are the thing that actually runs unattended
    print("\n  scheduled jobs:")
    found = 0
    for it in items:
        if it["type"] not in ("DataPipeline", "Notebook", "SparkJobDefinition"):
            continue
        for jt in ("Pipeline", "RunNotebook", "sparkjob"):
            sch = call("GET", f"{API}/workspaces/{wid}/items/{it['id']}/jobs/instances"
                              f"?jobType={jt}", tok)
            if "_error" in sch:
                continue
        s = call("GET", f"{API}/workspaces/{wid}/items/{it['id']}/jobs/"
                        f"{'Pipeline' if it['type']=='DataPipeline' else 'RunNotebook'}"
                        f"/schedules", tok)
        for sc in s.get("value", []):
            found += 1
            state = "ENABLED" if sc.get("enabled") else "disabled"
            print(f"    [{state:>8}] {it['displayName']} ({it['type']})  id={sc.get('id')}")
    if not found:
        print("    none found")
    return wid


def stop(tok, wid):
    """Disable every schedule. Does not delete anything."""
    items = call("GET", f"{API}/workspaces/{wid}/items", tok).get("value", [])
    disabled = 0
    for it in items:
        if it["type"] not in ("DataPipeline", "Notebook", "SparkJobDefinition"):
            continue
        jt = "Pipeline" if it["type"] == "DataPipeline" else "RunNotebook"
        s = call("GET", f"{API}/workspaces/{wid}/items/{it['id']}/jobs/{jt}/schedules", tok)
        for sc in s.get("value", []):
            if not sc.get("enabled"):
                continue
            body = {"enabled": False, "configuration": sc.get("configuration")}
            r = call("PATCH", f"{API}/workspaces/{wid}/items/{it['id']}/jobs/{jt}"
                              f"/schedules/{sc['id']}", tok, body)
            ok = "_error" not in r
            print(f"    {'disabled' if ok else 'FAILED  '} {it['displayName']} / {sc['id']}")
            disabled += ok
    print(f"\n  {disabled} schedule(s) disabled")

    # Cancel anything mid-flight
    for it in items:
        if it["type"] not in ("DataPipeline", "Notebook"):
            continue
        jt = "Pipeline" if it["type"] == "DataPipeline" else "RunNotebook"
        runs = call("GET", f"{API}/workspaces/{wid}/items/{it['id']}/jobs/instances", tok)
        for r in runs.get("value", []):
            if r.get("status") in ("InProgress", "NotStarted"):
                call("POST", f"{API}/workspaces/{wid}/items/{it['id']}/jobs/instances"
                             f"/{r['id']}/cancel", tok)
                print(f"    cancelled in-flight run {r['id']} ({it['displayName']})")
    return disabled


def nuke(tok, wid, assume_yes=False):
    """Delete the workspace. Interactive by default; --yes is for the scheduled teardown.

    The typed-name confirmation exists so this cannot be run by accident from a shell. But a
    scheduled task has no stdin: input() would raise EOFError, the teardown would never
    happen, and the task history would still show the job as having run. That is the worst
    possible outcome, because the capacity keeps billing while the log says it was cleaned
    up. --yes makes the non-interactive path explicit rather than implicit.
    """
    print("\n  DELETING the workspace and everything in it.")
    if assume_yes:
        print(f"  --yes supplied: proceeding without typed confirmation ({WORKSPACE})")
    else:
        ans = input(f"  Type the workspace name to confirm ({WORKSPACE}): ").strip()
        if ans != WORKSPACE:
            print("  aborted — name did not match")
            return
    r = call("DELETE", f"{API}/workspaces/{wid}", tok)
    print("  deleted" if "_error" not in r else f"  FAILED: {r['_error']}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--stop", action="store_true")
    ap.add_argument("--nuke", action="store_true")
    ap.add_argument("--yes", action="store_true",
                    help="skip the typed confirmation — for the scheduled teardown, which "
                         "has no stdin")
    a = ap.parse_args()
    if not (a.check or a.stop or a.nuke):
        a.check = True

    banner()
    tok = token()
    if not tok:
        print("\n  No Azure CLI token. Run `az login` first.")
        print("\n  MANUAL FALLBACK — do these in the Fabric portal:")
        print("    1. Workspace -> each pipeline/notebook -> Schedule -> set Off")
        print("    2. Workspace settings -> License mode -> remove the trial capacity")
        print("    3. Or delete the workspace entirely: Workspace settings -> Remove")
        print("    4. Profile -> Cancel trial (stops the 60-day clock immediately)")
        sys.exit(1)

    wid = check(tok)
    if not wid:
        sys.exit(1)
    if a.stop or a.nuke:
        stop(tok, wid)
    if a.nuke:
        nuke(tok, wid, assume_yes=a.yes)

    d = days_left()
    if d <= 7:
        print(f"\n  *** TRIAL EXPIRES IN {d} DAYS — stop or delete the workspace now. ***")
    elif d <= 14:
        print(f"\n  Trial expires in {d} days. Plan the shutdown.")


if __name__ == "__main__":
    main()
